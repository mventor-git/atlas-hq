"""Append-only audit service; actor and scope come only from a handle."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from atlas_sdk import AuditEntry, AuthorizationError, ExecutionHandle, Scope
from atlas_sdk.context import AuditPort

from ..domain.audit import AuditRecord
from ..domain.execution import ExecutionFacts
from ..domain.role import AUDIT_READ
from .execution_guard import authorization_for_uow, require_execution_handle
from .unit_of_work import UnitOfWorkPort

if TYPE_CHECKING:
    from .authorization import AuthorizationService

if TYPE_CHECKING:
    from .execution import ExecutionHandleResolver


def _to_read_model(record: AuditRecord) -> AuditEntry:
    return AuditEntry(
        audit_id=record.audit_id,
        occurred_at=record.occurred_at,
        actor=record.actor,
        action=record.action,
        scope=Scope(
            organization_id=record.organization_id,
            workplace_id=record.workplace_id,
            principal_id=record.principal_id,
        ),
        details=dict(record.details),
    )


class AuditService(AuditPort):
    def __init__(
        self,
        uow: UnitOfWorkPort,
        *,
        resolver: ExecutionHandleResolver | None = None,
        authorization: AuthorizationService | None = None,
    ) -> None:
        self._uow = uow
        if resolver is None or authorization is None:
            bound = authorization_for_uow(uow)
            resolver = resolver or bound._handle_resolver  # type: ignore[attr-defined]
            authorization = authorization or bound
        self._resolver = resolver
        self._authorization = authorization

    def _facts(self, handle: ExecutionHandle) -> ExecutionFacts | None:
        facts = require_execution_handle(
            handle,
            resolver=self._resolver.resolve if self._resolver is not None else None,
        )
        return facts if isinstance(facts, ExecutionFacts) else None

    def record(
        self,
        action: str,
        details: Mapping[str, object] | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> str:
        facts = self._facts(execution_handle)
        if facts is None:
            raise AuthorizationError("a resolvable ExecutionHandle is required for audit")
        record = AuditRecord(
            actor=facts.principal_id,
            action=action,
            organization_id=facts.scope.organization_id,
            workplace_id=facts.scope.workplace_id,
            principal_id=facts.scope.principal_id,
            details=dict(details or {}),
        )
        self._uow.audit.append(record)
        return record.audit_id

    def list_records(
        self,
        organization_id: str | None = None,
        limit: int = 100,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[AuditEntry]:
        scope = None if organization_id is None else Scope(organization_id=organization_id)
        facts = self._facts(execution_handle)
        if facts is None:
            raise AuthorizationError("a resolvable ExecutionHandle is required for audit")
        effective_scope = scope or facts.scope
        if self._authorization is not None:
            decision = self._authorization.authorize(execution_handle, AUDIT_READ, effective_scope)
            if not decision.allowed:
                raise AuthorizationError(f"audit read denied: {decision.code}")
        return [
            _to_read_model(r)
            for r in self._uow.audit.all(organization_id=organization_id, limit=limit)
        ]


__all__ = ["AuditService"]
