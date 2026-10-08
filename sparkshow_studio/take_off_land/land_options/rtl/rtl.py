from __future__ import annotations

from typing import TYPE_CHECKING

import bpy
import numpy as np

from sparkshow_studio._loader.parameters import LAND_PARAMETERS

from ....base import BaseOperator
from ....setup import FPS, get_lightshow
from ....tools.collection_tools import get_drones
from ....tools.distance_tools import (
    calculate_min_distance_squared_sync,
    calculate_min_distance_squared_trajectories,
)
from ....tools.fcurve_tools import find_fcurve
from ....tools.tutorial_links_tools import draw_tutorial_button, link
from ..land_base import LandBasePanel
from ..utils import get_takeoff_location, land_drone, remove_constraints_influence
from ...utils import keyframe_location

if TYPE_CHECKING:
    from numpy.typing import NDArray


MIN_RTL_ALTITUDE = 5.0
MAX_NB_FRAMES_TO_WAIT = 1000
RTL_MIN_CRUISE_SPEED_FACTOR = 0.30  # legacy, retained for .blend compatibility
RTL_CRUISE_SPEED_LEVELS = 25      # legacy, retained for .blend compatibility
RTL_AUTO_MIN_SPEED = 0.40
RTL_AUTO_MAX_EXTRA_FRAMES = 1000      # safety ceiling; automatic window is geometry/speed driven
RTL_AUTO_CANDIDATE_SPEED_LEVELS = 64
RTL_AUTO_MAX_REPAIRS = 1200
_RTL_ACTIVE_SPEED = 3.5
_RTL_ACTIVE_ACCELERATION = 1.5


def _set_location_linear(drone: bpy.types.Object, frames: tuple[int, ...]) -> None:
    """Make location motion segments linear for the supplied frames."""
    if drone.animation_data is None or drone.animation_data.action is None:
        return
    for axis in range(3):
        fcurve = find_fcurve(drone, "location", axis)
        for keyframe in fcurve.keyframe_points:
            if int(round(keyframe.co.x)) in frames:
                keyframe.interpolation = "LINEAR"
        fcurve.update()


def _remove_keys_after(drone: bpy.types.Object, frame: int) -> None:
    """Remove RTL-created location and color keys after the RTL start frame."""
    if drone.animation_data is None or drone.animation_data.action is None:
        return
    action = drone.animation_data.action
    for fcurve in list(action.fcurves):
        if fcurve.data_path not in {"location", "color"}:
            continue
        keep = [kp for kp in fcurve.keyframe_points if kp.co.x <= frame]
        fcurve.keyframe_points.clear()
        for kp in keep:
            fcurve.keyframe_points.insert(frame=kp.co.x, value=kp.co.y)
        fcurve.update()


def _xy_aabb_cells(
    points: "NDArray[np.float32]",
    *,
    cell_size: float,
    margin: float = 0.0,
) -> list[tuple[int, int]]:
    """Return the uniform-grid cells intersected by an XY AABB.

    The grid is only a broad phase. Exact distance tests are always performed
    after the query, so false positives are harmless and false negatives are
    avoided by expanding the query by the minimum safety distance.
    """
    mins = np.min(points[:, :2], axis=0) - margin
    maxs = np.max(points[:, :2], axis=0) + margin
    min_x = int(np.floor(float(mins[0]) / cell_size))
    max_x = int(np.floor(float(maxs[0]) / cell_size))
    min_y = int(np.floor(float(mins[1]) / cell_size))
    max_y = int(np.floor(float(maxs[1]) / cell_size))
    return [
        (x, y)
        for x in range(min_x, max_x + 1)
        for y in range(min_y, max_y + 1)
    ]


def _hash_add_spatial_cells(
    spatial_hash: dict[tuple[int, int], set[int]],
    index: int,
    cells: list[tuple[int, int]],
) -> None:
    for cell in cells:
        spatial_hash.setdefault(cell, set()).add(index)


def _hash_remove_spatial_cells(
    spatial_hash: dict[tuple[int, int], set[int]],
    index: int,
    cells: list[tuple[int, int]],
) -> None:
    for cell in cells:
        indices = spatial_hash.get(cell)
        if indices is None:
            continue
        indices.discard(index)
        if not indices:
            spatial_hash.pop(cell, None)


def _hash_query_spatial_cells(
    spatial_hash: dict[tuple[int, int], set[int]],
    cells: list[tuple[int, int]],
) -> list[int]:
    result: set[int] = set()
    for cell in cells:
        indices = spatial_hash.get(cell)
        if indices:
            result.update(indices)
    return list(result)



def _motion_profile_parameters(
    distance: float,
    max_speed: float,
    max_acceleration: float,
) -> tuple[float, float, float, float]:
    """Return (total_time, accel_time, cruise_time, peak_speed).

    The profile is symmetric trapezoidal/triangular with zero velocity at both
    ends.  Acceleration is never greater than ``max_acceleration`` and speed is
    never greater than ``max_speed``.
    """
    if distance <= 1e-9:
        return 0.0, 0.0, 0.0, 0.0
    if max_speed <= 0.0:
        raise ValueError("RTL speed must be greater than 0")
    if max_acceleration <= 0.0:
        raise ValueError("RTL acceleration must be greater than 0")

    t_acc = max_speed / max_acceleration
    d_acc = 0.5 * max_acceleration * t_acc * t_acc
    if 2.0 * d_acc >= distance:
        t_acc = float(np.sqrt(distance / max_acceleration))
        peak_speed = max_acceleration * t_acc
        cruise_time = 0.0
    else:
        peak_speed = max_speed
        cruise_time = (distance - 2.0 * d_acc) / max_speed
    return 2.0 * t_acc + cruise_time, t_acc, cruise_time, peak_speed


def _distance_at_time(distance: float, t: float, max_speed: float, max_acceleration: float) -> float:
    """Distance travelled at time ``t`` for the symmetric S-curve-like profile."""
    total, t_acc, t_cruise, peak_speed = _motion_profile_parameters(
        distance, max_speed, max_acceleration
    )
    if total <= 0.0:
        return 0.0
    t = min(max(float(t), 0.0), total)
    if t <= t_acc:
        return 0.5 * max_acceleration * t * t
    cruise_end = t_acc + t_cruise
    if t <= cruise_end:
        d_acc = 0.5 * max_acceleration * t_acc * t_acc
        return d_acc + peak_speed * (t - t_acc)
    tau = total - t
    return distance - 0.5 * max_acceleration * tau * tau


def _velocity_at_time(distance: float, t: float, max_speed: float, max_acceleration: float) -> float:
    """Return the scalar speed magnitude at time ``t``."""
    total, t_acc, t_cruise, peak_speed = _motion_profile_parameters(
        distance, max_speed, max_acceleration
    )
    if total <= 0.0:
        return 0.0
    t = min(max(float(t), 0.0), total)
    if t <= t_acc:
        return min(peak_speed, max_acceleration * t)
    if t <= t_acc + t_cruise:
        return peak_speed
    return min(peak_speed, max_acceleration * (total - t))


def _profile_samples(
    start: np.ndarray,
    end: np.ndarray,
    *,
    total_time: float,
    max_speed: float,
    max_acceleration: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Return time and position samples suitable for Blender F-curves and collision broad/narrow phase."""
    vector = np.asarray(end, dtype=np.float32) - np.asarray(start, dtype=np.float32)
    distance = float(np.linalg.norm(vector))
    if distance <= 1e-9 or total_time <= 1e-9:
        return (
            np.asarray([0.0, total_time], dtype=np.float32),
            np.asarray([start, end], dtype=np.float32),
        )

    # The planner has already guaranteed that ``total_time`` is safe for the
    # requested speed/acceleration.  Re-solve the profile for this rounded-up
    # duration so frame quantisation can only reduce the peak speed.
    T = float(total_time)
    a = float(max_acceleration)
    v_max = float(max_speed)
    min_triangular_time = 2.0 * np.sqrt(distance / a)
    if T < min_triangular_time - 1e-7:
        T = float(min_triangular_time)

    discriminant = max(0.0, T * T - 4.0 * distance / a)
    t_acc = 0.5 * (T - np.sqrt(discriminant))
    peak_speed = a * t_acc
    if peak_speed > v_max + 1e-7:
        _, t_acc, t_cruise, peak_speed = _motion_profile_parameters(distance, v_max, a)
        T = 2.0 * t_acc + t_cruise
    else:
        t_cruise = max(0.0, T - 2.0 * t_acc)

    sample_times = np.asarray(
        [0.0, 0.5 * t_acc, t_acc, t_acc + t_cruise,
         T - 0.5 * t_acc, T],
        dtype=np.float32,
    )
    sample_times = np.maximum.accumulate(sample_times)
    sample_times[-1] = np.float32(T)

    direction = vector / distance
    d_acc = 0.5 * a * t_acc * t_acc
    cruise_start_d = d_acc
    cruise_end_d = d_acc + peak_speed * t_cruise

    distances = np.empty(len(sample_times), dtype=np.float32)
    for i, time_value in enumerate(sample_times):
        t = float(time_value)
        if t <= t_acc:
            s = 0.5 * a * t * t
        elif t <= t_acc + t_cruise:
            s = cruise_start_d + peak_speed * (t - t_acc)
        else:
            tau = T - t
            s = distance - 0.5 * a * tau * tau
        distances[i] = np.float32(min(distance, max(0.0, s)))
    positions = np.asarray(start, dtype=np.float32)[None, :] + distances[:, None] * direction[None, :]
    positions[-1] = np.asarray(end, dtype=np.float32)
    return sample_times, positions.astype(np.float32, copy=False)


def _unique_profile(samples: tuple[np.ndarray, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    times, positions = samples
    keep = [0]
    for i in range(1, len(times)):
        if float(times[i]) > float(times[keep[-1]]) + 1e-7:
            keep.append(i)
    return times[keep], positions[keep]


def _trajectory_from_profiles(
    starts: np.ndarray,
    ends: np.ndarray,
    start_frame: int,
    durations: np.ndarray,
    speed: float,
    acceleration: float,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Build a common 6-point semantic profile for arrays of drones."""
    # This helper is intentionally evaluated per semantic phase, so it remains
    # cheap while still capturing acceleration/deceleration for collision checks.
    phase_times = np.zeros((6, len(starts)), dtype=np.float32)
    phase_positions = [np.zeros_like(starts, dtype=np.float32) for _ in range(6)]
    for i in range(len(starts)):
        total_time = float(durations[i]) / FPS
        times, positions = _profile_samples(
            starts[i], ends[i], total_time=total_time,
            max_speed=speed, max_acceleration=acceleration,
        )
        # _profile_samples normally returns six points; pad/copy if a zero-length
        # route collapsed to two points.
        for p in range(6):
            src_p = min(p, len(times) - 1)
            phase_times[p, i] = np.float32(start_frame + float(times[src_p]) * FPS)
            phase_positions[p][i] = positions[src_p]
    return [(phase_positions[p], phase_times[p]) for p in range(6)]


def _set_acceleration_profile(
    drone: bpy.types.Object,
    start_frame: int,
    duration_frames: int,
    start_position: np.ndarray,
    end_position: np.ndarray,
    speed: float,
    acceleration: float,
) -> None:
    """Keyframe an acceleration/deceleration-limited RTL segment."""
    if duration_frames <= 0:
        drone.location = tuple(float(v) for v in end_position)
        keyframe_location(drone, start_frame)
        return
    total_time = float(duration_frames) / FPS
    times, positions = _profile_samples(
        start_position,
        end_position,
        total_time=total_time,
        max_speed=speed,
        max_acceleration=acceleration,
    )
    for frame_offset, position in zip(times * FPS, positions, strict=True):
        frame = float(start_frame) + float(frame_offset)
        drone.location = tuple(float(v) for v in position)
        keyframe_location(drone, frame)

    # Use custom Bezier tangents matching the instantaneous velocity at each
    # phase boundary. This preserves zero speed at departure/arrival and avoids
    # the visible "instant jump" caused by a linear segment.
    for axis in range(3):
        fcurve = find_fcurve(drone, "location", axis)
        points = fcurve.keyframe_points
        if not points:
            continue
        for idx, kp in enumerate(points):
            if kp.co.x < start_frame - 1e-4 or kp.co.x > start_frame + duration_frames + 1e-4:
                continue
            local_t = (float(kp.co.x) - float(start_frame)) / FPS
            velocity = _velocity_at_time(
                float(np.linalg.norm(np.asarray(end_position) - np.asarray(start_position))),
                local_t,
                speed,
                acceleration,
            )
            distance = np.asarray(end_position, dtype=np.float32) - np.asarray(start_position, dtype=np.float32)
            norm = float(np.linalg.norm(distance))
            velocity_component = 0.0 if norm <= 1e-9 else float(distance[axis]) / norm * velocity
            prev_frame = float(points[max(idx - 1, 0)].co.x)
            next_frame = float(points[min(idx + 1, len(points) - 1)].co.x)
            if idx < len(points) - 1:
                dt_right = max(1e-6, float(points[idx + 1].co.x - kp.co.x))
                kp.handle_right_type = "FREE"
                kp.handle_right = (
                    float(kp.co.x + dt_right / 3.0),
                    float(kp.co.y + velocity_component * dt_right / 3.0 / FPS),
                )
            if idx > 0:
                dt_left = max(1e-6, float(kp.co.x - points[idx - 1].co.x))
                kp.handle_left_type = "FREE"
                kp.handle_left = (
                    float(kp.co.x - dt_left / 3.0),
                    float(kp.co.y - velocity_component * dt_left / 3.0 / FPS),
                )
        fcurve.update()



def _rtl_duration_frames(distance: float, speed: float, acceleration: float | None = None) -> int:
    if speed <= 0.0:
        raise ValueError("RTL speed must be greater than 0")
    if acceleration is None:
        acceleration = _RTL_ACTIVE_ACCELERATION
    if acceleration <= 0.0:
        raise ValueError("RTL acceleration must be greater than 0")
    total, _t_acc, _t_cruise, _peak = _motion_profile_parameters(float(distance), float(speed), float(acceleration))
    return max(1, int(np.ceil(total * FPS)))


def _rtl_trajectory(
    start: np.ndarray,
    landing: np.ndarray,
    touchdown: np.ndarray,
    start_frame: int,
    duration: int,
    reposition_duration: int,
    land_duration: int,
    *,
    speed: float = 3.5,
    acceleration: float = 1.5,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Build the physical RTL trajectory used by both solver and Blender.

    The travel segment uses the same acceleration/deceleration-limited profile
    that is later written to the drone F-curves.  The pre-landing hold remains
    explicit so it cannot be confused with travel.  The final landing segment
    stays vertical and is represented separately.
    """
    total_time = max(0.0, float(duration) / FPS)
    times, positions = _profile_samples(
        np.asarray(start, dtype=np.float32),
        np.asarray(landing, dtype=np.float32),
        total_time=total_time,
        max_speed=float(speed),
        max_acceleration=float(acceleration),
    )
    points: list[tuple[np.ndarray, np.ndarray]] = []
    for t, p in zip(times, positions, strict=True):
        points.append((np.asarray(p, dtype=np.float32).reshape(1, 3), np.asarray([start_frame + float(t) * FPS], dtype=np.float32)))
    travel_end = int(start_frame + duration)
    hold_end = int(travel_end + reposition_duration)
    points.append((np.asarray(landing, dtype=np.float32).reshape(1, 3), np.asarray([hold_end], dtype=np.float32)))
    if int(land_duration) > 0:
        touchdown_arr = np.asarray(touchdown, dtype=np.float32)
        landing_duration = float(land_duration)
        for frac in (1.0 / 3.0, 2.0 / 3.0, 1.0):
            t = landing_duration * frac
            # Smoothstep vertical descent.
            u = frac
            s = 3.0 * u * u - 2.0 * u * u * u
            p = np.asarray(landing, dtype=np.float32) + (touchdown_arr - np.asarray(landing, dtype=np.float32)) * np.float32(s)
            points.append((p.reshape(1, 3), np.asarray([hold_end + t], dtype=np.float32)))
    return points


def _trajectory_min_distance_squared(
    trajectory1: list[tuple[np.ndarray, np.ndarray]],
    trajectory2: list[tuple[np.ndarray, np.ndarray]],
) -> float:
    """Exact minimum squared distance for two small piecewise-linear timed paths.

    This is deliberately implemented without allocating a NumPy array for every
    segment pair. The synchronized RTL solver can evaluate tens of thousands of
    trajectory pairs, so the previous generator-based implementation created an
    excessive number of tiny NumPy objects and could exhaust Blender's process
    during collision repair.
    """
    if not trajectory1 or not trajectory2:
        return float(np.inf)

    def unpack(traj: list[tuple[np.ndarray, np.ndarray]]):
        times = np.asarray([float(np.asarray(t).reshape(-1)[0]) for _, t in traj], dtype=np.float64)
        positions = np.asarray([np.asarray(pos, dtype=np.float64).reshape(-1, 3)[0] for pos, _ in traj], dtype=np.float64)
        return times, positions

    times1, pos1 = unpack(trajectory1)
    times2, pos2 = unpack(trajectory2)

    # Union of all semantic boundaries. Between two consecutive boundaries the
    # relative trajectory is linear, so its exact minimum is a 1D quadratic.
    end_time = max(float(times1[-1]), float(times2[-1]))
    boundaries = sorted(set([0.0, end_time, *times1.tolist(), *times2.tolist()]))
    minimum = float(np.inf)

    def state_at(times: np.ndarray, positions: np.ndarray, t: float) -> tuple[np.ndarray, np.ndarray]:
        if t <= float(times[0]) + 1e-9:
            return positions[0], np.zeros(3, dtype=np.float64)
        if t >= float(times[-1]) - 1e-9:
            return positions[-1], np.zeros(3, dtype=np.float64)
        idx = int(np.searchsorted(times, t, side='right') - 1)
        idx = max(0, min(idx, len(times) - 2))
        dt = float(times[idx + 1] - times[idx])
        if dt <= 1e-12:
            return positions[idx], np.zeros(3, dtype=np.float64)
        velocity = (positions[idx + 1] - positions[idx]) / dt
        position = positions[idx] + velocity * (t - float(times[idx]))
        return position, velocity

    for left, right in zip(boundaries[:-1], boundaries[1:], strict=True):
        if right - left <= 1e-10:
            continue
        p1, v1 = state_at(times1, pos1, left)
        p2, v2 = state_at(times2, pos2, left)
        relative = p1 - p2
        relative_velocity = v1 - v2
        duration = float(right - left)
        vv = float(np.dot(relative_velocity, relative_velocity))
        if vv > 1e-18:
            tau = float(np.clip(-np.dot(relative, relative_velocity) / vv, 0.0, duration))
        else:
            tau = 0.0
        r = relative + relative_velocity * tau
        value = float(np.dot(r, r))
        if value < minimum:
            minimum = value
            if minimum <= 0.0:
                return 0.0

    return minimum


def _trajectory_aabb(
    trajectory: list[tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Return spatial AABB and time range for a tiny RTL trajectory."""
    if not trajectory:
        inf = np.full(3, np.inf, dtype=np.float32)
        return inf, -inf, np.inf, -np.inf
    positions = np.asarray(
        [np.asarray(pos, dtype=np.float32).reshape(-1, 3)[0] for pos, _ in trajectory],
        dtype=np.float32,
    )
    times = np.asarray(
        [float(np.asarray(t).reshape(-1)[0]) for _, t in trajectory],
        dtype=np.float32,
    )
    return np.min(positions, axis=0), np.max(positions, axis=0), float(times[0]), float(times[-1])


def _aabb_distance_squared(
    min_a: np.ndarray,
    max_a: np.ndarray,
    min_b: np.ndarray,
    max_b: np.ndarray,
) -> float:
    """Squared gap between two axis-aligned boxes (zero when they overlap)."""
    gap = np.maximum(0.0, np.maximum(min_a - max_b, min_b - max_a))
    return float(np.dot(gap, gap))


def _is_candidate_safe(
    candidate: list[tuple[np.ndarray, np.ndarray]],
    others: list[list[tuple[np.ndarray, np.ndarray]]],
    min_distance_squared: float,
) -> bool:
    """Check a candidate against all trajectories using an AABB broad phase."""
    candidate_min, candidate_max, _, _ = _trajectory_aabb(candidate)
    for other in others:
        other_min, other_max, _, _ = _trajectory_aabb(other)
        if _aabb_distance_squared(candidate_min, candidate_max, other_min, other_max) > float(min_distance_squared):
            continue
        if _trajectory_min_distance_squared(candidate, other) <= float(min_distance_squared):
            return False
    return True


def _rtl_automatic_duration_candidates(
    distance: float,
    max_speed: float,
    *,
    max_extra_frames: int = RTL_AUTO_MAX_EXTRA_FRAMES,
) -> tuple[int, ...]:
    """Build a geometry-driven automatic duration window.

    There is no user-facing minimum cruise-speed percentage. Internally, the
    planner explores the complete safe speed range from ``max_speed`` down to
    ``RTL_AUTO_MIN_SPEED``. The old implementation clipped that range to a
    fixed +150-frame window, which could make an otherwise feasible synchronized
    solution impossible for longer RTL legs.

    Candidates are sampled primarily in *speed* space (the quantity the user
    actually controls) and locally densified in frame space so small timing
    adjustments remain available without creating hundreds of full-fleet
    collision passes.
    """
    fastest = _rtl_duration_frames(distance, max_speed)
    if distance <= 1e-6:
        return (fastest,)

    min_speed = min(float(max_speed), RTL_AUTO_MIN_SPEED)
    slowest = _rtl_duration_frames(distance, min_speed)

    # Respect the global safety ceiling, but do not impose the old arbitrary
    # +150-frame restriction.
    max_duration = min(slowest, fastest + int(max_extra_frames))
    max_duration = max(fastest, max_duration)

    if max_duration <= fastest:
        return (fastest,)

    span = max_duration - fastest

    # Full integer coverage is cheap for short routes and gives exact frame
    # solutions. Longer routes use speed-space sampling plus local frame
    # densification around each sampled point.
    if span <= 600:
        return tuple(range(fastest, max_duration + 1))

    count = max(8, int(RTL_AUTO_CANDIDATE_SPEED_LEVELS))
    speeds = np.linspace(
        float(max_speed),
        float(distance) / (float(max_duration) / float(FPS)),
        count,
        dtype=np.float64,
    )
    candidates: set[int] = {fastest, max_duration}
    for candidate_speed in speeds:
        if candidate_speed <= 0.0:
            continue
        duration = _rtl_duration_frames(distance, float(candidate_speed))
        duration = max(fastest, min(max_duration, int(duration)))
        candidates.add(duration)
        for delta in range(-4, 5):
            value = duration + delta
            if fastest <= value <= max_duration:
                candidates.add(value)

    # Always give the fastest region a dense set of timings because that is
    # where most collision repairs converge.
    for value in range(fastest, min(max_duration, fastest + 48) + 1):
        candidates.add(value)

    return tuple(sorted(candidates))


def _trajectory_for_index(
    index: int,
    starts: np.ndarray,
    landing_positions: np.ndarray,
    touchdown_positions: np.ndarray,
    durations: np.ndarray,
    *,
    reposition_duration: int,
    land_duration: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    return _rtl_trajectory(
        starts[index],
        landing_positions[index],
        touchdown_positions[index],
        0,
        int(durations[index]),
        reposition_duration,
        land_duration,
        speed=_RTL_ACTIVE_SPEED,
        acceleration=_RTL_ACTIVE_ACCELERATION,
    )


def _build_synchronized_trajectory_cache(
    starts: np.ndarray,
    landing_positions: np.ndarray,
    touchdown_positions: np.ndarray,
    durations: np.ndarray,
    *,
    reposition_duration: int,
    land_duration: int,
) -> list[list[tuple[np.ndarray, np.ndarray]]]:
    return [
        _trajectory_for_index(
            i,
            starts,
            landing_positions,
            touchdown_positions,
            durations,
            reposition_duration=reposition_duration,
            land_duration=land_duration,
        )
        for i in range(len(starts))
    ]


def _find_synchronized_collisions(
    starts: np.ndarray,
    landing_positions: np.ndarray,
    touchdown_positions: np.ndarray,
    durations: np.ndarray,
    *,
    reposition_duration: int,
    land_duration: int,
    min_distance_squared: float,
    trajectory_cache: list[list[tuple[np.ndarray, np.ndarray]]] | None = None,
) -> list[tuple[int, int, float]]:
    """Return the first detected synchronized collision.

    Only the first collision is needed by the repair solver. The previous code
    calculated and sorted *every* colliding pair on every repair pass, which was
    the primary reason large shows could make Blender unresponsive or terminate.
    """
    trajectories = trajectory_cache or _build_synchronized_trajectory_cache(
        starts,
        landing_positions,
        touchdown_positions,
        durations,
        reposition_duration=reposition_duration,
        land_duration=land_duration,
    )
    nb = len(trajectories)
    bounds = [_trajectory_aabb(traj) for traj in trajectories]
    threshold = float(min_distance_squared)

    for i in range(nb):
        min_i, max_i, t0_i, t1_i = bounds[i]
        for j in range(i + 1, nb):
            min_j, max_j, t0_j, t1_j = bounds[j]
            if t1_i < t0_j or t1_j < t0_i:
                continue
            if _aabb_distance_squared(min_i, max_i, min_j, max_j) > threshold:
                continue
            value = _trajectory_min_distance_squared(trajectories[i], trajectories[j])
            if value <= threshold:
                return [(i, j, float(value))]
    return []


def _duration_safe_against_all(
    index: int,
    candidate_duration: int,
    starts: np.ndarray,
    landing_positions: np.ndarray,
    touchdown_positions: np.ndarray,
    durations: np.ndarray,
    *,
    reposition_duration: int,
    land_duration: int,
    min_distance_squared: float,
    trajectory_cache: list[list[tuple[np.ndarray, np.ndarray]]] | None = None,
) -> bool:
    """Check one candidate duration against cached fleet trajectories."""
    candidate = _rtl_trajectory(
        starts[index],
        landing_positions[index],
        touchdown_positions[index],
        0,
        int(candidate_duration),
        reposition_duration,
        land_duration,
        speed=_RTL_ACTIVE_SPEED,
        acceleration=_RTL_ACTIVE_ACCELERATION,
    )
    if trajectory_cache is None:
        trajectory_cache = _build_synchronized_trajectory_cache(
            starts,
            landing_positions,
            touchdown_positions,
            durations,
            reposition_duration=reposition_duration,
            land_duration=land_duration,
        )
    others = [traj for j, traj in enumerate(trajectory_cache) if j != index]
    return _is_candidate_safe(candidate, others, min_distance_squared)


def _find_fastest_safe_duration(
    index: int,
    current_duration: int,
    duration_candidates: list[tuple[int, ...]],
    starts: np.ndarray,
    landing_positions: np.ndarray,
    touchdown_positions: np.ndarray,
    durations: np.ndarray,
    *,
    reposition_duration: int,
    land_duration: int,
    min_distance_squared: float,
    trajectory_cache: list[list[tuple[np.ndarray, np.ndarray]]] | None = None,
) -> int | None:
    """Find the smallest safe duration at or above the current duration."""
    for candidate_duration in duration_candidates[index]:
        if candidate_duration < current_duration:
            continue
        if _duration_safe_against_all(
            index, candidate_duration, starts, landing_positions, touchdown_positions, durations,
            reposition_duration=reposition_duration, land_duration=land_duration,
            min_distance_squared=min_distance_squared, trajectory_cache=trajectory_cache,
        ):
            return int(candidate_duration)
    return None


def _solve_synchronized_speeds(
    starts: np.ndarray,
    landing_positions: np.ndarray,
    touchdown_positions: np.ndarray,
    *,
    reposition_duration: int,
    speed: float,
    min_distance_squared: float,
    land_duration: int,
) -> tuple[list[int], list[int], list[float]] | None:
    """Find a collision-free common departure while minimizing speed spread.

    Unlike the previous greedy assignment, this planner starts every drone at
    its fastest safe duration, then slows only the smallest amount required to
    remove actual collisions.  A final restoration pass re-accelerates drones
    whenever later adjustments made their slowdown unnecessary.  There is no
    user-defined minimum-speed percentage in the decision path.
    """
    nb_drones = len(starts)
    if nb_drones == 0:
        return [], [], []

    distances = np.linalg.norm(landing_positions - starts, axis=1)
    duration_candidates = [
        _rtl_automatic_duration_candidates(float(distance), float(speed))
        for distance in distances
    ]
    if nb_drones:
        min_candidate = min(len(c) for c in duration_candidates)
        max_candidate = max(len(c) for c in duration_candidates)
        global_max_duration = max(int(c[-1]) for c in duration_candidates)
        print(
            f"[Sparkshow RTL] automatic speed window: "
            f"{RTL_AUTO_MIN_SPEED:.2f}..{float(speed):.2f} m/s | "
            f"candidate counts {min_candidate}..{max_candidate} | "
            f"max duration {global_max_duration} frames",
            flush=True,
        )
    fastest = np.asarray([candidates[0] for candidates in duration_candidates], dtype=np.int32)
    durations = fastest.copy()
    trajectory_cache = _build_synchronized_trajectory_cache(
        starts, landing_positions, touchdown_positions, durations,
        reposition_duration=reposition_duration, land_duration=land_duration,
    )

    print(f"[Sparkshow RTL] synchronized planner: {nb_drones} drones", flush=True)

    # Iteratively repair the first remaining collision.  Only one drone in the
    # offending pair is modified at a time, and every candidate is validated
    # against the entire fleet before it is accepted.
    for repair_index in range(RTL_AUTO_MAX_REPAIRS):
        if repair_index and repair_index % 50 == 0:
            print(f"[Sparkshow RTL] collision repair pass {repair_index}", flush=True)
        collisions = _find_synchronized_collisions(
            starts, landing_positions, touchdown_positions, durations,
            reposition_duration=reposition_duration, land_duration=land_duration,
            min_distance_squared=min_distance_squared, trajectory_cache=trajectory_cache,
        )
        if not collisions:
            break

        i, j, _ = collisions[0]
        options: list[tuple[float, int, int]] = []
        for index in (i, j):
            current = int(durations[index])
            candidate_duration = _find_fastest_safe_duration(
                index, current + 1, duration_candidates,
                starts, landing_positions, touchdown_positions, durations,
                reposition_duration=reposition_duration, land_duration=land_duration,
                min_distance_squared=min_distance_squared, trajectory_cache=trajectory_cache,
            )
            if candidate_duration is None:
                continue

            trial = durations.copy()
            trial[index] = candidate_duration
            spread = float(np.max(trial) - np.min(trial))
            added = float(candidate_duration - current)
            median_distance = float(abs(candidate_duration - np.median(trial)))
            # Primary objective = smallest slowdown.  Secondary objective =
            # keep the fleet's travel times clustered.
            cost = added + 0.12 * spread + 0.03 * median_distance
            options.append((cost, index, candidate_duration))

        if not options:
            return None

        _, chosen_index, chosen_duration = min(options, key=lambda option: option[0])
        durations[chosen_index] = np.int32(chosen_duration)
        trajectory_cache[chosen_index] = _rtl_trajectory(
            starts[chosen_index], landing_positions[chosen_index], touchdown_positions[chosen_index],
            0, chosen_duration, reposition_duration, land_duration,
            speed=_RTL_ACTIVE_SPEED, acceleration=_RTL_ACTIVE_ACCELERATION,
        )
    else:
        return None

    if _find_synchronized_collisions(
        starts, landing_positions, touchdown_positions, durations,
        reposition_duration=reposition_duration, land_duration=land_duration,
        min_distance_squared=min_distance_squared, trajectory_cache=trajectory_cache,
    ):
        return None

    # Restore speed wherever possible.  Process the most slowed drones first
    # so later drones can reuse the resulting timing envelope.
    for index in sorted(range(nb_drones), key=lambda i: int(durations[i] - fastest[i]), reverse=True):
        current = int(durations[index])
        if current <= int(fastest[index]):
            continue
        candidates = duration_candidates[index]
        for candidate_duration in candidates:
            if candidate_duration >= current:
                break
            if _duration_safe_against_all(
                index, int(candidate_duration), starts, landing_positions, touchdown_positions, durations,
                reposition_duration=reposition_duration, land_duration=land_duration,
                min_distance_squared=min_distance_squared, trajectory_cache=trajectory_cache,
            ):
                durations[index] = np.int32(candidate_duration)
                trajectory_cache[index] = _rtl_trajectory(
                    starts[index], landing_positions[index], touchdown_positions[index],
                    0, candidate_duration, reposition_duration, land_duration,
                    speed=_RTL_ACTIVE_SPEED, acceleration=_RTL_ACTIVE_ACCELERATION,
                )
                break

    if _find_synchronized_collisions(
        starts, landing_positions, touchdown_positions, durations,
        reposition_duration=reposition_duration, land_duration=land_duration,
        min_distance_squared=min_distance_squared, trajectory_cache=trajectory_cache,
    ):
        return None

    speeds = [
        float(distances[i]) / (float(durations[i]) / float(FPS))
        if int(durations[i]) > 0 and distances[i] > 1e-6
        else float(speed)
        for i in range(nb_drones)
    ]
    return [0 for _ in range(nb_drones)], [int(v) for v in durations], speeds


def calculate_rtl_wait_times_and_durations(  # noqa: PLR0913
    start_positions: "NDArray[np.float32]",
    end_positions: "NDArray[np.float32]",
    *,
    land_altitude: float,
    min_distance: float,
    reposition_duration: int,
    speed: float,
    acceleration: float,
    frame_delta: int,
    max_nb_frames_to_wait: int = MAX_NB_FRAMES_TO_WAIT,
    min_cruise_speed_factor: float | None = None,
    synchronized_departure: bool = True,
) -> tuple[list[int | None], list[int], list[float]]:
    """Calculate safe RTL timing using the physical acceleration-limited profile.

    The same motion profile is used by the collision solver and by the Blender
    F-curves, so the checked trajectory matches the generated animation.
    """
    global _RTL_ACTIVE_SPEED, _RTL_ACTIVE_ACCELERATION
    _RTL_ACTIVE_SPEED = float(speed)
    _RTL_ACTIVE_ACCELERATION = float(acceleration)
    del min_cruise_speed_factor  # legacy UI/scene field; automatic planner owns the speed range.

    starts = np.asarray(start_positions, dtype=np.float32)
    touchdown_positions = np.asarray(end_positions, dtype=np.float32)
    nb_drones = len(starts)
    if nb_drones == 0:
        return [], [], []
    if speed <= 0.0:
        raise ValueError("RTL speed must be greater than 0")
    if frame_delta < 1:
        raise ValueError("RTL frame interval must be at least 1 frame")
    if min_distance < 0.0:
        raise ValueError("RTL minimum distance cannot be negative")

    landing_positions = touchdown_positions.copy()
    landing_positions[:, 2] = np.float32(land_altitude)
    min_distance_squared = float(min_distance) ** 2
    land_duration = int(LAND_PARAMETERS.get_land_frame_delta(land_altitude))
    reposition_duration = int(reposition_duration)

    if synchronized_departure:
        result = _solve_synchronized_speeds(
            starts,
            landing_positions,
            touchdown_positions,
            reposition_duration=reposition_duration,
            speed=speed,
            min_distance_squared=min_distance_squared,
            land_duration=land_duration,
        )
        if result is None:
            raise ValueError(
                "Synchronized RTL departure cannot be made collision-free with the current "
                "geometry within the automatic speed range ("
                f"{RTL_AUTO_MIN_SPEED:.2f} to {speed:.2f} m/s). "
                "Change the RTL/formation geometry or disable synchronized departure."
            )
        return result

    # ------------------------------------------------------------------
    # Asynchronous mode: this is intentionally based directly on the proven
    # Lightshow Creator 3.15 RTL scheduler.  The only material adaptation is
    # keeping the return signature compatible with Sparkshow's variable-speed UI.
    # ------------------------------------------------------------------
    durations = np.asarray(
        [
            _rtl_duration_frames(
                float(np.linalg.norm(landing_positions[index] - starts[index])),
                speed,
            )
            for index in range(nb_drones)
        ],
        dtype=np.int32,
    )
    direction = np.sum(landing_positions - starts, axis=0)
    order = sorted(
        range(nb_drones),
        key=lambda index: -float(starts[index] @ direction),
    )

    start_frames = np.full(nb_drones, np.nan, dtype=np.float32)
    reposition_frames = np.full(nb_drones, np.nan, dtype=np.float32)
    landing_frames = np.full(nb_drones, np.nan, dtype=np.float32)
    end_frames = np.full(nb_drones, np.nan, dtype=np.float32)
    not_started = np.full(nb_drones, True, dtype=np.bool_)
    moving = np.full(nb_drones, False, dtype=np.bool_)

    start_frame = 0

    def start(index: int) -> None:
        start_frames[index] = start_frame
        reposition_frames[index] = start_frames[index] + durations[index]
        landing_frames[index] = reposition_frames[index] + reposition_duration
        end_frames[index] = landing_frames[index] + land_duration
        not_started[index] = False
        moving[index] = True

    def update_drone_states() -> None:
        moving[moving] = end_frames[moving] > start_frame

    def check_not_started(index: int) -> bool:
        not_started[index] = False
        nb_not_started = int(np.sum(not_started, dtype=np.int32))
        if nb_not_started == 0:
            result = True
        else:
            distance_squared = calculate_min_distance_squared_sync(
                np.repeat([starts[index]], nb_not_started, axis=0),
                np.repeat([landing_positions[index]], nb_not_started, axis=0),
                starts[not_started],
                starts[not_started],
            )
            result = bool(np.min(distance_squared) > min_distance_squared)
        not_started[index] = True
        return result

    def check_moving(index: int) -> bool:
        nb_moving = int(np.sum(moving, dtype=np.int32))
        if nb_moving == 0:
            return True

        candidate_trajectory = _rtl_trajectory(
            starts[index],
            landing_positions[index],
            touchdown_positions[index],
            start_frame,
            int(durations[index]),
            reposition_duration,
            land_duration,
        )
        other_trajectories = []
        moving_indices = np.flatnonzero(moving)
        for other in moving_indices:
            other_trajectories.append(
                _rtl_trajectory(
                    starts[int(other)],
                    landing_positions[int(other)],
                    touchdown_positions[int(other)],
                    int(start_frames[int(other)]),
                    int(durations[int(other)]),
                    reposition_duration,
                    land_duration,
                    speed=_RTL_ACTIVE_SPEED,
                    acceleration=_RTL_ACTIVE_ACCELERATION,
                )
            )
        return _is_candidate_safe(
            candidate_trajectory,
            other_trajectories,
            min_distance_squared,
        )

    last_start_frame = 0
    while order:
        update_drone_states()
        for drone_index in order.copy():
            if not check_moving(drone_index) or not check_not_started(drone_index):
                continue
            start(drone_index)
            order.remove(drone_index)
            last_start_frame = start_frame

        start_frame += int(frame_delta)
        if last_start_frame + max_nb_frames_to_wait < start_frame:
            raise ValueError("The RTL calculation is stuck")

    wait_times = [round(frame) if np.isfinite(frame) else None for frame in start_frames]
    return wait_times, [int(duration) for duration in durations], [float(speed) for _ in range(nb_drones)]


def _set_linear_rtl_keys(
    drone: bpy.types.Object,
    current_location: np.ndarray,
    landing_location: np.ndarray,
    current_frame: int,
    rtl_start_frame: int,
    reposition_frame: int,
    land_start_frame: int,
    *,
    speed: float | None = None,
    acceleration: float | None = None,
) -> None:
    """Write the same acceleration-limited RTL profile used by the solver."""
    speed = _RTL_ACTIVE_SPEED if speed is None else float(speed)
    acceleration = _RTL_ACTIVE_ACCELERATION if acceleration is None else float(acceleration)
    duration_frames = max(1, int(reposition_frame - rtl_start_frame))
    total_time = float(duration_frames) / FPS
    times, positions = _profile_samples(
        np.asarray(current_location, dtype=np.float32),
        np.asarray(landing_location, dtype=np.float32),
        total_time=total_time,
        max_speed=speed,
        max_acceleration=acceleration,
    )
    for frame_offset, position in zip(times * FPS, positions, strict=True):
        frame = float(rtl_start_frame) + float(frame_offset)
        drone.location = tuple(float(v) for v in position)
        keyframe_location(drone, frame)

    # Use velocity-matched handles for a visually smooth curve while preserving
    # zero velocity at the start/end and the physical profile.
    distance_vec = np.asarray(landing_location, dtype=np.float32) - np.asarray(current_location, dtype=np.float32)
    norm = float(np.linalg.norm(distance_vec))
    for axis in range(3):
        fcurve = find_fcurve(drone, "location", axis)
        pts = fcurve.keyframe_points
        for idx, kp in enumerate(pts):
            frame = float(kp.co.x)
            if frame < float(rtl_start_frame) - 1e-6 or frame > float(reposition_frame) + 1e-6:
                continue
            local_t = max(0.0, min(total_time, (frame - float(rtl_start_frame)) / FPS))
            velocity = _velocity_at_time(norm, local_t, speed, acceleration)
            component = 0.0 if norm <= 1e-9 else float(distance_vec[axis]) / norm * velocity
            if idx > 0:
                dt = max(1e-6, float(kp.co.x - pts[idx - 1].co.x))
                kp.handle_left_type = "FREE"
                kp.handle_left = (float(kp.co.x - dt / 3.0), float(kp.co.y - component * dt / 3.0 / FPS))
            if idx < len(pts) - 1:
                dt = max(1e-6, float(pts[idx + 1].co.x - kp.co.x))
                kp.handle_right_type = "FREE"
                kp.handle_right = (float(kp.co.x + dt / 3.0), float(kp.co.y + component * dt / 3.0 / FPS))
            kp.interpolation = "BEZIER"
        fcurve.update()


class RTL_PT_subpanel(LandBasePanel):
    bl_label = "\t\tRTL"
    bl_idname = "LIGHTSHOW_PT_rtl"
    bl_parent_id = "LIGHTSHOW_PT_land_panel"
    bl_options = {"HIDE_HEADER"}

    def draw(self, context: bpy.types.Context) -> None:
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        lightshow = get_lightshow(context.scene)
        props = getattr(context.scene, "rtl_props", None)
        if lightshow is None or props is None:
            layout.label(text="RTL properties unavailable", icon="ERROR")
            return

        box = layout.box()
        box.label(text="Return to launch")
        box.prop(lightshow, "rtl_min_distance")
        box.prop(lightshow, "rtl_speed")
        box.prop(lightshow, "rtl_synchronized_departure")
        box.label(text="RTL travel model: linear cruise (reference-safe)")
        box.label(text="Synchronized departure = common start; speeds adapt only as needed for safety")
        box.prop(lightshow, "rtl_reposition_duration")
        box.prop(lightshow, "rtl_frame_delta")
        box.prop(lightshow, "rtl_land_altitude")

        layout.separator()
        if props.cancelled:
            layout.operator("lightshow.rtl", icon="PLAY")
            layout.operator("lightshow.rtl_reset", icon="FILE_REFRESH")
        elif props.current_time_delta > 0:
            layout.label(text="RTL generated", icon="CHECKMARK")
            layout.label(
                text=f"Max waiting = {props.current_time_delta} frames",
                icon="INFO",
            )
            layout.operator("lightshow.rtl_reset", icon="FILE_REFRESH")
        else:
            draw_tutorial_button(
                layout,
                context,
                main_button_fn=lambda col: col.operator("lightshow.rtl", icon="PLAY"),
                section=link.takeoff_and_land,
                option="rtl_return_to_launch",
            )


def _verify_minimum_altitude(scene: bpy.types.Scene, drones: list[bpy.types.Object]) -> bool:
    if not drones:
        return False
    locations = np.asarray(
        [drone.matrix_world.to_translation()[:] for drone in drones],
        dtype=np.float32,
    )
    return bool(np.min(locations[:, 2]) >= MIN_RTL_ALTITUDE)


class LIGHTSHOW_OT_rtl(BaseOperator):
    bl_label = "RTL"
    bl_description = (
        "Return every drone to the XYZ position of its original takeoff point "
        "at the configured landing altitude, then perform the normal landing."
    )
    bl_idname = "lightshow.rtl"

    def execute(self, context: bpy.types.Context) -> set[str]:  # noqa: C901, PLR0915
        scene = context.scene
        lightshow = get_lightshow(scene)
        drones = get_drones(scene.collection)
        props = getattr(scene, "rtl_props", None)
        if lightshow is None or props is None:
            self.report_print({"ERROR"}, "Sparkshow RTL properties are unavailable")
            return {"CANCELLED"}
        if not drones:
            self.report_print({"ERROR"}, "No drones found")
            return {"CANCELLED"}

        current_frame = int(scene.frame_current)
        current_locations = np.asarray(
            [drone.matrix_world.to_translation()[:] for drone in drones],
            dtype=np.float32,
        )
        if float(np.min(current_locations[:, 2])) < MIN_RTL_ALTITUDE:
            self.report_print(
                {"ERROR"},
                f"The minimum altitude for RTL is {MIN_RTL_ALTITUDE:g} m",
            )
            return {"CANCELLED"}

        try:
            # Capture the real takeoff positions BEFORE adding RTL keys. This is
            # critical: the first key on each location F-curve is the launch point.
            takeoff_locations = np.asarray(
                [get_takeoff_location(drone)[:] for drone in drones],
                dtype=np.float32,
            )
        except (RuntimeError, IndexError, ValueError) as exc:
            self.report_print(
                {"ERROR"},
                f"Cannot determine a takeoff position for one or more drones: {exc}",
            )
            return {"CANCELLED"}

        reposition_duration = int(
            round(float(lightshow.rtl_reposition_duration) * FPS)
            + LAND_PARAMETERS.get_rtl_reposition_frame_delta()
        )
        try:
            wait_times, durations, cruise_speeds = calculate_rtl_wait_times_and_durations(
                current_locations,
                takeoff_locations,
                land_altitude=float(lightshow.rtl_land_altitude),
                min_distance=float(lightshow.rtl_min_distance),
                reposition_duration=reposition_duration,
                speed=float(lightshow.rtl_speed),
                acceleration=float(lightshow.acc_max),
                frame_delta=int(lightshow.rtl_frame_delta),
                    synchronized_departure=bool(lightshow.rtl_synchronized_departure),
            )
        except ValueError as exc:
            props.cancelled = True
            self.report_print({"ERROR"}, str(exc))
            return {"CANCELLED"}

        lightshow.rtl_start_frame = current_frame
        props.cancelled = False
        props.is_running = False
        props.nb_drones = len(drones)
        props.calculated_trajectories = len(drones)
        props.current_time_delta = max(wait_times, default=0) or 0

        if "RTL start" in scene.timeline_markers:
            scene.timeline_markers.remove(scene.timeline_markers["RTL start"])
        scene.timeline_markers.new("RTL start", frame=current_frame)

        land_last_frame = current_frame
        landing_altitude = float(lightshow.rtl_land_altitude)

        for drone, wait_time, duration, cruise_speed, takeoff_location in zip(
            drones,
            wait_times,
            durations,
            cruise_speeds,
            takeoff_locations,
            strict=True,
        ):
            if wait_time is None:
                continue

            remove_constraints_influence(scene, lightshow, drone)

            # Freeze the exact current pose while the drone waits for its slot.
            current_location = drone.matrix_world.to_translation().copy()
            keyframe_location(drone, current_frame - 1)
            drone.location = current_location
            keyframe_location(drone, current_frame)

            rtl_start_frame = current_frame + int(wait_time)
            keyframe_location(drone, rtl_start_frame)
            drone["sparkshow_rtl_cruise_speed"] = float(cruise_speed)

            # Return to the original takeoff XY, with the configured RTL altitude.
            # Keep the original takeoff Z out of the travel calculation so that all
            # drones reach the same safe pre-landing altitude before descending.
            land_location = np.asarray(takeoff_location, dtype=np.float32).copy()
            land_location[2] = landing_altitude
            reposition_frame = rtl_start_frame + int(duration)
            land_start_frame = reposition_frame + reposition_duration

            current_location_np = np.asarray(current_location, dtype=np.float32)
            land_location_np = np.asarray(land_location, dtype=np.float32)
            _set_linear_rtl_keys(
                drone,
                current_location_np,
                land_location_np,
                current_frame,
                rtl_start_frame,
                reposition_frame,
                land_start_frame,
                speed=float(cruise_speed),
                acceleration=float(lightshow.acc_max),
            )
            # Store the selected cruise speed for diagnostics/export.
            drone["sparkshow_rtl_cruise_speed"] = float(cruise_speed)

            land_end_frame = land_drone(
                lightshow,
                drone,
                drone.location.copy(),
                land_start_frame,
                set_keyframe=False,
            )
            land_last_frame = max(land_last_frame, land_end_frame)

        if lightshow.land_marker:
            if "RTL end" in scene.timeline_markers:
                scene.timeline_markers.remove(scene.timeline_markers["RTL end"])
            scene.timeline_markers.new("RTL end", frame=land_last_frame)
        scene.frame_end = land_last_frame
        scene.frame_set(land_last_frame)
        return {"FINISHED"}


class LIGHTSHOW_OT_rtl_cancel(BaseOperator):
    bl_label = "Cancel RTL"
    bl_description = "Remove the RTL portion added after the RTL start frame"
    bl_idname = "lightshow.rtl_cancel"

    def execute(self, context: bpy.types.Context) -> set[str]:
        props = getattr(context.scene, "rtl_props", None)
        if props is not None:
            props.cancelled = True
            props.is_running = False

        rtl_start = get_lightshow(context.scene).rtl_start_frame
        drones = get_drones(context.scene.collection)
        for drone in drones:
            _remove_keys_after(drone, int(rtl_start))

        if "RTL start" in context.scene.timeline_markers:
            context.scene.timeline_markers.remove(context.scene.timeline_markers["RTL start"])
        if "RTL end" in context.scene.timeline_markers:
            context.scene.timeline_markers.remove(context.scene.timeline_markers["RTL end"])
        return {"FINISHED"}


class LIGHTSHOW_OT_rtl_reset(BaseOperator):
    bl_label = "Reset RTL"
    bl_description = "Reset the RTL process and restore the show to the RTL start frame"
    bl_idname = "lightshow.rtl_reset"

    def execute(self, context: bpy.types.Context) -> set[str]:
        lightshow = get_lightshow(context.scene)
        start_marker = context.scene.timeline_markers.get("RTL start")
        if start_marker is None:
            self.report_print({"ERROR"}, "RTL start marker not found")
            return {"CANCELLED"}

        rtl_start = int(start_marker.frame)
        props = getattr(context.scene, "rtl_props", None)
        if props is not None:
            props.cancelled = False
            props.is_running = False
            props.calculated_trajectories = 0
            props.current_time_delta = 0

        for drone in get_drones(context.scene.collection):
            _remove_keys_after(drone, rtl_start)

        for marker_name in ("RTL start", "RTL end"):
            marker = context.scene.timeline_markers.get(marker_name)
            if marker is not None:
                context.scene.timeline_markers.remove(marker)

        context.scene.frame_end = max(1, rtl_start)
        context.scene.frame_set(rtl_start)
        lightshow.rtl_start_frame = -1
        return {"FINISHED"}


classes = [
    LIGHTSHOW_OT_rtl,
    LIGHTSHOW_OT_rtl_cancel,
    LIGHTSHOW_OT_rtl_reset,
    RTL_PT_subpanel,
]


def register() -> None:
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
