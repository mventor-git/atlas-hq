"""PostgreSQL connection and session construction (contract sections 3 and 22).

Atlas has one supported persistence engine: PostgreSQL. A database URL is
configuration, not a development convenience: callers must provide
``ATLAS_DATABASE_URL`` (or an explicit URL) and it must use SQLAlchemy's
``postgresql+psycopg`` driver. There is no alternate database fallback.

The physical schema is selected with a quoted PostgreSQL search path. The
production schema is ``atlas``; tests use a unique schema per test. Unqualified
ORM table names keep the existing ownership model while the connection path
keeps each environment's tables isolated.
"""

from __future__ import annotations

import os
import re
from typing import Any
from weakref import WeakKeyDictionary

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateSchema, DropSchema

from .orm import Base

ENV_VAR = "ATLAS_DATABASE_URL"
SCHEMA_ENV_VAR = "ATLAS_DATABASE_SCHEMA"
DEFAULT_SCHEMA = "atlas"
_POSTGRES_DRIVER = "postgresql+psycopg"
_TEST_SCHEMA_PREFIX = "atlas_test_"
_SCHEMA_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_ENGINE_SCHEMAS: WeakKeyDictionary[Engine, str] = WeakKeyDictionary()


def _validate_postgres_driver(drivername: str, source: str) -> None:
    if drivername != _POSTGRES_DRIVER:
        raise ValueError(
            f"{source} must use PostgreSQL with the psycopg driver (postgresql+psycopg://...)"
        )


def resolve_database_url(url: str | None = None, *, env_var: str = ENV_VAR) -> str:
    """Return an explicit PostgreSQL URL or fail with a useful configuration error."""
    configured = url if url is not None else os.environ.get(env_var)
    if not configured or not configured.strip():
        source = "database URL" if url is not None else env_var
        raise ValueError(f"{source} must be set to a PostgreSQL URL")

    try:
        parsed = make_url(configured)
    except (ArgumentError, TypeError) as exc:
        raise ValueError("database URL must be a valid PostgreSQL URL") from exc

    _validate_postgres_driver(parsed.drivername, "database URL")
    return configured


def _validate_schema(schema: str) -> str:
    if not isinstance(schema, str) or len(schema) > 63 or _SCHEMA_PATTERN.fullmatch(schema) is None:
        raise ValueError("database schema must be a simple PostgreSQL identifier")
    return schema


def resolve_database_schema(
    schema: str | None = None,
    *,
    env_var: str = SCHEMA_ENV_VAR,
) -> str:
    """Return a validated schema, optionally selected by configuration."""
    configured = schema if schema is not None else os.environ.get(env_var, DEFAULT_SCHEMA)
    return _validate_schema(configured)


def _validate_postgresql_engine(engine: Engine) -> None:
    if not isinstance(engine, Engine) or engine.dialect.name != "postgresql":
        raise ValueError(
            "database engine must use PostgreSQL with the psycopg driver (postgresql+psycopg://...)"
        )
    _validate_postgres_driver(engine.url.drivername, "database engine")
    if engine.dialect.driver != "psycopg":
        raise ValueError(
            "database engine must use PostgreSQL with the psycopg driver (postgresql+psycopg://...)"
        )


def _require_bound_schema(engine: Engine) -> str:
    _validate_postgresql_engine(engine)
    bound_schema = _ENGINE_SCHEMAS.get(engine)
    if bound_schema is None:
        raise ValueError("PostgreSQL engine is not bound to an Atlas schema")
    return _validate_schema(bound_schema)


def require_bound_session(session: Session) -> Engine:
    """Validate a session's engine and return the bound Atlas PostgreSQL engine."""
    bind = session.bind
    if bind is None:
        raise RuntimeError("session must be bound to an Atlas PostgreSQL engine")
    engine = bind if isinstance(bind, Engine) else bind.engine
    _require_bound_schema(engine)
    return engine


def _schema_for_engine(engine: Engine, schema: str | None) -> str:
    bound_schema = _require_bound_schema(engine)
    if schema is None:
        return bound_schema
    requested_schema = resolve_database_schema(schema)
    if requested_schema != bound_schema:
        raise ValueError(
            f"schema {requested_schema!r} does not match engine bound schema {bound_schema!r}"
        )
    return bound_schema


def _install_search_path(engine: Engine, schema: str) -> None:
    """Set a session-level, quoted search path for every pooled connection."""
    safe_schema = _validate_schema(schema)
    quoted_schema = engine.dialect.identifier_preparer.quote_identifier(safe_schema)

    @event.listens_for(engine, "connect")
    def set_search_path(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SET SESSION search_path TO {quoted_schema}")
        finally:
            cursor.close()


def ensure_schema(engine: Engine, schema: str | None = None) -> None:
    """Create one PostgreSQL schema if it is absent, without touching other schemas."""
    safe_schema = _schema_for_engine(engine, schema)
    with engine.begin() as connection:
        connection.execute(CreateSchema(safe_schema, if_not_exists=True))


def create_schema(engine: Engine, schema: str | None = None) -> None:
    """Create the core tables in the configured PostgreSQL schema."""
    ensure_schema(engine, schema)
    Base.metadata.create_all(engine, checkfirst=True)


def drop_schema(engine: Engine, schema: str) -> None:
    """Drop one isolated test schema; production schemas are never droppable here."""
    _validate_postgresql_engine(engine)
    safe_schema = _validate_schema(schema)
    if not safe_schema.startswith(_TEST_SCHEMA_PREFIX) or len(safe_schema) == len(
        _TEST_SCHEMA_PREFIX
    ):
        raise ValueError("drop_schema only accepts isolated atlas_test_ schemas")
    with engine.begin() as connection:
        connection.execute(DropSchema(safe_schema, cascade=True, if_exists=True))


def _build_engine(url: str, schema: str | None = None) -> Engine:
    """Build the one supported engine and bind it to a safe schema path."""
    safe_schema = resolve_database_schema(schema)
    engine = create_engine(resolve_database_url(url), future=True)
    _ENGINE_SCHEMAS[engine] = safe_schema
    _install_search_path(engine, safe_schema)
    return engine


def create_session_factory(
    url: str | None = None,
    *,
    schema: str | None = None,
) -> sessionmaker[Session]:
    """Build a session factory bound to an explicit PostgreSQL ``url``."""
    resolved = resolve_database_url(url)
    return sessionmaker(bind=_build_engine(resolved, schema), expire_on_commit=False, future=True)


class SessionFactory:
    """A callable session factory with an attached PostgreSQL engine."""

    def __init__(self, engine: Engine) -> None:
        _require_bound_schema(engine)
        self.engine = engine
        self._sessionmaker = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    def __call__(self) -> Session:
        return self._sessionmaker()

    def begin(self) -> Session:
        """A session with a transaction already open (for outbox-style flows)."""
        session = self()
        session.begin()
        return session


def create_session_factory_with_engine(
    url: str | None = None,
    *,
    schema: str | None = None,
) -> tuple[SessionFactory, Engine]:
    factory = SessionFactory(_build_engine(resolve_database_url(url), schema))
    return factory, factory.engine


__all__ = [
    "DEFAULT_SCHEMA",
    "ENV_VAR",
    "SCHEMA_ENV_VAR",
    "SessionFactory",
    "create_schema",
    "create_session_factory",
    "create_session_factory_with_engine",
    "drop_schema",
    "ensure_schema",
    "require_bound_session",
    "resolve_database_schema",
    "resolve_database_url",
]
