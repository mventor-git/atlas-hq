"""Shared test fixtures.

Every persistence test runs against a real SQLite database (file-backed so the
transactional outbox guarantee is exercised, not asserted). The factory below
swaps in per test via a temp directory, so no test sees another's rows.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from atlas_core.infrastructure.persistence.session import create_session_factory_with_engine
from atlas_core.infrastructure.persistence.unit_of_work import SqlUnitOfWork, create_schema
from atlas_core.kernel import Kernel


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A per-test SQLite file URL."""
    return f"sqlite:///{tmp_path / 'atlas-test.db'}"


@pytest.fixture
def session_factory(database_url: str) -> Callable[[], Session]:
    """A session factory bound to the test database."""
    factory, _engine = create_session_factory_with_engine(database_url)
    return factory


@pytest.fixture
def uow_factory(session_factory: Callable[[], Session]) -> Callable[[], SqlUnitOfWork]:
    """A unit-of-work factory that guarantees the schema exists first."""

    def factory() -> SqlUnitOfWork:
        session = session_factory()
        create_schema(session)
        return SqlUnitOfWork(session)

    return factory


@pytest.fixture
def kernel(uow_factory: Callable[[], SqlUnitOfWork]) -> Kernel:
    """A kernel wired to the test database."""
    return Kernel(uow_factory=uow_factory)


@pytest.fixture
def clean_uow(uow_factory: Callable[[], SqlUnitOfWork]) -> SqlUnitOfWork:
    """A single unit of work with the schema created."""
    return uow_factory()


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
