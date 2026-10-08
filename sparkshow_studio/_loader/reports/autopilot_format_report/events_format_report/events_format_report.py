# pyright: reportIncompatibleMethodOverride=false
import itertools
from collections import defaultdict
from typing import Annotated, Any

from pydantic import Field, field_serializer

from sparkshow_studio._loader.reports.base import BaseReport, BaseReportSummary, apply_func_on_optional_pair
from sparkshow_studio._loader.reports.ranges import get_ranges_from_drone_indices
from sparkshow_studio._loader.schemas.drone_px4 import DronePx4
from sparkshow_studio._loader.schemas.drone_px4.events import Events

from .events_format_infractions import (
    BoundaryInfraction,
    BoundaryInfractionsSummary,
    IncreasingFrameInfraction,
    IncreasingFrameInfractionsSummary,
)


class EventsReportSummary(BaseReportSummary):
    increasing_frame_infractions_summary: IncreasingFrameInfractionsSummary = (
        IncreasingFrameInfractionsSummary()
    )
    boundary_infractions_summary: defaultdict[
        str,
        Annotated[BoundaryInfractionsSummary, Field(default_factory=BoundaryInfractionsSummary)],
    ] = defaultdict(BoundaryInfractionsSummary)

    def __add__(self, other: "EventsReportSummary") -> "EventsReportSummary":
        return EventsReportSummary(
            increasing_frame_infractions_summary=self.increasing_frame_infractions_summary
            + other.increasing_frame_infractions_summary,
            boundary_infractions_summary=defaultdict(
                BoundaryInfractionsSummary,
                {
                    boundary_kind: self.boundary_infractions_summary[boundary_kind]
                    + other.boundary_infractions_summary[boundary_kind]
                    for boundary_kind in set(
                        itertools.chain(
                            self.boundary_infractions_summary.keys(),
                            other.boundary_infractions_summary.keys(),
                        ),
                    )
                },
            ),
        )


class EventsReport(BaseReport):
    increasing_frame_infractions: list[IncreasingFrameInfraction]
    boundary_infractions: defaultdict[str, list[BoundaryInfraction]]

    @classmethod
    def generate(
        cls,
        events: Events[Any],
    ) -> "EventsReport":
        increasing_infractions = IncreasingFrameInfraction.generate(events)
        boundary_infractions = BoundaryInfraction.generate(events)
        return EventsReport(
            increasing_frame_infractions=increasing_infractions,
            boundary_infractions=boundary_infractions,
        )

    def summarize(self) -> EventsReportSummary:
        return EventsReportSummary(
            increasing_frame_infractions_summary=sum(
                (
                    increasing_infraction.summarize()
                    for increasing_infraction in self.increasing_frame_infractions
                ),
                IncreasingFrameInfractionsSummary(),
            ),
            boundary_infractions_summary=defaultdict(
                BoundaryInfractionsSummary,
                {
                    boundary_kind: sum(
                        (
                            boundary_infraction.summarize()
                            for boundary_infraction in boundary_infractions
                        ),
                        BoundaryInfractionsSummary(),
                    )
                    for boundary_kind, boundary_infractions in self.boundary_infractions.items()
                },
            ),
        )


class EventsFormatReportSummary(BaseReportSummary):
    drone_indices: set[int] = set()
    position_events_report_summary: EventsReportSummary | None = None
    color_events_report_summary: EventsReportSummary | None = None
    fire_events_report_summary: EventsReportSummary | None = None
    yaw_events_report_summary: EventsReportSummary | None = None

    def __add__(self, other: "EventsFormatReportSummary") -> "EventsFormatReportSummary":
        return EventsFormatReportSummary(
            drone_indices=self.drone_indices.union(other.drone_indices),
            position_events_report_summary=apply_func_on_optional_pair(
                self.position_events_report_summary,
                other.position_events_report_summary,
                lambda x, y: x + y,
            ),
            color_events_report_summary=apply_func_on_optional_pair(
                self.color_events_report_summary,
                other.color_events_report_summary,
                lambda x, y: x + y,
            ),
            fire_events_report_summary=apply_func_on_optional_pair(
                self.fire_events_report_summary,
                other.fire_events_report_summary,
                lambda x, y: x + y,
            ),
            yaw_events_report_summary=apply_func_on_optional_pair(
                self.yaw_events_report_summary,
                other.yaw_events_report_summary,
                lambda x, y: x + y,
            ),
        )

    @field_serializer("drone_indices")
    def _serialize_drone_indices(self, value: set[int]) -> str:
        return get_ranges_from_drone_indices(value)


class EventsFormatReport(BaseReport):
    drone_index: int
    position_events_report: EventsReport | None
    color_events_report: EventsReport | None
    fire_events_report: EventsReport | None
    yaw_events_report: EventsReport | None

    @classmethod
    def generate(
        cls,
        drone_px4: DronePx4,
    ) -> "EventsFormatReport":
        position_events_report = EventsReport.generate_or_none(drone_px4.position_events)
        color_events_report = EventsReport.generate_or_none(drone_px4.color_events)
        fire_events_report = EventsReport.generate_or_none(drone_px4.fire_events)
        yaw_events_report = EventsReport.generate_or_none(drone_px4.yaw_events)
        return EventsFormatReport(
            drone_index=drone_px4.index,
            position_events_report=position_events_report,
            color_events_report=color_events_report,
            fire_events_report=fire_events_report,
            yaw_events_report=yaw_events_report,
        )

    def summarize(self) -> EventsFormatReportSummary:
        return EventsFormatReportSummary(
            drone_indices={self.drone_index},
            position_events_report_summary=self.position_events_report.summarize()
            if self.position_events_report
            else None,
            color_events_report_summary=self.color_events_report.summarize()
            if self.color_events_report
            else None,
            fire_events_report_summary=self.fire_events_report.summarize()
            if self.fire_events_report
            else None,
            yaw_events_report_summary=self.yaw_events_report.summarize()
            if self.yaw_events_report
            else None,
        )
