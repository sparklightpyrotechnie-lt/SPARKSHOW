from collections.abc import Generator
from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray


def evaluate_trajectory(
    x0: "NDArray[np.float32]",
    dx: "NDArray[np.float32]",
    t0: "NDArray[np.float32]",
    dt: "NDArray[np.float32]",
    t: "NDArray[np.float32]",
) -> "NDArray[np.float32]":
    """Evaluate the trajectory at the given time."""
    result = np.full_like(x0, np.nan, dtype=np.float32)
    is_dt_null = np.abs(dt) < 1e-6
    is_dt_not_null = ~is_dt_null
    result[is_dt_null] = x0[is_dt_null] + dx[is_dt_null] / 2
    result[is_dt_not_null] = x0[is_dt_not_null] + dx[is_dt_not_null] * (
        (t[is_dt_not_null] - t0[is_dt_not_null]) / dt[is_dt_not_null]
    ).reshape(-1, 1)
    return result


def calculate_min_distance_squared_sync(
    xs1: "NDArray[np.float32]",
    xe1: "NDArray[np.float32]",
    xs2: "NDArray[np.float32]",
    xe2: "NDArray[np.float32]",
) -> "NDArray[np.float32]":
    """Calculate the minimal squared distance between two synchronous linear trajectories.

    Synchronized trajectories are trajectories that start at the same time and end at the same time.
    """
    distance_squarred = np.full(len(xs1), np.nan, dtype=np.float32)

    alpha = (xe2 - xs2) - (xe1 - xs1)
    beta = xs2 - xs1

    is_parallel = (np.abs(alpha) < 1e-6).all(axis=1)
    distance_squarred[is_parallel] = np.sum(np.square(beta[is_parallel]), axis=1)

    is_not_parallel = np.logical_not(is_parallel)
    alpha_np = alpha[is_not_parallel]
    beta_np = beta[is_not_parallel]
    t_min = np.clip(
        -np.sum(alpha_np * beta_np, axis=1) / np.sum(np.square(alpha_np), axis=1),
        0,
        1,
    )
    distance_squarred[is_not_parallel] = np.sum(
        np.square(beta_np + alpha_np * t_min.reshape(-1, 1)),
        axis=1,
    )
    return distance_squarred


def calculate_min_distance_squared_async(  # noqa: PLR0913
    xs1: "NDArray[np.float32]",
    xe1: "NDArray[np.float32]",
    xs2: "NDArray[np.float32]",
    xe2: "NDArray[np.float32]",
    ts1: "NDArray[np.float32]",
    te1: "NDArray[np.float32]",
    ts2: "NDArray[np.float32]",
    te2: "NDArray[np.float32]",
    *,
    include_before_ts1: bool = True,
    include_after_te1: bool = True,
    include_before_ts2: bool = True,
    include_after_te2: bool = True,
) -> "NDArray[np.float32]":
    """Calculate the minimal squared distance between two asynchronous linear trajectories.

    Asynchronous trajectories are trajectories that either start at different times or end at different times.
    """
    dt1 = te1 - ts1
    dt2 = te2 - ts2
    dx1 = xe1 - xs1
    dx2 = xe2 - xs2

    min_distance_squarred = np.full_like(ts1, np.inf, dtype=np.float32)

    mask = (ts1 < ts2) & include_before_ts2
    te_min = np.min([te1[mask], ts2[mask]], axis=0)
    xe1_min = evaluate_trajectory(xs1[mask], dx1[mask], ts1[mask], dt1[mask], te_min)
    min_distance_squarred[mask] = np.min(
        [
            calculate_min_distance_squared_sync(xs1[mask], xe1_min, xs2[mask], xs2[mask]),
            min_distance_squarred[mask],
        ],
        axis=0,
    )
    mask = (te2 < te1) & include_after_te2
    ts_max = np.max([ts1[mask], te2[mask]], axis=0)
    xs1_max = evaluate_trajectory(xs1[mask], dx1[mask], ts1[mask], dt1[mask], ts_max)
    min_distance_squarred[mask] = np.min(
        [
            calculate_min_distance_squared_sync(xs1_max, xe1[mask], xe2[mask], xe2[mask]),
            min_distance_squarred[mask],
        ],
        axis=0,
    )
    mask = (ts2 < ts1) & include_before_ts1
    te_min = np.min([te2[mask], ts1[mask]], axis=0)
    xe2_min = evaluate_trajectory(xs2[mask], dx2[mask], ts2[mask], dt2[mask], te_min)
    min_distance_squarred[mask] = np.min(
        [
            calculate_min_distance_squared_sync(xs1[mask], xs1[mask], xs2[mask], xe2_min),
            min_distance_squarred[mask],
        ],
        axis=0,
    )
    mask = (te1 < te2) & include_after_te1
    ts_max = np.max([ts2[mask], te1[mask]], axis=0)
    xs2_max = evaluate_trajectory(xs2[mask], dx2[mask], ts2[mask], dt2[mask], ts_max)
    min_distance_squarred[mask] = np.min(
        [
            calculate_min_distance_squared_sync(xe1[mask], xe1[mask], xs2_max, xe2[mask]),
            min_distance_squarred[mask],
        ],
        axis=0,
    )
    mask = (ts1 <= ts2) & (ts2 <= te1) | (ts2 <= ts1) & (ts1 <= te2)
    ts_max = np.max([ts1[mask], ts2[mask]], axis=0)
    te_min = np.min([te1[mask], te2[mask]], axis=0)
    xs1_max = evaluate_trajectory(xs1[mask], dx1[mask], ts1[mask], dt1[mask], ts_max)
    xe1_min = evaluate_trajectory(xs1[mask], dx1[mask], ts1[mask], dt1[mask], te_min)
    xs2_max = evaluate_trajectory(xs2[mask], dx2[mask], ts2[mask], dt2[mask], ts_max)
    xe2_min = evaluate_trajectory(xs2[mask], dx2[mask], ts2[mask], dt2[mask], te_min)
    min_distance_squarred[mask] = np.min(
        [
            calculate_min_distance_squared_sync(xs1_max, xe1_min, xs2_max, xe2_min),
            min_distance_squarred[mask],
        ],
        axis=0,
    )

    return min_distance_squarred


def calculate_min_distance_squared_trajectories(  # noqa: PLR0913
    trajectories1: list[tuple["NDArray[np.float32]", "NDArray[np.float32]"]],
    trajectories2: list[tuple["NDArray[np.float32]", "NDArray[np.float32]"]],
    include_before_trajectories1: bool = True,
    include_after_trajectories1: bool = True,
    include_before_trajectories2: bool = True,
    include_after_trajectories2: bool = True,
) -> Generator["NDArray[np.float32]", None, None]:
    """Calculate the minimum distance between two trajectories.

    It will yield the minimum distance between each segment pair of the trajectories.
    """
    nb_pairs1 = len(trajectories1) - 1
    nb_pairs2 = len(trajectories2) - 1
    for index1, ((xs1, ts1), (xe1, te1)) in enumerate(pairwise(trajectories1)):
        for index2, ((xs2, ts2), (xe2, te2)) in enumerate(pairwise(trajectories2)):
            yield calculate_min_distance_squared_async(
                xs1,
                xe1,
                xs2,
                xe2,
                ts1,
                te1,
                ts2,
                te2,
                include_before_ts1=index1 == 0 and include_before_trajectories1,
                include_after_te1=index1 == nb_pairs1 - 1 and include_after_trajectories1,
                include_before_ts2=index2 == 0 and include_before_trajectories2,
                include_after_te2=index2 == nb_pairs2 - 1 and include_after_trajectories2,
            )
    return
    yield
