"""Scheduling engine (skeleton, callable). D1 keeps jobs in memory."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from atlas_sdk import ScheduledJob
from atlas_sdk.context import SchedulingPort

from ..domain.identifiers import new_id


class SchedulingService(SchedulingPort):
    def __init__(self) -> None:
        self._jobs: list[ScheduledJob] = []

    def schedule(
        self,
        key: str,
        run_at: datetime,
        payload: Mapping[str, object] | None = None,
    ) -> str:
        schedule_id = new_id("sch")
        self._jobs.append(
            ScheduledJob(
                schedule_id=schedule_id,
                key=key,
                run_at=run_at,
                payload=dict(payload or {}),
            ),
        )
        return schedule_id

    def due(self, now: datetime | None = None) -> list[ScheduledJob]:
        moment = datetime.now(UTC) if now is None else now
        return [job for job in self._jobs if job.run_at <= moment]


__all__ = ["SchedulingService"]
