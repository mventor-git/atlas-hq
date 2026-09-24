"""The internal SQLAlchemy unit-of-work context-manager seam."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from atlas_core.domain.organization import Organization
from atlas_core.infrastructure.persistence.session import resolve_database_url
from atlas_core.infrastructure.persistence.unit_of_work import SqlUnitOfWork


def test_clean_exit_rolls_back_when_commit_fails(
    uow_factory: Callable[[], SqlUnitOfWork],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = uow_factory()
    calls: list[str] = []
    error = RuntimeError("commit exploded")

    def fail_commit() -> None:
        raise error

    monkeypatch.setattr(uow, "commit", fail_commit)
    monkeypatch.setattr(uow, "rollback", lambda: calls.append("rollback"))

    with pytest.raises(RuntimeError) as caught, uow:
        pass

    assert caught.value is error
    assert calls == ["rollback"]


def test_clean_exit_preserves_commit_error_when_rollback_fails(
    uow_factory: Callable[[], SqlUnitOfWork],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = uow_factory()
    error = RuntimeError("commit exploded")

    def fail_commit() -> None:
        raise error

    def fail_rollback() -> None:
        raise RuntimeError("rollback exploded")

    monkeypatch.setattr(uow, "commit", fail_commit)
    monkeypatch.setattr(uow, "rollback", fail_rollback)

    with pytest.raises(RuntimeError) as caught, uow:
        pass

    assert caught.value is error
    assert any("rollback exploded" in note for note in caught.value.__notes__)
    with pytest.raises(RuntimeError, match="poisoned"), uow:
        pass


def test_exception_path_preserves_the_original_error_when_rollback_fails(
    uow_factory: Callable[[], SqlUnitOfWork],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = uow_factory()
    error = RuntimeError("body exploded")

    def fail_rollback() -> None:
        raise RuntimeError("rollback exploded")

    monkeypatch.setattr(uow, "rollback", fail_rollback)

    with pytest.raises(RuntimeError) as caught, uow:
        raise error

    assert caught.value is error
    assert any("rollback exploded" in note for note in caught.value.__notes__)


def test_exception_path_poisons_the_unit_of_work_when_rollback_fails(
    uow_factory: Callable[[], SqlUnitOfWork],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uow = uow_factory()
    error = RuntimeError("body exploded")

    def fail_rollback() -> None:
        raise RuntimeError("rollback exploded")

    monkeypatch.setattr(uow, "rollback", fail_rollback)

    with pytest.raises(RuntimeError) as caught, uow:
        raise error

    assert caught.value is error
    with pytest.raises(RuntimeError, match="poisoned"), uow:
        pass


def test_sqlite_session_cannot_construct_a_uow() -> None:
    engine = create_engine("sqlite://", future=True)
    session = Session(engine)
    try:
        with pytest.raises(ValueError, match=r"postgresql\+psycopg"):
            uow = SqlUnitOfWork(session)
            uow.organizations.add(Organization(name="Rejected", code="REJECT"))
    finally:
        session.close()
        engine.dispose()


def test_unbound_postgresql_session_cannot_construct_a_uow(database_url: str) -> None:
    engine = create_engine(resolve_database_url(database_url), future=True)
    session = Session(engine)
    try:
        with pytest.raises(ValueError, match="not bound"):
            SqlUnitOfWork(session)
    finally:
        session.close()
        engine.dispose()


def test_session_without_a_bind_cannot_construct_a_uow() -> None:
    with pytest.raises(RuntimeError, match="bound"):
        SqlUnitOfWork(Session())
