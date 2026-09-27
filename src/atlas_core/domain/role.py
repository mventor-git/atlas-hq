"""Roles and the capability catalogue.

Authorization is data-driven (contract section 35: *who* may perform an action
→ Capability). A :class:`Role` bundles capabilities; a :class:`RoleAssignment`
grants a role to a subject within a scope. Nothing here is hard-coded per
request — the catalogue is plain data the authorization service reads.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

from atlas_sdk import CapabilityId, CapabilityKind, Scope

from .identifiers import new_id

# --- capability catalogue -------------------------------------------------

PEOPLE_EMPLOYEE_CREATE = CapabilityId("people.employee.create")
PEOPLE_EMPLOYEE_READ = CapabilityId("people.employee.read")
ORGANIZATION_MANAGE = CapabilityId("organization.manage")
JOBS_MANAGE = CapabilityId("jobs.manage")
ASSIGNMENT_MANAGE = CapabilityId("assignment.manage")
AUDIT_READ = CapabilityId("audit.read")
POLICY_EVALUATE = CapabilityId("policy.evaluate")
PLUGIN_ADMIN = CapabilityId("plugin.admin")
ASSISTANT_USE = CapabilityId("assistant.use")
#: The Core-owned gate for administering principals' grants, role assignments,
#: and the management console's views of them (contract §38.3). It is declared
#: and seeded like any other Core capability and is in no role: a principal must
#: be granted it explicitly before any channel's management surface answers.
AUTHORIZATION_MANAGE = CapabilityId("authorization.manage")

CORE_CAPABILITY_KINDS: Mapping[CapabilityId, CapabilityKind] = {
    PEOPLE_EMPLOYEE_CREATE: CapabilityKind.MANAGE,
    PEOPLE_EMPLOYEE_READ: CapabilityKind.VIEW,
    ORGANIZATION_MANAGE: CapabilityKind.MANAGE,
    JOBS_MANAGE: CapabilityKind.MANAGE,
    ASSIGNMENT_MANAGE: CapabilityKind.MANAGE,
    AUDIT_READ: CapabilityKind.VIEW,
    POLICY_EVALUATE: CapabilityKind.MANAGE,
    PLUGIN_ADMIN: CapabilityKind.MANAGE,
    ASSISTANT_USE: CapabilityKind.VIEW,
    AUTHORIZATION_MANAGE: CapabilityKind.MANAGE,
}


class RoleId(StrEnum):
    """Well-known platform roles. Custom roles are registered at runtime."""

    HR_ADMIN = "role.hr_admin"
    MANAGER = "role.manager"
    EMPLOYEE = "role.employee"
    PLATFORM = "role.platform"


@dataclass(frozen=True)
class Role:
    role_id: str
    name: str
    capabilities: frozenset[CapabilityId] = field(default_factory=frozenset)
    capability_kinds: Mapping[CapabilityId, CapabilityKind] = field(default_factory=dict)
    active: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    owner_plugin_id: str = "core"


DEFAULT_ROLE_CATALOG: tuple[Role, ...] = (
    Role(
        role_id=RoleId.HR_ADMIN,
        name="HR Administrator",
        capabilities=frozenset(
            {
                PEOPLE_EMPLOYEE_CREATE,
                PEOPLE_EMPLOYEE_READ,
                ORGANIZATION_MANAGE,
                JOBS_MANAGE,
                ASSIGNMENT_MANAGE,
                AUDIT_READ,
                POLICY_EVALUATE,
            },
        ),
    ),
    Role(
        role_id=RoleId.MANAGER,
        name="Manager",
        capabilities=frozenset({PEOPLE_EMPLOYEE_READ, ASSIGNMENT_MANAGE}),
    ),
    Role(
        role_id=RoleId.EMPLOYEE,
        name="Employee",
        capabilities=frozenset({PEOPLE_EMPLOYEE_READ}),
    ),
    Role(
        role_id=RoleId.PLATFORM,
        name="Platform",
        capabilities=frozenset({PLUGIN_ADMIN, POLICY_EVALUATE, AUDIT_READ}),
    ),
)


@dataclass(frozen=True)
class RoleAssignment:
    """A principal holding a role within a scope."""

    role_assignment_id: str = field(default_factory=lambda: new_id("rasg"))
    subject_id: str = ""
    role_id: str = ""
    scope: Scope = field(default_factory=Scope)
    active: bool = True
    audit_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def principal_id(self) -> str:
        return self.subject_id


@dataclass(frozen=True)
class Capability:
    """Core-owned capability metadata; declaration is not a user grant."""

    capability_id: CapabilityId
    kind: CapabilityKind = CapabilityKind.VIEW
    name: str = ""
    active: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    provider_id: str = "core"


@dataclass(frozen=True)
class Principal:
    """A channel-neutral authenticated account."""

    principal_id: str
    display_name: str = ""
    active: bool = True
    metadata: Mapping[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class PrincipalIdentity:
    """A channel identity which is inert until linked to a principal."""

    identity_id: str
    channel: str
    external_id: str
    principal_id: str | None = None
    trusted: bool = False
    active: bool = False
    linked_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class CapabilityGrant:
    """An explicit, revocable grant of one capability to one principal."""

    grant_id: str = field(default_factory=lambda: new_id("cgr"))
    principal_id: str = ""
    capability_id: CapabilityId = CapabilityId("")
    scope: Scope = field(default_factory=Scope)
    active: bool = True
    audit_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class Confirmation:
    """A typed, one-time Core confirmation for a scoped action."""

    confirmation_id: str = field(default_factory=lambda: new_id("conf"))
    principal_id: str = ""
    action: str = ""
    scope: Scope = field(default_factory=Scope)
    capability_id: CapabilityId = CapabilityId("")
    channel: str = "web"
    resource_id: str | None = None
    active: bool = True
    used_at: datetime | None = None
    audit_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class EffectivePermissions:
    """The server-side union used by every channel."""

    principal_id: str
    scope: Scope
    capabilities: frozenset[CapabilityId]
    role_ids: frozenset[str] = field(default_factory=frozenset)
    direct_capability_ids: frozenset[CapabilityId] = field(default_factory=frozenset)

    def __contains__(self, capability: object) -> bool:
        return capability in self.capabilities

    def __iter__(self):
        return iter(self.capabilities)

    def __len__(self) -> int:
        return len(self.capabilities)


@dataclass(frozen=True)
class CapabilityGrantState:
    """One capability's grant state for one principal in one scope.

    ``direct`` is the explicit audited grant; ``role_ids`` are the roles that
    also carry the capability at that scope. Together they are the capability's
    sources, which is what a management view needs to explain why unticking a
    box did not remove the permission.
    """

    capability_id: CapabilityId
    direct: bool = False
    role_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RoleAssignmentState:
    """Whether a principal holds a role in the queried scope."""

    role_id: str
    assigned: bool = False


@dataclass(frozen=True)
class GrantState:
    """The whole grant picture for one principal in one scope.

    Read-only Core state for a management view. It reports what is stored and
    what the server therefore enforces; it never grants anything, and the
    server rechecks authorization on the mutation regardless of what it says.
    """

    principal_id: str
    scope: Scope
    capabilities: tuple[CapabilityGrantState, ...] = ()
    roles: tuple[RoleAssignmentState, ...] = ()
    effective_capability_ids: frozenset[CapabilityId] = field(default_factory=frozenset)


# Concise aliases for callers that use the authorization vocabulary.
EffectiveAuthorization = EffectivePermissions
Identity = PrincipalIdentity


__all__ = [
    "ASSIGNMENT_MANAGE",
    "ASSISTANT_USE",
    "AUDIT_READ",
    "AUTHORIZATION_MANAGE",
    "Capability",
    "CapabilityGrant",
    "CapabilityGrantState",
    "CapabilityKind",
    "CORE_CAPABILITY_KINDS",
    "Confirmation",
    "DEFAULT_ROLE_CATALOG",
    "EffectiveAuthorization",
    "EffectivePermissions",
    "GrantState",
    "Identity",
    "JOBS_MANAGE",
    "ORGANIZATION_MANAGE",
    "PEOPLE_EMPLOYEE_CREATE",
    "PEOPLE_EMPLOYEE_READ",
    "PLUGIN_ADMIN",
    "POLICY_EVALUATE",
    "Principal",
    "PrincipalIdentity",
    "Role",
    "RoleAssignment",
    "RoleAssignmentState",
    "RoleId",
]
