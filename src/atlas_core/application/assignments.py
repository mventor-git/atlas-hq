"""Assignments application service (contract section 2: Employee Assignments).

An assignment is the core fact plugins such as attendance and payroll keep
referring back to (``employee.assignment`` in the contract's module examples).
"""

from __future__ import annotations

from datetime import date

from atlas_sdk import (
    Assignment as SdkAssignment,
)
from atlas_sdk import (
    DomainEvent,
    EventId,
    EventPublisherPort,
    NotFoundError,
)
from atlas_sdk.context import AssignmentPort

from ..domain.assignment import Assignment, AssignmentStatus
from ..domain.identifiers import (
    AssignmentId,
    EmployeeId,
    JobId,
    WorkplaceId,
)
from .unit_of_work import UnitOfWorkPort

EMPLOYEE_ASSIGNED = EventId("employee.assigned")


def _to_read_model(assignment: Assignment) -> SdkAssignment:
    return SdkAssignment(
        assignment_id=assignment.assignment_id,
        employee_id=assignment.employee_id,
        job_id=assignment.job_id,
        organization_id=assignment.organization_id,
        workplace_id=assignment.workplace_id,
        status=assignment.status.value,
    )


class AssignmentsService(AssignmentPort):
    def __init__(self, uow: UnitOfWorkPort, publisher: EventPublisherPort) -> None:
        self._uow = uow
        self._publisher = publisher

    def assign(
        self,
        employee_id: str,
        job_id: str,
        workplace_id: str | None = None,
        start_date: date | None = None,
    ) -> SdkAssignment:
        employee = self._uow.employees.get(EmployeeId(employee_id))
        if employee is None:
            msg = f"employee {employee_id!r} does not exist"
            raise NotFoundError(msg, kind="employee", key=employee_id)
        job = self._uow.jobs.get(JobId(job_id))
        if job is None:
            msg = f"job {job_id!r} does not exist"
            raise NotFoundError(msg, kind="job", key=job_id)

        assignment = Assignment(
            employee_id=employee.employee_id,
            job_id=job.job_id,
            organization_id=job.organization_id,
            workplace_id=None if workplace_id is None else WorkplaceId(workplace_id),
            start_date=start_date,
            status=AssignmentStatus.ACTIVE,
        )
        self._uow.assignments.add(assignment)
        self._publisher.publish(
            DomainEvent(
                event_id=EMPLOYEE_ASSIGNED,
                payload={
                    "assignment_id": assignment.assignment_id,
                    "employee_id": assignment.employee_id,
                    "job_id": assignment.job_id,
                    "organization_id": assignment.organization_id,
                    "workplace_id": assignment.workplace_id,
                },
            ),
        )
        return _to_read_model(assignment)

    def get_assignment(self, assignment_id: str) -> SdkAssignment | None:
        found = self._uow.assignments.get(AssignmentId(assignment_id))
        return _to_read_model(found) if found else None

    def assignments_for(self, employee_id: str) -> list[SdkAssignment]:
        return [
            _to_read_model(a)
            for a in self._uow.assignments.all_for_employee(EmployeeId(employee_id))
        ]


__all__ = ["EMPLOYEE_ASSIGNED", "AssignmentsService"]
