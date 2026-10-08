from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

DECIMAL_NUMBER_TOLERANCE = 3


@dataclass(frozen=True)
class SimulationInfo:
    frame: int
    position: "NDArray[np.float64]"

    def __repr__(self) -> str:  # pragma: no cover
        return f"SimulationInfo frame={self.frame}, position={self.position}"

    def __eq__(self, other_simulation_info: object) -> bool:
        if not isinstance(other_simulation_info, SimulationInfo):
            return False
        return bool(
            self.frame == other_simulation_info.frame
            and np.allclose(
                self.position,
                other_simulation_info.position,
                atol=10 ** (-DECIMAL_NUMBER_TOLERANCE),
            ),
        )


def apply_decimal_number_tolerance(
    position_array: "NDArray[np.float64]",
) -> "NDArray[np.float64]":
    return np.round(position_array, DECIMAL_NUMBER_TOLERANCE)


def linear_interpolation(
    position_begin: tuple[float, float, float],
    position_end: tuple[float, float, float],
    nb_points: int,
) -> list["NDArray[np.float64]"]:
    if nb_points < 0:
        msg = f"nb_points must be positive: nb_points = {nb_points}"
        raise ValueError(msg)
    if nb_points == 0:
        return []
    return [
        apply_decimal_number_tolerance(
            np.array(position_begin, dtype=np.float64) * (1 - percentile)
            + np.array(position_end, dtype=np.float64) * percentile,
        )
        for percentile in np.linspace(0, 1, nb_points, endpoint=False)
    ]
