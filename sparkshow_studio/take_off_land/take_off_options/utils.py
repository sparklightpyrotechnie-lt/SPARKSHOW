from typing import TYPE_CHECKING

from ...setup import FPS
from ...tools.fcurve_tools import change_keyframes_type, find_fcurve
from ...tools.takeoff_land_tools import get_takeoff_duration
from ..utils import add_position

if TYPE_CHECKING:
    import bpy

    from ...setup import Lightshow
    from ..take_off_land_base import KeyframeType


def _set_smoothstep_segment(fcurve: "bpy.types.FCurve", start_frame: int, end_frame: int) -> None:
    duration = float(end_frame - start_frame)
    if duration <= 0.0:
        return
    for key in fcurve.keyframe_points:
        frame = float(key.co[0])
        if abs(frame - float(start_frame)) < 1e-6:
            key.interpolation = "BEZIER"
            key.handle_left_type = "FREE"
            key.handle_right_type = "FREE"
            key.handle_left = (frame - duration / 3.0, float(key.co[1]))
            key.handle_right = (frame + duration / 3.0, float(key.co[1]))
        elif abs(frame - float(end_frame)) < 1e-6:
            key.interpolation = "BEZIER"
            key.handle_left_type = "FREE"
            key.handle_right_type = "FREE"
            key.handle_left = (frame - duration / 3.0, float(key.co[1]))
            key.handle_right = (frame + duration / 3.0, float(key.co[1]))
    fcurve.update()


def takeoff_drone(
    blender_drone: "bpy.types.Object",
    frames: list[int],
    takeoff_position: tuple[float | None, float | None, float | None],
    takeoff_height: float,
    takeoff_keyframe_type: "KeyframeType",
) -> None:
    blender_drone.lock_location = (True, True, True)
    x, y, z = takeoff_position
    frame_start_takeoff, frame_middle_takeoff, frame_end_takeoff = frames

    # Three semantic flight states are enough when the F-curves use an exact
    # zero-velocity cubic at each segment boundary. The previous implementation
    # inserted a handful of extra keys near the end of the transition, which
    # created tangent discontinuities and acceleration spikes.
    add_position(blender_drone, frame_start_takeoff, z=0.0)
    add_position(blender_drone, frame_middle_takeoff, z=takeoff_height)
    add_position(blender_drone, frame_end_takeoff, x=x, y=y, z=z)

    frames = [frame_start_takeoff, frame_middle_takeoff, frame_end_takeoff]
    for index in range(3):
        fcurve = find_fcurve(blender_drone, "location", index)
        change_keyframes_type(fcurve, frames, takeoff_keyframe_type, interpolation="BEZIER")
        _set_smoothstep_segment(fcurve, frame_start_takeoff, frame_middle_takeoff)
        _set_smoothstep_segment(fcurve, frame_middle_takeoff, frame_end_takeoff)


def get_takeoff_frames(scene: "bpy.types.Scene", lightshow: "Lightshow") -> tuple[int, int, int]:
    props = getattr(scene, "takeoff_props", None)
    assert props is not None, "Takeoff properties not found in the scene"

    frame_start_takeoff = scene.frame_current
    frame_middle_takeoff = frame_start_takeoff + round(
        props.takeoff_duration * FPS,
    )

    takeoff_duration_second = get_takeoff_duration(
        lightshow.takeoff_altitude - props.takeoff_height,
        a=lightshow.acc_max,
        vmax=lightshow.vel_up_max,
        transition_duration=props.transition_duration,
    )
    frame_end_takeoff = frame_middle_takeoff + round(takeoff_duration_second * FPS)

    return frame_start_takeoff, frame_middle_takeoff, frame_end_takeoff
