"""Authorization application service (contract section 35: *who* → Capability).

``check`` is driven entirely by role→capability data and role assignments: a
subject holds roles, each role grants capabilities, and each assignment is
scoped. A capability is allowed only when some assignment both grants it and
covers the requested scope.
"""

from __future__ import annotations

from collections.abc import Iterable

from atlas_sdk import CapabilityId, NotFoundError, Scope
from atlas_sdk.context import AuthorizationPort

from ..domain.role import DEFAULT_ROLE_CATALOG, Role, RoleAssignment
from ..domain.scope import covers


class AuthorizationService(AuthorizationPort):
    def __init__(
        self,
        role_catalog: Iterable[Role] = DEFAULT_ROLE_CATALOG,
    ) -> None:
        self._roles: dict[str, Role] = {role.role_id: role for role in role_catalog}
        self._assignments: list[RoleAssignment] = []

    @property
    def roles(self) -> dict[str, Role]:
        return self._roles

    @property
    def assignments(self) -> list[RoleAssignment]:
        return list(self._assignments)

    def grant(self, subject_id: str, role: str, scope: Scope) -> None:
        if role not in self._roles:
            msg = f"unknown role {role!r}"
            raise NotFoundError(msg, kind="role", key=role)
        self._assignments.append(
            RoleAssignment(subject_id=subject_id, role_id=role, scope=scope),
        )

    def register_role(
        self,
        role_id: str,
        name: str,
        capabilities: frozenset[CapabilityId],
    ) -> None:
        self._roles[role_id] = Role(role_id=role_id, name=name, capabilities=capabilities)

    def check(self, capability: CapabilityId, scope: Scope, subject_id: str) -> bool:
        for assignment in self._assignments:
            if assignment.subject_id != subject_id:
                continue
            if not covers(assignment.scope, scope):
                continue
            granted = self._roles[assignment.role_id].capabilities
            if capability in granted:
                return True
        return False


__all__ = ["AuthorizationService"]
