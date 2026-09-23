"""Internal event bus: outbox relay + in-process subscriber routing.

The contract's guarantee (section 21) is that a business state change and the
event describing it are stored atomically, and the event is routed only after
commit. Two objects split that responsibility:

* :class:`OutboxEventPublisher` writes an envelope inside the *current*
  transaction, so it shares the fate of the state change.
* :class:`EventDispatcher` reads committed envelopes in a fresh transaction and
  hands them to in-process subscribers. Because it re-reads the outbox after
  commit, an envelope from a rolled-back transaction is invisible to it — and
  is therefore never delivered.

The seam is :class:`~atlas_sdk.context.EventPublisherPort` plus a subscriber
API. A future external broker replaces :class:`EventDispatcher` behind the same
seam without touching any publisher.
"""

from __future__ import annotations

from collections.abc import Callable

from atlas_sdk import DomainEvent, EventEnvelope, EventId

from ...application.unit_of_work import UnitOfWorkPort
from ...domain.identifiers import new_id

#: Signature of an in-process subscriber: receives the routed event.
EventSubscriber = Callable[[DomainEvent], None]


class OutboxEventPublisher:
    """Adapts :class:`~atlas_sdk.context.EventPublisherPort`.

    Every publish lands in the unit of work's outbox *within its transaction*,
    which is the atomicity guarantee the contract demands.
    """

    def __init__(self, uow: UnitOfWorkPort, publisher: str | None = None) -> None:
        self._uow = uow
        self._publisher = publisher

    def publish(self, event: DomainEvent) -> None:
        envelope = EventEnvelope(
            envelope_id=new_id("env"),
            event=event,
            publisher=self._publisher,
        )
        self._uow.outbox.append(envelope)


class EventDispatcher:
    """Routes committed outbox envelopes to in-process subscribers.

    A subscriber registers for an :class:`~atlas_sdk.EventId` and is called for
    every committed envelope carrying that id. Delivery is at-least-once within
    one process: an envelope stays pending until its subscribers all succeed, so
    a crash between commit and dispatch replays it on the next run.
    """

    def __init__(self, uow_factory: Callable[[], UnitOfWorkPort]) -> None:
        self._uow_factory = uow_factory
        self._subscribers: dict[EventId, list[EventSubscriber]] = {}

    def subscribe(self, event_id: EventId, subscriber: EventSubscriber) -> None:
        """Register ``subscriber`` for ``event_id``. Duplicate calls are ignored."""
        bucket = self._subscribers.setdefault(event_id, [])
        if subscriber not in bucket:
            bucket.append(subscriber)

    def unsubscribe(self, event_id: EventId, subscriber: EventSubscriber) -> None:
        bucket = self._subscribers.get(event_id)
        if bucket is not None and subscriber in bucket:
            bucket.remove(subscriber)

    def subscriber_count(self, event_id: EventId) -> int:
        return len(self._subscribers.get(event_id, []))

    def dispatch_pending(self, limit: int = 100) -> int:
        """Route up to ``limit`` committed envelopes. Returns the count routed.

        Each envelope is dispatched in its own transaction: a failing subscriber
        records the failure and the envelope is retried next time, while every
        other envelope still goes out. One bad subscriber cannot block the bus.
        """
        routed = 0
        for envelope in self._committed_pending(limit):
            routed += self._dispatch_one(envelope)
        return routed

    # --- internals --------------------------------------------------------

    def _committed_pending(self, limit: int) -> list[EventEnvelope]:
        """Pending envelopes as seen by a fresh, committed transaction."""
        uow = self._uow_factory()
        try:
            return uow.outbox.pending(limit)
        finally:
            uow.rollback()

    def _dispatch_one(self, envelope: EventEnvelope) -> int:
        subscribers = self._subscribers.get(envelope.event_id, [])
        uow = self._uow_factory()
        try:
            with uow:
                for subscriber in subscribers:
                    subscriber(envelope.event)
                uow.outbox.mark_dispatched(envelope.envelope_id)
        except Exception as exc:  # noqa: BLE001 - a subscriber may raise anything
            uow = self._uow_factory()
            with uow:
                uow.outbox.record_failure(envelope.envelope_id, str(exc))
            return 0
        return 1


__all__ = ["EventDispatcher", "EventSubscriber", "OutboxEventPublisher"]
