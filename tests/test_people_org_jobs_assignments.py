"""People, organization, jobs and assignments against the real database.

These exercise the persistence adapters behind the application services:
create then read-back, duplicate rejection, and scoping by organization.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from atlas_core.application.assignments import AssignmentsService
from atlas_core.application.jobs import JobsService
from atlas_core.application.organization import OrganizationService
from atlas_core.application.people import PeopleService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.infrastructure.events import OutboxEventPublisher
from atlas_sdk import DuplicateError, NotFoundError, WorkplaceType


def _people(uow: UnitOfWorkPort) -> PeopleService:
    return PeopleService(uow, OutboxEventPublisher(uow, publisher="test"))


def _assignments(uow: UnitOfWorkPort) -> AssignmentsService:
    return AssignmentsService(uow, OutboxEventPublisher(uow, publisher="test"))


def _org_and_employee(uow: UnitOfWorkPort) -> tuple[str, str]:
    org = OrganizationService(uow).create_organization(name="Acme", code="ACME")
    employee = _people(uow).create_employee(
        full_name="Ada Lovelace",
        employee_number="EMP-1",
        organization_id=org.organization_id,
    )
    return org.organization_id, employee.employee_id


def test_create_and_read_back_an_organization(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    with uow:
        org = OrganizationService(uow).create_organization(name="Acme", code="ACME")

    with uow_factory() as uow2:
        found = OrganizationService(uow2).get_organization(org.organization_id)

    assert found is not None
    assert found.name == "Acme"
    assert found.code == "ACME"


def test_duplicate_organization_code_is_rejected(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    with uow:
        OrganizationService(uow).create_organization(name="Acme", code="ACME")

    with pytest.raises(DuplicateError), uow_factory() as uow2:
        OrganizationService(uow2).create_organization(name="Other", code="ACME")


def test_create_and_read_back_an_employee(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    with uow:
        _org_id, employee_id = _org_and_employee(uow)

    with uow_factory() as uow2:
        found = _people(uow2).get_employee(employee_id)

    assert found is not None
    assert found.full_name == "Ada Lovelace"
    assert found.employee_number == "EMP-1"
    assert found.status == "active"


def test_employees_are_scoped_by_organization(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    with uow:
        org_a = OrganizationService(uow).create_organization(name="A", code="A")
        org_b = OrganizationService(uow).create_organization(name="B", code="B")
        _people(uow).create_employee("Ada", "EMP-1", org_a.organization_id)
        _people(uow).create_employee("Grace", "EMP-2", org_b.organization_id)

    with uow_factory() as uow2:
        people = _people(uow2)
        assert [e.employee_number for e in people.list_employees(org_a.organization_id)] == [
            "EMP-1"
        ]
        assert [e.employee_number for e in people.list_employees(org_b.organization_id)] == [
            "EMP-2"
        ]
        assert len(people.list_employees()) == 2


def test_duplicate_employee_number_is_rejected(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    with uow:
        _org_id, _employee_id = _org_and_employee(uow)

    with pytest.raises(DuplicateError), uow_factory() as uow2:
        _people(uow2).create_employee("Someone Else", "EMP-1", _org_id)


def test_an_employee_persists_only_when_committed(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    try:
        with uow:
            org = OrganizationService(uow).create_organization(name="Acme", code="ACME")
            _people(uow).create_employee("Ada", "EMP-1", org.organization_id)
            raise RuntimeError("rollback")
    except RuntimeError:
        pass

    with uow_factory() as uow2:
        assert _people(uow2).list_employees() == []


def test_workplace_kind_round_trips(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    with uow:
        org = OrganizationService(uow).create_organization(name="Acme", code="ACME")
        workplace = OrganizationService(uow).add_workplace(
            org.organization_id, "North Site", kind=WorkplaceType.SITE
        )

    with uow_factory() as uow2:
        found = OrganizationService(uow2).list_workplaces(org.organization_id)

    assert len(found) == 1
    assert found[0].workplace_id == workplace.workplace_id
    assert found[0].kind == WorkplaceType.SITE


def test_workplace_requires_an_existing_organization(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()

    with pytest.raises(NotFoundError), uow:
        OrganizationService(uow).add_workplace("org-missing", "Nowhere")


def test_create_and_read_back_a_job(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    with uow:
        org_id, _employee_id = _org_and_employee(uow)
        job = JobsService(uow).create_job(org_id, "Foreman")

    with uow_factory() as uow2:
        found = JobsService(uow2).get_job(job.job_id)

    assert found is not None
    assert found.title == "Foreman"
    assert found.status == "open"


def test_jobs_are_scoped_by_organization(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    with uow:
        org_a = OrganizationService(uow).create_organization(name="A", code="A")
        org_b = OrganizationService(uow).create_organization(name="B", code="B")
        JobsService(uow).create_job(org_a.organization_id, "Foreman")
        JobsService(uow).create_job(org_b.organization_id, "Driver")

    with uow_factory() as uow2:
        jobs = JobsService(uow2).list_jobs(org_a.organization_id)
        assert [j.title for j in jobs] == ["Foreman"]


def test_assign_an_employee_to_a_job(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    with uow:
        org_id, employee_id = _org_and_employee(uow)
        job = JobsService(uow).create_job(org_id, "Foreman")
        assignment = _assignments(uow).assign(employee_id, job.job_id)

    with uow_factory() as uow2:
        found = _assignments(uow2).get_assignment(assignment.assignment_id)

    assert found is not None
    assert found.employee_id == employee_id
    assert found.job_id == job.job_id
    assert found.organization_id == org_id
    assert found.status == "active"


def test_assignments_for_an_employee(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    with uow:
        org_id, employee_id = _org_and_employee(uow)
        first = JobsService(uow).create_job(org_id, "Foreman")
        second = JobsService(uow).create_job(org_id, "Driver")
        _assignments(uow).assign(employee_id, first.job_id)
        _assignments(uow).assign(employee_id, second.job_id)

    with uow_factory() as uow2:
        ids = [a.job_id for a in _assignments(uow2).assignments_for(employee_id)]

    assert set(ids) == {first.job_id, second.job_id}


def test_assigning_an_unknown_employee_raises(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    with uow:
        org_id, _employee_id = _org_and_employee(uow)
        job = JobsService(uow).create_job(org_id, "Foreman")

    with pytest.raises(NotFoundError), uow_factory() as uow2:
        _assignments(uow2).assign("emp-missing", job.job_id)


def test_assigning_to_an_unknown_job_raises(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    uow = uow_factory()
    with uow:
        _org_id, employee_id = _org_and_employee(uow)

    with pytest.raises(NotFoundError), uow_factory() as uow2:
        _assignments(uow2).assign(employee_id, "job-missing")
