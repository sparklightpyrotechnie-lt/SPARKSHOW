from typing import TYPE_CHECKING, cast

import numpy as np

from .asset_tools import get_asset
from .collection_tools import get_drones

if TYPE_CHECKING:
    import bpy

    from ..setup import Lightshow


def create_drone_node_group(drone_object: "bpy.types.Object") -> None:
    cast(
        "bpy.types.NodesModifier",
        drone_object.modifiers.new("Geometry Nodes", type="NODES"),
    ).node_group = get_asset("node_groups", "Drone")


def update_drone(lightshow: "Lightshow", context: "bpy.types.Context") -> None:
    for drone in get_drones(context.scene.collection):
        geometry_nodes = drone.modifiers.get("Geometry Nodes")

        # If the angle is 0, remove the geometry nodes modifier to optimize the scene
        if np.isclose(lightshow.angle_export, 0):
            if geometry_nodes is not None:
                drone.modifiers.remove(geometry_nodes)
            continue

        if geometry_nodes is None:
            create_drone_node_group(drone)
            geometry_nodes = drone.modifiers["Geometry Nodes"]
        geometry_nodes["Input_1"] = lightshow.angle_export
        geometry_nodes.show_viewport = True
