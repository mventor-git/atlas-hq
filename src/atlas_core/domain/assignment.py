"""Assignments: which employee holds which job, where, and since when.

An assignment is the core's answer to "who works on what" — the join the
contract's module examples keep referencing (``employee.assignment``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from .identifiers import (
    AssignmentId,
    EmployeeId,
    JobId,
    OrganizationId,
    WorkplaceId,
    new_id,
)


class AssignmentStatus(StrEnum):
    PLANNED = "planned"
    ACTIVE = "active"
    ENDED = "ended"


@dataclass(frozen=True)
class Assignment:
    assignment_id: AssignmentId = field(
        default_factory=lambda: AssignmentId(new_id("asg")),
    )
    employee_id: EmployeeId = field(default_factory=lambda: EmployeeId(""))
    job_id: JobId = field(default_factory=lambda: JobId(""))
    organization_id: OrganizationId = field(default_factory=lambda: OrganizationId(""))
    workplace_id: WorkplaceId | None = None
    start_date: date | None = None
    status: AssignmentStatus = AssignmentStatus.ACTIVE


__all__ = ["Assignment", "AssignmentStatus"]
