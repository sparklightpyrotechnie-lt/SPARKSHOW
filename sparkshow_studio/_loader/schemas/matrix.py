from collections.abc import Sequence
from typing import TYPE_CHECKING, overload

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray


@overload
def get_matrix(*, matrix: Sequence[Sequence[int]]) -> "NDArray[np.intp]": ...


@overload
def get_matrix(
    *,
    nb_x: int = 1,
    nb_y: int = 1,
    nb_drones_per_family: int = 1,
) -> "NDArray[np.intp]": ...


def get_matrix(
    *,
    matrix: Sequence[Sequence[int]] | None = None,
    nb_x: int = 1,
    nb_y: int = 1,
    nb_drones_per_family: int = 1,
) -> "NDArray[np.intp]":
    if matrix is not None:
        return np.array(matrix, dtype=np.intp)
    return np.full((nb_y, nb_x), nb_drones_per_family, dtype=np.intp)
