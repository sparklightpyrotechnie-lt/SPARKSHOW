import bpy

from sparkshow_studio._loader.reports import DanceSizeReport
from sparkshow_studio._loader.schemas import DronePx4, ShowUser

from ...setup import get_lightshow
from ...tools.collection_tools import get_drone_index_from_blender_drone, select_drones_from_indices
from ...tools.export_tools import update_show_user_export
from ...tools.fcurve_tools import get_last_frame_used
from ...tools.takeoff_land_tools import get_drone_infos


def get_dance_size_show_user_from_blender_drones(
    blender_drones: list[bpy.types.Object],
    scene: bpy.types.Scene,
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

    last_frame = get_last_frame_used(scene)
    drone_infos = get_drone_infos(blender_drones, show_user, last_frame)

    drone_infos_last_frame = max(drone_info.drone_frames.frame_end for drone_info in drone_infos)

    update_show_user_export(drone_infos, scene)
    scene.frame_set(drone_infos_last_frame)
    return show_user


def apply_dance_size_check(
    blender_drones: list[bpy.types.Object],
    scene: bpy.types.Scene,
) -> DanceSizeReport:
    show_user = get_dance_size_show_user_from_blender_drones(blender_drones, scene)

    autopilot_format = DronePx4.from_show_user(show_user)
    dance_size_report = DanceSizeReport.generate(autopilot_format)

    select_drones_from_indices(
        {
            dance_size_infraction.drone_index
            for dance_size_infraction in dance_size_report.dance_size_infractions
            if len(dance_size_infraction)
        },
        scene,
    )
    return dance_size_report


def get_dance_size_informations(dance_size_report: DanceSizeReport) -> str:
    return "\n".join(
        f"""\
Dance size of the drone {dance_size_infraction.drone_index}
Position events size percentage: {dance_size_infraction.position_percent}
Color events size percentage: {dance_size_infraction.color_percent}
Fire events size percentage: {dance_size_infraction.fire_percent}
Total events size percentage: {dance_size_infraction.total_percent}
"""
        for dance_size_infraction in dance_size_report.dance_size_infractions
    )
