import threading
import warnings
from collections.abc import Generator
from typing import Any

import numpy as np
from numpy.typing import NDArray
from tqdm import tqdm


class RTLCalculator:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args: Any, **kwargs: Any) -> "RTLCalculator":  # noqa: ANN401, ARG003
        with cls._lock:
            if not cls._instance:
                cls._instance = super().__new__(cls)
                # Initialize any variables here if needed
        return cls._instance

    def __init__(
        self,
        drones_landings: dict[int, list[tuple[int, NDArray[np.float32]]]],
        min_dist: float,
        frame_delta: int,
        mode: str = "RTL",
    ) -> None:
        self.report_message = ""
        self.min_dist = min_dist
        self.min_dist_squared = min_dist**2
        self._position_in_hashmap = {}
        self.mode = mode
        self.waiting_drones_hashmap = self.get_waiting_drones_hashmap(drones_landings)
        self.moving_drones_hashmap = {}
        self.drones_hashmap = self.init_drones_hashmap(drones_landings)
        self.nb_drones = len(drones_landings)
        self.frame_delta = frame_delta
        self.is_cancelled = False
        self._start_delta = 0

    def cancel(self) -> None:
        self.is_cancelled = True

    @classmethod
    def instance(cls, *args: Any, **kwargs: Any) -> "RTLCalculator":  # noqa: ANN401
        if not cls._instance:
            cls._instance = cls(*args, **kwargs)
        return cls._instance

    @classmethod
    def remove_instance(cls) -> None:
        cls._instance = None

    @property
    def start_delta(self) -> int:
        return self._start_delta

    def hash(self, position: NDArray[np.float32]) -> tuple[int, int, int]:
        return tuple((position // self.min_dist).astype(int))

    def get_waiting_drones_hashmap(
        self, drones_landings: dict[int, list[tuple[int, NDArray[np.float32]]]]
    ) -> dict[tuple[int, int, int], list[tuple[NDArray[np.float32], int]]]:
        """
        Take the drones' landing positions and returns the hashmap.

        The hashmap contains, for each "3D volume," the list of drones that are waiting to land.
        If two drones are too close to each other, return an error message.
        """
        waiting_drones_hashmap = {}

        for drone_index, drone_landing in drones_landings.items():
            if self.mode == "RTL":
                waiting_position = drone_landing[0][1]
            else:
                msg = f"Unknown mode: {self.mode}"
                raise ValueError(msg)

            drone_hash = self.hash(waiting_position)
            if drone_hash in waiting_drones_hashmap:
                for position, idx in waiting_drones_hashmap[drone_hash]:
                    if (
                        np.linalg.norm(np.array(position) - np.array(waiting_position))
                        < self.min_dist
                    ):
                        msg = f"Drone {drone_index} is too close to drone {idx} distance = {np.linalg.norm(np.array(position) - np.array(waiting_position))}, please update drones positions."
                        msg += f"\nDrone {drone_index} position: {waiting_position}"
                        msg += f"\nDrone {idx} position: {position}"
                        warnings.warn(msg)  # noqa: B028
                        self.report_message = msg
                        return {}
                waiting_drones_hashmap[drone_hash].append((waiting_position, drone_index))
                self._position_in_hashmap[drone_index] = (drone_hash, waiting_position)
            else:
                waiting_drones_hashmap[drone_hash] = [(waiting_position, drone_index)]
                self._position_in_hashmap[drone_index] = (drone_hash, waiting_position)

        return waiting_drones_hashmap

    def start_drone(self, drone_index: int, start_delta: int) -> None:
        drone_hash, position = self._position_in_hashmap[drone_index]

        # remove the drone from the waiting drones hashmap
        if len(self.waiting_drones_hashmap[drone_hash]) == 1:  # only drone in the hashmap
            del self.waiting_drones_hashmap[drone_hash]
        else:
            new_value = []
            for item in self.waiting_drones_hashmap[drone_hash]:
                pos, idx = item
                if idx == drone_index:
                    continue
                new_value.append((pos, idx))
            self.waiting_drones_hashmap[drone_hash] = new_value

        # add the drone to the moving drones hashmap
        drone_landing = self.drones_hashmap[drone_index]
        for frame_delta, position_hash, position in drone_landing:
            landing_frame = frame_delta + start_delta
            if landing_frame not in self.moving_drones_hashmap:
                self.moving_drones_hashmap[landing_frame] = {}
            if position_hash in self.moving_drones_hashmap[landing_frame]:
                self.moving_drones_hashmap[landing_frame][position_hash].append(
                    (position, drone_index)
                )
            else:
                self.moving_drones_hashmap[landing_frame][position_hash] = [(position, drone_index)]

    def init_drones_hashmap(
        self, drones_landings: dict[int, list[tuple[int, NDArray[np.float32]]]]
    ) -> dict[int, list[tuple[int, tuple[int, int, int], NDArray[np.float32]]]]:
        if self.report_message:  # skip if there is an error
            return {}
        drones_hash = {}

        for drone_index, drone_landing in drones_landings.items():
            drones_hash[drone_index] = []
            for frame_delta, position in drone_landing:
                drone_hash = self.hash(position)
                drones_hash[drone_index].append((frame_delta, drone_hash, position))
        return drones_hash

    def has_collision(
        self,
        hashcode: tuple[int, int, int],
        position: NDArray[np.float32],
        hashmap: dict[tuple[int, int, int], list[tuple[NDArray[np.float32], int]]],
        index: int,
    ) -> bool:
        x, y, z = hashcode
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                for dz in [-1, 0, 1]:
                    if (x + dx, y + dy, z + dz) in hashmap:
                        for drone_position, drone_index in hashmap[(x + dx, y + dy, z + dz)]:
                            if drone_index == index:
                                continue
                            dist_squared = np.sum(
                                (np.array(drone_position) - np.array(position)) ** 2
                            )
                            if dist_squared < self.min_dist_squared:
                                return True
        return False

    def has_collision_with_waiting_drones(
        self,
        drone_landing: list[tuple[int, tuple[int, int, int], NDArray[np.float32]]],
        drone_index: int,
    ) -> bool:
        for _, position_hash, position in drone_landing:
            if self.has_collision(
                position_hash, position, self.waiting_drones_hashmap, drone_index
            ):
                return True
        return False

    def has_collision_with_moving_drones(
        self,
        drone_landing: list[tuple[int, tuple[int, int, int], NDArray[np.float32]]],
        start_delta: int,
        index: int,
    ) -> bool:
        for frame_delta, position_hash, position in drone_landing:
            if start_delta + frame_delta not in self.moving_drones_hashmap:
                continue
            if self.has_collision(
                position_hash,
                position,
                self.moving_drones_hashmap[start_delta + frame_delta],
                index,
            ):
                return True
        return False

    def get_waiting_times(self) -> Generator[tuple[int, int] | None]:
        self._start_delta = 0
        waiting_drones = list(range(self.nb_drones))

        with tqdm(total=len(waiting_drones)) as pbar:
            while len(waiting_drones) > 0 and not self.is_cancelled:
                for drone_index in waiting_drones:
                    drone_landing = self.drones_hashmap[drone_index]

                    if self.has_collision_with_waiting_drones(drone_landing, drone_index):
                        continue

                    if self.has_collision_with_moving_drones(
                        drone_landing, self._start_delta, drone_index
                    ):
                        continue

                    self.start_drone(drone_index, self._start_delta)
                    yield (
                        drone_index,
                        self._start_delta,
                    )  # Return waiting times as they are calculated
                    waiting_drones.remove(drone_index)
                    pbar.update(1)

                self._start_delta += self.frame_delta
                pbar.set_description(f"start_delta: {self._start_delta}")

        yield None

    def parse_chunk(self, chunk: tuple[int, int]) -> dict[str, Any]:
        drone_idx, start_delta = chunk
        return {
            "drone_idx": drone_idx,
            "waiting_time": start_delta,
        }
