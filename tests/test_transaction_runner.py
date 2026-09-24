"""The transaction runner is the plugin-facing transaction seam."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from atlas_core.infrastructure.persistence.unit_of_work import SqlTransactionRunner


@dataclass
class _RecordingUnitOfWork:
    calls: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    committed: list[str] = field(default_factory=list)
    fail_begin: bool = False
    fail_commit: bool = False
    fail_rollback: bool = False
    poisoned: bool = False

    def begin(self) -> None:
        self.calls.append("begin")
        if self.poisoned:
            raise RuntimeError("poisoned transaction")
        if self.fail_begin:
            raise RuntimeError("begin exploded")

    def commit(self) -> None:
        self.calls.append("commit")
        if self.poisoned:
            raise RuntimeError("poisoned transaction")
        if self.fail_commit:
            raise RuntimeError("commit exploded")
        self.committed = list(self.pending)

    def rollback(self) -> None:
        self.calls.append("rollback")
        if self.fail_rollback:
            raise RuntimeError("rollback exploded")
        self.pending = list(self.committed)

    def poison(self) -> None:
        self.poisoned = True


def test_runner_commits_a_successful_operation() -> None:
    uow = _RecordingUnitOfWork()
    runner = SqlTransactionRunner(uow)

    def operation() -> str:
        uow.pending.append("written")
        return "result"

    assert runner.run(operation) == "result"
    assert uow.calls == ["begin", "commit"]
    assert uow.committed == ["written"]


def test_runner_rolls_back_an_operation_failure_and_reraises() -> None:
    uow = _RecordingUnitOfWork()
    runner = SqlTransactionRunner(uow)

    def operation() -> None:
        uow.pending.append("must-not-leak")
        raise ValueError("operation exploded")

    with pytest.raises(ValueError, match="operation exploded"):
        runner.run(operation)

    assert uow.calls == ["begin", "rollback"]
    assert uow.pending == []
    assert uow.committed == []


def test_runner_rolls_back_and_reraises_a_commit_failure() -> None:
    uow = _RecordingUnitOfWork(fail_commit=True)
    runner = SqlTransactionRunner(uow)

    def operation() -> None:
        uow.pending.append("must-not-leak")

    with pytest.raises(RuntimeError, match="commit exploded"):
        runner.run(operation)

    assert uow.calls == ["begin", "commit", "rollback"]
    assert uow.pending == []
    assert uow.committed == []


def test_a_later_operation_cannot_see_a_failed_operations_writes() -> None:
    uow = _RecordingUnitOfWork()
    runner = SqlTransactionRunner(uow)

    def failed_operation() -> None:
        uow.pending.append("leaked")
        raise RuntimeError("first operation failed")

    with pytest.raises(RuntimeError, match="first operation failed"):
        runner.run(failed_operation)

    def successful_operation() -> tuple[str, ...]:
        return tuple(uow.pending)

    assert runner.run(successful_operation) == ()


def test_runner_protects_and_reraises_a_begin_failure() -> None:
    uow = _RecordingUnitOfWork(fail_begin=True)
    runner = SqlTransactionRunner(uow)

    with pytest.raises(RuntimeError, match="begin exploded"):
        runner.run(lambda: None)

    assert uow.calls == ["begin", "rollback"]


def test_runner_preserves_the_operation_error_when_rollback_fails() -> None:
    uow = _RecordingUnitOfWork(fail_rollback=True)
    runner = SqlTransactionRunner(uow)
    error = ValueError("operation exploded")

    def operation() -> None:
        raise error

    with pytest.raises(ValueError) as caught:
        runner.run(operation)

    assert caught.value is error
    assert any("rollback exploded" in note for note in caught.value.__notes__)
    with pytest.raises(RuntimeError, match="poisoned"):
        runner.run(lambda: uow.pending.append("leaked again"))
    assert uow.committed == []


def test_runner_rolls_back_a_base_exception_and_allows_a_later_success() -> None:
    class Cancellation(BaseException):
        pass

    uow = _RecordingUnitOfWork()
    runner = SqlTransactionRunner(uow)

    def cancelled_operation() -> None:
        uow.pending.append("leaked")
        raise Cancellation("cancelled")

    with pytest.raises(Cancellation, match="cancelled"):
        runner.run(cancelled_operation)

    assert runner.run(lambda: tuple(uow.pending)) == ()
    uow.pending.append("good")
    runner.run(lambda: None)
    assert uow.committed == ["good"]
