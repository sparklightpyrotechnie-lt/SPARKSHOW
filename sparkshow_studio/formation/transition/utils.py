from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional, cast

import mathutils
import numpy as np
import bpy

from ...checks.check_algorithm.collision_check import apply_collision_check
from ...tools.collection_tools import add_arrow as add_arrow_tool
from ...tools.collection_tools import (
    get_blender_drone_from_drone_index,
    get_drones_last_anchor,
    get_selected_drones,
)
from ...tools.fcurve_tools import change_keyframes_type, find_fcurve, find_fcurve_or_none
from ...tools.scene_tools import refresh_scene

DIRECTION_ARROW_SIZE = 3
DIRECTION_ARROW_NAME = "Direction Arrow"

if TYPE_CHECKING:
    import bpy
    from numpy.typing import NDArray

    from ...setup import KeyframeType


def get_direction_arrow(scene: "bpy.types.Scene") -> Optional["bpy.types.Object"]:
    return scene.collection.objects.get(DIRECTION_ARROW_NAME)


def add_arrow(scene: "bpy.types.Scene") -> "bpy.types.Object":
    return add_arrow_tool(scene, DIRECTION_ARROW_NAME, DIRECTION_ARROW_SIZE)


def unselect_last_anchor(drones: list["bpy.types.Object"]) -> None:
    for anchor in get_drones_last_anchor(drones):
        anchor.select_set(False)


def get_positions(
    drones: list["bpy.types.Object"],
    targets: list["bpy.types.Object"],
) -> tuple["NDArray[np.float32]", "NDArray[np.float32]"]:
    drone_positions = np.array(
        [drone.matrix_world.to_translation() for drone in drones],
        dtype=np.float32,
    )
    target_positions = np.array(
        [target.matrix_world.to_translation() for target in targets],
        dtype=np.float32,
    )
    return drone_positions, target_positions


def move_drone(  # noqa: PLR0913
    index: int,
    drone: "bpy.types.Object",
    target: "bpy.types.Object",
    frame_current: int,
    frame_end: int,
    frame_step: int,
    go_to_target_keyframe: "KeyframeType",
    interpolation: str = "BEZIER",
) -> None:
    """Create a transition that keeps following the target anchor.

    Sparkshow 4.1.17 keeps Blender's COPY_LOCATION transition behavior for
    dynamic anchors. This is intentional: anchors can belong to an animated
    mesh/rig, so baking only the target's current world position would break
    the essential behavior that the drone follows the anchor while the mesh
    moves.

    One COPY_LOCATION constraint is created for each transition, matching the
    proven 3.19.2 behavior. Existing 4.1 direct-location transitions remain
    supported by the compatibility helpers below.
    """
    constraint = cast(
        "bpy.types.CopyLocationConstraint",
        drone.constraints.new("COPY_LOCATION"),
    )
    constraint.name = f"Sparkshow Target {frame_current}_{frame_end}_{index:04d}"
    constraint.target = target

    constraint_frame_start = frame_current + index * frame_step
    constraint_frame_end = frame_end + index * frame_step

    # Keep metadata for tools that need to identify the most recently created
    # transition without depending exclusively on the constraint stack.
    drone["lsc_transition_start"] = constraint_frame_start
    drone["lsc_transition_end"] = constraint_frame_end
    drone["lsc_transition_target_name"] = target.name

    constraint.influence = 0.0
    constraint.keyframe_insert(
        data_path="influence",
        frame=constraint_frame_start,
    )
    constraint.influence = 1.0
    constraint.keyframe_insert(
        data_path="influence",
        frame=constraint_frame_end,
    )

    influence_fcurve = find_fcurve(
        drone,
        f'constraints["{constraint.name}"].influence',
    )

    change_keyframes_type(
        influence_fcurve,
        [constraint_frame_start, constraint_frame_end],
        go_to_target_keyframe,
        interpolation=interpolation,
    )

    # Use the exact cubic minimum-jerk/smoothstep position profile
    # expected by the speed/acceleration model:
    #     s(u) = 3u^2 - 2u^3
    # This gives vmax = 1.5 * D / T and amax = 6 * D / T^2.
    # With the duration limitation computed by the association algorithm,
    # this keeps the realized acceleration below lightshow.acc_max.
    if interpolation == "BEZIER":
        duration = float(constraint_frame_end - constraint_frame_start)
        if duration > 0.0:
            start_value = 0.0
            end_value = 1.0
            for key in influence_fcurve.keyframe_points:
                frame = float(key.co[0])
                if abs(frame - constraint_frame_start) < 1e-6:
                    # Exact cubic smoothstep: s(u)=3u²-2u³.
                    # Both endpoint tangents are explicitly horizontal so
                    # neighbouring animation keys cannot introduce a jump.
                    key.interpolation = "BEZIER"
                    key.handle_left_type = "FREE"
                    key.handle_right_type = "FREE"
                    key.handle_left = (
                        constraint_frame_start - duration / 3.0,
                        start_value,
                    )
                    key.handle_right = (
                        constraint_frame_start + duration / 3.0,
                        start_value,
                    )
                elif abs(frame - constraint_frame_end) < 1e-6:
                    key.interpolation = "BEZIER"
                    key.handle_left_type = "FREE"
                    key.handle_right_type = "FREE"
                    key.handle_left = (
                        constraint_frame_end - duration / 3.0,
                        end_value,
                    )
                    key.handle_right = (
                        constraint_frame_end + duration / 3.0,
                        end_value,
                    )
            influence_fcurve.update()

    # Selecting/unselecting targets is part of the existing workflow.
    target.select_set(False)

def get_sorted_couples(
    scene: "bpy.types.Scene",
    couples: list[tuple["bpy.types.Object", "bpy.types.Object"]],
    drone_positions: "NDArray[np.float32]",
    target_positions: "NDArray[np.float32]",
    frame_step: int,
) -> list[tuple["bpy.types.Object", "bpy.types.Object"]]:
    if frame_step == 0:
        return couples

    direction_arrow = get_direction_arrow(scene)

    if direction_arrow is not None:
        transition_direction = direction_arrow.rotation_euler.to_matrix() @ mathutils.Vector(
            (0, 0, 1)
        )
    else:
        transition_direction = mathutils.Vector((target_positions - drone_positions).mean(axis=0))

    def calculate_direction_scalar_product(
        couple: tuple["bpy.types.Object", "bpy.types.Object"],
    ) -> float:
        drone, _ = couple
        couple_direction = drone.matrix_world.to_translation()
        # scalar product between the direction and the vector from the drone to the target
        return transition_direction @ couple_direction

    return sorted(couples, key=calculate_direction_scalar_product, reverse=True)


def _last_transition_fcurves(
    drone: "bpy.types.Object",
) -> tuple[list["bpy.types.FCurve"], int, int] | None:
    if drone.animation_data is None or drone.animation_data.action is None:
        return None
    frame_start = drone.get("lsc_transition_start")
    frame_end = drone.get("lsc_transition_end")
    if frame_start is None or frame_end is None:
        return None
    fcurves = [
        drone.animation_data.action.fcurves.find("location", index=index)
        for index in range(3)
    ]
    if any(fcurve is None for fcurve in fcurves):
        return None
    return [f for f in fcurves if f is not None], int(frame_start), int(frame_end)


def get_last_copy_location_constraint(
    drone: "bpy.types.Object",
) -> tuple["bpy.types.CopyLocationConstraint", "bpy.types.FCurve"] | None:
    # Legacy compatibility: new transitions are direct location F-curves.
    for constraint in reversed(drone.constraints.values()):
        if constraint.type != "COPY_LOCATION":
            continue
        fcurve = find_fcurve_or_none(
            constraint.id_data,
            f'constraints["{constraint.name}"].influence',
        )
        if fcurve is not None:
            return cast("bpy.types.CopyLocationConstraint", constraint), fcurve
    return None


def get_last_copy_rotation_constraints(
    drones: list["bpy.types.Object"],
) -> list[tuple[Any, "bpy.types.FCurve"]]:
    """Return transition handles compatible with both v3 and v4.1 shows."""
    error_messages: list[str] = []
    result: list[tuple[Any, bpy.types.FCurve]] = []
    for drone in drones:
        legacy = get_last_copy_location_constraint(drone)
        if legacy is not None:
            result.append(legacy)
            continue
        transition = _last_transition_fcurves(drone)
        if transition is None:
            error_messages.append(f"{drone.name} did not go to a target")
            continue
        _, frame_start, frame_end = transition
        # A location X curve acts as the frame-range carrier for compatibility.
        fcurve = transition[0][0]
        # Ensure the expected transition endpoints exist.
        if not any(round(k.co[0]) == frame_start for k in fcurve.keyframe_points) or not any(
            round(k.co[0]) == frame_end for k in fcurve.keyframe_points
        ):
            error_messages.append(f"{drone.name} has an invalid transition")
        else:
            result.append((None, fcurve))
    if error_messages:
        raise ValueError("\n".join(error_messages))
    return result


def _set_location_keyframe_time(
    drone: "bpy.types.Object",
    old_frame: int,
    new_frame: int,
) -> None:
    if drone.animation_data is None or drone.animation_data.action is None:
        return
    for fcurve in (
        drone.animation_data.action.fcurves.find("location", index=0),
        drone.animation_data.action.fcurves.find("location", index=1),
        drone.animation_data.action.fcurves.find("location", index=2),
    ):
        if fcurve is None:
            continue
        for key in fcurve.keyframe_points:
            if round(key.co[0]) == old_frame:
                key.co[0] = new_frame
        fcurve.update()


def swap_order(drone1: "bpy.types.Object", drone2: "bpy.types.Object") -> None:
    t1 = _last_transition_fcurves(drone1)
    t2 = _last_transition_fcurves(drone2)
    if t1 is None or t2 is None:
        # Keep legacy behavior for old v3 transitions.
        legacy = get_last_copy_rotation_constraints([drone1, drone2])
        if any(item[0] is None for item in legacy):
            raise ValueError("Selected drones do not have compatible transitions")
        return _legacy_swap_order(drone1, drone2)
    _, start1, end1 = t1
    _, start2, end2 = t2
    delta = start2 - start1
    _set_location_keyframe_time(drone1, start1, start1 + delta)
    _set_location_keyframe_time(drone1, end1, end1 + delta)
    _set_location_keyframe_time(drone2, start2, start2 - delta)
    _set_location_keyframe_time(drone2, end2, end2 - delta)
    drone1["lsc_transition_start"] = start1 + delta
    drone1["lsc_transition_end"] = end1 + delta
    drone2["lsc_transition_start"] = start2 - delta
    drone2["lsc_transition_end"] = end2 - delta


def _legacy_swap_order(drone1: "bpy.types.Object", drone2: "bpy.types.Object") -> None:
    (constraint1, fcurve1), (constraint2, fcurve2) = get_last_copy_rotation_constraints([drone1, drone2])
    frame_start1 = fcurve1.keyframe_points[0].co[0]
    frame_end1 = fcurve1.keyframe_points[1].co[0]
    frame_start2 = fcurve2.keyframe_points[0].co[0]
    frame_end2 = fcurve2.keyframe_points[1].co[0]
    constraint1.keyframe_delete(data_path="influence", frame=frame_start1)
    constraint1.keyframe_delete(data_path="influence", frame=frame_end1)
    constraint2.keyframe_delete(data_path="influence", frame=frame_start2)
    constraint2.keyframe_delete(data_path="influence", frame=frame_end2)
    frame_delta = frame_start2 - frame_start1
    constraint1.influence = 0
    constraint1.keyframe_insert(data_path="influence", frame=frame_start1 + frame_delta)
    constraint1.influence = 1
    constraint1.keyframe_insert(data_path="influence", frame=frame_end1 + frame_delta)
    constraint2.influence = 0
    constraint2.keyframe_insert(data_path="influence", frame=frame_start2 - frame_delta)
    constraint2.influence = 1
    constraint2.keyframe_insert(data_path="influence", frame=frame_end2 - frame_delta)


def swap_target(drone1: "bpy.types.Object", drone2: "bpy.types.Object") -> None:
    t1 = _last_transition_fcurves(drone1)
    t2 = _last_transition_fcurves(drone2)
    if t1 is None or t2 is None:
        legacy1 = get_last_copy_location_constraint(drone1)
        legacy2 = get_last_copy_location_constraint(drone2)
        if legacy1 is None or legacy2 is None:
            raise ValueError("Selected drones do not have compatible transitions")
        legacy1[0].target, legacy2[0].target = legacy2[0].target, legacy1[0].target
        return
    fcurves1, _, end1 = t1
    fcurves2, _, end2 = t2
    for f1, f2 in zip(fcurves1, fcurves2, strict=True):
        k1 = next((k for k in f1.keyframe_points if round(k.co[0]) == end1), None)
        k2 = next((k for k in f2.keyframe_points if round(k.co[0]) == end2), None)
        if k1 is None or k2 is None:
            raise ValueError("Could not find transition endpoints")
        k1.co[1], k2.co[1] = k2.co[1], k1.co[1]
        f1.update(); f2.update()
    target1 = tuple(drone1.get("lsc_transition_target", (0, 0, 0)))
    target2 = tuple(drone2.get("lsc_transition_target", (0, 0, 0)))
    drone1["lsc_transition_target"] = target2
    drone2["lsc_transition_target"] = target1


def transition_swap(
    context: "bpy.types.Context",
    report: Callable[[set[str], str | Any], None],
    swap_fn: Callable[["bpy.types.Object", "bpy.types.Object"], None],
    swap_name: str,
) -> set[str]:
    drones = get_selected_drones(context)
    if len(drones) != 2:
        report({"ERROR"}, "You must select exactly 2 drones")
        return {"CANCELLED"}

    try:
        swap_fn(drones[0], drones[1])
    except ValueError as e:
        report({"ERROR"}, f"Swap {swap_name} failed:\n" + str(e))
        return {"CANCELLED"}

    refresh_scene(context.scene)

    return {"FINISHED"}


def get_frame_start_end_from_transition(
    transition_fcurves: list[tuple[Any, "bpy.types.FCurve"]],
) -> tuple[int, int]:
    frame_start = min(int(round(item[1].keyframe_points[0].co[0])) for item in transition_fcurves)
    frame_end = max(int(round(item[1].keyframe_points[-1].co[0])) for item in transition_fcurves)
    return frame_start, frame_end


def auto_swap(
    context: "bpy.types.Context",
    report: Callable[[set[str], str | Any], None],
    swap_fn: Callable[["bpy.types.Object", "bpy.types.Object"], None],
    swap_name: str,
) -> set[str]:
    scene = context.scene
    drones = get_selected_drones(context)

    if len(drones) < 2:
        report({"ERROR"}, "You must select at least 2 drones")
        return {"CANCELLED"}

    try:
        constraint_fcurves = get_last_copy_rotation_constraints(drones)
    except ValueError as e:
        report({"ERROR"}, f"Auto swap {swap_name} failed:\n" + str(e))
        return {"CANCELLED"}

    frame_start, frame_end = get_frame_start_end_from_transition(constraint_fcurves)
    # Add 1 to the frame end to make sure the last frame is checked
    frame_end += 1

    _, collision_couples = apply_collision_check(drones, frame_start, frame_end, scene)
    old_total_collisions = len(collision_couples)

    if old_total_collisions == 0:
        report({"INFO"}, f"No collisions, no {swap_name} to swap")
        return {"FINISHED"}

    try:
        for drone_index1, drone_index2 in collision_couples:
            drone1 = get_blender_drone_from_drone_index(drone_index1, scene.collection)
            drone2 = get_blender_drone_from_drone_index(drone_index2, scene.collection)
            swap_fn(drone1, drone2)
    except ValueError as e:
        report({"ERROR"}, str(e))
        return {"CANCELLED"}

    _, collision_couples = apply_collision_check(drones, frame_start, frame_end, scene)
    new_total_collisions = len(collision_couples)

    if new_total_collisions == 0:
        report({"INFO"}, f"Swapped {old_total_collisions} {swap_name}(s), no more collisions")
    else:
        report(
            {"INFO"},
            f"Swapped {old_total_collisions} {swap_name}(s), remaining collision(s): {new_total_collisions}",
        )

    refresh_scene(scene)

    return {"FINISHED"}
