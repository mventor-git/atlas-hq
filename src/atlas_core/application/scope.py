"""Scope application service (contract section 35: *which records* → Scope).

Scope resolution narrows a request to the org/workplace context an actor may
actually see, so a workplace-scoped plugin never silently reads another
workplace's data.
"""

from __future__ import annotations

from atlas_sdk import Scope
from atlas_sdk.context import ScopePort

from ..domain import scope as domain_scope


class ScopeService(ScopePort):
    def resolve(
        self,
        organization_id: str | None,
        workplace_id: str | None = None,
    ) -> Scope:
        return domain_scope.resolve(organization_id, workplace_id)

    def narrow(self, requested: Scope, subject: Scope) -> Scope:
        return domain_scope.narrow(requested, subject)


__all__ = ["ScopeService"]
