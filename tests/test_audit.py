"""Audit service: canonical actor/scope from an opaque handle."""

from __future__ import annotations

import pytest
from tests.conftest import issue_uow_handle_for_test

from atlas_core.application.audit import AuditService
from atlas_core.domain.role import AUDIT_READ
from atlas_sdk import Scope

PRINCIPAL = "audit.principal"


def _handle(uow_factory, scope: Scope, action: str = "audit.read"):
    return issue_uow_handle_for_test(
        uow_factory,
        AUDIT_READ,
        action,
        scope,
        principal_id=PRINCIPAL,
    )


def test_record_returns_an_id_and_reads_back(uow_factory) -> None:
    handle = _handle(uow_factory, Scope(principal_id=PRINCIPAL))
    with uow_factory() as uow:
        audit_id = AuditService(uow).record(
            action="employee.created",
            details={"source": "test"},
            execution_handle=handle,
        )
    with uow_factory() as check:
        records = AuditService(check).list_records(execution_handle=handle)
    entries = [r for r in records if r.action == "employee.created"]
    assert len(entries) == 1
    assert entries[0].audit_id == audit_id
    assert entries[0].actor == PRINCIPAL
    assert entries[0].scope.principal_id == PRINCIPAL


def test_scope_and_details_are_preserved(uow_factory) -> None:
    scope = Scope(organization_id="org-1", workplace_id="wp-1")
    handle = _handle(uow_factory, scope, "audit.write")
    with uow_factory() as uow:
        audit_id = AuditService(uow).record(
            action="assignment.created",
            details={"employee_id": "emp-1", "job_id": "job-1"},
            execution_handle=handle,
        )
    with uow_factory() as check:
        list_handle = _handle(uow_factory, Scope(organization_id="org-1"), "audit.read")
        entry = next(
            r
            for r in AuditService(check).list_records(
                organization_id="org-1", execution_handle=list_handle
            )
            if r.action == "assignment.created"
        )
    assert entry.audit_id == audit_id
    assert entry.scope.organization_id == "org-1"
    assert entry.scope.workplace_id == "wp-1"
    assert entry.details["employee_id"] == "emp-1"
    assert entry.details["job_id"] == "job-1"


def test_audit_is_scoped_by_organization(uow_factory) -> None:
    scope_a = Scope(organization_id="org-a")
    scope_b = Scope(organization_id="org-b")
    handle_a = _handle(uow_factory, scope_a, "audit.write")
    handle_b = _handle(uow_factory, scope_b, "audit.write")
    with uow_factory() as uow:
        service = AuditService(uow)
        service.record(action="a", execution_handle=handle_a)
        service.record(action="b", execution_handle=handle_b)
    with uow_factory() as check:
        service = AuditService(check)
        assert [
            r.action
            for r in service.list_records(organization_id="org-a", execution_handle=handle_a)
            if r.action in {"a", "b"}
        ] == ["a"]
        assert [
            r.action
            for r in service.list_records(organization_id="org-b", execution_handle=handle_b)
            if r.action in {"a", "b"}
        ] == ["b"]


def test_audit_respects_the_limit(uow_factory) -> None:
    handle = _handle(uow_factory, Scope(principal_id=PRINCIPAL), "audit.write")
    with uow_factory() as uow:
        service = AuditService(uow)
        for i in range(10):
            service.record(action=f"a{i}", execution_handle=handle)
    with uow_factory() as check:
        assert len(AuditService(check).list_records(limit=3, execution_handle=handle)) == 3


def test_a_rolled_back_operation_leaves_no_audit_trail(uow_factory) -> None:
    handle = _handle(uow_factory, Scope(principal_id=PRINCIPAL), "audit.write")
    with pytest.raises(RuntimeError, match="rollback"), uow_factory() as uow:
        AuditService(uow).record(action="rolled.back", execution_handle=handle)
        raise RuntimeError("rollback")
    with uow_factory() as check:
        assert not any(
            r.action == "rolled.back"
            for r in AuditService(check).list_records(execution_handle=handle)
        )
