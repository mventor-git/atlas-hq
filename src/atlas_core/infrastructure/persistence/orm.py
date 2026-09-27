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
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
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
    principal_id: Mapped[str | None] = mapped_column(String(40))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ExecutionORM(Base):
    """Canonical execution facts addressed by a hashed opaque handle token."""

    __tablename__ = "execution_handle"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(40), nullable=False)
    identity_id: Mapped[str | None] = mapped_column(String(80))
    capability_id: Mapped[str] = mapped_column(String(255), nullable=False)
    allowed_capability_ids_json: Mapped[list[str]] = mapped_column(
        "allowed_capability_ids", JSON, default=list
    )
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255))
    organization_id: Mapped[str | None] = mapped_column(String(40))
    workplace_id: Mapped[str | None] = mapped_column(String(40))
    principal_scope_id: Mapped[str | None] = mapped_column(String(40))
    policy_context_json: Mapped[dict[str, Any]] = mapped_column(
        "policy_context", JSON, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PrincipalORM(Base):
    """A channel-neutral Core principal."""

    __tablename__ = "principal"

    principal_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class IdentityORM(Base):
    """A channel identity, inert until Core links it to a principal."""

    __tablename__ = "identity"
    __table_args__ = (
        UniqueConstraint("channel", "external_id", name="uq_identity_channel_external"),
    )

    identity_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    principal_id: Mapped[str | None] = mapped_column(String(40))
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    trusted: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class CapabilityORM(Base):
    """Core-owned capability metadata, never a user grant."""

    __tablename__ = "capability"

    capability_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="")
    provider_id: Mapped[str] = mapped_column(String(80), default="core")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class PolicyORM(Base):
    """A Core-owned effective-dated policy rule."""

    __tablename__ = "policy"

    policy_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    condition_json: Mapped[dict[str, Any]] = mapped_column("condition", JSON, default=dict)
    capability: Mapped[str | None] = mapped_column(String(255))
    action: Mapped[str | None] = mapped_column(String(255))
    channel: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class RoleORM(Base):
    __tablename__ = "role"

    role_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_plugin_id: Mapped[str] = mapped_column(String(80), default="core")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class RoleCapabilityORM(Base):
    __tablename__ = "role_capability"
    __table_args__ = (
        CheckConstraint("role_id <> ''", name="ck_role_capability_role_not_blank"),
        CheckConstraint("capability_id <> ''", name="ck_role_capability_capability_not_blank"),
    )

    role_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    capability_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class RoleAssignmentORM(Base):
    __tablename__ = "role_assignment"

    role_assignment_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(40), nullable=False)
    role_id: Mapped[str] = mapped_column(String(80), nullable=False)
    organization_id: Mapped[str | None] = mapped_column(String(40))
    workplace_id: Mapped[str | None] = mapped_column(String(40))
    principal_scope_id: Mapped[str | None] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    audit_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class CapabilityGrantORM(Base):
    __tablename__ = "capability_grant"

    grant_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(40), nullable=False)
    capability_id: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_id: Mapped[str | None] = mapped_column(String(40))
    workplace_id: Mapped[str | None] = mapped_column(String(40))
    principal_scope_id: Mapped[str | None] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    audit_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ConfirmationORM(Base):
    __tablename__ = "confirmation"

    confirmation_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(255), nullable=False)
    organization_id: Mapped[str | None] = mapped_column(String(40))
    workplace_id: Mapped[str | None] = mapped_column(String(40))
    principal_scope_id: Mapped[str | None] = mapped_column(String(40))
    capability_id: Mapped[str] = mapped_column(String(255), default="")
    channel: Mapped[str] = mapped_column(String(32), default="web")
    resource_id: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audit_id: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


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


# Readable compatibility names for callers that spell out the ownership.
PrincipalIdentityORM = IdentityORM
DirectCapabilityGrantORM = CapabilityGrantORM
RoleCapabilityLinkORM = RoleCapabilityORM


__all__ = [
    "AssignmentORM",
    "AuditORM",
    "Base",
    "CapabilityGrantORM",
    "CapabilityORM",
    "ConfirmationORM",
    "DirectCapabilityGrantORM",
    "EmployeeORM",
    "ExecutionORM",
    "IdentityORM",
    "PrincipalIdentityORM",
    "JobORM",
    "OrganizationORM",
    "OutboxORM",
    "PolicyORM",
    "PrincipalORM",
    "RoleAssignmentORM",
    "RoleCapabilityLinkORM",
    "RoleCapabilityORM",
    "RoleORM",
    "WorkplaceORM",
]
