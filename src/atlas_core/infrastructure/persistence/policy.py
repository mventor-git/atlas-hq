"""PostgreSQL adapter for Core-owned effective-dated policies."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...application.repositories import PolicyRepositoryPort
from ...domain.policy import Policy
from .orm import PolicyORM


def _to_policy(row: PolicyORM) -> Policy:
    return Policy(
        policy_id=row.policy_id,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        enabled=row.enabled,
        condition=dict(row.condition_json or {}),
        capability=row.capability,
        action=row.action,
        channel=row.channel,
    )


class PolicyRepository(PolicyRepositoryPort):
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, policy_id: str) -> Policy | None:
        row = self._session.get(PolicyORM, policy_id)
        return _to_policy(row) if row is not None else None

    def list(self) -> list[Policy]:
        rows = self._session.scalars(select(PolicyORM).order_by(PolicyORM.policy_id))
        return [_to_policy(row) for row in rows]

    def upsert(self, policy: Policy) -> None:
        row = self._session.get(PolicyORM, policy.policy_id)
        if row is None:
            self._session.add(
                PolicyORM(
                    policy_id=policy.policy_id,
                    effective_from=policy.effective_from,
                    effective_to=policy.effective_to,
                    enabled=policy.enabled,
                    condition_json=dict(policy.condition),
                    capability=policy.capability,
                    action=policy.action,
                    channel=policy.channel,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                ),
            )
            return
        row.effective_from = policy.effective_from
        row.effective_to = policy.effective_to
        row.enabled = policy.enabled
        row.condition_json = dict(policy.condition)
        row.capability = policy.capability
        row.action = policy.action
        row.channel = policy.channel
        row.updated_at = datetime.now(UTC)


__all__ = ["PolicyRepository"]
