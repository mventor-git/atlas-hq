"""SQLAlchemy ORM mapping for the core's persisted state.

The tables are owned by the core alone and are grouped by aggregate (contract
section 22: clear ownership, no giant shared schema a plugin may read freely).
Plugins never see these tables: they go through application services and
contracts.

``atlas_outbox`` lives in the same schema as the business tables on purpose
(contract section 21): an envelope must be stored in the *same transaction* as
the business state change it describes.

PostgreSQL is the only persistence dialect. The connection URL and schema search
path are configured in :mod:`atlas_core.infrastructure.persistence.session`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    MetaData,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ...domain.assignment import AssignmentStatus
from ...domain.employee import EmployeeStatus
from ...domain.job import JobStatus
from ...domain.organization import WorkplaceType

#: The logical owner of every table here. Plugins never touch these tables
#: (contract section 9); they go through services, contracts and events.
SCHEMA = "atlas"


class Base(DeclarativeBase):
    """Declarative base for the core's tables."""

    metadata = MetaData()


class EmployeeORM(Base):
    """An employee plus the flattened person record it is composed of."""

    __tablename__ = "employee"
    __table_args__ = (
        UniqueConstraint("employee_number", name="uq_employee_number"),
        CheckConstraint("employee_number <> ''", name="ck_employee_number_not_blank"),
    )

    employee_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    person_id: Mapped[str] = mapped_column(String(40), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    employee_number: Mapped[str] = mapped_column(String(64), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=EmployeeStatus.ACTIVE.value)
    hired_on: Mapped[date | None] = mapped_column()


class OrganizationORM(Base):
    __tablename__ = "organization"
    __table_args__ = (UniqueConstraint("code", name="uq_organization_code"),)

    organization_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)


class WorkplaceORM(Base):
    __tablename__ = "workplace"

    workplace_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default=WorkplaceType.OFFICE.value)


class JobORM(Base):
    __tablename__ = "job"

    job_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    workplace_id: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default=JobStatus.OPEN.value)


class AssignmentORM(Base):
    __tablename__ = "assignment"

    assignment_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    employee_id: Mapped[str] = mapped_column(String(40), nullable=False)
    job_id: Mapped[str] = mapped_column(String(40), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(40), nullable=False)
    workplace_id: Mapped[str | None] = mapped_column(String(40))
    start_date: Mapped[date | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(24), default=AssignmentStatus.ACTIVE.value)


class AuditORM(Base):
    """Insert-only (contract section 35: audit is never updated or deleted)."""

    __tablename__ = "audit"

    audit_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_id: Mapped[str | None] = mapped_column(String(40))
    workplace_id: Mapped[str | None] = mapped_column(String(40))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class OutboxORM(Base):
    """The transactional outbox (contract section 21)."""

    __tablename__ = "outbox"
    __table_args__ = (CheckConstraint("attempts >= 0", name="ck_outbox_attempts_non_negative"),)

    envelope_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    publisher: Mapped[str | None] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    dispatched_at: Mapped[datetime | None] = mapped_column()
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(String(1000))


__all__ = [
    "AssignmentORM",
    "AuditORM",
    "Base",
    "EmployeeORM",
    "JobORM",
    "OrganizationORM",
    "OutboxORM",
    "WorkplaceORM",
]
