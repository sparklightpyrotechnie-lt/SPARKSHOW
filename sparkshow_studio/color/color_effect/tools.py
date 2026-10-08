from typing import TYPE_CHECKING, cast

import bpy

from ...tools.asset_tools import get_asset
from ...tools.collection_tools import add_collection, get_drone_index_from_blender_drone, get_drones

if TYPE_CHECKING:
    from .properties import ColorEffectProperties


def is_color_effect_preview_enabled(context: "bpy.types.Context") -> bool:
    system_collection = bpy.data.collections.get("System")
    if system_collection is None:
        return False

    props = context.scene.color_effect_properties
    if props is None:
        msg = "Color effect properties not found in the scene"
        raise ValueError(msg)

    if props.color_effect == "NONE":
        return False

    effect_object = system_collection.objects.get(props.color_effect)
    return effect_object is not None


def create_color_effect_geometry_node(context: "bpy.types.Context") -> None:
    props = context.scene.color_effect_properties

    add_collection("System", context.scene.collection, color_tag="COLOR_01")

    color_effect_object = bpy.data.objects.get(props.color_effect)
    if color_effect_object is None:
        color_effect_object = bpy.data.objects.new(
            props.color_effect, bpy.data.meshes.new(props.color_effect)
        )

        cast(
            "bpy.types.NodesModifier",
            color_effect_object.modifiers.new("Geometry Nodes", type="NODES"),
        ).node_group = get_asset("node_groups", context.scene.color_effect_properties.color_effect)

    if color_effect_object.name not in bpy.data.collections["System"].objects:
        bpy.data.collections["System"].objects.link(color_effect_object)


def create_drone_color_geometry_node(
    drone: bpy.types.Object, props: bpy.types.PropertyGroup, scene: bpy.types.Scene
) -> bpy.types.NodeTree:
    node_group = cast(
        bpy.types.NodeTree,
        get_asset("node_groups", "Drone Color").copy(),
    )

    # Retrieve existing Group Input and Output nodes
    group_input = next((node for node in node_group.nodes if node.type == "GROUP_INPUT"), None)
    group_output = next((node for node in node_group.nodes if node.type == "GROUP_OUTPUT"), None)
    if not group_input or not group_output:
        print("Group Input or Output node not found.")
        return

    color_effect_group = bpy.data.node_groups.get(props.color_effect)
    if not color_effect_group:
        print("Color Effect node group not found.")
        return

    # Add the "Color Effect" node group to the node tree
    color_effect_node = node_group.nodes.new("GeometryNodeGroup")
    color_effect_node.node_tree = color_effect_group
    color_effect_node.location = (100, 0)
    group_output.location = (300, 0)

    # Create links
    links = node_group.links
    links.new(group_input.outputs["Geometry"], color_effect_node.inputs["Geometry"])
    if "Drone Index" in color_effect_node.inputs:
        links.new(node_group.nodes["Integer"].outputs[0], color_effect_node.inputs["Drone Index"])
    links.new(color_effect_node.outputs["Geometry"], group_output.inputs["Geometry"])

    mod_name = "Geometry Nodes"
    if mod_name in drone.modifiers:
        geo_mod = cast(bpy.types.NodesModifier, drone.modifiers[mod_name])
    else:
        geo_mod = cast(bpy.types.NodesModifier, drone.modifiers.new(name=mod_name, type="NODES"))

    geo_mod.node_group = node_group  # set the node group to the drone

    drone_index = get_drone_index_from_blender_drone(drone, scene.collection)
    cast(bpy.types.FunctionNodeInputInt, geo_mod.node_group.nodes["Integer"]).integer = drone_index


def create_drone_material(drone: bpy.types.Object) -> None:
    material = drone.active_material
    assert material is not None
    node_tree = material.node_tree
    assert node_tree is not None, "Material node tree is None"
    rgbw_emission = node_tree.nodes["RGBW Emission"]
    color_attribute = node_tree.nodes["Color Attribute"]
    node_tree.links.new(color_attribute.outputs[0], rgbw_emission.inputs[0])


def enable_color_effect_preview(
    self: "ColorEffectProperties",
    context: "bpy.types.Context",
) -> None:
    if self is None:
        msg = "Color effect properties not found in the scene"
        raise ValueError(msg)

    if self.color_effect == "NONE":
        return

    create_color_effect_geometry_node(context)

    for drone in get_drones(context.scene.collection):
        geometry_nodes = drone.modifiers.get("Geometry Nodes")
        if (
            geometry_nodes is None
            or geometry_nodes.node_group is None
            or geometry_nodes.node_group.name != "Drone Color"
        ):
            create_drone_color_geometry_node(drone, self, context.scene)

        create_drone_material(drone)


def disable_color_effect_preview(context: "bpy.types.Context") -> None:
    props = getattr(context.scene, "color_effect_properties", None)
    if props is None:
        msg = "Color effect properties not found in the scene"
        raise ValueError(msg)

    for drone in get_drones(context.scene.collection):
        material = drone.active_material
        assert material is not None
        node_tree = material.node_tree
        node_tree.links.remove(node_tree.links[-1])  # pyright: ignore

        drone.modifiers.remove(drone.modifiers.get("Geometry Nodes", None))

    system_collection = bpy.data.collections.get("System")
    if system_collection:
        effect_object = system_collection.objects.get(props.color_effect)
        if effect_object:
            system_collection.objects.unlink(effect_object)
            bpy.data.objects.remove(effect_object)
