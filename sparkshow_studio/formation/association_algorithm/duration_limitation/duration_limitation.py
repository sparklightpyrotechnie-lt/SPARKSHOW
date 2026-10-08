from typing import TYPE_CHECKING

import numpy as np

from sparkshow_studio._loader.parameters import IostarPhysicParameters
from sparkshow_studio._loader.reports import PerformanceReport
from sparkshow_studio._loader.schemas import DroneUser, ShowUser

from .theorical_duration_limitation import get_theorical_duration_limitation_second

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from ....setup import Lightshow


def add_numpy_to_drone_user(
    drone_user: DroneUser,
    frames: "NDArray[np.intp]",
    positions: "NDArray[np.float32]",
) -> None:
    for frame, xyz_position in zip(frames, positions, strict=False):
        drone_user.add_position_event(
            int(frame),
            (
                float(xyz_position[0]),
                float(xyz_position[1]),
                float(xyz_position[2]),
            ),
        )


# Bezier equation development reference.
def get_bezier_positions_from_pos_time_max(
    pos_max: float,
    t_max: float,
) -> "NDArray[np.float32]":
    a_o = (12 * pos_max) / (t_max**2)
    # TODO(thomas): find a way to have the magic value 4 (position_export_fps)
    nb_iteration = int(4 * t_max)
    if nb_iteration == 0:
        return np.array([0.0])
    return np.array(
        [
            (1 / 4) * a_o * (t_max * trajectory_index / nb_iteration) ** 2
            - (1 / 6) * (a_o / t_max) * (t_max * trajectory_index / nb_iteration) ** 3
            for trajectory_index in range(nb_iteration + 1)
        ],
    )


def get_trajectory_simulation_show_user(
    duration_limitation_second: float,
    numpy_drones: "NDArray[np.float32]",
    numpy_targets: "NDArray[np.float32]",
    lightshow: "Lightshow",
) -> ShowUser:
    duration_limitation_second = max(duration_limitation_second, 0.25)
    trajectory_simulation_show_user = ShowUser.create(
        nb_drones=len(numpy_drones),
        angle_takeoff=lightshow.angle_takeoff,
        step_x=lightshow.step_x,
        step_y=lightshow.step_y,
    )
    # TODO(thomas): find a way to have the magic value 24 (fps) and 6 (position_frame_step)
    frames = np.arange(0, int(24 * duration_limitation_second + 1), 6).astype(np.intp)
    for drone_user, numpy_drone, numpy_target in zip(
        trajectory_simulation_show_user.drones_user,
        numpy_drones,
        numpy_targets,
        strict=False,
    ):
        xyz_positions = np.transpose(
            np.array(
                [
                    get_bezier_positions_from_pos_time_max(
                        abs(numpy_drone[position_index] - numpy_target[position_index]),
                        duration_limitation_second,
                    )
                    for position_index in range(3)
                ],
            ),
        )
        add_numpy_to_drone_user(drone_user, frames, xyz_positions)
    return trajectory_simulation_show_user


def get_nb_performance_infraction_from_transition(
    duration_limitation_second: float,  # TODO(thomas): round to milimeter and handle the case where the duration is 0
    numpy_drones: "NDArray[np.float32]",
    numpy_targets: "NDArray[np.float32]",
    lightshow: "Lightshow",
    physic_parameters: IostarPhysicParameters | None = None,
) -> int:
    trajectory_simulation_show_user = get_trajectory_simulation_show_user(
        duration_limitation_second,
        numpy_drones,
        numpy_targets,
        lightshow,
    )
    if any(
        len(drone_user.position_events) == 1
        for drone_user in trajectory_simulation_show_user.drones_user
    ):
        return 1
    if physic_parameters is not None:
        trajectory_simulation_show_user.physic_parameters = physic_parameters
    return len(
        PerformanceReport.generate(trajectory_simulation_show_user, is_partial=True),
    )


def get_performance_check_duration_limitation_second(
    theorical_limitation_second: float,
    numpy_drones: "NDArray[np.float32]",
    numpy_targets: "NDArray[np.float32]",
    lightshow: "Lightshow",
    physic_parameters: IostarPhysicParameters | None = None,
) -> float:
    max_delta_correction_limitation_second = 30
    time_search_step = 0.5

    time_candidates = np.arange(
        theorical_limitation_second,
        theorical_limitation_second + max_delta_correction_limitation_second,
        time_search_step,
    )
    for time_candidate in time_candidates:
        if (
            get_nb_performance_infraction_from_transition(
                time_candidate,
                numpy_drones,
                numpy_targets,
                lightshow,
                physic_parameters,
            )
            == 0
        ):
            # TODO(thomas): "+ time_search_step" because I do not trust 100% the get_bezier_positions_from_pos_time_max simulation
            return time_candidate + time_search_step
    msg = "No duration limitation found."
    raise ValueError(msg)


def get_duration_limitation_second(
    drone_positions: "NDArray[np.float32]",
    target_positions: "NDArray[np.float32]",
    physic_parameters: IostarPhysicParameters,
    lightshow: "Lightshow",
) -> float:
    theorical_limitation_second = get_theorical_duration_limitation_second(
        drone_positions,
        target_positions,
        physic_parameters,
    )
    return get_performance_check_duration_limitation_second(
        theorical_limitation_second,
        drone_positions,
        target_positions,
        lightshow,
        physic_parameters,
    )
