"""Core-owned canonical facts for an execution handle.

The SDK handle contains none of these values.  They are persisted and resolved
only inside Core, after which Core evaluates policy and effective permissions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType

from atlas_sdk import CapabilityId, Channel, Scope


@dataclass(frozen=True)
class ExecutionFacts:
    """Canonical facts stored for one issued execution."""

    principal_id: str
    capability_id: CapabilityId
    action: str
    scope: Scope
    channel: Channel
    allowed_capability_ids: frozenset[CapabilityId] = frozenset()
    resource_id: str | None = None
    identity_id: str | None = None
    policy_context: Mapping[str, object] = field(default_factory=dict)
    expires_at: datetime | None = None


@dataclass(frozen=True)
class PersistedExecution:
    """A token hash and its canonical facts; the raw token is never persisted."""

    token_hash: str
    facts: ExecutionFacts
    created_at: datetime
    revoked_at: datetime | None = None


def freeze_policy_context(values: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType(dict(values))


__all__ = ["ExecutionFacts", "PersistedExecution", "freeze_policy_context"]
