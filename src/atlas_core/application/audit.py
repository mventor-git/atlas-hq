"""Audit application service (contract section 35: historical accountability).

Every audit record is append-only. ``record`` writes through the unit of work,
so an audit entry shares the transaction of the operation it describes: an
operation that rolls back leaves no audit trail behind.
"""

from __future__ import annotations

from collections.abc import Mapping

from atlas_sdk import AuditEntry, Scope
from atlas_sdk.context import AuditPort

from ..domain.audit import AuditRecord
from .unit_of_work import UnitOfWorkPort


def _to_read_model(record: AuditRecord) -> AuditEntry:
    return AuditEntry(
        audit_id=record.audit_id,
        occurred_at=record.occurred_at,
        actor=record.actor,
        action=record.action,
        scope=Scope(
            organization_id=record.organization_id,
            workplace_id=record.workplace_id,
        ),
        details=dict(record.details),
    )


class AuditService(AuditPort):
    def __init__(self, uow: UnitOfWorkPort) -> None:
        self._uow = uow

    def record(
        self,
        action: str,
        actor: str,
        scope: Scope | None = None,
        details: Mapping[str, object] | None = None,
    ) -> str:
        record = AuditRecord(
            actor=actor,
            action=action,
            organization_id=None if scope is None else scope.organization_id,
            workplace_id=None if scope is None else scope.workplace_id,
            details=dict(details or {}),
        )
        self._uow.audit.append(record)
        return record.audit_id

    def list_records(
        self,
        organization_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditEntry]:
        return [
            _to_read_model(r)
            for r in self._uow.audit.all(organization_id=organization_id, limit=limit)
        ]


__all__ = ["AuditService"]
