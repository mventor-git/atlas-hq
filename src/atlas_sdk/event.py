"""Domain events and outbox envelopes.

A :class:`DomainEvent` records *what happened* (contract section 20). Its
``event_id`` is also its registry key — ``employee.created`` is simultaneously
the event's identity and its type, matching the naming used throughout the
contract.

An :class:`EventEnvelope` is the transactional outbox record that wraps a
domain event so the "business state change + event creation" pair (contract
section 21) is stored atomically. The envelope is immutable; dispatch state
lives in the outbox and is advanced by the dispatcher.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NewType

EventId = NewType("EventId", str)


@dataclass(frozen=True)
class DomainEvent:
    """Something that happened in the domain."""

    event_id: EventId
    """Stable registry key and logical type of the event, e.g. ``employee.created``."""

    payload: dict[str, object] = field(default_factory=dict)
    """Typed-ish, JSON-serialisable payload describing the change."""

    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    """When the event occurred, UTC by default."""


@dataclass(frozen=True)
class EventEnvelope:
    """An outbox record wrapping a :class:`DomainEvent`."""

    envelope_id: str
    event: DomainEvent
    publisher: str | None = None
    """Plugin id that published the event, if known."""

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    dispatched_at: datetime | None = None
    attempts: int = 0
    last_error: str | None = None

    @property
    def event_id(self) -> EventId:
        return self.event.event_id

    @property
    def delivered(self) -> bool:
        return self.dispatched_at is not None


__all__ = ["DomainEvent", "EventEnvelope", "EventId"]
