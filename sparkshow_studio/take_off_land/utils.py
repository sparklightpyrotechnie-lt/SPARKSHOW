from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import bpy


def add_position(
    blender_drone: "bpy.types.Object",
    frame: int,
    x: float | None = None,
    y: float | None = None,
    z: float | None = None,
) -> None:
    """Add a keyframe for the position of the drone."""
    if x is not None:
        blender_drone.location.x = x
    if y is not None:
        blender_drone.location.y = y
    if z is not None:
        blender_drone.location.z = z

    blender_drone.keyframe_insert(data_path="location", frame=frame)


def keyframe_location(drone: "bpy.types.Object", frame: int) -> None:
    drone.keyframe_insert(data_path="location", frame=frame)
