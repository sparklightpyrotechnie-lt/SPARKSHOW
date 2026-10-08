# pyright: reportIncompatibleMethodOverride=false
import itertools
from enum import Enum

import numpy as np
from tqdm import tqdm

from sparkshow_studio._loader.parameters import IOSTAR_PHYSIC_PARAMETERS_MAX, IostarPhysicParameters
from sparkshow_studio._loader.reports.base import BaseInfraction, BaseInfractionsSummary, apply_func_on_optional_pair
from sparkshow_studio._loader.schemas import ShowUser
from sparkshow_studio._loader.schemas.show_user.show_trajectory_performance import (
    DroneTrajectoryPerformance,
    Performance,
)


class PerformanceKind(Enum):
    HORIZONTAL_VELOCITY = "horizontal velocity"
    UP_VELOCITY = "up velocity"
    DOWN_VELOCITY = "down velocity"
    ACCELERATION = "acceleration"

    def check(
        self,
        physic_parameters: IostarPhysicParameters,
        performance: Performance,
        tolerance_percentage: float,
    ) -> tuple[bool, float]:
        """Check if the performance is above the threshold."""
        if self == PerformanceKind.HORIZONTAL_VELOCITY:
            threshold = physic_parameters.horizontal_velocity_max
            value = float(np.linalg.norm(performance.velocity[0:2]))
        elif self == PerformanceKind.UP_VELOCITY:
            threshold = physic_parameters.velocity_up_max
            value = float(performance.velocity[2])
        elif self == PerformanceKind.DOWN_VELOCITY:
            threshold = physic_parameters.velocity_down_max
            value = float(-performance.velocity[2])
        elif self == PerformanceKind.ACCELERATION:
            threshold = physic_parameters.acceleration_max
            value = float(np.linalg.norm(performance.acceleration))
        else:  # pragma: no cover
            msg = f"PerformanceKind {self} not implemented in check_performance()."
            raise NotImplementedError(msg)

        return value > threshold * tolerance_percentage, value


class PerformanceInfraction(BaseInfraction):
    performance_name: str
    drone_index: int
    frame: int
    value: float

    @classmethod
    def _get_performance_infractions_from_performance(
        cls,
        drone_index: int,
        frame: int,
        performance: Performance,
        physic_parameters: IostarPhysicParameters,
        tolerance_percentage: float,
    ) -> list["PerformanceInfraction"]:
        performance_infractions: list[PerformanceInfraction] = []
        for performance_kind in PerformanceKind:
            is_infraction, value = performance_kind.check(
                physic_parameters,
                performance,
                tolerance_percentage=tolerance_percentage,
            )
            if is_infraction:
                performance_infractions.append(
                    PerformanceInfraction(
                        performance_name=performance_kind.value,
                        drone_index=drone_index,
                        frame=frame,
                        value=value,
                    ),
                )
        return performance_infractions

    @classmethod
    def _get_performance_infractions_from_drone_performance(
        cls,
        drone_trajectory_performance: DroneTrajectoryPerformance,
        physic_parameters: IostarPhysicParameters,
        tolerance_percentage: float,
    ) -> list["PerformanceInfraction"]:
        return list(
            itertools.chain.from_iterable(
                cls._get_performance_infractions_from_performance(
                    drone_trajectory_performance.index,
                    trajectory_performance_info.frame,
                    trajectory_performance_info.performance,
                    physic_parameters,
                    tolerance_percentage,
                )
                for (
                    trajectory_performance_info
                ) in drone_trajectory_performance.trajectory_performance_infos
            ),
        )

    @classmethod
    def generate(
        cls,
        show_user: ShowUser,
        *,
        is_partial: bool,
        is_import: bool,
    ) -> list["PerformanceInfraction"]:
        show_trajectory_performance = DroneTrajectoryPerformance.from_show_user(show_user)
        physic_parameters = show_user.physic_parameters
        if (
            physic_parameters.horizontal_velocity_max
            > IOSTAR_PHYSIC_PARAMETERS_MAX.horizontal_velocity_max
        ):
            msg = f"Horizontal velocity max {physic_parameters.horizontal_velocity_max} is greater than {IOSTAR_PHYSIC_PARAMETERS_MAX.horizontal_velocity_max}"
            raise ValueError(msg)
        if physic_parameters.velocity_up_max > IOSTAR_PHYSIC_PARAMETERS_MAX.velocity_up_max:
            msg = f"Up velocity max {physic_parameters.velocity_up_max} is greater than {IOSTAR_PHYSIC_PARAMETERS_MAX.velocity_up_max}"
            raise ValueError(msg)
        if physic_parameters.velocity_down_max > IOSTAR_PHYSIC_PARAMETERS_MAX.velocity_down_max:
            msg = f"Down velocity max {physic_parameters.velocity_down_max} is greater than {IOSTAR_PHYSIC_PARAMETERS_MAX.velocity_down_max}"
            raise ValueError(msg)
        if physic_parameters.acceleration_max > IOSTAR_PHYSIC_PARAMETERS_MAX.acceleration_max:
            msg = f"Acceleration max {physic_parameters.acceleration_max} is greater than {IOSTAR_PHYSIC_PARAMETERS_MAX.acceleration_max}"
            raise ValueError(msg)

        if is_partial:
            tolerance_percentage = 1.0
        elif is_import:
            tolerance_percentage = 1.10
        else:
            tolerance_percentage = 1.05

        infractions = itertools.chain.from_iterable(
            cls._get_performance_infractions_from_drone_performance(
                drone_trajectory_performance,
                physic_parameters,
                tolerance_percentage,
            )
            for drone_trajectory_performance in tqdm(
                show_trajectory_performance,
                desc="Checking speed profiles",
                unit="drone",
            )
        )
        if show_user.rtl_start_frame is None:
            return list(infractions)

        return [
            infraction
            for infraction in infractions
            if not (
                infraction.performance_name == PerformanceKind.ACCELERATION.value
                and infraction.frame >= show_user.rtl_start_frame
            )
        ]

    def summarize(self) -> "PerformanceInfractionsSummary":
        return PerformanceInfractionsSummary(
            nb_infractions=len(self),
            min_performance_infraction=self,
            max_performance_infraction=self,
            first_performance_infraction=self,
            last_performance_infraction=self,
        )


class PerformanceInfractionsSummary(BaseInfractionsSummary):
    min_performance_infraction: PerformanceInfraction | None = None
    max_performance_infraction: PerformanceInfraction | None = None
    first_performance_infraction: PerformanceInfraction | None = None
    last_performance_infraction: PerformanceInfraction | None = None

    def __add__(self, other: "PerformanceInfractionsSummary") -> "PerformanceInfractionsSummary":
        return PerformanceInfractionsSummary(
            nb_infractions=self.nb_infractions + other.nb_infractions,
            min_performance_infraction=apply_func_on_optional_pair(
                self.min_performance_infraction,
                other.min_performance_infraction,
                lambda x, y: x if x.value < y.value else y,
            ),
            max_performance_infraction=apply_func_on_optional_pair(
                self.max_performance_infraction,
                other.max_performance_infraction,
                lambda x, y: x if x.value > y.value else y,
            ),
            first_performance_infraction=apply_func_on_optional_pair(
                self.first_performance_infraction,
                other.first_performance_infraction,
                lambda x, y: x if x.frame < y.frame else y,
            ),
            last_performance_infraction=apply_func_on_optional_pair(
                self.last_performance_infraction,
                other.last_performance_infraction,
                lambda x, y: x if x.frame > y.frame else y,
            ),
        )
