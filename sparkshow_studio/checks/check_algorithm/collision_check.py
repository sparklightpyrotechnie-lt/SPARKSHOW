from typing import TYPE_CHECKING

from sparkshow_studio._loader.parameters import IostarPhysicParameters
from sparkshow_studio._loader.reports import CollisionReport
from sparkshow_studio._loader.schemas import ShowUser

from ...setup import get_lightshow
from ...tools.collection_tools import get_drone_index_from_blender_drone, select_drones_from_indices
from ...tools.export_tools import update_show_user_export
from ...tools.takeoff_land_tools import get_drone_infos

if TYPE_CHECKING:
    import bpy


def get_show_simulation_from_blender_drones(
    blender_drones: list["bpy.types.Object"],
    frame_start: int,
    frame_end: int,
    scene: "bpy.types.Scene",
) -> ShowUser:
    lightshow = get_lightshow(scene)
    show_user = ShowUser.create(
        nb_drones=len(blender_drones),
        angle_takeoff=lightshow.angle_takeoff,
        step_x=lightshow.step_x,
        step_y=lightshow.step_y,
    )

    show_user.rtl_start_frame = (
        lightshow.rtl_start_frame if lightshow.rtl_start_frame > -1 else None
    )
    show_user.takeoff_end_frame = (
        lightshow.takeoff_end_frame if lightshow.takeoff_end_frame > -1 else None
    )

    show_user.update_drones_user_indices(
        [
            get_drone_index_from_blender_drone(blender_drone, scene.collection)
            for blender_drone in blender_drones
        ],
    )
    drone_infos = get_drone_infos(
        blender_drones,
        show_user,
        frame_end,
        first_frame=frame_start,
    )
    update_show_user_export(drone_infos, scene, frame_offset=0)
    return show_user


def apply_collision_check(
    blender_drones: list["bpy.types.Object"],
    frame_start: int,
    frame_end: int,
    scene: "bpy.types.Scene",
) -> tuple[str, set[frozenset[int]]]:
    show_simulation = get_show_simulation_from_blender_drones(
        blender_drones,
        frame_start,
        frame_end,
        scene,
    )
    show_simulation.physic_parameters = IostarPhysicParameters(
        minimum_distance=get_lightshow(scene).collision_distance,
    )
    collision_report = CollisionReport.generate(
        show_simulation,
        is_partial=True,
    )
    if not len(collision_report):
        return "OK", set()

    collision_infractions = collision_report.collision_infractions
    first_collision_infraction = collision_infractions[0]
    scene.frame_set(first_collision_infraction.frame)

    blender_drone1, blender_drone2 = select_drones_from_indices(
        {
            first_collision_infraction.drone_index_1,
            first_collision_infraction.drone_index_2,
        },
        scene,
    )

    collision_couples = {
        frozenset((infraction.drone_index_1, infraction.drone_index_2))
        for infraction in collision_infractions
    }
    total_collisions = len(collision_couples)
    nb_drones = len(
        {
            drone_index
            for infraction in collision_infractions
            for drone_index in (infraction.drone_index_1, infraction.drone_index_2)
        }
    )

    return (
        (
            f"Collision at the frame {first_collision_infraction.frame} between the drones "
            f"{blender_drone1.name} and {blender_drone2.name} "
            f"with a distance of {first_collision_infraction.distance:.2f} meters "
            f"(total collisions: {total_collisions} on {nb_drones} drones)"
        ),
        collision_couples,
    )
