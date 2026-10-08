# pyright: reportIncompatibleMethodOverride=false

from tqdm import tqdm

from sparkshow_studio._loader.reports.base import BaseReport, BaseReportSummary
from sparkshow_studio._loader.schemas.drone_px4 import DronePx4
from sparkshow_studio._loader.schemas.show_user import ShowUser

from .events_format_report import EventsFormatReport, EventsFormatReportSummary


class AutopilotFormatReportSummary(BaseReportSummary):
    events_format_report_summary: EventsFormatReportSummary


class AutopilotFormatReport(BaseReport):
    events_format_reports: list[EventsFormatReport] = []

    @classmethod
    def generate(
        cls,
        show_user_or_autopilot_format: ShowUser | list[DronePx4],
    ) -> "AutopilotFormatReport":
        if isinstance(show_user_or_autopilot_format, ShowUser):
            autopilot_format = DronePx4.from_show_user(show_user_or_autopilot_format)
        else:
            autopilot_format = show_user_or_autopilot_format

        events_format_reports = [
            events_format_report
            for drone_px4 in tqdm(autopilot_format, desc="Checking autopilot format", unit="drone")
            if len(events_format_report := EventsFormatReport.generate(drone_px4))
        ]
        return AutopilotFormatReport(
            events_format_reports=events_format_reports,
        )

    def summarize(self) -> AutopilotFormatReportSummary:
        return AutopilotFormatReportSummary(
            events_format_report_summary=sum(
                (
                    events_format_report.summarize()
                    for events_format_report in tqdm(
                        self.events_format_reports,
                        desc="Summarizing autopilot format report",
                        unit="events format report",
                    )
                ),
                EventsFormatReportSummary(),
            ),
        )
