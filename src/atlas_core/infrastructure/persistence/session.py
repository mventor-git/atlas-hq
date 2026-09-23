"""The one place the database choice is made (contract section 22).

PostgreSQL is the contractual primary (contract section 3), but no server is
reachable on this machine, so the default URL is SQLite. The abstraction cost of
that choice is intentionally one line: the connection URL. Everything else —
sessions, the transactional outbox, the unit of work — is dialect-agnostic and
already exercised by the test suite against a real file-backed SQLite database.

Swapping in Postgres later means: install ``psycopg``, set ``ATLAS_DATABASE_URL``
to a ``postgresql+psycopg://`` URL, and run. No core or application code changes.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_SQLITE_URL = "sqlite:///atlas.db"
ENV_VAR = "ATLAS_DATABASE_URL"


def resolve_database_url(url: str | None = None) -> str:
    """Pick the connection URL: explicit argument, then env var, then default."""
    if url is not None:
        return url
    return os.environ.get(ENV_VAR, DEFAULT_SQLITE_URL)


def _sqlite_engine(url: str) -> Engine:
    """SQLite with WAL mode.

    The outbox dispatcher commits its own transaction while plugin sessions may
    still be open; the default rollback-journal mode serializes those as a hard
    lock. WAL permits a writer alongside readers, so dispatch never deadlocks
    against an idle plugin transaction. Postgres needs no equivalent.
    """
    engine = create_engine(url, future=True)
    with engine.connect() as connection:
        connection.execute(text("PRAGMA journal_mode=WAL"))
        connection.commit()
    return engine


def _build_engine(url: str) -> Engine:
    return _sqlite_engine(url) if url.startswith("sqlite") else create_engine(url, future=True)


def create_session_factory(url: str | None = None) -> sessionmaker[Session]:
    """Build a session factory bound to ``url``.

    ``expire_on_commit=False`` is deliberate: the outbox dispatcher reads
    committed rows into read models after commit, and re-fetching them from an
    expired session would defeat that.
    """
    return sessionmaker(
        bind=_build_engine(resolve_database_url(url)), expire_on_commit=False, future=True
    )


class SessionFactory:
    """A callable session factory with an attached engine.

    Keeping the engine next to the factory lets the kernel create the schema
    once at boot without any other module having to know an engine exists.
    """

    def __init__(self, engine: Engine) -> None:
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
) -> tuple[SessionFactory, Engine]:
    factory = SessionFactory(_build_engine(resolve_database_url(url)))
    return factory, factory.engine


__all__ = [
    "DEFAULT_SQLITE_URL",
    "ENV_VAR",
    "SessionFactory",
    "create_session_factory",
    "create_session_factory_with_engine",
    "resolve_database_url",
]
