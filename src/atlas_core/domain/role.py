"""Roles and the capability catalogue.

Authorization is data-driven (contract section 35: *who* may perform an action
→ Capability). A :class:`Role` bundles capabilities; a :class:`RoleAssignment`
grants a role to a subject within a scope. Nothing here is hard-coded per
request — the catalogue is plain data the authorization service reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from atlas_sdk import CapabilityId, Scope

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
    """A subject holding a role within a scope."""

    role_assignment_id: str = field(default_factory=lambda: new_id("rasg"))
    subject_id: str = ""
    role_id: str = ""
    scope: Scope = field(default_factory=Scope)


__all__ = [
    "ASSIGNMENT_MANAGE",
    "AUDIT_READ",
    "DEFAULT_ROLE_CATALOG",
    "JOBS_MANAGE",
    "ORGANIZATION_MANAGE",
    "PEOPLE_EMPLOYEE_CREATE",
    "PEOPLE_EMPLOYEE_READ",
    "PLUGIN_ADMIN",
    "POLICY_EVALUATE",
    "Role",
    "RoleAssignment",
    "RoleId",
]
