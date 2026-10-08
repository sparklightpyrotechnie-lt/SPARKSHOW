from typing import TYPE_CHECKING

from ..tools.fcurve_tools import change_keyframes_type, find_fcurve

if TYPE_CHECKING:
    import bpy

    from ..setup import KeyframeType


def keyframe_fire(  # noqa: PLR0913
    drone: "bpy.types.Object",
    index: int,
    frame: int,
    duration: int,
    keyframe_type: "KeyframeType",
    vdl: str,
    *,
    preview_position: tuple[float, float, float] | None = None,
) -> None:
    drone["fire"][index] = duration
    drone[f"fire_vdl{index}"] = vdl
    drone.keyframe_insert(data_path='["fire"]', index=index, frame=frame)
    change_keyframes_type(find_fcurve(drone, '["fire"]', index), [frame], keyframe_type)

    # Non-exported viewport preview snapshot. Manual fire uses the current evaluated
    # position; import paths can explicitly provide the event position when known.
    try:
        from .preview import record_event_position

        record_event_position(drone, index, frame, position=preview_position)
    except ImportError:
        # Keeps unit-test/import contexts that do not load the optional preview path.
        pass
