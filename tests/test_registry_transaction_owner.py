"""The contract registry's explicit transaction-owner seam."""

from __future__ import annotations

import pytest

from atlas_core.infrastructure.registry import InMemoryContractRegistry, TransactionOwner
from atlas_sdk import ContractDeclaration, ContractId


class _Cancellation(BaseException):
    pass


class _StatefulHandler:
    def __init__(self) -> None:
        self.pending: list[str] = []
        self.committed: list[str] = []
        self.rollbacks = 0
        self.fail_commit = False
        self.fail_rollback = False
        self.poisoned = False
        self.operation_error: BaseException | None = None

    def handle(self, request: str) -> str:
        if self.operation_error is not None:
            raise self.operation_error
        if request == "cancel":
            self.pending.append("leaked")
            raise _Cancellation("cancelled")
        if request == "write":
            self.pending.append("written")
            return "written"
        return request

    def commit(self) -> None:
        if self.poisoned:
            raise RuntimeError("poisoned transaction")
        if self.fail_commit:
            raise RuntimeError("commit exploded")
        self.committed = list(self.pending)

    def rollback(self) -> None:
        self.rollbacks += 1
        if self.fail_rollback:
            raise RuntimeError("rollback exploded")
        self.pending = list(self.committed)

    def poison(self) -> None:
        self.poisoned = True


def _registry(handler: _StatefulHandler) -> tuple[InMemoryContractRegistry, ContractId]:
    contract_id = ContractId("test.write")
    registry = InMemoryContractRegistry()
    registry.register(ContractDeclaration(contract_id=contract_id), "provider")
    registry.bind(contract_id, "provider", handler)
    registry.register_transaction_owner(
        "provider",
        TransactionOwner(
            commit=handler.commit,
            rollback=handler.rollback,
            poison=handler.poison,
        ),
    )
    return registry, contract_id


def test_base_exception_rolls_back_and_a_later_success_commits_cleanly() -> None:
    handler = _StatefulHandler()
    registry, contract_id = _registry(handler)

    with pytest.raises(_Cancellation, match="cancelled"):
        registry.invoke(contract_id, "cancel")

    assert handler.pending == []
    assert handler.rollbacks == 1
    assert registry.invoke(contract_id, "write") == "written"
    assert handler.committed == ["written"]


def test_rollback_failure_does_not_mask_the_operation_error() -> None:
    handler = _StatefulHandler()
    handler.fail_rollback = True
    registry, contract_id = _registry(handler)
    error = RuntimeError("operation exploded")
    handler.operation_error = error

    with pytest.raises(RuntimeError) as caught:
        registry.invoke(contract_id, "write")

    assert caught.value is error
    assert any("rollback exploded" in note for note in caught.value.__notes__)
    handler.operation_error = None
    with pytest.raises(RuntimeError, match="poisoned"):
        registry.invoke(contract_id, "write")
    assert handler.committed == []


def test_rollback_failure_does_not_mask_the_commit_error() -> None:
    handler = _StatefulHandler()
    handler.fail_commit = True
    handler.fail_rollback = True
    registry, contract_id = _registry(handler)

    with pytest.raises(RuntimeError, match="commit exploded") as caught:
        registry.invoke(contract_id, "write")

    assert caught.value.args == ("commit exploded",)
    assert any("rollback exploded" in note for note in caught.value.__notes__)
