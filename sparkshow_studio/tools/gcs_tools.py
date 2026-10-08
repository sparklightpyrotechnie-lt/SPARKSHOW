from typing import cast

import bmesh
import bpy

from sparkshow_studio._loader.schemas import ShowUser

from .color_tools import RGBW
from .fcurve_tools import find_fcurve_or_create
from .import_tools import add_takeoff_land_intermediate_position


def get_drones_object() -> bpy.types.Object | None:
    return bpy.data.objects.get("Drones")


def init_drones_object() -> bpy.types.Object:
    mesh = bpy.data.meshes.new("Drones")
    drones = bpy.data.objects.new("Drones", mesh)
    bpy.context.scene.collection.objects.link(drones)
    return drones


def set_drones_position(
    drones: bpy.types.Object,
    positions: list[tuple[float, float, float]],
) -> None:
    bm = bmesh.new()
    for position in positions:
        bm.verts.new(position)
    bm.to_mesh(cast(bpy.types.Mesh, drones.data))
    bm.free()


XYZ_FCURVES = tuple[bpy.types.FCurve, bpy.types.FCurve, bpy.types.FCurve]


def import_drone_show_position(drones: bpy.types.Object, show_user: ShowUser) -> None:
    set_drones_position(drones, [(0, 0, 0) for _ in range(show_user.nb_drones)])

    drones_xyz_fcurves: list[XYZ_FCURVES] = [
        cast(
            XYZ_FCURVES,
            tuple(
                find_fcurve_or_create(
                    cast(bpy.types.Mesh, drones.data),
                    f"vertices[{drone_index}].co",
                    axis_index,
                )
                for axis_index in range(3)
            ),
        )
        for drone_index in range(show_user.nb_drones)
    ]

    for xyz_fcurves, drone_user in zip(drones_xyz_fcurves, show_user.drones_user, strict=True):
        add_takeoff_land_intermediate_position(
            drone_user.position_events, show_user.rtl_start_frame
        )
        nb_position_events = len(drone_user.position_events)

        for axis_index, axis_fcurve in enumerate(xyz_fcurves):
            axis_fcurve.keyframe_points.clear()
            axis_fcurve.keyframe_points.add(nb_position_events)

            for position_index, position_event in enumerate(drone_user.position_events):
                keyframe = axis_fcurve.keyframe_points[position_index]
                keyframe.co = (
                    position_event.frame,
                    position_event.xyz[axis_index],
                )


def get_drones_color(drones: bpy.types.Object) -> list[RGBW]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    drones_eval = cast(bpy.types.Object, drones.evaluated_get(depsgraph))
    return [
        cast(RGBW, tuple(color_data.color))
        for color_data in cast(
            bpy.types.FloatColorAttribute,
            cast(bpy.types.Mesh, drones_eval.data).attributes["Color"],
        ).data
    ]
