"""People application service (contract section 2: People / Employee Identity).

Creates employees, reads them back through the published read model, and
publishes ``employee.created`` in the same transaction as the state change.
"""

from __future__ import annotations

from atlas_sdk import (
    DomainEvent,
    DuplicateError,
    EventId,
    EventPublisherPort,
)
from atlas_sdk import (
    Employee as SdkEmployee,
)
from atlas_sdk.context import PeoplePort

from ..domain.employee import Employee, EmployeeStatus, Person
from ..domain.identifiers import EmployeeId, OrganizationId
from .repositories import EmployeeRepositoryPort
from .unit_of_work import UnitOfWorkPort

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
    """The people-facing half of the core's identity services."""

    def __init__(self, uow: UnitOfWorkPort, publisher: EventPublisherPort) -> None:
        self._uow = uow
        self._publisher = publisher

    @property
    def repository(self) -> EmployeeRepositoryPort:
        return self._uow.employees

    def create_employee(
        self,
        full_name: str,
        employee_number: str,
        organization_id: str,
    ) -> SdkEmployee:
        if not full_name.strip():
            msg = "full_name is required"
            raise ValueError(msg)
        if self._uow.employees.find_by_number(employee_number) is not None:
            msg = f"employee_number {employee_number!r} already exists"
            raise DuplicateError(msg)

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
        )
        return _to_read_model(employee)

    def get_employee(self, employee_id: str) -> SdkEmployee | None:
        found = self._uow.employees.get(EmployeeId(employee_id))
        return _to_read_model(found) if found else None

    def list_employees(self, organization_id: str | None = None) -> list[SdkEmployee]:
        org = None if organization_id is None else OrganizationId(organization_id)
        return [_to_read_model(e) for e in self._uow.employees.all(org)]


__all__ = ["EMPLOYEE_CREATED", "PeopleService"]
