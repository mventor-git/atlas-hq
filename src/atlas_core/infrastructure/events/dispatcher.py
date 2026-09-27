"""Internal event bus with Core-authorized subscription ownership."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from atlas_sdk import (
    AuthorizationError,
    DomainEvent,
    EventEnvelope,
    EventId,
    ExecutionHandle,
)

from ...application.unit_of_work import UnitOfWorkPort
from ...domain.execution import ExecutionFacts
from ...domain.identifiers import new_id
from ...domain.role import PLUGIN_ADMIN

EventSubscriber = Callable[[DomainEvent], None]


class _HandleResolver(Protocol):
    def resolve(self, handle: ExecutionHandle) -> object: ...


class OutboxEventPublisher:
    """Append an event to the current transaction after Core handle resolution."""

    def __init__(
        self,
        uow: UnitOfWorkPort,
        publisher: str | None = None,
        *,
        resolver: _HandleResolver | None = None,
    ) -> None:
        self._uow = uow
        self._publisher = publisher
        if resolver is None:
            from ...application.execution import ExecutionHandleResolver, ExecutionHandleStore

            resolver = ExecutionHandleResolver(uow, ExecutionHandleStore(uow))
        self._resolver = resolver

    def publish(self, event: DomainEvent, *, execution_handle: ExecutionHandle) -> None:
        if not isinstance(execution_handle, ExecutionHandle):
            raise AuthorizationError("a server-issued ExecutionHandle is required to publish")
        self._resolver.resolve(execution_handle)
        envelope = EventEnvelope(
            envelope_id=new_id("env"),
            event=event,
            publisher=self._publisher,
        )
        self._uow.outbox.append(envelope)


class EventDispatcher:
    """Routes committed envelopes; subscription mutation is owner-authorized."""

    def __init__(self, uow_factory: Callable[[], UnitOfWorkPort]) -> None:
        self._uow_factory = uow_factory
        self._subscribers: dict[EventId, list[tuple[str, EventSubscriber]]] = {}

    def for_plugin(
        self,
        plugin_id: str,
        *,
        resolver: _HandleResolver,
        authorization: Any,
    ) -> PluginEventDispatcher:
        return PluginEventDispatcher(
            self,
            plugin_id,
            resolver=resolver,
            authorization=authorization,
        )

    def _register(self, event_id: EventId, subscriber: EventSubscriber, *, owner: str) -> None:
        bucket = self._subscribers.setdefault(event_id, [])
        if all(existing_subscriber != subscriber for _, existing_subscriber in bucket):
            bucket.append((owner, subscriber))

    def _remove(self, event_id: EventId, subscriber: EventSubscriber, *, owner: str) -> None:
        bucket = self._subscribers.get(event_id, [])
        for index, (registered_owner, registered) in enumerate(bucket):
            if registered == subscriber:
                if registered_owner != owner:
                    raise AuthorizationError("a plugin cannot unsubscribe another owner")
                bucket.pop(index)
                return

    def subscribe(
        self,
        event_id: EventId,
        subscriber: EventSubscriber,
        *,
        execution_handle: ExecutionHandle,
        owner: str | None = None,
        resolver: _HandleResolver | None = None,
        authorization: Any | None = None,
    ) -> None:
        """Guarded compatibility entry point for Core callers."""
        if owner is None or resolver is None or authorization is None:
            raise AuthorizationError("a Core-owned plugin dispatcher is required")
        _authorize_subscription(
            execution_handle, event_id, resolver, authorization, "events.subscribe"
        )
        self._register(event_id, subscriber, owner=owner)

    def unsubscribe(
        self,
        event_id: EventId,
        subscriber: EventSubscriber,
        *,
        execution_handle: ExecutionHandle,
        owner: str | None = None,
        resolver: _HandleResolver | None = None,
        authorization: Any | None = None,
    ) -> None:
        if owner is None or resolver is None or authorization is None:
            raise AuthorizationError("a Core-owned plugin dispatcher is required")
        _authorize_subscription(
            execution_handle, event_id, resolver, authorization, "events.unsubscribe"
        )
        self._remove(event_id, subscriber, owner=owner)

    def subscriber_count(self, event_id: EventId) -> int:
        return len(self._subscribers.get(event_id, []))

    def dispatch_pending(self, limit: int = 100) -> int:
        routed = 0
        for envelope in self._committed_pending(limit):
            routed += self._dispatch_one(envelope)
        return routed

    def _committed_pending(self, limit: int) -> list[EventEnvelope]:
        uow = self._uow_factory()
        try:
            return uow.outbox.pending(limit)
        finally:
            uow.rollback()

    def _dispatch_one(self, envelope: EventEnvelope) -> int:
        subscribers = [
            subscriber for _owner, subscriber in self._subscribers.get(envelope.event_id, [])
        ]
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


class PluginEventDispatcher:
    """Owner-scoped facade handed to exactly one plugin context."""

    def __init__(
        self,
        dispatcher: EventDispatcher,
        owner: str,
        *,
        resolver: _HandleResolver,
        authorization: Any,
    ) -> None:
        self._dispatcher = dispatcher
        self._owner = owner
        self._resolver = resolver
        self._authorization = authorization

    def subscribe(
        self, event_id: EventId, subscriber: EventSubscriber, *, execution_handle: ExecutionHandle
    ) -> None:
        _authorize_subscription(
            execution_handle, event_id, self._resolver, self._authorization, "events.subscribe"
        )
        self._dispatcher._register(event_id, subscriber, owner=self._owner)

    def unsubscribe(
        self, event_id: EventId, subscriber: EventSubscriber, *, execution_handle: ExecutionHandle
    ) -> None:
        _authorize_subscription(
            execution_handle, event_id, self._resolver, self._authorization, "events.unsubscribe"
        )
        self._dispatcher._remove(event_id, subscriber, owner=self._owner)

    def subscriber_count(self, event_id: EventId) -> int:
        return self._dispatcher.subscriber_count(event_id)


def _authorize_subscription(
    handle: ExecutionHandle,
    event_id: EventId,
    resolver: _HandleResolver,
    authorization: Any,
    action: str,
) -> None:
    if not isinstance(handle, ExecutionHandle):
        raise AuthorizationError("a server-issued ExecutionHandle is required")
    try:
        facts = resolver.resolve(handle)
    except (AuthorizationError, TypeError, ValueError) as exc:
        raise AuthorizationError("a Core-resolved ExecutionHandle is required") from exc
    if not isinstance(facts, ExecutionFacts):
        raise AuthorizationError("a Core-resolved ExecutionHandle is required")
    decision = authorization.authorize(
        handle,
        PLUGIN_ADMIN,
        facts.scope,
        requested_action=action,
        requested_resource_id=str(event_id),
    )
    if not decision.allowed:
        raise AuthorizationError(f"event subscription denied: {decision.code}")


__all__ = [
    "EventDispatcher",
    "EventSubscriber",
    "OutboxEventPublisher",
    "PluginEventDispatcher",
]
