"""The internal SQLAlchemy unit-of-work context-manager seam."""

from __future__ import annotations

from collections.abc import Callable

import pytest

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
