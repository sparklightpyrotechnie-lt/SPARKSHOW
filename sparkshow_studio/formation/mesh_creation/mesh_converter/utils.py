from typing import cast

import bpy

from ....setup import get_lightshow
from ....tools.asset_tools import get_asset
from ....tools.mesh_tools import update_mesh_converter_node


def clear_armature_keyframes(obj: bpy.types.Object) -> None:
    if obj.type == "ARMATURE" and obj.animation_data and obj.animation_data.action:
        for fcurve in obj.animation_data.action.fcurves:
            if fcurve.data_path == "rotation_euler":
                obj.animation_data.action.fcurves.remove(fcurve)


def select_only_object(context: bpy.types.Context, obj: bpy.types.Object) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    context.view_layer.objects.active = obj


def preview_mesh_to_points(context: bpy.types.Context) -> None:
    lightshow = get_lightshow(context.scene)
    obj = lightshow.mesh_converter_object
    if obj is None or obj.type != "MESH":
        return

    if obj.parent and obj.parent.type == "ARMATURE":
        clear_armature_keyframes(obj.parent)
        select_only_object(context, obj.parent)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        select_only_object(context, obj)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        static_obj = None
        for ctx_obj in context.scene.objects:
            if ctx_obj.name.startswith(obj.name) and ctx_obj != obj:
                static_obj = ctx_obj
                break
        if static_obj is None:
            bpy.ops.object.duplicate()
            static_obj = context.active_object
            assert static_obj is not None, "Error duplicating object"
            static_obj.parent = None
            for modifier in static_obj.modifiers:
                bpy.ops.object.modifier_remove(modifier=modifier.name)
            static_obj.hide_viewport = True
        lightshow.mesh_converter_static_object = static_obj
    else:
        select_only_object(context, obj)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

        lightshow.mesh_converter_static_object = obj

    geometry_nodes = obj.modifiers.get("Geometry Nodes")
    if geometry_nodes is None:
        geometry_nodes = obj.modifiers.new("Geometry Nodes", "NODES")

    if geometry_nodes.node_group is not None:
        bpy.data.node_groups.remove(geometry_nodes.node_group)
    geometry_nodes.node_group = cast(
        bpy.types.NodeTree,
        get_asset("node_groups", "Animated mesh to formation").copy(),
    )
    update_mesh_converter_node(lightshow, context)


def cancel_mesh_to_points(context: bpy.types.Context) -> None:
    lightshow = get_lightshow(context.scene)
    obj = lightshow.mesh_converter_object
    if obj is None or obj.type != "MESH":
        return

    geometry_nodes = obj.modifiers.get("Geometry Nodes")
    if geometry_nodes is not None:
        bpy.data.node_groups.remove(geometry_nodes.node_group)
        obj.modifiers.remove(geometry_nodes)


def apply_mesh_to_points(context: bpy.types.Context) -> None:
    lightshow = get_lightshow(context.scene)
    obj = lightshow.mesh_converter_object
    if obj is None or obj.type != "MESH":
        return

    geometry_nodes = obj.modifiers.get("Geometry Nodes")
    if geometry_nodes is None:
        return

    select_only_object(context, obj)
    bpy.ops.object.modifier_apply(modifier=geometry_nodes.name)


def add_anchors_to_rigged_mesh(context: bpy.types.Context) -> None:
    lightshow = get_lightshow(context.scene)
    obj = lightshow.mesh_converter_object

    if obj and obj.type == "MESH":
        # Define the frame range
        start_frame = bpy.context.scene.frame_start
        end_frame = bpy.context.scene.frame_end

        # Create a list to store references to the Empties
        empties = []

        # Access the evaluated object via the dependency graph
        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_obj = obj.evaluated_get(depsgraph)

        # Retrieve the mesh data
        mesh = eval_obj.to_mesh()

        # Create an Empty for each vertex
        for i in range(len(mesh.vertices)):
            # Create a new Empty
            empty = bpy.data.objects.new(f"Empty_{i}", None)
            context.collection.objects.link(empty)
            empty.parent = obj
            empties.append(empty)

        # Clean up: remove the temporary mesh data
        eval_obj.to_mesh_clear()

        # Iterate over each frame
        for frame in range(start_frame, end_frame + 1):
            # Set the current frame
            bpy.context.scene.frame_set(frame)
            bpy.context.view_layer.update()

            # Access the evaluated object via the dependency graph
            depsgraph = bpy.context.evaluated_depsgraph_get()
            eval_obj = obj.evaluated_get(depsgraph)

            # Retrieve the mesh data
            mesh = eval_obj.to_mesh()

            # Update each Empty's position and insert a keyframe
            for i, vert in enumerate(mesh.vertices):
                # Calculate the world position of the vertex
                world_position = eval_obj.matrix_world @ vert.co

                # Set the Empty's location to the vertex's world position
                empties[i].location = world_position

                # Insert a keyframe for the Empty's location
                empties[i].keyframe_insert(data_path="location", frame=frame)

            # Clean up: remove the temporary mesh data
            eval_obj.to_mesh_clear()
