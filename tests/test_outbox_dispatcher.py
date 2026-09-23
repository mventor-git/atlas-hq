"""Outbox + dispatcher: the transactional event guarantee (contract §21).

The two paths that matter:

* a committed state change delivers its event;
* a rolled-back state change delivers nothing.

Both are exercised against the real SQLite database, not a mock: the dispatcher
reads committed rows from a *fresh* transaction, so an envelope written by a
transaction that rolled back is genuinely invisible to it.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from atlas_core.application.assignments import EMPLOYEE_ASSIGNED
from atlas_core.application.people import EMPLOYEE_CREATED, PeopleService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.infrastructure.events import EventDispatcher, OutboxEventPublisher
from atlas_sdk import DomainEvent, EventId

EVENT_A = EventId("test.thing_happened")


def _publisher(uow: UnitOfWorkPort) -> OutboxEventPublisher:
    return OutboxEventPublisher(uow, publisher="test")


def _dispatcher(uow_factory: Callable[[], UnitOfWorkPort]) -> EventDispatcher:
    return EventDispatcher(uow_factory)


def test_committed_state_change_delivers_its_event(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    """Business state + event commit together, so the event is delivered."""
    received: list[DomainEvent] = []
    dispatcher = _dispatcher(uow_factory)
    dispatcher.subscribe(EVENT_A, received.append)

    uow = uow_factory()
    with uow:
        _publisher(uow).publish(DomainEvent(event_id=EVENT_A, payload={"n": 1}))
        uow.audit.append(_audit("committed"))
    assert uow.outbox.pending() == [] or len(uow.outbox.pending()) == 1

    delivered = dispatcher.dispatch_pending()

    assert delivered == 1
    assert len(received) == 1
    assert received[0].event_id == EVENT_A
    assert received[0].payload == {"n": 1}

    # The envelope is now marked dispatched and is not re-delivered.
    assert dispatcher.dispatch_pending() == 0
    assert len(received) == 1


def test_rolled_back_state_change_delivers_no_event(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    """A rolled-back transaction leaves no committed envelope, so nothing routes.

    This is the real test of the outbox: the envelope existed in the session, but
    because it was never committed the dispatcher cannot see it.
    """
    received: list[DomainEvent] = []
    dispatcher = _dispatcher(uow_factory)
    dispatcher.subscribe(EVENT_A, received.append)

    uow = uow_factory()
    with pytest.raises(RollbackRequested), uow:
        _publisher(uow).publish(DomainEvent(event_id=EVENT_A))
        uow.audit.append(_audit("rolled-back"))
        raise RollbackRequested()

    # Nothing was committed: the dispatcher sees no envelope for this event.
    assert dispatcher.dispatch_pending() == 0
    assert received == []
    assert uow_factory().outbox.pending() == []


class RollbackRequested(Exception):  # noqa: N818 - sentinel, not an error condition
    """Sentinel exception so the context manager rolls the transaction back."""


def test_people_service_publishes_in_the_same_transaction(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    """``employee.created`` is written with the employee, or not at all."""
    received: list[DomainEvent] = []
    dispatcher = _dispatcher(uow_factory)
    dispatcher.subscribe(EMPLOYEE_CREATED, received.append)
    dispatcher.subscribe(EMPLOYEE_ASSIGNED, received.append)

    from atlas_core.application.organization import OrganizationService

    uow = uow_factory()
    with uow:
        org = OrganizationService(uow).create_organization(name="Acme", code="ACME")
        people = PeopleService(uow, _publisher(uow))
        employee = people.create_employee(
            full_name="Ada Lovelace",
            employee_number="EMP-1",
            organization_id=org.organization_id,
        )
        assert employee.employee_id

    assert dispatcher.dispatch_pending() == 1
    created = [e for e in received if e.event_id == EMPLOYEE_CREATED]
    assert len(created) == 1
    assert created[0].payload["employee_number"] == "EMP-1"

    # The read-back proves the employee really was persisted.
    with uow_factory() as uow2:
        assert uow2.employees.find_by_number("EMP-1") is not None


def test_a_failing_subscriber_records_the_failure_without_blocking(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    """One bad subscriber must not stop the rest of the bus (contract §18)."""
    delivered: list[DomainEvent] = []

    def broken(_event: DomainEvent) -> None:
        raise RuntimeError("subscriber exploded")

    dispatcher = _dispatcher(uow_factory)
    dispatcher.subscribe(EVENT_A, broken)
    dispatcher.subscribe(EventId("test.other"), delivered.append)

    uow = uow_factory()
    with uow:
        _publisher(uow).publish(DomainEvent(event_id=EVENT_A))
        _publisher(uow).publish(DomainEvent(event_id=EventId("test.other")))

    routed = dispatcher.dispatch_pending()

    # The healthy subscriber's event went out; the broken one did not.
    assert routed == 1
    assert len(delivered) == 1

    # The failed envelope is still pending and records the error.
    pending = uow_factory().outbox.pending()
    failed = [e for e in pending if e.event_id == EVENT_A]
    assert len(failed) == 1
    assert failed[0].last_error is not None
    assert "subscriber exploded" in failed[0].last_error
    assert failed[0].attempts == 1


def test_subscribers_can_be_added_and_removed(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    received: list[DomainEvent] = []
    dispatcher = _dispatcher(uow_factory)
    dispatcher.subscribe(EVENT_A, received.append)
    assert dispatcher.subscriber_count(EVENT_A) == 1

    dispatcher.unsubscribe(EVENT_A, received.append)
    assert dispatcher.subscriber_count(EVENT_A) == 0

    uow = uow_factory()
    with uow:
        _publisher(uow).publish(DomainEvent(event_id=EVENT_A))

    assert dispatcher.dispatch_pending() == 1
    assert received == []


def _audit(action: str):
    from atlas_core.domain.audit import AuditRecord

    return AuditRecord(actor="test", action=action)
