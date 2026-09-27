"""PostgreSQL adapter for Core-owned execution handle records."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.orm import Session

from atlas_sdk import CapabilityId, Channel, Scope

from ...application.repositories import ExecutionRepositoryPort
from ...domain.execution import ExecutionFacts, PersistedExecution, freeze_policy_context
from .orm import ExecutionORM


class ExecutionRepository(ExecutionRepositoryPort):
    """Stores only token hashes and canonical facts; never a caller DTO."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, execution: PersistedExecution) -> None:
        facts = execution.facts
        self._session.add(
            ExecutionORM(
                token_hash=execution.token_hash,
                principal_id=facts.principal_id,
                identity_id=facts.identity_id,
                capability_id=str(facts.capability_id),
                allowed_capability_ids_json=sorted(
                    str(capability) for capability in facts.allowed_capability_ids
                ),
                action=facts.action,
                channel=facts.channel.value,
                resource_id=facts.resource_id,
                organization_id=facts.scope.organization_id,
                workplace_id=facts.scope.workplace_id,
                principal_scope_id=facts.scope.principal_id,
                policy_context_json=dict(facts.policy_context),
                created_at=execution.created_at,
                expires_at=facts.expires_at,
            )
        )

    def get(self, token_hash: str) -> PersistedExecution | None:
        self._session.flush()
        row = self._session.get(ExecutionORM, token_hash)
        if row is None:
            return None
        facts = ExecutionFacts(
            principal_id=row.principal_id,
            identity_id=row.identity_id,
            capability_id=CapabilityId(row.capability_id),
            allowed_capability_ids=frozenset(
                CapabilityId(value) for value in (row.allowed_capability_ids_json or [])
            ),
            action=row.action,
            channel=Channel(row.channel),
            resource_id=row.resource_id,
            scope=Scope(
                organization_id=row.organization_id,
                workplace_id=row.workplace_id,
                principal_id=row.principal_scope_id,
            ),
            policy_context=freeze_policy_context(dict(row.policy_context_json or {})),
            expires_at=row.expires_at,
        )
        return PersistedExecution(
            token_hash=row.token_hash,
            facts=facts,
            created_at=row.created_at,
            revoked_at=row.revoked_at,
        )

    def revoke(self, token_hash: str) -> bool:
        row = self._session.get(ExecutionORM, token_hash)
        if row is None or row.revoked_at is not None:
            return False
        row.revoked_at = datetime.now(UTC)
        return True

    def expire_due(self, now: datetime) -> int:
        result = self._session.execute(
            update(ExecutionORM)
            .where(
                ExecutionORM.revoked_at.is_(None),
                ExecutionORM.expires_at <= now,
            )
            .values(revoked_at=now)
            .execution_options(synchronize_session=False)
        )
        return int(getattr(result, "rowcount", 0) or 0)


def new_token_hash(token: str) -> str:
    """Hash a bearer token before it reaches PostgreSQL."""
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


__all__ = ["ExecutionRepository", "new_token_hash"]
