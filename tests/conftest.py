"""Shared fixtures for real PostgreSQL acceptance tests.

Every test gets a fresh PostgreSQL schema. The schema name is generated per test,
all pooled connections are pinned to it with a quoted search path, and teardown
drops only that schema. The developer database and the ``public`` schema are
never reset or truncated, so pytest workers can run in parallel safely.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from tests.synthetic import TEST_ENTRY_POINT_GROUP

from atlas_core.infrastructure.persistence.session import (
    SessionFactory,
    create_schema,
    create_session_factory_with_engine,
    drop_schema,
    resolve_database_url,
)
from atlas_core.infrastructure.persistence.unit_of_work import SqlUnitOfWork
from atlas_core.kernel import Kernel

TEST_DATABASE_ENV = "ATLAS_TEST_DATABASE_URL"


@pytest.fixture
def test_schema() -> str:
    """A short, unique PostgreSQL schema name for this test only."""
    return f"atlas_test_{uuid.uuid4().hex}"


@pytest.fixture
def database_url() -> str:
    """The explicitly configured PostgreSQL URL used by database tests."""
    configured = os.environ.get(TEST_DATABASE_ENV)
    if not configured:
        pytest.fail(
            f"{TEST_DATABASE_ENV} must be set to a PostgreSQL URL; "
            "no alternate database or substitute is supported"
        )
    return resolve_database_url(configured, env_var=TEST_DATABASE_ENV)


@pytest.fixture
def test_engine(database_url: str, test_schema: str) -> Iterator[Engine]:
    """A real PostgreSQL engine with core tables in this test's schema."""
    _factory, engine = create_session_factory_with_engine(database_url, schema=test_schema)
    try:
        create_schema(engine, test_schema)
        yield engine
    finally:
        engine.dispose()
        admin_engine = create_engine(resolve_database_url(database_url), future=True)
        try:
            drop_schema(admin_engine, test_schema)
        finally:
            admin_engine.dispose()


@pytest.fixture
def session_factory(test_engine: Engine) -> Iterator[Callable[[], Session]]:
    """A session factory bound to the isolated test schema."""
    sessions: list[Session] = []
    factory_impl = SessionFactory(test_engine)

    def factory() -> Session:
        session = factory_impl()
        sessions.append(session)
        return session

    yield factory
    for session in sessions:
        session.close()


@pytest.fixture
def uow_factory(
    session_factory: Callable[[], Session],
) -> Iterator[Callable[[], SqlUnitOfWork]]:
    """A unit-of-work factory sharing one isolated PostgreSQL engine."""
    units: list[SqlUnitOfWork] = []

    def factory() -> SqlUnitOfWork:
        unit = SqlUnitOfWork(session_factory())
        units.append(unit)
        return unit

    yield factory
    for unit in reversed(units):
        unit.session.close()


@pytest.fixture
def kernel(uow_factory: Callable[[], SqlUnitOfWork]) -> Kernel:
    """A kernel wired to the isolated PostgreSQL database.

    It boots against the test-only entry-point group so the eight plugins shipped
    in this distribution never appear in a unit test's registry. Tests that
    specifically exercise the real plugins opt into the real group.
    """
    return Kernel(uow_factory=uow_factory, entry_point_group=TEST_ENTRY_POINT_GROUP)


@pytest.fixture
def clean_uow(uow_factory: Callable[[], SqlUnitOfWork]) -> SqlUnitOfWork:
    """A single unit of work with the core schema already created."""
    return uow_factory()


@pytest.fixture
def real_kernel(uow_factory: Callable[[], SqlUnitOfWork]) -> Kernel:
    """A kernel that discovers the plugins shipped in this distribution.

    Used by the D2 acceptance tests, which are the ones that must see the real
    entry-point-registered plugins.
    """
    return Kernel(uow_factory=uow_factory)


@pytest.fixture
def isolated_plugins(tmp_path: Path) -> Iterator[Path]:
    """A directory on ``sys.path`` holding a synthetic plugin distribution.

    Tests write a real ``.dist-info`` directory plus a module into this path and
    add it to ``sys.path``; ``importlib.metadata`` then discovers the entry point
    exactly as it would for any installed package. No core file is touched.
    """
    import sys

    sys.path.insert(0, str(tmp_path))
    try:
        yield tmp_path
    finally:
        sys.path.remove(str(tmp_path))
        modules = [name for name in list(sys.modules) if name.startswith("synthetic_")]
        for name in modules:
            del sys.modules[name]
