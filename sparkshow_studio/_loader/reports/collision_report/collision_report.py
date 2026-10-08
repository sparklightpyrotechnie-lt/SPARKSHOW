# pyright: reportIncompatibleMethodOverride=false
from typing import Optional

from tqdm import tqdm

from sparkshow_studio._loader.reports.base import BaseReport, BaseReportSummary
from sparkshow_studio._loader.schemas.show_user import ShowUser

from .collision_infraction import CollisionInfraction, CollisionInfractionsSummary


class CollisionReportSummary(BaseReportSummary):
    collision_infractions_summary: Optional["CollisionInfractionsSummary"] = None


class CollisionReport(BaseReport):
    collision_infractions: list[CollisionInfraction] = []

    @classmethod
    def generate(
        cls,
        show_user: ShowUser,
        *,
        is_partial: bool = False,
    ) -> "CollisionReport":
        collision_infractions = CollisionInfraction.generate(show_user, is_partial=is_partial)
        return CollisionReport(collision_infractions=collision_infractions)

    def summarize(self) -> CollisionReportSummary:
        return CollisionReportSummary(
            collision_infractions_summary=sum(
                (
                    collision_infraction.summarize()
                    for collision_infraction in tqdm(
                        self.collision_infractions,
                        desc="Summarizing collision report",
                        unit="collision",
                    )
                ),
                CollisionInfractionsSummary(),
            ),
        )
