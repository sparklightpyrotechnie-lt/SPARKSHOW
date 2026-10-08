from math import ceil
from typing import TYPE_CHECKING, cast

import bpy

if TYPE_CHECKING:
    from ..setup import KeyframeType


Animatable = bpy.types.Curve | bpy.types.Object | bpy.types.NodeTree | bpy.types.Mesh


def find_fcurve_or_none_from_fcurves(
    fcurves: bpy.types.ActionFCurves,
    data_path: str,
    array_index: int = -1,
) -> bpy.types.FCurve | None:
    """Find fcurve with given data_path and array_index in the given fcurves.

    Returns:
        First fcurve found or None if search failed
    """
    for fcurve in fcurves:
        if fcurve.data_path == data_path and array_index in (fcurve.array_index, -1):
            return fcurve
    return None


def find_fcurve_or_none(
    struct: Animatable,
    data_path: str,
    array_index: int = -1,
) -> bpy.types.FCurve | None:
    """Find fcurve with given data_path and array_index.

    Returns:
        First fcurve found or None if search failed
    """
    if (
        cast(bpy.types.AnimData | None, struct.animation_data) is None
        or struct.animation_data.action is None
    ):
        return None
    return find_fcurve_or_none_from_fcurves(
        struct.animation_data.action.fcurves,
        data_path,
        array_index,
    )


def find_fcurve(
    struct: Animatable,
    data_path: str,
    array_index: int = -1,
) -> bpy.types.FCurve:
    """Find fcurve with given data_path and array_index.

    Raise:
        RuntimeError if search failed
    """
    fcurve = find_fcurve_or_none(struct, data_path, array_index)
    if fcurve is None:
        msg = f"Could not find fcurve with data_path={data_path} and array_index={array_index}"
        raise RuntimeError(msg)
    return fcurve


def find_fcurve_or_create(
    struct: Animatable,
    data_path: str,
    array_index: int = -1,
) -> bpy.types.FCurve:
    """Find fcurve with given data_path and array_index.

    If no fcurve is found, create a new one.

    Returns:
        First fcurve found or new fcurve created
    """
    fcurve = find_fcurve_or_none(struct, data_path, array_index)
    if fcurve is not None:
        return fcurve
    if cast(bpy.types.AnimData | None, struct.animation_data) is None:
        struct.animation_data_create()
    if struct.animation_data.action is None:
        struct.animation_data.action = bpy.data.actions.new(name=struct.name)
    return struct.animation_data.action.fcurves.new(data_path, index=array_index)


def change_interpolation(fcurve: bpy.types.FCurve, interpolation: str, frame: int) -> None:
    """Set the interpolation method on the given frame."""
    index = None
    for i, keyframe_point in enumerate(fcurve.keyframe_points):
        if keyframe_point.co[0] == frame:
            index = i
            break
        if keyframe_point.co[0] > frame:
            if i == 0:
                return
            index = i - 1
            break
        index = i
    if index is not None:
        fcurve.keyframe_points[index].interpolation = interpolation  # type: ignore


def get_frame(fcurve: bpy.types.FCurve, index: int) -> int:
    """Get the frame of the keyframe at the given index."""
    return int(round(fcurve.keyframe_points[index].co[0]))


def get_len(fcurve: bpy.types.FCurve) -> int:
    """Get the length of the list keyframe_points."""
    return len(fcurve.keyframe_points)


RGBW_EMISSION_MATERIAL_DATA_PATH = 'nodes["RGBW Emission"].inputs[0].default_value'

DATA_PATHS = [
    "location",
    "color",
    "rotation",
    "scale",
    "diffuse_color",
    RGBW_EMISSION_MATERIAL_DATA_PATH,
    "constraints",
    '["fire"]',
]


def get_last_frame_used(scene: bpy.types.Scene) -> int:
    """Get the last frame used in the scene."""
    last_frame = scene.frame_end
    for action in bpy.data.actions:
        for fcurve in action.fcurves:
            if (
                any(fcurve.data_path.startswith(data_path) for data_path in DATA_PATHS)
                and fcurve.keyframe_points
            ):
                last_frame = max(last_frame, ceil(fcurve.keyframe_points[-1].co[0]))
    return last_frame


def change_keyframes_type(
    fcurve: bpy.types.FCurve,
    frames: list[int],
    keyframe_type: "KeyframeType",
    interpolation: str = "BEZIER",
) -> None:
    frames_iter = iter(frames)
    frame = next(frames_iter)
    try:
        for keyframe_point in fcurve.keyframe_points:
            while keyframe_point.co[0] > frame:
                frame = next(frames_iter)
            if keyframe_point.co[0] == frame:
                keyframe_point.type = keyframe_type
                frame = next(frames_iter)
                keyframe_point.interpolation = interpolation  # pyright: ignore
    except StopIteration:
        pass


def copy_keyframe(source_keyframe: bpy.types.Keyframe, target_keyframe: bpy.types.Keyframe) -> None:
    """Copy the values from the target keyframe to the source keyframe."""
    target_keyframe.amplitude = source_keyframe.amplitude
    target_keyframe.back = source_keyframe.back
    target_keyframe.co = source_keyframe.co
    target_keyframe.easing = source_keyframe.easing
    target_keyframe.handle_left = source_keyframe.handle_left
    target_keyframe.handle_left_type = source_keyframe.handle_left_type
    target_keyframe.handle_right = source_keyframe.handle_right
    target_keyframe.handle_right_type = source_keyframe.handle_right_type
    target_keyframe.interpolation = source_keyframe.interpolation
    target_keyframe.period = source_keyframe.period
    target_keyframe.type = source_keyframe.type


def remove_range_keyframes(fcurve: bpy.types.FCurve, frame_start: int, frame_end: int) -> None:
    """Remove all keyframes in the range [frame_start, frame_end]."""
    for keyframe in reversed(fcurve.keyframe_points):
        if frame_start <= round(keyframe.co[0]) <= frame_end:
            fcurve.keyframe_points.remove(keyframe)
