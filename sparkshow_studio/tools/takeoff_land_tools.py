from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from tqdm import tqdm

from sparkshow_studio._loader.parameters import IostarPhysicParameters

from .collection_tools import get_family_drones_by_index, get_family_index, get_selected_drones
from .fcurve_tools import find_fcurve, find_fcurve_or_none, get_frame

if TYPE_CHECKING:
    import bpy

    from sparkshow_studio._loader.schemas import DroneUser, ShowUser


@dataclass(frozen=True)
class DroneFrames:
    frame_start: int
    frame_dance_start: int
    frame_end: int


def has_drone_takeoff(
    blender_drone: "bpy.types.Object",
    frame: int | None = None,
) -> bool:
    fcurve_z = find_fcurve_or_none(blender_drone, "location", 2)
    return (
        fcurve_z is not None
        and len(fcurve_z.keyframe_points) > 2
        and (frame is None or frame > get_frame(fcurve_z, 2) + 1)
    )


def has_drone_land(
    blender_drone: "bpy.types.Object",
    *,
    frame: int | None = None,
    fcurve_z: Optional["bpy.types.FCurve"] = None,
) -> bool:
    if fcurve_z is None:
        fcurve_z = find_fcurve_or_none(blender_drone, "location", 2)

    if fcurve_z is None:
        return False

    if frame is None:
        frame = get_frame(fcurve_z, -1)

    return fcurve_z.evaluate(frame) == 0.0


def get_drone_frames(
    blender_drone: "bpy.types.Object",
    last_frame: int,
) -> DroneFrames:
    fcurve_z = find_fcurve(blender_drone, "location", 2)

    if not len(fcurve_z.keyframe_points) > 2:
        msg = "Could not get drone frames, some drones did not take off."
        raise RuntimeError(msg)

    if has_drone_land(blender_drone, fcurve_z=fcurve_z):
        return DroneFrames(
            get_frame(fcurve_z, 0),
            get_frame(fcurve_z, 1),
            get_frame(fcurve_z, -3),
        )

    return DroneFrames(
        get_frame(fcurve_z, 0),
        get_frame(fcurve_z, 1),
        last_frame,
    )


def get_selected_drones_to_takeoff(
    context: "bpy.types.Context",
) -> tuple[list["bpy.types.Object"], bool]:
    """Return the drones to takeoff are the first drones of selected families that hasn't taken off."""
    drones_to_takeoff: list[bpy.types.Object] = []
    taken_off_family_indices: set[int] = set()
    has_unselected_takeoff_drones = False

    for drone in tqdm(get_selected_drones(context), desc="Getting drones to takeoff", unit="drone"):
        # Skip the drones that has taken off or are in a family that has taken off.
        drone.select_set(False)
        has_takeoff = has_drone_takeoff(drone)
        family_index = get_family_index(drone)
        if has_takeoff or family_index in taken_off_family_indices:
            has_unselected_takeoff_drones = has_unselected_takeoff_drones or has_takeoff
            continue

        # Find the first drone of the family that hasn't taken off
        # and swap it with the selected drone.
        drone_to_takeoff = drone
        for family_drone in get_family_drones_by_index(context.scene.collection, family_index):
            if not has_drone_takeoff(family_drone):
                drone_to_takeoff = family_drone
                break
        if drone is context.active_object and drone_to_takeoff is not drone:
            context.view_layer.objects.active = drone_to_takeoff

        # Select the drone to takeoff and add it to the list.
        drone_to_takeoff.select_set(True)
        taken_off_family_indices.add(family_index)
        drones_to_takeoff.append(drone_to_takeoff)
    return drones_to_takeoff, has_unselected_takeoff_drones


def set_selected_drones_to_takeoff(drones: list["bpy.types.Object"]) -> None:
    """
    Input: list of all drones you want to take off.

    Select all drones that aren't taken off.
    """
    for drone in drones:
        drone.select_set(not has_drone_takeoff(drone))


def get_selected_drones_to_land(
    context: "bpy.types.Context",
) -> tuple[list["bpy.types.Object"], bool, bool]:
    """Return the selected drones that hasn't landed and deselect the others."""
    scene = context.scene
    drones_to_land: list[bpy.types.Object] = []
    has_unselected_land_drones = False
    has_unselected_takeoff_drones = False

    for drone in get_selected_drones(context):
        if has_drone_land(drone):
            drone.select_set(False)
            has_unselected_land_drones = True
        elif not has_drone_takeoff(drone, scene.frame_current):
            drone.select_set(False)
            has_unselected_takeoff_drones = True
        else:
            drones_to_land.append(drone)
    return drones_to_land, has_unselected_land_drones, has_unselected_takeoff_drones


@dataclass(frozen=True)
class DroneInfo:
    blender_drone: "bpy.types.Object"
    user_drone: "DroneUser"
    drone_frames: DroneFrames


def get_drone_infos(
    drones: list["bpy.types.Object"],
    show_user: "ShowUser",
    last_frame: int,
    *,
    first_frame: int | None = None,
) -> list[DroneInfo]:
    return [
        DroneInfo(
            drone,
            drone_user,
            get_drone_frames(drone, last_frame),
        )
        if first_frame is None
        else DroneInfo(
            drone,
            drone_user,
            DroneFrames(
                first_frame,
                first_frame,
                last_frame,
            ),
        )
        for drone, drone_user in tqdm(
            zip(
                drones,
                show_user.drones_user,
                strict=False,
            ),
            total=len(drones),
            desc="Getting drone infos",
            unit="drone",
        )
    ]


def get_takeoff_duration(
    takeoff_altitude: float,
    a: float = IostarPhysicParameters.acceleration_max,
    vmax: float = IostarPhysicParameters.velocity_up_max,
    transition_duration: float = 0,
) -> float:
    # Step 1: Calculate the distance required to reach vmax
    d1 = (vmax**2) / (2 * a)
    t1 = vmax / a

    if takeoff_altitude <= 2 * d1:
        # Case where maximum speed is not reached
        d_half = takeoff_altitude / 2
        vmax_reached = (2 * a * d_half) ** 0.5
        t_half = vmax_reached / a
        takeoff_duration = 2 * t_half
    else:
        # Case where there is a constant speed phase
        d2 = takeoff_altitude - 2 * d1
        t2 = d2 / vmax
        takeoff_duration = 2 * t1 + t2

    return max(takeoff_duration, transition_duration)  # Ensure a minimum duration of 10 seconds
