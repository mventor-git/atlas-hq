"""Repository ports: the persistence seam (contract section 22).

Application services talk to these ports; the PostgreSQL adapter in
``atlas_core.infrastructure.persistence`` implements them. The seam keeps
application services independent of SQLAlchemy details.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from atlas_sdk import CapabilityId, EventEnvelope, Scope

from ..domain.assignment import Assignment
from ..domain.audit import AuditRecord
from ..domain.employee import Employee
from ..domain.execution import PersistedExecution
from ..domain.identifiers import (
    AssignmentId,
    EmployeeId,
    JobId,
    OrganizationId,
)
from ..domain.job import Job
from ..domain.organization import Organization, Workplace
from ..domain.policy import Policy
from ..domain.role import (
    Capability,
    CapabilityGrant,
    Confirmation,
    Principal,
    PrincipalIdentity,
    Role,
    RoleAssignment,
)


class EmployeeRepositoryPort(Protocol):
    def add(self, employee: Employee) -> None: ...
    def get(self, employee_id: EmployeeId) -> Employee | None: ...
    def all(self, organization_id: OrganizationId | None = None) -> list[Employee]: ...
    def find_by_number(self, employee_number: str) -> Employee | None: ...


class OrganizationRepositoryPort(Protocol):
    def add(self, organization: Organization) -> None: ...
    def get(self, organization_id: OrganizationId) -> Organization | None: ...
    def get_by_code(self, code: str) -> Organization | None: ...
    def all(self) -> list[Organization]: ...


class WorkplaceRepositoryPort(Protocol):
    def add(self, workplace: Workplace) -> None: ...
    def get(self, workplace_id: str) -> Workplace | None: ...
    def all(self, organization_id: OrganizationId | None = None) -> list[Workplace]: ...


class JobRepositoryPort(Protocol):
    def add(self, job: Job) -> None: ...
    def get(self, job_id: JobId) -> Job | None: ...
    def all(self, organization_id: OrganizationId | None = None) -> list[Job]: ...


class AssignmentRepositoryPort(Protocol):
    def add(self, assignment: Assignment) -> None: ...
    def get(self, assignment_id: AssignmentId) -> Assignment | None: ...
    def all_for_employee(self, employee_id: EmployeeId) -> list[Assignment]: ...
    def all(self, organization_id: OrganizationId | None = None) -> list[Assignment]: ...


class AuditRepositoryPort(Protocol):
    def append(self, record: AuditRecord) -> None:
        """Insert one audit record. Append-only: there is no update or delete."""

    def get(self, audit_id: str) -> AuditRecord | None:
        """Read one record without exposing mutation operations."""
        ...

    def all(
        self,
        organization_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditRecord]: ...


class ExecutionRepositoryPort(Protocol):
    """Persistent Core-only store for opaque execution handles."""

    def add(self, execution: PersistedExecution) -> None: ...
    def get(self, token_hash: str) -> PersistedExecution | None: ...
    def revoke(self, token_hash: str) -> bool: ...
    def expire_due(self, now: datetime) -> int: ...


class PolicyRepositoryPort(Protocol):
    """Persistent Core-owned policy state."""

    def get(self, policy_id: str) -> Policy | None: ...
    def list(self) -> list[Policy]: ...
    def upsert(self, policy: Policy) -> None: ...


class AuthorizationRepositoryPort(Protocol):
    """The single Core-owned authorization persistence seam."""

    def get_principal(self, principal_id: str) -> Principal | None: ...
    def add_principal(self, principal: Principal) -> None: ...
    def list_principals(self) -> list[Principal]: ...

    def get_identity(self, identity_id: str) -> PrincipalIdentity | None: ...
    def find_identity(self, channel: str, external_id: str) -> PrincipalIdentity | None: ...
    def list_identities(self) -> list[PrincipalIdentity]: ...
    def add_identity(self, identity: PrincipalIdentity) -> None: ...
    def update_identity(self, identity: PrincipalIdentity) -> None: ...
    def link_identity_once(
        self,
        identity_id: str,
        principal_id: str,
    ) -> PrincipalIdentity | None: ...

    def get_capability(self, capability_id: CapabilityId) -> Capability | None: ...
    def upsert_capability(self, capability: Capability) -> None: ...
    def list_capabilities(self, *, active_only: bool = True) -> list[Capability]: ...

    def get_role(self, role_id: str) -> Role | None: ...
    def upsert_role(self, role: Role) -> None: ...
    def list_roles(self, *, active_only: bool = True) -> list[Role]: ...

    def add_assignment(self, assignment: RoleAssignment) -> None: ...
    def revoke_assignment(
        self,
        principal_id: str,
        role_id: str,
        scope: Scope,
    ) -> list[RoleAssignment]: ...
    def assignments_for(self, principal_id: str) -> list[RoleAssignment]: ...

    def add_grant(self, grant: CapabilityGrant) -> None: ...
    def revoke_grant(
        self,
        principal_id: str,
        capability_id: CapabilityId,
        scope: Scope,
    ) -> list[CapabilityGrant]: ...
    def grants_for(self, principal_id: str) -> list[CapabilityGrant]: ...

    def add_confirmation(self, confirmation: Confirmation) -> None: ...
    def get_confirmation(self, confirmation_id: str) -> Confirmation | None: ...
    def consume_confirmation(
        self,
        confirmation_id: str,
        *,
        principal_id: str | None = None,
        capability_id: CapabilityId | None = None,
        action: str | None = None,
        resource_id: str | None = None,
        channel: str | None = None,
        scope: Scope | None = None,
    ) -> Confirmation | None: ...


class OutboxRepositoryPort(Protocol):
    def append(self, envelope: EventEnvelope) -> None:
        """Store an envelope in the current transaction."""

    def pending(self, limit: int = 100) -> list[EventEnvelope]:
        """Envelopes stored by committed transactions but not yet dispatched."""
        ...

    def mark_dispatched(self, envelope_id: str) -> None: ...
    def record_failure(self, envelope_id: str, error: str) -> None: ...


__all__ = [
    "AssignmentRepositoryPort",
    "AuditRepositoryPort",
    "AuthorizationRepositoryPort",
    "EmployeeRepositoryPort",
    "ExecutionRepositoryPort",
    "JobRepositoryPort",
    "OrganizationRepositoryPort",
    "OutboxRepositoryPort",
    "PolicyRepositoryPort",
    "WorkplaceRepositoryPort",
]
