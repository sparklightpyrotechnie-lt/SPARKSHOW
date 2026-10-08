"""One-time migration helpers for Sparkshow Studio 5.0.

The migration converts v3 drone representation (unique mesh/material with
material color animation) into the v4.1 representation (shared mesh/material
with per-object color animation). Location, fire and other object animation are
left intact.
"""
from __future__ import annotations

import bpy

from .setup import get_lightshow
from .tools.collection_tools import get_drones
from .tools.color_tools import create_shared_drone_material

MIGRATION_KEY = "sparkshow_creator_41_migrated"
COLOR_PATH = 'nodes["RGBW Emission"].inputs[0].default_value'


def _copy_color_action_to_object(drone: bpy.types.Object) -> bool:
    material = drone.active_material
    if material is None or material.node_tree.animation_data is None:
        return False
    action = material.node_tree.animation_data.action
    if action is None:
        return False
    source = [fc for fc in action.fcurves if fc.data_path == COLOR_PATH]
    if len(source) != 4:
        return False

    if drone.animation_data is None:
        drone.animation_data_create()
    object_action = drone.animation_data.action
    if object_action is None:
        object_action = bpy.data.actions.new(name=f"{drone.name}_Action")
        drone.animation_data.action = object_action

    for index, source_curve in enumerate(source):
        target = object_action.fcurves.find("color", index=index)
        if target is None:
            target = object_action.fcurves.new("color", index=index)
        for key in source_curve.keyframe_points:
            point = target.keyframe_points.insert(key.co[0], key.co[1], options={"FAST"})
            point.interpolation = key.interpolation
            point.type = key.type
        target.update()
    return True


def migrate_scene(scene: bpy.types.Scene) -> int:
    if scene.get(MIGRATION_KEY):
        return 0
    drones = get_drones(scene.collection)
    if not drones:
        scene[MIGRATION_KEY] = True
        return 0

    lightshow = get_lightshow(scene)
    shared_material = create_shared_drone_material(lightshow)
    shared_mesh = drones[0].data.copy()
    shared_mesh.name = "Sparkshow Drone (Shared Mesh)"
    shared_mesh.materials.clear()
    shared_mesh.materials.append(shared_material)

    migrated = 0
    for drone in drones:
        # Evaluate and retain the current visible color before replacing the material.
        old_color = tuple(drone.color)
        try:
            material = drone.active_material
            if material is not None and material.node_tree.nodes.get("RGBW Emission") is not None:
                old_color = tuple(material.node_tree.nodes["RGBW Emission"].inputs["Color"].default_value)
        except (AttributeError, KeyError):
            pass

        _copy_color_action_to_object(drone)
        drone["sparkshow_object_color"] = True
        drone.data = shared_mesh
        drone.color = old_color
        migrated += 1

    scene[MIGRATION_KEY] = True
    return migrated


def register() -> None:
    # Migration is intentionally automatic but strictly one-time per scene.
    for scene in bpy.data.scenes:
        try:
            migrate_scene(scene)
        except Exception as exc:  # pragma: no cover - Blender data can be partially loaded
            print(f"[Sparkshow Studio 5.0] Migration skipped for {scene.name}: {exc}")


def unregister() -> None:
    pass
