"""Notification engine (skeleton, callable). D1 keeps an in-memory out-tray."""

from __future__ import annotations

from datetime import UTC, datetime

from atlas_sdk import Notification
from atlas_sdk.context import NotificationPort

from ..domain.identifiers import new_id


class NotificationService(NotificationPort):
    def __init__(self) -> None:
        self._sent: list[Notification] = []

    def send(
        self,
        channel: str,
        recipient: str,
        subject: str,
        body: str,
    ) -> str:
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

    def list_sent(self, recipient: str | None = None) -> list[Notification]:
        if recipient is None:
            return list(self._sent)
        return [n for n in self._sent if n.recipient == recipient]


__all__ = ["NotificationService"]
