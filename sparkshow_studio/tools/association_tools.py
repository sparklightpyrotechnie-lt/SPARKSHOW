"""Association between drones and targets."""

from typing import TYPE_CHECKING

import numpy as np
from scipy.optimize import linear_sum_assignment
from tqdm import tqdm

from .distance_tools import calculate_min_distance_squared_sync

if TYPE_CHECKING:
    from numpy.typing import NDArray


def get_hungarian_association(
    drones: "NDArray[np.float32]",
    targets: "NDArray[np.float32]",
) -> "NDArray[np.uint16]":
    """Get the association using the Hungarian algorithm."""
    cost_matrix = np.linalg.norm(drones.reshape(-1, 1, 3) - targets.reshape(1, -1, 3), axis=2)
    row_ind, col_ind = linear_sum_assignment(cost_matrix)
    return col_ind.astype(np.uint16)


def get_couple_combination(n: int) -> "NDArray[np.uint16]":
    """Get the combination of couples of indices."""
    a = np.arange(n, dtype=np.uint16)
    combinations = np.stack(np.meshgrid(a, a)).reshape(2, -1)
    return combinations[:, combinations[0] != combinations[1]]


def get_association(
    drones: "NDArray[np.float32]",
    targets: "NDArray[np.float32]",
) -> "NDArray[np.uint16]":
    if len(drones) == 1:
        return np.array([0], dtype=np.uint16)

    centered_drones = drones - drones.mean(axis=0)
    centered_targets = targets - targets.mean(axis=0)
    association = get_hungarian_association(centered_drones, centered_targets)
    combinations = get_couple_combination(len(drones))
    best_association = None
    best_min_distance = None

    nb_iterations = 1
    drone_index1 = None
    drone_index2 = None
    last_drone_index1 = None
    last_drone_index2 = None
    bar = tqdm()
    while drone_index1 is None or (
        (drone_index1, drone_index2) != (last_drone_index1, last_drone_index2)
    ):
        sorted_targets = targets[association]
        nb_iterations += 1
        distance_squarred = calculate_min_distance_squared_sync(
            drones[combinations[0]],
            sorted_targets[combinations[0]],
            drones[combinations[1]],
            sorted_targets[combinations[1]],
        )
        min_index = np.argmin(distance_squarred)
        min_distance = np.sqrt(distance_squarred[min_index])

        if best_min_distance is None or min_distance > best_min_distance:
            best_min_distance = min_distance
            bar.n = best_min_distance
            bar.display(msg=f"Best min distance found: {best_min_distance:.2f}m")
            best_association = association.copy()

        last_drone_index1, last_drone_index2 = drone_index1, drone_index2
        drone_index1, drone_index2 = combinations[:, min_index]
        association = association.copy()
        association[[drone_index1, drone_index2]] = association[[drone_index2, drone_index1]]

    assert best_association is not None

    return best_association
