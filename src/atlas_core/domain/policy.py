"""Effective-dated policies (contract section 35: a business rule → Policy).

A policy is in effect between ``effective_from`` and ``effective_to`` (inclusive,
open-ended when ``None``) while ``enabled``. Its ``condition`` is a set of
``fact name → expected value`` pairs; a request satisfies the policy when every
declared fact matches. Deterministic, introspectable, no magic (section 14).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Policy:
    policy_id: str = ""
    effective_from: date = date.min
    effective_to: date | None = None
    enabled: bool = True
    condition: Mapping[str, str] = field(default_factory=dict)

    def is_effective_on(self, on: date) -> bool:
        if not self.enabled:
            return False
        if on < self.effective_from:
            return False
        return self.effective_to is None or on <= self.effective_to

    def matches(self, facts: Mapping[str, object]) -> bool:
        return all(str(facts.get(name)) == expected for name, expected in self.condition.items())


__all__ = ["Policy"]
