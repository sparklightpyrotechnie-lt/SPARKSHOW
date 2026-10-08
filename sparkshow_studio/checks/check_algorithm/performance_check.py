from typing import TYPE_CHECKING

from sparkshow_studio._loader.reports import PerformanceReport
from sparkshow_studio._loader.schemas import ShowUser

from ...setup import POSITION_FRAME_STEP, get_lightshow, get_physic_parameters
from ...tools.collection_tools import get_drone_index_from_blender_drone, select_drones_from_indices
from ...tools.export_tools import (
    is_event_breaking_monotony,
    is_event_in_flight,
    is_event_non_redundant,
)
from ...tools.takeoff_land_tools import DroneInfo, get_drone_infos

if TYPE_CHECKING:
    import bpy


def update_performance_show_user(drone_info: DroneInfo, frame: int) -> None:
    xyz_blender = drone_info.blender_drone.matrix_world.to_translation()
    xyz_user = (xyz_blender[0], xyz_blender[1], xyz_blender[2])
    if (is_event_in_flight(frame, drone_info.drone_frames)) and (
        is_event_non_redundant(xyz_user, drone_info.user_drone)
    ):
        if is_event_breaking_monotony(frame, drone_info, 0):
            drone_info.user_drone.add_position_event(
                frame - POSITION_FRAME_STEP,
                drone_info.user_drone.position_events[-1].xyz,
            )
        drone_info.user_drone.add_position_event(frame, xyz_user)


def get_show_user_performance_from_blender_drones(
    blender_drones: list["bpy.types.Object"],
    scene: "bpy.types.Scene",
    frame_start: int,
    frame_end: int,
) -> ShowUser:
    lightshow = get_lightshow(scene)
    show_user = ShowUser.create(
        nb_drones=len(blender_drones),
        angle_takeoff=lightshow.angle_takeoff,
        step_x=lightshow.step_x,
        step_y=lightshow.step_y,
    )
    show_user.rtl_start_frame = (
        lightshow.rtl_start_frame if lightshow.rtl_start_frame != -1 else None
    )
    show_user.update_drones_user_indices(
        [
            get_drone_index_from_blender_drone(blender_drone, scene.collection)
            for blender_drone in blender_drones
        ],
    )
    drone_infos = get_drone_infos(blender_drones, show_user, frame_end)
    lightshow = get_lightshow(scene)
    for frame in range(
        POSITION_FRAME_STEP * (frame_start // POSITION_FRAME_STEP),
        frame_end,
        POSITION_FRAME_STEP,
    ):
        scene.frame_set(frame)
        for drone_info in drone_infos:
            update_performance_show_user(drone_info, frame)
    show_user.drones_user = [
        drone_user for drone_user in show_user.drones_user if len(drone_user.position_events) > 1
    ]
    return show_user


def apply_performance_check(
    blender_drones: list["bpy.types.Object"],
    frame_start: int,
    frame_end: int,
    scene: "bpy.types.Scene",
) -> str:
    show_user = get_show_user_performance_from_blender_drones(
        blender_drones,
        scene,
        frame_start,
        frame_end,
    )
    lightshow = get_lightshow(scene)
    show_user.physic_parameters = get_physic_parameters(lightshow)

    performance_report = PerformanceReport.generate(show_user, is_partial=True)
    if not len(performance_report):
        return "OK"
    first_performance_infraction = performance_report.performance_infractions[0]
    scene.frame_set(first_performance_infraction.frame)

    (blender_drone,) = select_drones_from_indices({first_performance_infraction.drone_index}, scene)

    nb_drones = len(
        {
            performance_infraction.drone_index
            for performance_infraction in performance_report.performance_infractions
        }
    )

    return (
        f"Performance infraction [{first_performance_infraction.performance_name}] "
        f"with the drone {blender_drone.name} "
        f"at the frame {first_performance_infraction.frame} "
        f"with the value {first_performance_infraction.value:.2f} "
        f"(total infractions: {len(performance_report.performance_infractions)} on {nb_drones} drones)"
    )
