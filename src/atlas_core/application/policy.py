"""Policy application service (contract section 2: Policy Engine, effective-dated)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from atlas_sdk import PolicyError
from atlas_sdk.context import PolicyPort

from ..domain.policy import Policy


class PolicyService(PolicyPort):
    def __init__(self) -> None:
        self._policies: dict[str, Policy] = {}

    def register(
        self,
        policy_id: str,
        effective_from: date,
        effective_to: date | None = None,
        enabled: bool = True,
        condition: Mapping[str, str] | None = None,
    ) -> None:
        self._policies[policy_id] = Policy(
            policy_id=policy_id,
            effective_from=effective_from,
            effective_to=effective_to,
            enabled=enabled,
            condition=dict(condition or {}),
        )

    def evaluate(self, policy_id: str, on: date, facts: Mapping[str, object]) -> bool:
        policy = self._policies.get(policy_id)
        if policy is None:
            msg = f"policy {policy_id!r} is not defined"
            raise PolicyError(msg)
        return policy.is_effective_on(on) and policy.matches(facts)


__all__ = ["PolicyService"]
