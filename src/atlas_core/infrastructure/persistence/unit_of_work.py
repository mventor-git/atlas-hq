"""The unit of work: one transaction spanning state and events (contract §21).

``SqlUnitOfWork`` is a context manager. Entering it opens a session and begins
a transaction; every repository write and every outbox append lands in that same
transaction. A clean exit commits both; an exception rolls back both — so an
event can never be delivered for work that did not happen.

The dispatcher reads committed envelopes in a *fresh* session (see
:mod:`atlas_core.infrastructure.events`), which is what makes the rollback
guarantee observable rather than merely asserted.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Protocol, Self, TypeVar

from sqlalchemy.orm import Session

from atlas_sdk import PluginPersistencePort, TransactionRunnerPort

from ...application.unit_of_work import SessionFactoryPort, UnitOfWorkPort
from .repositories import (
    AssignmentRepository,
    AuditRepository,
    EmployeeRepository,
    JobRepository,
    OrganizationRepository,
    OutboxRepository,
    WorkplaceRepository,
)
from .session import (
    create_schema as create_database_schema,
)
from .session import (
    create_session_factory_with_engine,
    ensure_schema,
    require_bound_session,
    resolve_database_schema,
)

T = TypeVar("T")


class _TransactionLifecycle(Protocol):
    """The small internal lifecycle the transaction adapter needs."""

    def begin(self) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def poison(self) -> None: ...


class PluginPersistenceAdapter(PluginPersistencePort):
    """Restricts a SQLAlchemy session to plugin-owned persistence operations."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, entity: object) -> None:
        self._session.add(entity)

    def delete(self, entity: object) -> None:
        self._session.delete(entity)

    def get(self, entity_type: type[Any], entity_id: object) -> Any | None:
        return self._session.get(entity_type, entity_id)

    def query(self, statement: Any) -> Iterable[Any]:
        return self._session.scalars(statement)

    def create_schema(self, metadata: Any) -> None:
        engine = require_bound_session(self._session)
        ensure_schema(engine)
        metadata.create_all(engine, checkfirst=True)


def _rollback_preserving(uow: _TransactionLifecycle, error: BaseException) -> None:
    try:
        uow.rollback()
    except BaseException as rollback_error:
        error.add_note(f"transaction rollback failed: {rollback_error!r}")
        try:
            uow.poison()
        except BaseException as poison_error:
            error.add_note(f"transaction poison failed: {poison_error!r}")


class SqlTransactionRunner(TransactionRunnerPort):
    """Adapts the platform unit of work to the plugin transaction seam.

    The adapter is the only place a direct plugin operation enters the
    transaction. A normal return commits; an operation, begin, or commit failure
    rolls back before the original exception is re-raised.
    """

    def __init__(self, uow: _TransactionLifecycle) -> None:
        self._uow = uow

    def run(self, operation: Callable[[], T]) -> T:
        try:
            self._uow.begin()
            result = operation()
            self._uow.commit()
        except BaseException as error:
            _rollback_preserving(self._uow, error)
            raise
        return result


class SqlUnitOfWork(UnitOfWorkPort):
    """One SQLAlchemy transaction exposing every repository the core needs."""

    def __init__(self, session: Session) -> None:
        require_bound_session(session)
        self._session = session
        self._poisoned = False
        self.employees = EmployeeRepository(session)
        self.organizations = OrganizationRepository(session)
        self.workplaces = WorkplaceRepository(session)
        self.jobs = JobRepository(session)
        self.assignments = AssignmentRepository(session)
        self.audit = AuditRepository(session)
        self.outbox = OutboxRepository(session)
        #: Plugins receive the restricted adapter, never this raw session.
        self.persistence: PluginPersistencePort = PluginPersistenceAdapter(session)
        #: The internal session factory remains available to core adapters.
        self.sessions: SessionFactoryPort = _SharedSessionFactory(session)

    @property
    def session(self) -> Session:
        """The live session. Test helpers reach in here; production code does not."""
        return self._session

    def _ensure_usable(self) -> None:
        if self._poisoned:
            msg = "transaction is poisoned after rollback failure"
            raise RuntimeError(msg)

    def begin(self) -> None:
        self._ensure_usable()
        if not self._session.in_transaction():
            self._session.begin()

    def commit(self) -> None:
        self._ensure_usable()
        self._session.commit()

    def rollback(self) -> None:
        self._ensure_usable()
        self._session.rollback()

    def poison(self) -> None:
        """Make this cached UoW fail closed for every later transaction call."""
        self._poisoned = True

    def __enter__(self) -> Self:
        self.begin()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            try:
                self.commit()
            except BaseException as error:
                _rollback_preserving(self, error)
                raise
            return
        if exc is not None:
            _rollback_preserving(self, exc)
        else:
            self.rollback()


def create_schema(session: Session) -> None:
    """Create the core PostgreSQL schema if it does not exist. Idempotent."""
    engine = require_bound_session(session)
    create_database_schema(engine)


def create_sql_uow_factory(
    url: str | None = None,
    *,
    schema: str | None = None,
) -> Callable[[], SqlUnitOfWork]:
    """Build the production UoW factory after creating its PostgreSQL schema."""
    safe_schema = resolve_database_schema(schema)
    session_factory, engine = create_session_factory_with_engine(url, schema=safe_schema)
    create_database_schema(engine, safe_schema)

    def factory() -> SqlUnitOfWork:
        return SqlUnitOfWork(session_factory())

    return factory


@dataclass(frozen=True)
class _SharedSessionFactory:
    """Internal session factory for core adapters sharing this unit of work.

    Plugin code receives :class:`PluginPersistenceAdapter` instead; this raw
    session factory remains inside the core persistence seam.
    """

    session: Session

    def __call__(self) -> Session:
        return self.session


__all__ = [
    "PluginPersistenceAdapter",
    "SqlTransactionRunner",
    "SqlUnitOfWork",
    "create_schema",
    "create_sql_uow_factory",
]
