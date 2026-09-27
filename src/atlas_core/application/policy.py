"""Effective-dated, Core-owned authorization policy rules."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from atlas_sdk import AuthorizationError, CapabilityId, Channel, ExecutionHandle, Scope
from atlas_sdk.context import PolicyPort

from ..domain.execution import ExecutionFacts
from ..domain.policy import Policy
from .unit_of_work import UnitOfWorkPort


class PolicyService(PolicyPort):
    """Resolve policy only from Core-persisted canonical execution facts."""

    def __init__(
        self,
        uow: UnitOfWorkPort | None = None,
        *,
        _shared: PolicyService | None = None,
    ) -> None:
        self._uow = uow
        if _shared is None:
            self._policies: dict[str, Policy] = {}
            self._rules: dict[tuple[str | None, str | None, str | None], str] = {}
        else:
            # Each UoW view owns an immutable-by-convention snapshot.  A
            # refresh never mutates the catalogue shared by another decision.
            self._policies = dict(_shared._policies)
            self._rules = dict(_shared._rules)
        if uow is not None:
            for persisted in uow.policies.list():
                self._policies[persisted.policy_id] = persisted
                self._rules[(persisted.capability, persisted.action, persisted.channel)] = (
                    persisted.policy_id
                )

    def refresh(self) -> None:
        """Reload Core policy rows before a public decision."""
        if self._uow is None:
            return
        self._policies.clear()
        self._rules.clear()
        for persisted in self._uow.policies.list():
            self._policies[persisted.policy_id] = persisted
            self._rules[(persisted.capability, persisted.action, persisted.channel)] = (
                persisted.policy_id
            )

    def bind_uow(self, uow: UnitOfWorkPort) -> PolicyService:
        return PolicyService(uow=uow, _shared=self)

    def register(
        self,
        policy_id: str,
        effective_from: date,
        effective_to: date | None = None,
        enabled: bool = True,
        condition: Mapping[str, str] | None = None,
        *,
        capability: str | None = None,
        action: str | None = None,
        channel: str | Channel | None = None,
    ) -> None:
        """Register a rule through Core management, never PluginContext."""
        channel_value = None if channel is None else str(getattr(channel, "value", channel))
        policy = Policy(
            policy_id=policy_id,
            effective_from=effective_from,
            effective_to=effective_to,
            enabled=enabled,
            condition=dict(condition or {}),
            capability=capability,
            action=action,
            channel=channel_value,
        )
        self._policies[policy_id] = policy
        self._rules[(capability, action, channel_value)] = policy_id
        if self._uow is not None:
            self._uow.policies.upsert(policy)

    def register_default(self, capability: str, channel: Channel = Channel.WEB) -> None:
        key = (capability, "*", channel.value)
        policy_id = f"default.{capability}.{channel.value}"
        if key in self._rules and (
            self._uow is None or self._uow.policies.get(policy_id) is not None
        ):
            return
        self.register(
            f"default.{capability}.{channel.value}",
            date.min,
            capability=capability,
            action="*",
            channel=channel,
        )

    def evaluate(self, facts: ExecutionFacts, capability: CapabilityId) -> bool:
        policy = self._resolve(facts, capability)
        if policy is None or not policy.is_effective_on(date.today()):
            return False
        policy_facts = self._facts(facts, capability)
        policy_facts.pop("confirmation_required", None)
        return policy.matches(policy_facts)

    def requires_confirmation(self, facts: ExecutionFacts, capability: CapabilityId) -> bool:
        policy = self._resolve(facts, capability)
        return bool(policy and policy.condition.get("confirmation_required") == "true")

    def _resolve(self, facts: ExecutionFacts, capability_id: CapabilityId) -> Policy | None:
        capability = str(capability_id)
        channel = facts.channel.value
        candidates = (
            (capability, facts.action, channel),
            (capability, "*", channel),
            (capability, facts.action, None),
            (capability, "*", None),
            (None, None, None),
        )
        for key in candidates:
            policy_id = self._rules.get(key)
            if policy_id is not None:
                return self._policies.get(policy_id)
        return None

    @staticmethod
    def _facts(facts: ExecutionFacts, capability: CapabilityId) -> dict[str, object]:
        """Build facts from Core state; payload policy context cannot override them."""
        result: dict[str, object] = {
            "principal_id": facts.principal_id,
            "identity_id": facts.identity_id,
            "capability": str(capability),
            "channel": facts.channel.value,
            "action": facts.action,
            "resource_id": facts.resource_id,
            "organization_id": facts.scope.organization_id,
            "workplace_id": facts.scope.workplace_id,
            "scope_principal_id": facts.scope.principal_id,
        }
        for name, value in facts.policy_context.items():
            if name not in result:
                result[name] = value
        return result


class ReadOnlyPolicyAdapter:
    """Plugin-safe policy view; registration and fact resolution stay in Core."""

    def __init__(self, authorization: object) -> None:
        self._authorization = authorization

    def evaluate(
        self,
        handle: ExecutionHandle,
        capability: CapabilityId,
        requested_scope: Scope,
    ) -> bool:
        evaluator = getattr(self._authorization, "_evaluate_policy", None)
        if evaluator is None:
            return False
        try:
            return bool(evaluator(handle, capability, requested_scope))
        except AuthorizationError:
            return False


__all__ = ["PolicyService", "ReadOnlyPolicyAdapter"]
