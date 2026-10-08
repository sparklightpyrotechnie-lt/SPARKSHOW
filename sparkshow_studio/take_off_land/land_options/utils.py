from typing import TYPE_CHECKING

from sparkshow_studio._loader.parameters import LAND_PARAMETERS

from ...setup import FPS
from ...tools.color_tools import register_emission_color
from ...tools.fcurve_tools import change_keyframes_type, find_fcurve
from ...tools.scene_tools import create_family_grids
from ..utils import add_position, keyframe_location

if TYPE_CHECKING:
    import bpy

    from ...setup import Lightshow

from mathutils import Vector


def _set_smoothstep_segment(fcurve: "bpy.types.FCurve", start_frame: int, end_frame: int) -> None:
    duration = float(end_frame - start_frame)
    if duration <= 0.0:
        return
    for key in fcurve.keyframe_points:
        frame = float(key.co[0])
        if abs(frame - float(start_frame)) < 1e-6 or abs(frame - float(end_frame)) < 1e-6:
            key.interpolation = "BEZIER"
            key.handle_left_type = "FREE"
            key.handle_right_type = "FREE"
            key.handle_left = (frame - duration / 3.0, float(key.co[1]))
            key.handle_right = (frame + duration / 3.0, float(key.co[1]))
    fcurve.update()


def remove_constraints_influence(
    scene: "bpy.types.Scene",
    lightshow: "Lightshow",
    drone: "bpy.types.Object",
) -> None:
    """Remove the influence of the constraints on the drone."""
    for constraint in drone.constraints:
        constraint.keyframe_insert(data_path="influence", frame=scene.frame_current - 1)

        constraint.influence = 0
        constraint.keyframe_insert(data_path="influence", frame=scene.frame_current)
        change_keyframes_type(
            find_fcurve(drone, f'constraints["{constraint.name}"].influence'),
            [scene.frame_current],
            lightshow.land_keyframe,
        )


def land_drone(
    lightshow: "Lightshow",
    drone: "bpy.types.Object",
    location: Vector,
    land_start_frame: int,
    set_keyframe: bool = True,
) -> int:
    first_vertical_position = float(location.z)

    land_middle_frame = land_start_frame + int(
        FPS * LAND_PARAMETERS.get_first_land_second_delta(first_vertical_position),
    )
    land_end_frame = (
        land_start_frame
        + int(FPS * LAND_PARAMETERS.get_land_second_delta(first_vertical_position))
        + 1
    )

    drone.location = location
    if set_keyframe:
        keyframe_location(drone, frame=land_start_frame)

    add_position(
        drone, land_middle_frame, z=LAND_PARAMETERS.get_first_land_altitude(first_vertical_position)
    )
    add_position(drone, land_end_frame, z=0)
    for index in range(3):
        change_keyframes_type(
            find_fcurve(drone, "location", index),
            [land_start_frame, land_middle_frame, land_end_frame],
            lightshow.land_keyframe,
        )

    # Exact zero-velocity cubic easing for both descent phases.
    fcurve_z = find_fcurve(drone, "location", 2)
    _set_smoothstep_segment(fcurve_z, land_start_frame, land_middle_frame)
    _set_smoothstep_segment(fcurve_z, land_middle_frame, land_end_frame)

    # Switch off all the LEDs
    register_emission_color(
        drone, (0.0, 0.0, 0.0, 0.0), "CONSTANT", lightshow.land_keyframe, land_start_frame
    )

    return land_end_frame


def rtl_drone(  # noqa: PLR0913
    drone: "bpy.types.Object",
    wait_time: int | None,
    duration: int,
    land_altitude: float,
    reposition_duration: int,
    scene: "bpy.types.Scene",
    lightshow: "Lightshow",
    land_last_frame: int,
    set_keyframe: bool = True,
    rtl_start_frame: int | None = None,
) -> int:
    if wait_time is None:
        return land_last_frame

    if rtl_start_frame is not None:
        scene.frame_set(rtl_start_frame + 1)
    location = drone.matrix_world.to_translation()
    remove_constraints_influence(scene, lightshow, drone)

    keyframe_location(drone, scene.frame_current - 1)
    drone.location = location
    keyframe_location(drone, scene.frame_current)
    rtl_start_frame = scene.frame_current + wait_time
    keyframe_location(drone, rtl_start_frame)

    takeoff_location = get_takeoff_location(drone)
    land_location = takeoff_location + Vector((0, 0, land_altitude))

    land_start_frame = rtl_start_frame + duration + reposition_duration
    drone.location = land_location

    if set_keyframe:
        reposition_frame = rtl_start_frame + duration
        keyframe_location(drone, reposition_frame)
        keyframe_location(drone, land_start_frame)

    last_end_frame = land_drone(
        lightshow, drone, land_location, land_start_frame, set_keyframe=set_keyframe
    )
    return max(land_last_frame, last_end_frame)


def get_takeoff_location(drone: "bpy.types.Object") -> Vector:
    xyz_fcurves = [find_fcurve(drone, "location", index) for index in range(3)]
    return Vector(tuple(fcurve.keyframe_points[0].co[1] for fcurve in xyz_fcurves))


def get_grids(lightshow: "Lightshow", step: float) -> list["bpy.types.Object"]:
    return create_family_grids(
        nb_drones_per_family=lightshow.nb_drones_per_family,
        nb_x=lightshow.nb_x,
        nb_y=lightshow.nb_y,
        step=step,
        angle=lightshow.angle_takeoff,
    )
