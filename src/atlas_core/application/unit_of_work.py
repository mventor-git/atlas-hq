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

from collections.abc import Callable
from typing import Protocol, Self

from atlas_sdk import PluginPersistencePort

from .repositories import (
    AssignmentRepositoryPort,
    AuditRepositoryPort,
    AuthorizationRepositoryPort,
    EmployeeRepositoryPort,
    ExecutionRepositoryPort,
    JobRepositoryPort,
    OrganizationRepositoryPort,
    OutboxRepositoryPort,
    PolicyRepositoryPort,
    WorkplaceRepositoryPort,
)


class UnitOfWorkPort(Protocol):
    """One transactional view of every repository the core needs."""

    employees: EmployeeRepositoryPort
    organizations: OrganizationRepositoryPort
    workplaces: WorkplaceRepositoryPort
    jobs: JobRepositoryPort
    assignments: AssignmentRepositoryPort
    audit: AuditRepositoryPort
    authorization: AuthorizationRepositoryPort
    policies: PolicyRepositoryPort
    executions: ExecutionRepositoryPort
    outbox: OutboxRepositoryPort

    def plugin_persistence(
        self,
        plugin_id: str,
        owned_tables: tuple[str, ...],
    ) -> PluginPersistencePort:
        """Create an owner-checked adapter for a plugin."""
        ...

    @property
    def independent_uow_factory(self) -> Callable[[], UnitOfWorkPort]:
        """A factory for separate units of work on the same database.

        The durable denial audit commits independently, so it can never be
        written through the caller's own unit of work.
        """
        ...

    def begin(self) -> None:
        """Start a transaction. Idempotent: a nested begin is a no-op."""
        ...

    @property
    def in_transaction(self) -> bool:
        """Whether this UoW currently owns an open transaction."""
        ...

    def finish_read(self) -> None:
        """Close an implicit read transaction without claiming a write commit."""
        ...

    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def poison(self) -> None:
        """Mark this cached unit of work unusable after rollback failure."""
        ...

    def close(self) -> None:
        """Close the Core-owned session; not exposed through PluginContext."""
        ...

    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc, tb) -> None:
        """Commit on a clean exit, roll back on any exception."""
        ...


__all__ = ["UnitOfWorkPort"]
