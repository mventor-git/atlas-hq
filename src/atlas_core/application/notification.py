"""Notification engine with handle-bound Core authorization."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from atlas_sdk import (
    AuthorizationError,
    CapabilityId,
    ExecutionHandle,
    Notification,
)
from atlas_sdk.context import NotificationPort

from ..domain.execution import ExecutionFacts
from ..domain.identifiers import new_id
from .execution_guard import require_execution_handle


class NotificationService(NotificationPort):
    def __init__(self, *, resolver: Any | None = None, authorization: Any | None = None) -> None:
        self._sent: list[Notification] = []
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
            raise AuthorizationError(f"notification operation denied: {decision.code}")

    def send(
        self,
        channel: str,
        recipient: str,
        subject: str,
        body: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> str:
        self._authorize(execution_handle, "notification.send")
        notification_id = new_id("ntf")
        self._sent.append(
            Notification(
                notification_id=notification_id,
                channel=channel,
                recipient=recipient,
                subject=subject,
                body=body,
                sent_at=datetime.now(UTC),
            ),
        )
        return notification_id

    def list_sent(
        self,
        recipient: str | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[Notification]:
        self._authorize(execution_handle, "notification.list")
        if recipient is None:
            return list(self._sent)
        return [n for n in self._sent if n.recipient == recipient]


__all__ = ["NotificationService"]
