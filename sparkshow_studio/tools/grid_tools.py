"""Tools to create the drone grid preview."""

from typing import TYPE_CHECKING, cast

import bpy

from .asset_tools import get_asset

if TYPE_CHECKING:
    from ..setup import Lightshow


def create_drone_grid(scene_collection: "bpy.types.Collection") -> None:
    # create object
    drone_grid = bpy.data.objects.get("Drone Grid")
    if drone_grid is None:
        drone_grid = bpy.data.objects.new("Drone Grid", bpy.data.meshes.new("Drone Grid"))

        cast(
            "bpy.types.NodesModifier",
            drone_grid.modifiers.new("Geometry Nodes", type="NODES"),
        ).node_group = get_asset("node_groups", "Drone Grid")
        # Drone Grid Material is a dependency of Drone Grid
        # And is therefore loaded when getting Drone Grid
        drone_grid.active_material = bpy.data.materials["Drone Grid Material"]
    if drone_grid.name not in scene_collection.objects:
        scene_collection.objects.link(drone_grid)


def is_drone_grid_initialized(scene_collection: "bpy.types.Collection") -> bool:
    return scene_collection.objects.get("Drone Grid") is not None


def update_drone_grid(lightshow: "Lightshow", context: "bpy.types.Context") -> None:
    drone_grid = context.scene.collection.objects.get("Drone Grid")
    if drone_grid is None:
        return

    assert (
        "Geometry Nodes" in drone_grid.modifiers
    ), f"Geometry node error: {drone_grid.modifiers.keys()}"
    key = "Geometry Nodes"
    drone_grid.modifiers[key]["Input_1"] = lightshow.nb_drones_per_family
    drone_grid.modifiers[key]["Input_2"] = lightshow.nb_x
    drone_grid.modifiers[key]["Input_3"] = lightshow.nb_y
    drone_grid.modifiers[key]["Input_4"] = lightshow.step_x
    drone_grid.modifiers[key]["Socket_0"] = lightshow.step_y
    drone_grid.modifiers[key]["Input_5"] = lightshow.angle_takeoff
    drone_grid.modifiers[key].show_viewport = True

    assert (
        drone_grid.active_material is not None
    ), f"drone grid: {drone_grid} > active_material: {drone_grid.active_material}"
    drone_grid.active_material.diffuse_color = (
        (1.0, 1.0, 1.0, 1.0)
        if lightshow.nb_drones == lightshow.nb_x * lightshow.nb_y * lightshow.nb_drones_per_family
        else (1.0, 0.0, 0.0, 1.0)
    )


def remove_drone_grid(scene_collection: "bpy.types.Collection") -> None:
    """Remove the drone grid from the scene."""
    drone_grid = scene_collection.objects.get("Drone Grid")
    if drone_grid is None:
        return
    bpy.data.objects.remove(drone_grid, do_unlink=True)
