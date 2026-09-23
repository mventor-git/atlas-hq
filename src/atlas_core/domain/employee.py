"""People and employees.

``Person`` is human identity; ``Employee`` is the employment relationship an
organisation has with a person. Both are core-owned (contract section 10: the
core owns employee identity) and plugins only ever see the mapped
:class:`atlas_sdk.Employee` read model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from .identifiers import EmployeeId, OrganizationId, new_id


class EmployeeStatus(StrEnum):
    ACTIVE = "active"
    ON_LEAVE = "on_leave"
    TERMINATED = "terminated"


@dataclass(frozen=True)
class Person:
    """Human identity, independent of any employment."""

    person_id: str = field(default_factory=lambda: new_id("person"))
    full_name: str = ""
    email: str | None = None
    phone: str | None = None


@dataclass(frozen=True)
class Employee:
    """An employment relationship: a person working for an organisation."""

    employee_id: EmployeeId = field(default_factory=lambda: EmployeeId(new_id("emp")))
    person: Person = field(default_factory=Person)
    employee_number: str = ""
    organization_id: OrganizationId = field(default_factory=lambda: OrganizationId(""))
    status: EmployeeStatus = EmployeeStatus.ACTIVE
    hired_on: date | None = None

    @property
    def full_name(self) -> str:
        return self.person.full_name


__all__ = ["Employee", "EmployeeStatus", "Person"]
