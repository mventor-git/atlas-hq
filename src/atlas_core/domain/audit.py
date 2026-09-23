"""Audit records — append-only historical accountability (contract section 35).

An audit record is immutable once written and is never deleted; the repository
layer enforces insert-only access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .identifiers import new_id


@dataclass(frozen=True)
class AuditRecord:
    audit_id: str = field(default_factory=lambda: new_id("aud"))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    actor: str = ""
    action: str = ""
    organization_id: str | None = None
    workplace_id: str | None = None
    details: dict[str, object] = field(default_factory=dict)


__all__ = ["AuditRecord"]
