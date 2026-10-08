"""This module provides tools for displaying proximity warning lines between drones or objects."""

from typing import TYPE_CHECKING, cast

import bpy

from .asset_tools import get_asset
from .collection_tools import add_collection

if TYPE_CHECKING:
    from ..setup import Lightshow


def create_proximity_warning_lines() -> None:
    # create object
    proximity_warning_lines = bpy.data.objects.get("Proximity Lines")
    if proximity_warning_lines is None:
        create_proximity_lines_material()

        proximity_warning_lines = bpy.data.objects.new(
            "Proximity Lines", bpy.data.meshes.new("Proximity Lines")
        )

        cast(
            "bpy.types.NodesModifier",
            proximity_warning_lines.modifiers.new("Geometry Nodes", type="NODES"),
        ).node_group = get_asset("node_groups", "Proximity Lines")
        proximity_warning_lines.modifiers["Geometry Nodes"]["Socket_2"] = bpy.data.collections.get(
            "Families"
        )
        proximity_warning_lines.modifiers["Geometry Nodes"]["Socket_4"] = bpy.data.materials[
            "Proximity Lines Material"
        ]

    add_collection("System", bpy.context.scene.collection, "COLOR_01")

    if proximity_warning_lines.name not in bpy.data.collections["System"].objects:
        bpy.data.collections["System"].objects.link(proximity_warning_lines)


def update_proximity_warning_lines(lightshow: "Lightshow", context: "bpy.types.Context") -> None:  # noqa: ARG001
    if not lightshow.enable_proximity_warning:
        collection = bpy.data.collections.get("System")
        if collection is not None:
            geonode = collection.objects.get("Proximity Lines")
            if geonode is not None:
                collection.objects.unlink(geonode)
                bpy.data.objects.remove(geonode)
        return

    if (
        bpy.data.collections.get("System") is None
        or bpy.data.collections["System"].objects.get("Proximity Lines") is None
    ):
        create_proximity_warning_lines()

    proximity_warning_lines = bpy.data.collections["System"].objects.get("Proximity Lines")

    assert proximity_warning_lines is not None, "Proximity Lines not found in System collection"
    assert (
        "Geometry Nodes" in proximity_warning_lines.modifiers
    ), f"Geometry node error: {proximity_warning_lines.modifiers.keys()}"
    key = "Geometry Nodes"
    proximity_warning_lines.modifiers[key]["Socket_3"] = lightshow.collision_distance
    proximity_warning_lines.modifiers[key]["Socket_5"] = lightshow.proximity_line_object
    proximity_warning_lines.modifiers[key].show_viewport = True


def create_proximity_lines_material() -> "bpy.types.Material":
    material = bpy.data.materials.get("Proximity Lines Material")
    if material is None:
        material = bpy.data.materials.new("Proximity Lines Material")
        material.use_nodes = True
        assert material.node_tree is not None, "Material node tree is None"
        material.node_tree.nodes.clear()
        material_output = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
        material_output.location = (200, 0)
        material_output.label = "Material Output"
        emission = material.node_tree.nodes.new("ShaderNodeEmission")
        emission.name = "RGBW Emission"
        emission.location = (-100, 0)
        emission.inputs["Color"].default_value = (1, 1, 0, 1)  # pyright: ignore
        emission.inputs["Strength"].default_value = 1  # pyright: ignore
        material.node_tree.links.new(
            emission.outputs["Emission"], material_output.inputs["Surface"]
        )

    material.diffuse_color = (1, 1, 0, 1)  # RGBA: Yellow with full opacity for viewport display
    return material
