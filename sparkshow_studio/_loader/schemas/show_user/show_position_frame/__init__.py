from typing import TYPE_CHECKING

import numpy as np
from tqdm import tqdm

from sparkshow_studio._loader.schemas.show_user.show_position_frame.simulation.flight_simulation import (
    get_flight_simulation,
    get_partial_flight_simulation,
)
from sparkshow_studio._loader.schemas.show_user.show_user import ShowUser

if TYPE_CHECKING:
    from numpy.typing import NDArray


class ShowPositionFrame:
    def __init__(self, frame: int, drone_indices: list["int"]) -> None:
        nb_drones = len(drone_indices)

        self.frame = frame
        self._indices = np.array(drone_indices, dtype=np.intp)
        self._positions = np.zeros((nb_drones, 3), dtype=np.float64)

    def __repr__(self) -> str:  # pragma: no cover
        return f"ShowPositionFrame frame={self.frame}, positions={self._positions}..."

    def update_position_air_flag(
        self,
        index: int,
        position: "NDArray[np.float64]",
    ) -> None:
        index = np.where(self._indices == index)[0][0]
        self._positions[index] = position

    @property
    def in_air_indices(self) -> "NDArray[np.intp]":
        return self._indices[~np.isclose(self._positions[:, 2], 0, atol=5e-2)]

    @property
    def in_air_positions(self) -> "NDArray[np.float64]":
        return self._positions[~np.isclose(self._positions[:, 2], 0, atol=5e-2)]

    def __len__(self) -> int:
        return len(self._indices)

    @classmethod
    def from_show_user(
        cls,
        show_user: ShowUser,
        *,
        is_partial: bool,
    ) -> list["ShowPositionFrame"]:
        drone_indices = [drone_user.index for drone_user in show_user.drones_user]
        flight_simulations = [
            get_partial_flight_simulation(drone_user)
            if is_partial
            else get_flight_simulation(drone_user, show_user.last_frame, show_user.land_type)
            for drone_user in tqdm(
                show_user.drones_user,
                desc="Computing flight simulations",
                unit="drone",
            )
        ]
        show_position_frames = [
            ShowPositionFrame(frame, drone_indices)
            for frame in range(
                min(flight_simulation[0].frame for flight_simulation in flight_simulations),
                max(flight_simulation[-1].frame for flight_simulation in flight_simulations) + 1,
                6,
            )
        ]
        for drone_index, flight_simulation in tqdm(
            zip(drone_indices, flight_simulations, strict=True),
            desc="Computing show position frames",
            total=len(drone_indices),
            unit="drone",
        ):
            for show_slice, simulation_info in zip(
                show_position_frames, flight_simulation[::6], strict=False
            ):
                show_slice.update_position_air_flag(
                    drone_index,
                    simulation_info.position,
                )
        return show_position_frames
