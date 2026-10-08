from typing import TYPE_CHECKING

import numpy as np

from sparkshow_studio._loader.parameters import FRAME_PARAMETERS, LAND_PARAMETERS

from .position_simulation import SimulationInfo, linear_interpolation

if TYPE_CHECKING:
    from numpy.typing import NDArray


def generate_land_first_part(
    land_start_position: tuple[float, float, float],
) -> list["NDArray[np.float64]"]:
    land_middle_position = (
        land_start_position[0],
        land_start_position[1],
        LAND_PARAMETERS.get_second_land_altitude_start(land_start_position[2]),
    )
    return linear_interpolation(
        land_start_position,
        land_middle_position,
        FRAME_PARAMETERS.from_second_to_frame(
            LAND_PARAMETERS.get_first_land_second_delta(land_start_position[2]),
        ),
    )


def generate_land_second_part(
    land_start_position: tuple[float, float, float],
) -> list["NDArray[np.float64]"]:
    land_middle_position = (
        land_start_position[0],
        land_start_position[1],
        LAND_PARAMETERS.get_second_land_altitude_start(land_start_position[2]),
    )
    land_end_position = (
        land_start_position[0],
        land_start_position[1],
        0,
    )
    return linear_interpolation(
        land_middle_position,
        land_end_position,
        FRAME_PARAMETERS.from_second_to_frame(
            LAND_PARAMETERS.get_second_land_second_delta(land_start_position[2]),
        ),
    )


def land_simulation(
    land_start_position: tuple[float, float, float],
    frame_begin: int,
) -> list["SimulationInfo"]:
    land_positions = generate_land_first_part(
        land_start_position,
    ) + generate_land_second_part(
        land_start_position,
    )
    return [
        SimulationInfo(
            frame=frame_begin + frame_index,
            position=land_position,
        )
        for frame_index, land_position in enumerate(land_positions)
    ]


def rtl_simulation(
    takeoff_position: tuple[float, float, float],
    rtl_start_position: tuple[float, float, float],
    frame_begin: int,
    speed: float = 2.0,
) -> list["SimulationInfo"]:
    rtl_end_position = (
        takeoff_position[0],
        takeoff_position[1],
        0.0,
    )

    rtl_duration = round(
        np.linalg.norm(
            np.array(rtl_end_position, dtype=np.float32)
            - np.array(rtl_start_position, dtype=np.float32)
        )
        * 1.57
        / speed
        * FRAME_PARAMETERS.fps
    )

    land_positions = linear_interpolation(
        rtl_start_position,
        rtl_end_position,
        rtl_duration,
    )

    return [
        SimulationInfo(
            frame=frame_begin + frame_index,
            position=land_position,
        )
        for frame_index, land_position in enumerate(land_positions)
    ]
