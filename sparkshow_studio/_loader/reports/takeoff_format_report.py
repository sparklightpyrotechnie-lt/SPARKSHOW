# pyright: reportIncompatibleMethodOverride=false
from typing import Optional

import numpy as np
from pydantic import field_serializer
from tqdm import tqdm

from sparkshow_studio._loader.parameters import TAKEOFF_PARAMETERS
from sparkshow_studio._loader.reports.base import (
    BaseInfraction,
    BaseInfractionsSummary,
    BaseReport,
    BaseReportSummary,
    apply_func_on_optional_pair,
)
from sparkshow_studio._loader.reports.ranges import get_ranges_from_drone_indices
from sparkshow_studio._loader.schemas.show_user import DroneUser, ShowUser


class TakeoffDurationInfraction(BaseInfraction):
    start_frame: float  # frame
    end_frame: float  # frame
    duration: float  # second

    @classmethod
    def generate(
        cls,
        drone_user: DroneUser,
    ) -> Optional["TakeoffDurationInfraction"]:
        first_event = drone_user.position_events[0]
        second_event = drone_user.position_events[1]
        duration = second_event.absolute_time - first_event.absolute_time

        if not np.allclose(
            duration,
            TAKEOFF_PARAMETERS.takeoff_elevation_duration_second,
            atol=TAKEOFF_PARAMETERS.takeoff_total_duration_tolerance,
        ):
            return TakeoffDurationInfraction(
                start_frame=first_event.frame,
                end_frame=second_event.frame,
                duration=duration,
            )
        return None

    def summarize(self) -> "TakeoffDurationInfractionsSummary":
        return TakeoffDurationInfractionsSummary(
            nb_infractions=len(self),
            min_duration_infraction=self,
            max_duration_infraction=self,
            first_duration_infraction=self,
            last_duration_infraction=self,
        )


class TakeoffDurationInfractionsSummary(BaseInfractionsSummary):
    min_duration_infraction: TakeoffDurationInfraction | None = None
    max_duration_infraction: TakeoffDurationInfraction | None = None
    first_duration_infraction: TakeoffDurationInfraction | None = None
    last_duration_infraction: TakeoffDurationInfraction | None = None

    def __add__(
        self,
        other: "TakeoffDurationInfractionsSummary",
    ) -> "TakeoffDurationInfractionsSummary":
        return TakeoffDurationInfractionsSummary(
            nb_infractions=self.nb_infractions + other.nb_infractions,
            min_duration_infraction=apply_func_on_optional_pair(
                self.min_duration_infraction,
                other.min_duration_infraction,
                lambda x, y: x if x.duration < y.duration else y,
            ),
            max_duration_infraction=apply_func_on_optional_pair(
                self.max_duration_infraction,
                other.max_duration_infraction,
                lambda x, y: x if x.duration > y.duration else y,
            ),
            first_duration_infraction=apply_func_on_optional_pair(
                self.first_duration_infraction,
                other.first_duration_infraction,
                lambda x, y: x if x.start_frame < y.start_frame else y,
            ),
            last_duration_infraction=apply_func_on_optional_pair(
                self.last_duration_infraction,
                other.last_duration_infraction,
                lambda x, y: x if x.end_frame > y.end_frame else y,
            ),
        )


class TakeoffPositionInfraction(BaseInfraction):
    start_position: tuple[float, float, float]
    end_position: tuple[float, float, float]

    @classmethod
    def generate(
        cls,
        drone_user: DroneUser,
    ) -> Optional["TakeoffPositionInfraction"]:
        first_position = drone_user.position_events[0].xyz
        second_position = drone_user.position_events[1].xyz

        position_infraction = TakeoffPositionInfraction(
            start_position=first_position, end_position=second_position
        )
        if first_position[0] != second_position[0]:
            return position_infraction
        if first_position[1] != second_position[1]:
            return position_infraction
        if (
            first_position[2] != 0
            or second_position[2] != TAKEOFF_PARAMETERS.takeoff_altitude_meter_min
        ):
            return position_infraction
        return None

    def summarize(self) -> "TakeoffPositionInfractionsSummary":
        return TakeoffPositionInfractionsSummary(
            nb_infractions=len(self),
            min_position_infraction=self,
            max_position_infraction=self,
        )


class TakeoffPositionInfractionsSummary(BaseInfractionsSummary):
    min_position_infraction: TakeoffPositionInfraction | None = None
    max_position_infraction: TakeoffPositionInfraction | None = None

    def __add__(
        self,
        other: "TakeoffPositionInfractionsSummary",
    ) -> "TakeoffPositionInfractionsSummary":
        def get_distance(
            position1: tuple[float, float, float],
            position2: tuple[float, float, float],
        ) -> np.float64:
            return np.linalg.norm(np.array(position1) - np.array(position2))

        return TakeoffPositionInfractionsSummary(
            nb_infractions=self.nb_infractions + other.nb_infractions,
            min_position_infraction=apply_func_on_optional_pair(
                self.min_position_infraction,
                other.min_position_infraction,
                lambda x, y: x
                if get_distance(x.start_position, x.end_position)
                < get_distance(y.start_position, y.end_position)
                else y,
            ),
            max_position_infraction=apply_func_on_optional_pair(
                self.max_position_infraction,
                other.max_position_infraction,
                lambda x, y: x
                if get_distance(x.start_position, x.end_position)
                > get_distance(y.start_position, y.end_position)
                else y,
            ),
        )


class TakeoffReport(BaseReport):
    duration_infraction: TakeoffDurationInfraction | None = None
    position_infraction: TakeoffPositionInfraction | None = None

    @classmethod
    def generate(
        cls,
        drone_user: DroneUser,
    ) -> "TakeoffReport":
        duration_infraction = TakeoffDurationInfraction.generate(
            drone_user,
        )
        position_infraction = TakeoffPositionInfraction.generate(
            drone_user,
        )
        return TakeoffReport(
            duration_infraction=duration_infraction,
            position_infraction=position_infraction,
        )

    def summarize(self) -> "TakeoffReportSummary":
        return TakeoffReportSummary(
            duration_infractions_summary=self.duration_infraction.summarize()
            if self.duration_infraction
            else None,
            position_infractions_summary=self.position_infraction.summarize()
            if self.position_infraction
            else None,
        )


class TakeoffReportSummary(BaseReportSummary):
    duration_infractions_summary: TakeoffDurationInfractionsSummary | None = None
    position_infractions_summary: TakeoffPositionInfractionsSummary | None = None

    def __add__(self, other: "TakeoffReportSummary") -> "TakeoffReportSummary":
        return TakeoffReportSummary(
            duration_infractions_summary=apply_func_on_optional_pair(
                self.duration_infractions_summary,
                other.duration_infractions_summary,
                lambda x, y: x + y,
            ),
            position_infractions_summary=apply_func_on_optional_pair(
                self.position_infractions_summary,
                other.position_infractions_summary,
                lambda x, y: x + y,
            ),
        )


class MinimumPositionEventsInfraction(BaseInfraction):
    events_number: int

    @classmethod
    def generate(
        cls,
        drone_user: DroneUser,
    ) -> Optional["MinimumPositionEventsInfraction"]:
        if len(drone_user.position_events) >= 2:
            return None
        return MinimumPositionEventsInfraction(
            events_number=len(drone_user.position_events),
        )

    def summarize(self) -> "MinimumPositionEventsInfractionsSummary":
        return MinimumPositionEventsInfractionsSummary(
            nb_infractions=len(self),
            min_position_events_infraction=self,
            max_position_events_infraction=self,
        )


class MinimumPositionEventsInfractionsSummary(BaseInfractionsSummary):
    min_position_events_infraction: MinimumPositionEventsInfraction | None = None
    max_position_events_infraction: MinimumPositionEventsInfraction | None = None

    def __add__(
        self,
        other: "MinimumPositionEventsInfractionsSummary",
    ) -> "MinimumPositionEventsInfractionsSummary":
        return MinimumPositionEventsInfractionsSummary(
            nb_infractions=self.nb_infractions + other.nb_infractions,
            min_position_events_infraction=apply_func_on_optional_pair(
                self.min_position_events_infraction,
                other.min_position_events_infraction,
                lambda x, y: x if x.events_number < y.events_number else y,
            ),
            max_position_events_infraction=apply_func_on_optional_pair(
                self.max_position_events_infraction,
                other.max_position_events_infraction,
                lambda x, y: x if x.events_number > y.events_number else y,
            ),
        )


class DroneUserReport(BaseReport):
    drone_index: int
    minimal_position_event: MinimumPositionEventsInfraction | None = None
    takeoff: TakeoffReport | None = None

    @classmethod
    def generate(
        cls,
        drone_user: DroneUser,
    ) -> "DroneUserReport":
        minimal_position_event_report = MinimumPositionEventsInfraction.generate(
            drone_user,
        )
        if minimal_position_event_report is not None:
            return DroneUserReport(
                drone_index=drone_user.index,
                minimal_position_event=minimal_position_event_report,
            )
        takeoff_report = TakeoffReport.generate_or_none(drone_user)
        return DroneUserReport(drone_index=drone_user.index, takeoff=takeoff_report)

    def summarize(self) -> "DroneUserReportSummary":
        return DroneUserReportSummary(
            drone_indices={self.drone_index},
            minimal_position_events_infractions_summary=self.minimal_position_event.summarize()
            if self.minimal_position_event
            else None,
            takeoff_report_summary=self.takeoff.summarize() if self.takeoff else None,
        )


class DroneUserReportSummary(BaseReportSummary):
    drone_indices: set[int] = set()
    minimal_position_events_infractions_summary: MinimumPositionEventsInfractionsSummary | None = (
        None
    )
    takeoff_report_summary: TakeoffReportSummary | None = None

    def __add__(
        self,
        other: "DroneUserReportSummary",
    ) -> "DroneUserReportSummary":
        return DroneUserReportSummary(
            drone_indices=self.drone_indices.union(other.drone_indices),
            minimal_position_events_infractions_summary=apply_func_on_optional_pair(
                self.minimal_position_events_infractions_summary,
                other.minimal_position_events_infractions_summary,
                lambda x, y: x + y,
            ),
            takeoff_report_summary=apply_func_on_optional_pair(
                self.takeoff_report_summary,
                other.takeoff_report_summary,
                lambda x, y: x + y,
            ),
        )

    @field_serializer("drone_indices")
    def _serialize_drone_indices(self, value: set[int]) -> str:
        return get_ranges_from_drone_indices(value)


class TakeoffFormatReport(BaseReport):
    drone_users: list[DroneUserReport] = []

    @classmethod
    def generate(
        cls,
        show_user: ShowUser,
    ) -> "TakeoffFormatReport":
        drone_user_reports = [
            drone_user_report
            for drone_user in tqdm(show_user.drones_user, desc="Checking takeoffs", unit="drone")
            if len(drone_user_report := DroneUserReport.generate(drone_user))
        ]
        return TakeoffFormatReport(drone_users=drone_user_reports)

    def summarize(self) -> "TakeoffFormatReportSummary":
        return TakeoffFormatReportSummary(
            drone_user_report_summary=sum(
                (
                    drone_user_report.summarize()
                    for drone_user_report in tqdm(
                        self.drone_users,
                        desc="Summarizing takeoff format report",
                        unit="drone user report",
                    )
                ),
                DroneUserReportSummary(),
            ),
        )


class TakeoffFormatReportSummary(BaseReportSummary):
    drone_user_report_summary: DroneUserReportSummary | None = None
