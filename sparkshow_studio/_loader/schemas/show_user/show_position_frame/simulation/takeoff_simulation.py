from typing import TYPE_CHECKING

from sparkshow_studio._loader.parameters import FRAME_PARAMETERS, TAKEOFF_PARAMETERS

from .position_simulation import SimulationInfo, linear_interpolation

if TYPE_CHECKING:
    import numpy as np
    from numpy.typing import NDArray


def generate_takeoff_first_part(
    takeoff_start_position: tuple[float, float, float],
    takeoff_middle_position: tuple[float, float, float],
) -> list["NDArray[np.float64]"]:
    return linear_interpolation(
        takeoff_start_position,
        takeoff_middle_position,
        FRAME_PARAMETERS.from_second_to_frame(
            TAKEOFF_PARAMETERS.takeoff_elevation_duration_second,
        ),
    )


def generate_takeoff_second_part(
    takeoff_middle_position: tuple[float, float, float],
    takeoff_end_position: tuple[float, float, float],
    frame_middle_takeoff: int,
    frame_end_takeoff: int,
) -> list["NDArray[np.float64]"]:
    return linear_interpolation(
        takeoff_middle_position,
        takeoff_end_position,
        frame_end_takeoff - frame_middle_takeoff,
    )


def takeoff_simulation(
    takeoff_start_position: tuple[float, float, float],
    takeoff_end_position: tuple[float, float, float],
    frame_begin: int,
    frame_end: int,
) -> list["SimulationInfo"]:
    takeoff_middle_position = (
        takeoff_start_position[0],
        takeoff_start_position[1],
        takeoff_start_position[2] + TAKEOFF_PARAMETERS.takeoff_altitude_meter_min,
    )

    takeoff_positions = generate_takeoff_first_part(takeoff_start_position, takeoff_middle_position)
    takeoff_positions += generate_takeoff_second_part(
        takeoff_middle_position,
        takeoff_end_position,
        frame_begin + len(takeoff_positions),
        frame_end,
    )

    return [
        SimulationInfo(
            frame=frame_begin + frame_index,
            position=takeoff_position,
        )
        for frame_index, takeoff_position in enumerate(takeoff_positions)
    ]
