import itertools
from collections.abc import Generator, Iterator
from typing import TYPE_CHECKING, TypeVar, cast

import numpy as np
from tqdm import tqdm

from ..setup import POSITION_FRAME_STEP
from .color_tools import (
    RGBW,
    check_color_keyframes_consistency,
    get_color_fcurves,
    get_colors_keyframes,
    get_keyframes_color,
)
from .fcurve_tools import find_fcurve_or_none

if TYPE_CHECKING:
    import bpy

    from sparkshow_studio._loader.schemas import DroneUser

    from .takeoff_land_tools import DroneFrames, DroneInfo


def is_event_mandatory(frame: int, drone_frames: "DroneFrames") -> bool:
    return frame in {
        drone_frames.frame_start,
        drone_frames.frame_dance_start,
        drone_frames.frame_end,
    }


def is_event_in_flight(frame: int, drone_frames: "DroneFrames") -> bool:
    return (
        frame > drone_frames.frame_dance_start
        and frame < drone_frames.frame_end
        and frame % POSITION_FRAME_STEP == 0
    )


def is_event_non_redundant(xyz: tuple[float, float, float], user_drone: "DroneUser") -> bool:
    return len(user_drone.position_events) == 0 or xyz != user_drone.position_events[-1].xyz


def is_event_breaking_monotony(frame: int, drone_info: "DroneInfo", frame_offset: int) -> bool:
    return (
        len(drone_info.user_drone.position_events) != 0
        and (
            frame
            != drone_info.user_drone.position_events[-1].frame + frame_offset + POSITION_FRAME_STEP
        )
        and (frame - POSITION_FRAME_STEP > drone_info.drone_frames.frame_dance_start)
    )


def add_position_events_export(drone_info: "DroneInfo", frame: int, frame_offset: int) -> None:
    xyz_blender = drone_info.blender_drone.matrix_world.to_translation()
    xyz_user = (xyz_blender[0], xyz_blender[1], xyz_blender[2])
    if is_event_mandatory(frame, drone_info.drone_frames):
        drone_info.user_drone.add_position_event(frame - frame_offset, xyz_user)
    if is_event_in_flight(frame, drone_info.drone_frames) and (
        is_event_non_redundant(xyz_user, drone_info.user_drone)
    ):
        if is_event_breaking_monotony(frame, drone_info, frame_offset):
            drone_info.user_drone.add_position_event(
                frame - frame_offset - POSITION_FRAME_STEP,
                drone_info.user_drone.position_events[-1].xyz,
            )
        drone_info.user_drone.add_position_event(frame - frame_offset, xyz_user)


T = TypeVar("T")


def pairwise(iterable: Iterator[T]) -> Iterator[tuple[T, T | None]]:
    """S -> (s0,s1), (s1,s2), (s2, s3), ..."""
    a, b = itertools.tee(iterable)
    return zip(a, itertools.chain(itertools.islice(b, 1, None), [None]), strict=False)


def add_color_events_export(
    drone_info: "DroneInfo",
    frame_offset: int,
    frame_end: int,
) -> None:
    rgbw_fcurves = get_color_fcurves(drone_info.blender_drone)
    if rgbw_fcurves is None:
        return

    rgbw_keyframes = get_colors_keyframes(rgbw_fcurves)
    if rgbw_keyframes is None:
        return

    for rgbw, next_rgbw in pairwise(rgbw_keyframes):
        frame, interpolation = check_color_keyframes_consistency(rgbw)

        if frame < frame_offset:
            continue
        if frame > frame_end:
            break

        color = get_keyframes_color(rgbw)

        drone_info.user_drone.add_color_event(
            frame - frame_offset,
            color,
            interpolate=interpolation != "CONSTANT",
        )

        if interpolation == "BEZIER" and next_rgbw is not None:
            next_frame, _ = check_color_keyframes_consistency(next_rgbw)

            for split_frame, split_color in split_bezier(
                rgbw_fcurves,
                frame,
                next_frame,
            ):
                if split_frame > frame_end:
                    break

                drone_info.user_drone.add_color_event(
                    split_frame - frame_offset,
                    cast(RGBW, split_color),
                    interpolate=True,
                )


def add_fire_events_export(
    drone_info: "DroneInfo",
    frame_offset: int,
    frame_end: int,
) -> None:
    for frame, channel_index, duration in sorted(
        [
            (frame - frame_offset, index, int(keyframe_point.co[1]))
            for index in range(3)
            if (fcurve := find_fcurve_or_none(drone_info.blender_drone, '["fire"]', index))
            is not None
            for keyframe_point in fcurve.keyframe_points
            if frame_offset <= (frame := int(keyframe_point.co[0])) <= frame_end
        ],
    ):
        vdl = cast(str, drone_info.blender_drone.get(f"fire_vdl{channel_index}", ""))
        drone_info.user_drone.add_fire_event(frame, channel_index, duration, vdl)


def add_yaw_events_export(
    drone_info: "DroneInfo",
    frame_offset: int,
    frame_end: int,
) -> None:
    if (
        drone_info.blender_drone.rotation_mode != "XYZ"
        or (fcurve := find_fcurve_or_none(drone_info.blender_drone, "rotation_euler", 2)) is None
    ):
        return

    for keyframe, next_keyframe in pairwise(
        cast(Iterator["bpy.types.Keyframe"], fcurve.keyframe_points)
    ):
        frame = round(keyframe.co[0])

        if frame < frame_offset:
            continue
        if frame > frame_end:
            break

        angle = round(np.rad2deg(keyframe.co[1]))
        interpolation = keyframe.interpolation

        drone_info.user_drone.add_yaw_event(frame - frame_offset, angle)

        if interpolation == "BEZIER" and next_keyframe is not None:
            next_frame = round(next_keyframe.co[0])

            for split_frame, (split_angle,) in split_bezier(
                (fcurve,),
                frame,
                next_frame,
            ):
                if split_frame > frame_end:
                    break

                drone_info.user_drone.add_yaw_event(
                    split_frame - frame_offset,
                    round(np.rad2deg(split_angle)),
                )


def update_show_user_export(
    drone_infos: list["DroneInfo"],
    scene: "bpy.types.Scene",
    *,
    frame_offset: int = 0,
    frame_end: int | None = None,
    with_yaw: bool = False,
) -> None:
    frame_start = min(drone_info.drone_frames.frame_start for drone_info in drone_infos)
    frame_end = (
        max(drone_info.drone_frames.frame_end for drone_info in drone_infos) + 1
        if frame_end is None
        else frame_end
    )

    for frame in tqdm(range(frame_start, frame_end), desc="Loading Blender events", unit="frame"):
        scene.frame_set(frame)
        for drone_info in drone_infos:
            add_position_events_export(drone_info, frame, frame_offset)
    for drone_info in drone_infos:
        add_color_events_export(drone_info, frame_offset, frame_end)
        add_fire_events_export(drone_info, frame_offset, frame_end)
        if with_yaw:
            add_yaw_events_export(drone_info, frame_offset, frame_end)

        drone_info.user_drone.clean_position_events()
        drone_info.user_drone.clean_color_events()


def evaluate_fcurves(fcurves: tuple["bpy.types.FCurve", ...], frame: int) -> tuple[float, ...]:
    return tuple(fcurve.evaluate(frame) for fcurve in fcurves)


def get_middle_keyframe(
    fcurves: tuple["bpy.types.FCurve", ...],
    start_frame: float,
    end_frame: float,
) -> tuple[int, tuple[float, ...]]:
    """Return the keyframe in the middle of the given frames."""
    frame = round(start_frame + (end_frame - start_frame) / 2)
    return frame, evaluate_fcurves(fcurves, frame)


def should_halt_splitting_bezier(
    start_frame: float,
    end_frame: float,
    min_frame_delta: int,
) -> bool:
    """Return False if the bezier curve should be split.

    `min_frame_delta` is the minimum number of frames between two keyframes.
    """
    return end_frame - start_frame < 2 * min_frame_delta


def split_bezier_left(
    fcurves: tuple["bpy.types.FCurve", ...],
    start_frame: float,
    end_frame: float,
    min_frame_delta: int,
) -> Generator[tuple[int, tuple[float, ...]], None, None]:
    """Return a generator of the keyframes of the bezier curve left split."""
    if should_halt_splitting_bezier(start_frame, end_frame, min_frame_delta):
        return
        yield

    frame, value = get_middle_keyframe(fcurves, start_frame, end_frame)
    yield from split_bezier_left(fcurves, start_frame, frame, min_frame_delta)
    yield frame, value
    yield get_middle_keyframe(fcurves, frame, end_frame)


def split_bezier_right(
    fcurves: tuple["bpy.types.FCurve", ...],
    start_frame: float,
    end_frame: float,
    min_frame_delta: int,
) -> Generator[tuple[int, tuple[float, ...]], None, None]:
    """Return a generator of the keyframes of the bezier curve right split."""
    if should_halt_splitting_bezier(start_frame, end_frame, min_frame_delta):
        return
        yield

    frame, value = get_middle_keyframe(fcurves, start_frame, end_frame)
    yield get_middle_keyframe(fcurves, start_frame, frame)
    yield frame, value
    yield from split_bezier_right(fcurves, frame, end_frame, min_frame_delta)


def split_bezier(
    fcurves: tuple["bpy.types.FCurve", ...],
    start_frame: float,
    end_frame: float,
    min_frame_delta: int = 2,
) -> Generator[tuple[int, tuple[float, ...]], None, None]:
    """Return a generator of the keyframes of the bezier curve split.

    `min_frame_delta` is the minimum number of frames between two keyframes after splitting.
    """
    if should_halt_splitting_bezier(start_frame, end_frame, min_frame_delta):
        return
        yield

    frame, value = get_middle_keyframe(fcurves, start_frame, end_frame)
    yield from split_bezier_left(fcurves, start_frame, frame, min_frame_delta)
    yield frame, value
    yield from split_bezier_right(fcurves, frame, end_frame, min_frame_delta)
