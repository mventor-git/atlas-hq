"""Audit service: append-only records that share the transaction (§35)."""

from __future__ import annotations

from collections.abc import Callable

from atlas_core.application.audit import AuditService
from atlas_core.application.unit_of_work import UnitOfWorkPort


def test_record_returns_an_id_and_reads_back(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    service = AuditService(uow)

    with uow:
        audit_id = service.record(action="employee.created", actor="hr.admin")

    assert audit_id
    with uow_factory() as uow2:
        records = AuditService(uow2).list_records()

    assert len(records) == 1
    assert records[0].audit_id == audit_id
    assert records[0].actor == "hr.admin"
    assert records[0].action == "employee.created"
    assert records[0].scope.organization_id is None


def test_scope_and_details_are_preserved(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    from atlas_sdk import Scope

    uow = uow_factory()
    with uow:
        audit_id = AuditService(uow).record(
            action="assignment.created",
            actor="manager@acme",
            scope=Scope(organization_id="org-1", workplace_id="wp-1"),
            details={"employee_id": "emp-1", "job_id": "job-1"},
        )

    with uow_factory() as uow2:
        entry = AuditService(uow2).list_records(organization_id="org-1")[0]

    assert entry.audit_id == audit_id
    assert entry.scope.organization_id == "org-1"
    assert entry.scope.workplace_id == "wp-1"
    assert entry.details["employee_id"] == "emp-1"
    assert entry.details["job_id"] == "job-1"


def test_audit_is_scoped_by_organization(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    from atlas_sdk import Scope

    uow = uow_factory()
    with uow:
        service = AuditService(uow)
        service.record(action="a", actor="x", scope=Scope(organization_id="org-a"))
        service.record(action="b", actor="y", scope=Scope(organization_id="org-b"))

    with uow_factory() as uow2:
        service = AuditService(uow2)
        assert [r.action for r in service.list_records(organization_id="org-a")] == ["a"]
        assert [r.action for r in service.list_records(organization_id="org-b")] == ["b"]
        assert len(service.list_records()) == 2


def test_audit_respects_the_limit(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    with uow:
        service = AuditService(uow)
        for i in range(10):
            service.record(action=f"a{i}", actor="x")

    with uow_factory() as uow2:
        assert len(AuditService(uow2).list_records(limit=3)) == 3


def test_a_rolled_back_operation_leaves_no_audit_trail(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    """Audit shares the transaction: no audit for work that never committed."""
    uow = uow_factory()
    try:
        with uow:
            AuditService(uow).record(action="rolled.back", actor="x")
            raise RuntimeError("rollback")
    except RuntimeError:
        pass

    with uow_factory() as uow2:
        assert AuditService(uow2).list_records() == []
