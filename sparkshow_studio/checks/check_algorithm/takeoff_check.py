from typing import TYPE_CHECKING

from sparkshow_studio._loader.reports import TakeoffFormatReport
from sparkshow_studio._loader.schemas import ShowUser

from ...setup import get_lightshow
from ...tools.collection_tools import get_drone_index_from_blender_drone, select_drones_from_indices
from ...tools.export_tools import update_show_user_export
from ...tools.fcurve_tools import find_fcurve_or_none
from ...tools.takeoff_land_tools import get_drone_infos

if TYPE_CHECKING:
    import bpy


def get_takeoff_end_frame(drone: "bpy.types.Object") -> int | None:
    fcurve_z = find_fcurve_or_none(drone, "location", 2)
    if fcurve_z is None or len(fcurve_z.keyframe_points) < 3:
        return None
    return int(fcurve_z.keyframe_points[2].co[0])


def get_takeoff_show_user_from_blender_drones(
    blender_drones: list["bpy.types.Object"],
    scene: "bpy.types.Scene",
) -> ShowUser:
    lightshow = get_lightshow(scene)
    show_user = ShowUser.create(
        nb_drones=len(blender_drones),
        angle_takeoff=lightshow.angle_takeoff,
        step_x=lightshow.step_x,
        step_y=lightshow.step_y,
    )
    show_user.update_drones_user_indices(
        [
            get_drone_index_from_blender_drone(blender_drone, scene.collection)
            for blender_drone in blender_drones
        ],
    )
    last_takeoff_end_frame = max(
        takeoff_end_frame
        for takeoff_end_frame in (
            get_takeoff_end_frame(blender_drone) for blender_drone in blender_drones
        )
        if takeoff_end_frame is not None
    )
    drone_infos = get_drone_infos(
        blender_drones,
        show_user,
        last_takeoff_end_frame + 1,
    )
    update_show_user_export(
        drone_infos,
        scene,
        frame_offset=0,
        frame_end=max(drone_info.drone_frames.frame_dance_start for drone_info in drone_infos) + 1,
    )
    return show_user


def apply_takeoff_check(
    blender_drones: list["bpy.types.Object"],
    scene: "bpy.types.Scene",
) -> str | None:
    show_user = get_takeoff_show_user_from_blender_drones(blender_drones, scene)
    takeoff_report = TakeoffFormatReport.generate(show_user)
    if not len(takeoff_report):
        return None

    select_drones_from_indices(
        {drone_user.drone_index for drone_user in takeoff_report.drone_users},
        scene,
    )

    return f"There are {len(takeoff_report.drone_users)} invalid takeoff."
