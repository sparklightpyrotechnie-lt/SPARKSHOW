from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from sparkshow_studio._loader.parameters import IostarPhysicParameters


def get_duration_bezier_from_vel_max(distance: float, vel_max: float) -> float:
    return 1.5 * distance / vel_max


def get_duration_bezier_from_acc_max(distance: float, acc_max: float) -> float:
    return np.sqrt(6 * distance / acc_max)


def get_theorical_duration_limitation_second(
    numpy_drones: "NDArray[np.float32]",
    numpy_targets: "NDArray[np.float32]",
    physic_parameters: "IostarPhysicParameters",
) -> float:
    drone_target_differences = [
        numpy_drones - numpy_targets
        for numpy_drones, numpy_targets in zip(numpy_drones, numpy_targets, strict=False)
    ]
    dist_h_max = max(
        float(np.linalg.norm(drone_target_difference[0:2]))
        for drone_target_difference in drone_target_differences
    )
    dist_v_max = max(
        float(np.linalg.norm(drone_target_difference[2]))
        for drone_target_difference in drone_target_differences
    )
    dist_max = max(
        float(np.linalg.norm(drone_target_difference))
        for drone_target_difference in drone_target_differences
    )
    duration_limitation_h_vel = get_duration_bezier_from_vel_max(
        dist_h_max,
        physic_parameters.horizontal_velocity_max,
    )
    duration_limitation_up_vel = get_duration_bezier_from_vel_max(
        dist_v_max,
        physic_parameters.velocity_up_max,
    )
    duration_limitation_down_vel = get_duration_bezier_from_vel_max(
        dist_v_max,
        physic_parameters.velocity_down_max,
    )
    duration_limitation_acc = get_duration_bezier_from_acc_max(
        dist_max,
        physic_parameters.acceleration_max,
    )
    return max(
        duration_limitation_h_vel,
        duration_limitation_up_vel,
        duration_limitation_down_vel,
        duration_limitation_acc,
    )
