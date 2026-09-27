"""Assignments application service with mandatory handle-bound authorization."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from atlas_sdk import (
    Assignment as SdkAssignment,
)
from atlas_sdk import (
    AuthorizationError,
    DomainEvent,
    EventId,
    EventPublisherPort,
    ExecutionHandle,
    NotFoundError,
    Scope,
)
from atlas_sdk.context import AssignmentPort

from ..domain.assignment import Assignment, AssignmentStatus
from ..domain.execution import ExecutionFacts
from ..domain.identifiers import AssignmentId, EmployeeId, JobId, WorkplaceId
from ..domain.role import ASSIGNMENT_MANAGE, PEOPLE_EMPLOYEE_READ
from .execution_guard import authorization_for_uow, require_execution_handle
from .unit_of_work import UnitOfWorkPort

if TYPE_CHECKING:
    from .authorization import AuthorizationService
    from .execution import ExecutionHandleResolver

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
    def __init__(
        self,
        uow: UnitOfWorkPort,
        publisher: EventPublisherPort,
        *,
        resolver: ExecutionHandleResolver | None = None,
        authorization: AuthorizationService | None = None,
    ) -> None:
        self._uow = uow
        self._publisher = publisher
        if resolver is None or authorization is None:
            bound = authorization_for_uow(uow)
            resolver = resolver or bound._handle_resolver  # type: ignore[attr-defined]
            authorization = authorization or bound
        self._resolver = resolver
        self._authorization = authorization

    def _check(
        self,
        handle: ExecutionHandle,
        scope: Scope,
        capability=ASSIGNMENT_MANAGE,
    ) -> ExecutionFacts | None:
        facts = require_execution_handle(
            handle,
            scope,
            resolver=self._resolver.resolve if self._resolver is not None else None,
        )
        if not isinstance(facts, ExecutionFacts):
            return None
        if self._authorization is not None:
            decision = self._authorization.authorize(handle, capability, scope)
            if not decision.allowed:
                raise AuthorizationError(f"assignment operation denied: {decision.code}")
        return facts

    def assign(
        self,
        employee_id: str,
        job_id: str,
        workplace_id: str | None = None,
        start_date: date | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> SdkAssignment:
        employee = self._uow.employees.get(EmployeeId(employee_id))
        if employee is None:
            raise NotFoundError(
                f"employee {employee_id!r} does not exist", kind="employee", key=employee_id
            )
        job = self._uow.jobs.get(JobId(job_id))
        if job is None:
            raise NotFoundError(f"job {job_id!r} does not exist", kind="job", key=job_id)
        self._check(execution_handle, Scope(organization_id=job.organization_id))
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
            execution_handle=execution_handle,
        )
        return _to_read_model(assignment)

    def get_assignment(
        self,
        assignment_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> SdkAssignment | None:
        found = self._uow.assignments.get(AssignmentId(assignment_id))
        self._check(
            execution_handle,
            Scope(organization_id=found.organization_id) if found is not None else Scope(),
            PEOPLE_EMPLOYEE_READ,
        )
        return _to_read_model(found) if found else None

    def assignments_for(
        self,
        employee_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[SdkAssignment]:
        require_execution_handle(
            execution_handle,
            resolver=self._resolver.resolve if self._resolver is not None else None,
        )
        assignments = self._uow.assignments.all_for_employee(EmployeeId(employee_id))
        for assignment in assignments:
            self._check(
                execution_handle,
                Scope(organization_id=assignment.organization_id),
                PEOPLE_EMPLOYEE_READ,
            )
        return [_to_read_model(a) for a in assignments]


__all__ = ["EMPLOYEE_ASSIGNED", "AssignmentsService"]
