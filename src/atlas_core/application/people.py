"""People application service with mandatory handle-bound authorization."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlas_sdk import (
    AuthorizationError,
    CapabilityId,
    DomainEvent,
    DuplicateError,
    EventId,
    EventPublisherPort,
    ExecutionHandle,
    Scope,
)
from atlas_sdk import Employee as SdkEmployee
from atlas_sdk.context import PeoplePort

from ..domain.employee import Employee, EmployeeStatus, Person
from ..domain.execution import ExecutionFacts
from ..domain.identifiers import EmployeeId, OrganizationId
from ..domain.role import PEOPLE_EMPLOYEE_CREATE, PEOPLE_EMPLOYEE_READ
from .execution_guard import authorization_for_uow, require_execution_handle
from .repositories import EmployeeRepositoryPort
from .unit_of_work import UnitOfWorkPort

if TYPE_CHECKING:
    from .authorization import AuthorizationService
    from .execution import ExecutionHandleResolver

EMPLOYEE_CREATED = EventId("employee.created")


def _to_read_model(employee: Employee) -> SdkEmployee:
    return SdkEmployee(
        employee_id=employee.employee_id,
        full_name=employee.full_name,
        employee_number=employee.employee_number,
        organization_id=employee.organization_id,
        status=employee.status.value,
    )


class PeopleService(PeoplePort):
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
        capability: CapabilityId,
        scope: Scope | None,
    ) -> ExecutionFacts | None:
        raw_facts = require_execution_handle(
            handle,
            scope,
            resolver=self._resolver.resolve if self._resolver is not None else None,
        )
        facts = raw_facts if isinstance(raw_facts, ExecutionFacts) else None
        effective_scope = scope or (facts.scope if facts is not None else Scope())
        if self._authorization is not None:
            decision = self._authorization.authorize(handle, capability, effective_scope)
            if not decision.allowed:
                raise AuthorizationError(f"people operation denied: {decision.code}")
        return facts

    @property
    def repository(self) -> EmployeeRepositoryPort:
        return self._uow.employees

    def create_employee(
        self,
        full_name: str,
        employee_number: str,
        organization_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> SdkEmployee:
        self._check(
            execution_handle,
            PEOPLE_EMPLOYEE_CREATE,
            Scope(organization_id=organization_id),
        )
        if not full_name.strip():
            raise ValueError("full_name is required")
        if self._uow.employees.find_by_number(employee_number) is not None:
            raise DuplicateError(f"employee_number {employee_number!r} already exists")
        employee = Employee(
            person=Person(full_name=full_name),
            employee_number=employee_number,
            organization_id=OrganizationId(organization_id),
            status=EmployeeStatus.ACTIVE,
        )
        self._uow.employees.add(employee)
        self._publisher.publish(
            DomainEvent(
                event_id=EMPLOYEE_CREATED,
                payload={
                    "employee_id": employee.employee_id,
                    "employee_number": employee.employee_number,
                    "organization_id": employee.organization_id,
                    "full_name": employee.full_name,
                },
            ),
            execution_handle=execution_handle,
        )
        return _to_read_model(employee)

    def get_employee(
        self,
        employee_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> SdkEmployee | None:
        self._check(execution_handle, PEOPLE_EMPLOYEE_READ, None)
        found = self._uow.employees.get(EmployeeId(employee_id))
        if found is not None:
            self._check(
                execution_handle, PEOPLE_EMPLOYEE_READ, Scope(organization_id=found.organization_id)
            )
        return _to_read_model(found) if found else None

    def list_employees(
        self,
        organization_id: str | None = None,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[SdkEmployee]:
        scope = None if organization_id is None else Scope(organization_id=organization_id)
        self._check(execution_handle, PEOPLE_EMPLOYEE_READ, scope)
        org = None if organization_id is None else OrganizationId(organization_id)
        return [_to_read_model(e) for e in self._uow.employees.all(org)]


__all__ = ["EMPLOYEE_CREATED", "PeopleService"]
