"""Unit of Work — the transaction boundary (contract section 21).

Business state change and event creation must be stored atomically. Every
application service mutates state through a unit of work's repositories and
publishes events through the same unit's outbox. Committing persists both;
rolling back discards both — no event is ever dispatched for work that did not
happen.

Usage::

    with uow:
        services.people.create_employee(...)
        services.events.publish(DomainEvent(...))
    dispatcher.dispatch_pending()
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self

from .repositories import (
    AssignmentRepositoryPort,
    AuditRepositoryPort,
    EmployeeRepositoryPort,
    JobRepositoryPort,
    OrganizationRepositoryPort,
    OutboxRepositoryPort,
    WorkplaceRepositoryPort,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class SessionFactoryPort(Protocol):
    """Sessions sharing this unit of work's transaction (contract section 22).

    Plugins that own tables reach the *same* transaction the platform commits
    through this port — never a connection of their own — so a plugin's state
    change and the event it published commit together or not at all (§21).
    """

    def __call__(self) -> Session:
        """A session already sharing this unit of work's transaction."""
        ...


class UnitOfWorkPort(Protocol):
    """One transactional view of every repository the core needs."""

    employees: EmployeeRepositoryPort
    organizations: OrganizationRepositoryPort
    workplaces: WorkplaceRepositoryPort
    jobs: JobRepositoryPort
    assignments: AssignmentRepositoryPort
    audit: AuditRepositoryPort
    outbox: OutboxRepositoryPort
    #: Sessions sharing this transaction, for plugins that own tables (§22).
    sessions: SessionFactoryPort

    def begin(self) -> None:
        """Start a transaction. Idempotent: a nested begin is a no-op."""
        ...

    def commit(self) -> None: ...
    def rollback(self) -> None: ...

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc, tb) -> None:
        """Commit on a clean exit, roll back on any exception."""
        ...


__all__ = ["SessionFactoryPort", "UnitOfWorkPort"]
