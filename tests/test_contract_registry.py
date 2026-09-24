"""Contract registry behaviour, including multi-implementation discovery (§13)."""

from __future__ import annotations

import pytest

from atlas_core.infrastructure.registry import InMemoryContractRegistry, TransactionOwner
from atlas_sdk import (
    ContractDeclaration,
    ContractId,
    NotFoundError,
)


def test_register_and_get_a_contract() -> None:
    registry = InMemoryContractRegistry()
    declaration = ContractDeclaration(
        contract_id=ContractId("attendance.daily_summary"),
        version="1.0",
        description="Daily attendance summary",
    )

    registry.register(declaration, "attendance")

    assert registry.exists(ContractId("attendance.daily_summary"))
    found = registry.get(ContractId("attendance.daily_summary"))
    assert found.declaration.contract_id == "attendance.daily_summary"
    assert found.plugin_id == "attendance"


def test_implementations_of_returns_every_provider() -> None:
    """Composability depends on learning there may be several providers."""
    registry = InMemoryContractRegistry()
    registry.register(
        ContractDeclaration(contract_id=ContractId("report.dataset")),
        "report.studio",
    )
    registry.register(
        ContractDeclaration(contract_id=ContractId("report.dataset"), version="2.0"),
        "report.studio.v2",
    )

    impls = registry.implementations_of(ContractId("report.dataset"))
    assert {i.plugin_id for i in impls} == {"report.studio", "report.studio.v2"}


def test_provided_by_filters_by_plugin() -> None:
    registry = InMemoryContractRegistry()
    registry.register(
        ContractDeclaration(contract_id=ContractId("attendance.daily_summary")),
        "attendance",
    )
    registry.register(
        ContractDeclaration(contract_id=ContractId("leave.summary")),
        "leave",
    )

    assert [i.declaration.contract_id for i in registry.provided_by("attendance")] == [
        "attendance.daily_summary"
    ]
    assert registry.provided_by("ghost") == []


def test_unknown_contract_raises_not_found() -> None:
    registry = InMemoryContractRegistry()

    with pytest.raises(NotFoundError):
        registry.get(ContractId("nope"))
    assert not registry.exists(ContractId("nope"))


def test_contract_invocation_commits_exactly_once() -> None:
    registry = InMemoryContractRegistry()
    contract_id = ContractId("attendance.daily_summary")
    registry.register(ContractDeclaration(contract_id=contract_id), "attendance")
    registry.bind(contract_id, "attendance", _Handler())
    commits = 0

    def commit() -> None:
        nonlocal commits
        commits += 1

    registry.register_transaction_owner(
        "attendance",
        TransactionOwner(commit=commit, rollback=lambda: None),
    )

    assert registry.invoke(contract_id, object()) == "handled"
    assert commits == 1


def test_contract_commit_failure_rolls_back_the_provider_transaction() -> None:
    class FailingTransaction:
        def __init__(self) -> None:
            self.rollbacks = 0

        def commit(self) -> None:
            raise RuntimeError("commit exploded")

        def rollback(self) -> None:
            self.rollbacks += 1

    transaction = FailingTransaction()
    registry = InMemoryContractRegistry()
    contract_id = ContractId("attendance.daily_summary")
    registry.register(ContractDeclaration(contract_id=contract_id), "attendance")
    registry.bind(contract_id, "attendance", _Handler())
    registry.register_transaction_owner(
        "attendance",
        TransactionOwner(commit=transaction.commit, rollback=transaction.rollback),
    )

    with pytest.raises(RuntimeError, match="commit exploded"):
        registry.invoke(contract_id, object())

    assert transaction.rollbacks == 1


class _Handler:
    def handle(self, request: object) -> str:
        return "handled"
