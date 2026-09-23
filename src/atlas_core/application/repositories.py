"""Repository ports: the persistence seam (contract section 22).

Application services talk to these ports; the SQLite adapters in
``atlas_core.infrastructure.persistence`` implement them. A Postgres adapter can
swap in behind the same ports without touching a single service — that is the
entire point of the seam.
"""

from __future__ import annotations

from typing import Protocol

from atlas_sdk import EventEnvelope

from ..domain.assignment import Assignment
from ..domain.audit import AuditRecord
from ..domain.employee import Employee
from ..domain.identifiers import (
    AssignmentId,
    EmployeeId,
    JobId,
    OrganizationId,
)
from ..domain.job import Job
from ..domain.organization import Organization, Workplace


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

    def all(
        self,
        organization_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditRecord]: ...


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
    "EmployeeRepositoryPort",
    "JobRepositoryPort",
    "OrganizationRepositoryPort",
    "OutboxRepositoryPort",
    "WorkplaceRepositoryPort",
]
