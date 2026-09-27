"""People, organization, jobs and assignments with required opaque handles."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from tests.conftest import issue_uow_handle_for_test

from atlas_core.application.assignments import AssignmentsService
from atlas_core.application.jobs import JobsService
from atlas_core.application.organization import OrganizationService
from atlas_core.application.people import PeopleService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.domain.role import (
    ASSIGNMENT_MANAGE,
    JOBS_MANAGE,
    ORGANIZATION_MANAGE,
    PEOPLE_EMPLOYEE_CREATE,
    PEOPLE_EMPLOYEE_READ,
)
from atlas_core.infrastructure.events import OutboxEventPublisher
from atlas_sdk import DuplicateError, NotFoundError, Scope, WorkplaceType


def _people(uow: UnitOfWorkPort) -> PeopleService:
    return PeopleService(uow, OutboxEventPublisher(uow, publisher="test"))


def _assignments(uow: UnitOfWorkPort) -> AssignmentsService:
    return AssignmentsService(uow, OutboxEventPublisher(uow, publisher="test"))


def _handle(
    uow_factory: Callable[[], UnitOfWorkPort],
    capability,
    action: str,
    organization_id: str,
    *,
    resource_id: str | None = None,
):
    return issue_uow_handle_for_test(
        uow_factory,
        capability,
        action,
        Scope(organization_id=organization_id),
        resource_id=resource_id,
    )


def _org_and_employee(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> tuple[str, str]:
    with uow_factory() as uow:
        org_handle = _handle(
            uow_factory,
            ORGANIZATION_MANAGE,
            "organization.create",
            "seed-org",
        )
        # The seed helper scope must match the organization being created.
        org = OrganizationService(uow).create_organization(
            name="Acme",
            code="ACME",
            execution_handle=org_handle,
        )
        employee_handle = _handle(
            uow_factory,
            PEOPLE_EMPLOYEE_CREATE,
            "people.employee.create",
            org.organization_id,
        )
        employee = _people(uow).create_employee(
            full_name="Ada Lovelace",
            employee_number="EMP-1",
            organization_id=org.organization_id,
            execution_handle=employee_handle,
        )
        return org.organization_id, employee.employee_id


def test_create_and_read_back_an_organization(uow_factory) -> None:
    with uow_factory() as uow:
        handle = _handle(uow_factory, ORGANIZATION_MANAGE, "organization.create", "org-a")
        org = OrganizationService(uow).create_organization(
            name="Acme", code="ACME", execution_handle=handle
        )
    with uow_factory() as check:
        found = OrganizationService(check).get_organization(
            org.organization_id,
            execution_handle=_handle(
                uow_factory, ORGANIZATION_MANAGE, "organization.read", org.organization_id
            ),
        )
    assert found is not None
    assert (found.name, found.code) == ("Acme", "ACME")


def test_duplicate_organization_code_is_rejected(uow_factory) -> None:
    with uow_factory() as uow:
        handle = _handle(uow_factory, ORGANIZATION_MANAGE, "organization.create", "org-a")
        OrganizationService(uow).create_organization(
            name="Acme", code="ACME", execution_handle=handle
        )
    with pytest.raises(DuplicateError), uow_factory() as uow2:
        OrganizationService(uow2).create_organization(
            name="Other",
            code="ACME",
            execution_handle=_handle(
                uow_factory, ORGANIZATION_MANAGE, "organization.create", "org-b"
            ),
        )


def test_create_and_read_back_an_employee(uow_factory) -> None:
    _org_id, employee_id = _org_and_employee(uow_factory)
    with uow_factory() as check:
        found = _people(check).get_employee(
            employee_id,
            execution_handle=_handle(
                uow_factory, PEOPLE_EMPLOYEE_READ, "people.employee.read", _org_id
            ),
        )
    assert found is not None
    assert found.full_name == "Ada Lovelace"
    assert found.employee_number == "EMP-1"
    assert found.status == "active"


def test_employees_are_scoped_by_organization(uow_factory) -> None:
    with uow_factory() as uow:
        org_a = OrganizationService(uow).create_organization(
            name="A",
            code="A",
            execution_handle=_handle(uow_factory, ORGANIZATION_MANAGE, "organization.create", "a"),
        )
        org_b = OrganizationService(uow).create_organization(
            name="B",
            code="B",
            execution_handle=_handle(uow_factory, ORGANIZATION_MANAGE, "organization.create", "b"),
        )
        _people(uow).create_employee(
            "Ada",
            "EMP-1",
            org_a.organization_id,
            execution_handle=_handle(
                uow_factory, PEOPLE_EMPLOYEE_CREATE, "people.employee.create", org_a.organization_id
            ),
        )
        _people(uow).create_employee(
            "Grace",
            "EMP-2",
            org_b.organization_id,
            execution_handle=_handle(
                uow_factory, PEOPLE_EMPLOYEE_CREATE, "people.employee.create", org_b.organization_id
            ),
        )
    with uow_factory() as check:
        people = _people(check)
        assert [
            e.employee_number
            for e in people.list_employees(
                org_a.organization_id,
                execution_handle=_handle(
                    uow_factory, PEOPLE_EMPLOYEE_READ, "people.employee.read", org_a.organization_id
                ),
            )
        ] == ["EMP-1"]
        assert [
            e.employee_number
            for e in people.list_employees(
                org_b.organization_id,
                execution_handle=_handle(
                    uow_factory, PEOPLE_EMPLOYEE_READ, "people.employee.read", org_b.organization_id
                ),
            )
        ] == ["EMP-2"]


def test_duplicate_employee_number_is_rejected(uow_factory) -> None:
    org_id, _employee_id = _org_and_employee(uow_factory)
    with pytest.raises(DuplicateError), uow_factory() as uow2:
        _people(uow2).create_employee(
            "Someone Else",
            "EMP-1",
            org_id,
            execution_handle=_handle(
                uow_factory, PEOPLE_EMPLOYEE_CREATE, "people.employee.create", org_id
            ),
        )


def test_an_employee_persists_only_when_committed(uow_factory) -> None:
    with pytest.raises(RuntimeError, match="rollback"), uow_factory() as uow:
        org_handle = _handle(uow_factory, ORGANIZATION_MANAGE, "organization.create", "org-a")
        org = OrganizationService(uow).create_organization(
            name="Acme", code="ACME", execution_handle=org_handle
        )
        _people(uow).create_employee(
            "Ada",
            "EMP-1",
            org.organization_id,
            execution_handle=_handle(
                uow_factory, PEOPLE_EMPLOYEE_CREATE, "people.employee.create", org.organization_id
            ),
        )
        raise RuntimeError("rollback")
    with uow_factory() as check:
        assert (
            _people(check).list_employees(
                execution_handle=_handle(
                    uow_factory, PEOPLE_EMPLOYEE_READ, "people.employee.read", "org-a"
                )
            )
            == []
        )


def test_workplace_kind_round_trips(uow_factory) -> None:
    with uow_factory() as uow:
        org = OrganizationService(uow).create_organization(
            name="Acme",
            code="ACME",
            execution_handle=_handle(
                uow_factory, ORGANIZATION_MANAGE, "organization.create", "org-a"
            ),
        )
        workplace = OrganizationService(uow).add_workplace(
            org.organization_id,
            "North Site",
            kind=WorkplaceType.SITE,
            execution_handle=_handle(
                uow_factory, ORGANIZATION_MANAGE, "organization.workplace.add", org.organization_id
            ),
        )
    with uow_factory() as check:
        found = OrganizationService(check).list_workplaces(
            org.organization_id,
            execution_handle=_handle(
                uow_factory, ORGANIZATION_MANAGE, "organization.workplace.list", org.organization_id
            ),
        )
    assert len(found) == 1
    assert found[0].workplace_id == workplace.workplace_id
    assert found[0].kind == WorkplaceType.SITE


def test_workplace_requires_an_existing_organization(uow_factory) -> None:
    with pytest.raises(NotFoundError), uow_factory() as uow:
        OrganizationService(uow).add_workplace(
            "org-missing",
            "Nowhere",
            execution_handle=_handle(
                uow_factory, ORGANIZATION_MANAGE, "organization.workplace.add", "org-missing"
            ),
        )


def test_create_and_read_back_a_job(uow_factory) -> None:
    with uow_factory() as uow:
        org_id, _employee_id = _org_and_employee(uow_factory)
        job = JobsService(uow).create_job(
            org_id,
            "Foreman",
            execution_handle=_handle(uow_factory, JOBS_MANAGE, "jobs.create", org_id),
        )
    with uow_factory() as check:
        found = JobsService(check).get_job(
            job.job_id,
            execution_handle=_handle(uow_factory, JOBS_MANAGE, "jobs.read", org_id),
        )
    assert found is not None
    assert found.title == "Foreman"
    assert found.status == "open"


def test_jobs_are_scoped_by_organization(uow_factory) -> None:
    with uow_factory() as uow:
        org_a = OrganizationService(uow).create_organization(
            name="A",
            code="A",
            execution_handle=_handle(uow_factory, ORGANIZATION_MANAGE, "organization.create", "a"),
        )
        org_b = OrganizationService(uow).create_organization(
            name="B",
            code="B",
            execution_handle=_handle(uow_factory, ORGANIZATION_MANAGE, "organization.create", "b"),
        )
        JobsService(uow).create_job(
            org_a.organization_id,
            "Foreman",
            execution_handle=_handle(
                uow_factory, JOBS_MANAGE, "jobs.create", org_a.organization_id
            ),
        )
        JobsService(uow).create_job(
            org_b.organization_id,
            "Driver",
            execution_handle=_handle(
                uow_factory, JOBS_MANAGE, "jobs.create", org_b.organization_id
            ),
        )
    with uow_factory() as check:
        jobs = JobsService(check).list_jobs(
            org_a.organization_id,
            execution_handle=_handle(uow_factory, JOBS_MANAGE, "jobs.list", org_a.organization_id),
        )
    assert [job.title for job in jobs] == ["Foreman"]


def test_assign_an_employee_to_a_job(uow_factory) -> None:
    with uow_factory() as uow:
        org_id, employee_id = _org_and_employee(uow_factory)
        job = JobsService(uow).create_job(
            org_id,
            "Foreman",
            execution_handle=_handle(uow_factory, JOBS_MANAGE, "jobs.create", org_id),
        )
        assignment = _assignments(uow).assign(
            employee_id,
            job.job_id,
            execution_handle=_handle(uow_factory, ASSIGNMENT_MANAGE, "assignment.create", org_id),
        )
    with uow_factory() as check:
        found = _assignments(check).get_assignment(
            assignment.assignment_id,
            execution_handle=_handle(uow_factory, PEOPLE_EMPLOYEE_READ, "assignment.read", org_id),
        )
    assert found is not None
    assert found.employee_id == employee_id
    assert found.job_id == job.job_id
    assert found.organization_id == org_id
    assert found.status == "active"


def test_assignments_for_an_employee(uow_factory) -> None:
    with uow_factory() as uow:
        org_id, employee_id = _org_and_employee(uow_factory)
        first = JobsService(uow).create_job(
            org_id,
            "Foreman",
            execution_handle=_handle(uow_factory, JOBS_MANAGE, "jobs.create", org_id),
        )
        second = JobsService(uow).create_job(
            org_id,
            "Driver",
            execution_handle=_handle(uow_factory, JOBS_MANAGE, "jobs.create", org_id),
        )
        _assignments(uow).assign(
            employee_id,
            first.job_id,
            execution_handle=_handle(uow_factory, ASSIGNMENT_MANAGE, "assignment.create", org_id),
        )
        _assignments(uow).assign(
            employee_id,
            second.job_id,
            execution_handle=_handle(uow_factory, ASSIGNMENT_MANAGE, "assignment.create", org_id),
        )
    with uow_factory() as check:
        ids = [
            a.job_id
            for a in _assignments(check).assignments_for(
                employee_id,
                execution_handle=_handle(
                    uow_factory, PEOPLE_EMPLOYEE_READ, "assignment.list", org_id
                ),
            )
        ]
    assert set(ids) == {first.job_id, second.job_id}


def test_assigning_an_unknown_employee_raises(uow_factory) -> None:
    with uow_factory() as uow:
        org_id, _employee_id = _org_and_employee(uow_factory)
        job = JobsService(uow).create_job(
            org_id,
            "Foreman",
            execution_handle=_handle(uow_factory, JOBS_MANAGE, "jobs.create", org_id),
        )
    with pytest.raises(NotFoundError), uow_factory() as check:
        _assignments(check).assign(
            "emp-missing",
            job.job_id,
            execution_handle=_handle(uow_factory, ASSIGNMENT_MANAGE, "assignment.create", org_id),
        )


def test_assigning_to_an_unknown_job_raises(uow_factory) -> None:
    org_id, employee_id = _org_and_employee(uow_factory)
    with pytest.raises(NotFoundError), uow_factory() as check:
        _assignments(check).assign(
            employee_id,
            "job-missing",
            execution_handle=_handle(uow_factory, ASSIGNMENT_MANAGE, "assignment.create", org_id),
        )
