"""The PostgreSQL unit of work and the plugin-owned persistence boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from types import TracebackType
from typing import Any, Protocol, Self, TypeVar
from weakref import WeakKeyDictionary

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.orm import Session, sessionmaker

from atlas_sdk import PluginPersistencePort, TransactionRunnerPort

from ...application.unit_of_work import UnitOfWorkPort
from .authorization import AuthorizationRepository
from .execution import ExecutionRepository
from .migrations import apply_migrations
from .orm import Base
from .policy import PolicyRepository
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
    create_session_factory_with_engine,
    ensure_schema,
    require_bound_session,
    resolve_database_schema,
)

T = TypeVar("T")

#: One independent session factory per engine, so a denial audit does not
#: rebuild a sessionmaker on every denied decision.
_INDEPENDENT_FACTORIES: WeakKeyDictionary[Engine, Callable[[], SqlUnitOfWork]] = WeakKeyDictionary()


def _independent_uow_factory(engine: Engine) -> Callable[[], SqlUnitOfWork]:
    """Build a factory for separate units of work on the same PostgreSQL engine."""
    cached = _INDEPENDENT_FACTORIES.get(engine)
    if cached is None:
        sessions = sessionmaker(bind=engine, expire_on_commit=False, future=True)
        cached = lambda: SqlUnitOfWork(sessions())  # noqa: E731
        _INDEPENDENT_FACTORIES[engine] = cached
    return cached


class _TransactionLifecycle(Protocol):
    def begin(self) -> None: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def poison(self) -> None: ...


class PluginPersistenceAdapter(PluginPersistencePort):
    """A table-owner checked facade over the current transaction.

    Plugins receive entity add/get/find/all/delete and owner-scoped table
    creation only.  There is no raw session, arbitrary SQL statement, or
    metadata escape hatch.
    """

    def __init__(
        self,
        session: Session,
        *,
        plugin_id: str,
        owned_tables: Iterable[str],
    ) -> None:
        self._session = session
        self._plugin_id = plugin_id
        self._owned_tables = frozenset(owned_tables)
        core_tables = frozenset(Base.metadata.tables)
        if self._owned_tables & core_tables:
            forbidden = ", ".join(sorted(self._owned_tables & core_tables))
            raise PermissionError(f"a plugin cannot own Core tables: {forbidden}")

    def _table_name(self, entity_type: type[Any]) -> str:
        try:
            return str(sa_inspect(entity_type).mapper.local_table.name)
        except (AttributeError, NoInspectionAvailable, TypeError) as exc:
            raise TypeError("plugin persistence accepts mapped entity types only") from exc

    def _check_type(self, entity_type: type[Any]) -> str:
        table = self._table_name(entity_type)
        if table not in self._owned_tables:
            raise PermissionError(f"plugin {self._plugin_id!r} does not own table {table!r}")
        return table

    def _check_entity(self, entity: object) -> str:
        entity_type = type(entity)
        try:
            return self._check_type(entity_type)
        except TypeError as exc:
            raise TypeError("plugin persistence accepts mapped entity instances only") from exc

    def add(self, entity: object) -> None:
        self._check_entity(entity)
        self._session.add(entity)

    def delete(self, entity: object) -> None:
        self._check_entity(entity)
        self._session.delete(entity)

    def get(self, entity_type: type[Any], entity_id: object) -> Any | None:
        self._check_type(entity_type)
        return self._session.get(entity_type, entity_id)

    def find(self, entity_type: type[Any], **filters: object) -> Any | None:
        self._check_type(entity_type)
        stmt = select(entity_type)
        for name, value in filters.items():
            column = getattr(entity_type, name, None)
            if column is None:
                raise TypeError(f"unknown entity field {name!r}")
            stmt = stmt.where(column == value)
        return self._session.scalars(stmt).first()

    def all(self, entity_type: type[Any], **filters: object) -> list[Any]:
        self._check_type(entity_type)
        stmt = select(entity_type)
        for name, value in filters.items():
            column = getattr(entity_type, name, None)
            if column is None:
                raise TypeError(f"unknown entity field {name!r}")
            stmt = stmt.where(column == value)
        return list(self._session.scalars(stmt))

    def create_tables(self, *entity_types: type[Any]) -> None:
        """Create only the declared plugin-owned tables."""
        if not entity_types:
            raise ValueError("at least one plugin entity type is required")
        tables = []
        for entity_type in entity_types:
            self._check_type(entity_type)
            tables.append(sa_inspect(entity_type).mapper.local_table)
        engine = require_bound_session(self._session)
        ensure_schema(engine)
        for table in tables:
            table.create(bind=engine, checkfirst=True)


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
    """Run one plugin operation inside the platform-owned transaction."""

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
    """One SQLAlchemy transaction exposing repositories to Core only."""

    def __init__(self, session: Session) -> None:
        engine = require_bound_session(session)
        self._session = session
        self._independent_uow_factory = _independent_uow_factory(engine)
        self._poisoned = False
        self._explicit_transaction = False
        self.employees = EmployeeRepository(session)
        self.organizations = OrganizationRepository(session)
        self.workplaces = WorkplaceRepository(session)
        self.jobs = JobRepository(session)
        self.assignments = AssignmentRepository(session)
        self.audit = AuditRepository(session)
        self.authorization = AuthorizationRepository(session)
        self.executions = ExecutionRepository(session)
        self.policies = PolicyRepository(session)
        self.outbox = OutboxRepository(session)

    def plugin_persistence(
        self,
        plugin_id: str,
        owned_tables: Iterable[str],
    ) -> PluginPersistenceAdapter:
        return PluginPersistenceAdapter(
            self._session,
            plugin_id=plugin_id,
            owned_tables=owned_tables,
        )

    @property
    def independent_uow_factory(self) -> Callable[[], SqlUnitOfWork]:
        """A factory for separate units of work outside this transaction.

        The durable denial audit must commit even when the business transaction
        rolls back, so it is never written through this unit of work.
        """
        return self._independent_uow_factory

    def _ensure_usable(self) -> None:
        if self._poisoned:
            raise RuntimeError("transaction is poisoned after rollback failure")

    def begin(self) -> None:
        self._ensure_usable()
        if not self._session.in_transaction():
            self._session.begin()
        self._explicit_transaction = True

    @property
    def in_transaction(self) -> bool:
        return self._explicit_transaction

    def finish_read(self) -> None:
        self._ensure_usable()
        if not self._explicit_transaction and self._session.in_transaction():
            self._session.rollback()

    def commit(self) -> None:
        self._ensure_usable()
        self._session.commit()
        self._explicit_transaction = False

    def rollback(self) -> None:
        self._ensure_usable()
        self._session.rollback()
        self._explicit_transaction = False

    def poison(self) -> None:
        self._poisoned = True

    def close(self) -> None:
        """Close the Core-owned session; this is not exposed to PluginContext."""
        self._session.close()

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
    """Create the Core PostgreSQL schema and tables if they do not exist."""
    engine = require_bound_session(session)
    ensure_schema(engine)
    apply_migrations(engine)
    Base.metadata.create_all(engine, checkfirst=True)


def create_sql_uow_factory(
    url: str | None = None,
    *,
    schema: str | None = None,
) -> Callable[[], SqlUnitOfWork]:
    """Build a production UoW factory after creating its PostgreSQL schema."""
    safe_schema = resolve_database_schema(schema)
    session_factory, engine = create_session_factory_with_engine(url, schema=safe_schema)
    ensure_schema(engine, safe_schema)
    apply_migrations(engine)
    Base.metadata.create_all(engine, checkfirst=True)

    def factory() -> SqlUnitOfWork:
        return SqlUnitOfWork(session_factory())

    return factory


__all__ = [
    "PluginPersistenceAdapter",
    "SqlTransactionRunner",
    "SqlUnitOfWork",
    "create_schema",
    "create_sql_uow_factory",
]
