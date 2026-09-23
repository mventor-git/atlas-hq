"""Repository adapters behind the ports in ``application/repositories.py``.

Every adapter takes the :class:`~sqlalchemy.orm.Session` of the *current*
unit of work, so a write made through any repository commits or rolls back with
every other write in the same transaction — including an outbox append
(contract section 21).
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from atlas_sdk import DomainEvent, EventEnvelope, EventId

from ...domain.assignment import Assignment, AssignmentStatus
from ...domain.audit import AuditRecord
from ...domain.employee import Employee, EmployeeStatus, Person
from ...domain.identifiers import (
    AssignmentId,
    EmployeeId,
    JobId,
    OrganizationId,
    WorkplaceId,
)
from ...domain.job import Job, JobStatus
from ...domain.organization import Organization, Workplace, WorkplaceType
from .orm import (
    AssignmentORM,
    AuditORM,
    EmployeeORM,
    JobORM,
    OrganizationORM,
    OutboxORM,
    WorkplaceORM,
)


class EmployeeRepository:
    """Adapts :class:`~atlas_core.application.repositories.EmployeeRepositoryPort`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, employee: Employee) -> None:
        self._session.add(
            EmployeeORM(
                employee_id=employee.employee_id,
                person_id=employee.person.person_id,
                full_name=employee.person.full_name,
                email=employee.person.email,
                phone=employee.person.phone,
                employee_number=employee.employee_number,
                organization_id=employee.organization_id,
                status=employee.status.value,
                hired_on=employee.hired_on,
            ),
        )

    def get(self, employee_id: EmployeeId) -> Employee | None:
        row = self._session.get(EmployeeORM, employee_id)
        return _to_employee(row) if row else None

    def all(self, organization_id: OrganizationId | None = None) -> list[Employee]:
        stmt = select(EmployeeORM)
        if organization_id is not None:
            stmt = stmt.where(EmployeeORM.organization_id == organization_id)
        return [_to_employee(row) for row in self._session.scalars(stmt)]

    def find_by_number(self, employee_number: str) -> Employee | None:
        stmt = select(EmployeeORM).where(EmployeeORM.employee_number == employee_number)
        row = self._session.scalars(stmt).first()
        return _to_employee(row) if row else None


class OrganizationRepository:
    """Adapts :class:`~atlas_core.application.repositories.OrganizationRepositoryPort`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, organization: Organization) -> None:
        self._session.add(
            OrganizationORM(
                organization_id=organization.organization_id,
                name=organization.name,
                code=organization.code,
            ),
        )

    def get(self, organization_id: OrganizationId) -> Organization | None:
        row = self._session.get(OrganizationORM, organization_id)
        return _to_organization(row) if row else None

    def get_by_code(self, code: str) -> Organization | None:
        stmt = select(OrganizationORM).where(OrganizationORM.code == code)
        row = self._session.scalars(stmt).first()
        return _to_organization(row) if row else None

    def all(self) -> list[Organization]:
        return [_to_organization(row) for row in self._session.scalars(select(OrganizationORM))]


class WorkplaceRepository:
    """Adapts :class:`~atlas_core.application.repositories.WorkplaceRepositoryPort`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, workplace: Workplace) -> None:
        self._session.add(
            WorkplaceORM(
                workplace_id=workplace.workplace_id,
                organization_id=workplace.organization_id,
                name=workplace.name,
                kind=workplace.kind.value,
            ),
        )

    def get(self, workplace_id: str) -> Workplace | None:
        row = self._session.get(WorkplaceORM, workplace_id)
        return _to_workplace(row) if row else None

    def all(self, organization_id: OrganizationId | None = None) -> list[Workplace]:
        stmt = select(WorkplaceORM)
        if organization_id is not None:
            stmt = stmt.where(WorkplaceORM.organization_id == organization_id)
        return [_to_workplace(row) for row in self._session.scalars(stmt)]


class JobRepository:
    """Adapts :class:`~atlas_core.application.repositories.JobRepositoryPort`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, job: Job) -> None:
        self._session.add(
            JobORM(
                job_id=job.job_id,
                organization_id=job.organization_id,
                title=job.title,
                workplace_id=job.workplace_id,
                status=job.status.value,
            ),
        )

    def get(self, job_id: JobId) -> Job | None:
        row = self._session.get(JobORM, job_id)
        return _to_job(row) if row else None

    def all(self, organization_id: OrganizationId | None = None) -> list[Job]:
        stmt = select(JobORM)
        if organization_id is not None:
            stmt = stmt.where(JobORM.organization_id == organization_id)
        return [_to_job(row) for row in self._session.scalars(stmt)]


class AssignmentRepository:
    """Adapts :class:`~atlas_core.application.repositories.AssignmentRepositoryPort`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, assignment: Assignment) -> None:
        self._session.add(
            AssignmentORM(
                assignment_id=assignment.assignment_id,
                employee_id=assignment.employee_id,
                job_id=assignment.job_id,
                organization_id=assignment.organization_id,
                workplace_id=assignment.workplace_id,
                start_date=assignment.start_date,
                status=assignment.status.value,
            ),
        )

    def get(self, assignment_id: AssignmentId) -> Assignment | None:
        row = self._session.get(AssignmentORM, assignment_id)
        return _to_assignment(row) if row else None

    def all_for_employee(self, employee_id: EmployeeId) -> list[Assignment]:
        stmt = select(AssignmentORM).where(AssignmentORM.employee_id == employee_id)
        return [_to_assignment(row) for row in self._session.scalars(stmt)]

    def all(self, organization_id: OrganizationId | None = None) -> list[Assignment]:
        stmt = select(AssignmentORM)
        if organization_id is not None:
            stmt = stmt.where(AssignmentORM.organization_id == organization_id)
        return [_to_assignment(row) for row in self._session.scalars(stmt)]


class AuditRepository:
    """Adapts :class:`~atlas_core.application.repositories.AuditRepositoryPort`.

    There is intentionally no ``update`` or ``delete``: audit is append-only
    (contract section 35).
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, record: AuditRecord) -> None:
        self._session.add(
            AuditORM(
                audit_id=record.audit_id,
                occurred_at=record.occurred_at,
                actor=record.actor,
                action=record.action,
                organization_id=record.organization_id,
                workplace_id=record.workplace_id,
                details=record.details,
            ),
        )

    def all(
        self,
        organization_id: str | None = None,
        limit: int = 100,
    ) -> list[AuditRecord]:
        stmt = select(AuditORM).order_by(AuditORM.occurred_at.desc(), AuditORM.audit_id.desc())
        if organization_id is not None:
            stmt = stmt.where(AuditORM.organization_id == organization_id)
        stmt = stmt.limit(limit)
        return [_to_audit(row) for row in self._session.scalars(stmt)]


class OutboxRepository:
    """Adapts :class:`~atlas_core.application.repositories.OutboxRepositoryPort`.

    Appends share the caller's transaction. ``pending`` reads only committed
    rows, so nothing that rolled back is ever handed to the dispatcher.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, envelope: EventEnvelope) -> None:
        self._session.add(
            OutboxORM(
                envelope_id=envelope.envelope_id,
                event_id=envelope.event.event_id,
                publisher=envelope.publisher,
                payload=envelope.event.payload,
                created_at=envelope.event.occurred_at,
            ),
        )

    def pending(self, limit: int = 100) -> list[EventEnvelope]:
        stmt = (
            select(OutboxORM)
            .where(OutboxORM.dispatched_at.is_(None))
            .order_by(OutboxORM.created_at, OutboxORM.envelope_id)
            .limit(limit)
        )
        return [_to_envelope(row) for row in self._session.scalars(stmt)]

    def mark_dispatched(self, envelope_id: str) -> None:
        row = self._session.get(OutboxORM, envelope_id)
        if row is not None:
            row.dispatched_at = datetime.now(UTC)

    def record_failure(self, envelope_id: str, error: str) -> None:
        row = self._session.get(OutboxORM, envelope_id)
        if row is not None:
            row.attempts += 1
            row.last_error = error[:1000]


# --- row -> domain --------------------------------------------------------


def _to_employee(row: EmployeeORM) -> Employee:
    return Employee(
        employee_id=EmployeeId(row.employee_id),
        person=Person(
            person_id=row.person_id,
            full_name=row.full_name,
            email=row.email,
            phone=row.phone,
        ),
        employee_number=row.employee_number,
        organization_id=OrganizationId(row.organization_id),
        status=EmployeeStatus(row.status),
        hired_on=row.hired_on,
    )


def _to_organization(row: OrganizationORM) -> Organization:
    return Organization(
        organization_id=OrganizationId(row.organization_id),
        name=row.name,
        code=row.code,
    )


def _to_workplace(row: WorkplaceORM) -> Workplace:
    return Workplace(
        workplace_id=WorkplaceId(row.workplace_id),
        organization_id=OrganizationId(row.organization_id),
        name=row.name,
        kind=WorkplaceType(row.kind),
    )


def _to_job(row: JobORM) -> Job:
    return Job(
        job_id=JobId(row.job_id),
        organization_id=OrganizationId(row.organization_id),
        title=row.title,
        workplace_id=None if row.workplace_id is None else WorkplaceId(row.workplace_id),
        status=JobStatus(row.status),
    )


def _to_assignment(row: AssignmentORM) -> Assignment:
    return Assignment(
        assignment_id=AssignmentId(row.assignment_id),
        employee_id=EmployeeId(row.employee_id),
        job_id=JobId(row.job_id),
        organization_id=OrganizationId(row.organization_id),
        workplace_id=None if row.workplace_id is None else WorkplaceId(row.workplace_id),
        start_date=row.start_date,
        status=AssignmentStatus(row.status),
    )


def _to_audit(row: AuditORM) -> AuditRecord:
    return AuditRecord(
        audit_id=row.audit_id,
        occurred_at=row.occurred_at,
        actor=row.actor,
        action=row.action,
        organization_id=row.organization_id,
        workplace_id=row.workplace_id,
        details=dict(row.details or {}),
    )


def _to_envelope(row: OutboxORM) -> EventEnvelope:
    return EventEnvelope(
        envelope_id=row.envelope_id,
        event=DomainEvent(
            event_id=EventId(row.event_id),
            payload=dict(row.payload or {}),
            occurred_at=row.created_at,
        ),
        publisher=row.publisher,
        created_at=row.created_at,
        dispatched_at=row.dispatched_at,
        attempts=row.attempts,
        last_error=row.last_error,
    )


__all__ = [
    "AssignmentRepository",
    "AuditRepository",
    "EmployeeRepository",
    "JobRepository",
    "OrganizationRepository",
    "OutboxRepository",
    "WorkplaceRepository",
]
