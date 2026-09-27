"""Scheduling engine with handle-bound Core authorization."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from atlas_sdk import (
    AuthorizationError,
    CapabilityId,
    ExecutionHandle,
    ScheduledJob,
)
from atlas_sdk.context import SchedulingPort

from ..domain.execution import ExecutionFacts
from ..domain.identifiers import new_id
from .execution_guard import require_execution_handle


class SchedulingService(SchedulingPort):
    def __init__(self, *, resolver: Any | None = None, authorization: Any | None = None) -> None:
        self._jobs: list[ScheduledJob] = []
        self._resolver = resolver
        self._authorization = authorization

    def _authorize(self, handle: ExecutionHandle, action: str) -> None:
        facts = require_execution_handle(
            handle,
            resolver=self._resolver.resolve if self._resolver is not None else None,
        )
        if not isinstance(facts, ExecutionFacts) or self._authorization is None:
            raise AuthorizationError("a Core ExecutionHandle resolver is required")
        decision = self._authorization.authorize(
            handle,
            CapabilityId("policy.evaluate"),
            facts.scope,
            requested_action=action,
        )
        if not decision.allowed:
            raise AuthorizationError(f"scheduling operation denied: {decision.code}")

    def schedule(
        self,
        key: str,
        run_at: datetime,
        payload: Mapping[str, object] | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> str:
        self._authorize(execution_handle, "scheduling.schedule")
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

    def due(
        self,
        now: datetime | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[ScheduledJob]:
        self._authorize(execution_handle, "scheduling.due")
        moment = datetime.now(UTC) if now is None else now
        return [job for job in self._jobs if job.run_at <= moment]


__all__ = ["SchedulingService"]
