"""Plugin-facing value types: the published language of the platform.

The SDK owns these read models deliberately. Core domain objects are not
importable by plugins (that would be implementation coupling), so core maps its
domain entities to these types at the application-service boundary. This is the
anti-corruption layer between core's rich domain and a plugin's stable view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class WorkplaceType(StrEnum):
    """The kinds of workplace a company may operate (contract section 8).

    "Site" is one type among many — it is not the platform's identity.
    """

    OFFICE = "office"
    HQ = "hq"
    BRANCH = "branch"
    SITE = "site"
    WAREHOUSE = "warehouse"
    FACTORY = "factory"
    PLANT = "plant"
    PROJECT_LOCATION = "project_location"
    SERVICE_CENTER = "service_center"
    REMOTE = "remote"
    OTHER = "other"


@dataclass(frozen=True)
class Scope:
    """The context in which an operation or record lives (contract section 35).

    ``organization_id`` ``None`` means "no access" — a query narrowed to a
    disjoint scope yields a global-less scope rather than raising.
    """

    organization_id: str | None = None
    workplace_id: str | None = None

    @property
    def is_empty(self) -> bool:
        return self.organization_id is None


@dataclass(frozen=True)
class Employee:
    employee_id: str
    full_name: str
    employee_number: str
    organization_id: str
    status: str = "active"


@dataclass(frozen=True)
class Organization:
    organization_id: str
    name: str
    code: str


@dataclass(frozen=True)
class Workplace:
    workplace_id: str
    organization_id: str
    name: str
    kind: WorkplaceType = WorkplaceType.OFFICE


@dataclass(frozen=True)
class Job:
    job_id: str
    organization_id: str
    title: str
    workplace_id: str | None = None
    status: str = "open"


@dataclass(frozen=True)
class Assignment:
    assignment_id: str
    employee_id: str
    job_id: str
    organization_id: str
    workplace_id: str | None = None
    status: str = "active"


@dataclass(frozen=True)
class AuditEntry:
    """One append-only audit record (contract section 35: historical accountability)."""

    audit_id: str
    occurred_at: datetime
    actor: str
    action: str
    scope: Scope
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkflowCase:
    case_id: str
    workflow_id: str
    entity_id: str
    state: str
    started_at: datetime
    input: dict[str, object] = field(default_factory=dict)
    updated_at: datetime | None = None


@dataclass(frozen=True)
class Notification:
    notification_id: str
    channel: str
    recipient: str
    subject: str
    body: str
    sent_at: datetime


@dataclass(frozen=True)
class ScheduledJob:
    schedule_id: str
    key: str
    run_at: datetime
    payload: dict[str, object] = field(default_factory=dict)


__all__ = [
    "Assignment",
    "AuditEntry",
    "Employee",
    "Job",
    "Notification",
    "Organization",
    "ScheduledJob",
    "Scope",
    "Workplace",
    "WorkplaceType",
    "WorkflowCase",
]
