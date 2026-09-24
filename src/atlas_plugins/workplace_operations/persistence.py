"""Plugin-owned persistence for Workplace Operations (contract section 22).

The two tables here belong to ``workplace_operations`` alone. No other plugin,
and not the core, reads them: other plugins reach this domain only through the
contracts this plugin provides (contract section 9). The tables are created from
this module and from nowhere else, which is what "the plugin owns its tables"
means operationally.

Restricted persistence comes from ``context.persistence`` — the *platform's*
transaction — so a workplace state change and the ``workplace.*`` event
describing it commit in one transaction or not at all (contract section 21).
The plugin never manages the transaction lifecycle.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import ForeignKey, MetaData, String, UniqueConstraint, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from atlas_sdk import PluginPersistencePort, WorkplaceType

#: The logical owner of every table here. The platform supplies the physical
#: PostgreSQL schema through the connection search path; table names remain
#: prefixed so ownership is visible in the DDL.
SCHEMA = "atlas"

#: Every table this plugin owns is prefixed so ownership is visible in the DDL
#: and no plugin can collide with another plugin's tables (contract section 22).
TABLE_PREFIX = "wpop_"


class Base(DeclarativeBase):
    """Declarative base for this plugin's tables — separate from the core's."""

    metadata = MetaData()


class WorkplaceORM(Base):
    """A typed business location: an office, a site, a warehouse, ..."""

    __tablename__ = f"{TABLE_PREFIX}workplace"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "code",
            name=f"uq_{TABLE_PREFIX}workplace_code",
        ),
    )

    workplace_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default=WorkplaceType.OFFICE.value
    )
    parent_workplace_id: Mapped[str | None] = mapped_column(
        String(40),
        ForeignKey(f"{TABLE_PREFIX}workplace.workplace_id"),
    )
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class WorkforceMembershipORM(Base):
    """The workplace-side view of workforce membership.

    The core still owns the *assignment record* (contract section 10); this row
    is the workplace's own book of who is currently on its roster, and it is the
    single source of truth for that roster.
    """

    __tablename__ = f"{TABLE_PREFIX}workforce_membership"
    __table_args__ = (
        UniqueConstraint(
            "workplace_id",
            "employee_id",
            name=f"uq_{TABLE_PREFIX}membership_workplace_employee",
        ),
    )

    membership_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workplace_id: Mapped[str] = mapped_column(String(40), nullable=False)
    employee_id: Mapped[str] = mapped_column(String(40), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(40), nullable=False)
    joined_on: Mapped[date] = mapped_column(default=lambda: datetime.now(UTC).date())


class WorkplaceOperationsRepository:
    """Read/write access to this plugin's tables through the restricted adapter.

    The adapter shares the platform transaction but exposes no raw session or
    transaction lifecycle, so this repository cannot escape the platform seam.
    """

    def __init__(self, persistence: PluginPersistencePort) -> None:
        self._persistence = persistence

    # --- schema ------------------------------------------------------------

    def create_schema(self) -> None:
        """Create this plugin's tables if they do not exist. Idempotent.

        DDL runs on a short-lived engine connection that closes immediately,
        rather than retaining the shared transaction session.
        """
        self._persistence.create_schema(Base.metadata)

    # --- workplaces --------------------------------------------------------

    def add_workplace(self, workplace: WorkplaceORM) -> None:
        self._persistence.add(workplace)

    def get_workplace(self, workplace_id: str) -> WorkplaceORM | None:
        return self._persistence.get(WorkplaceORM, workplace_id)

    def find_by_code(self, organization_id: str, code: str) -> WorkplaceORM | None:
        stmt = select(WorkplaceORM).where(
            WorkplaceORM.organization_id == organization_id,
            WorkplaceORM.code == code,
        )
        return next(iter(self._persistence.query(stmt)), None)

    def list_workplaces(
        self,
        organization_id: str | None = None,
        kind: WorkplaceType | None = None,
    ) -> list[WorkplaceORM]:
        stmt = select(WorkplaceORM)
        if organization_id is not None:
            stmt = stmt.where(WorkplaceORM.organization_id == organization_id)
        if kind is not None:
            stmt = stmt.where(WorkplaceORM.kind == kind.value)
        return list(self._persistence.query(stmt))

    # --- workforce membership ----------------------------------------------

    def add_membership(self, membership: WorkforceMembershipORM) -> None:
        self._persistence.add(membership)

    def delete_membership(self, membership_id: str) -> None:
        """Remove a membership row. No-op if it is already gone."""
        row = self._persistence.get(WorkforceMembershipORM, membership_id)
        if row is not None:
            self._persistence.delete(row)

    def get_membership(self, workplace_id: str, employee_id: str) -> WorkforceMembershipORM | None:
        stmt = select(WorkforceMembershipORM).where(
            WorkforceMembershipORM.workplace_id == workplace_id,
            WorkforceMembershipORM.employee_id == employee_id,
        )
        return next(iter(self._persistence.query(stmt)), None)

    def list_memberships(self, workplace_id: str) -> list[WorkforceMembershipORM]:
        stmt = select(WorkforceMembershipORM).where(
            WorkforceMembershipORM.workplace_id == workplace_id,
        )
        return list(self._persistence.query(stmt))

    def list_memberships_for_organization(
        self,
        organization_id: str,
    ) -> list[WorkforceMembershipORM]:
        stmt = select(WorkforceMembershipORM).where(
            WorkforceMembershipORM.organization_id == organization_id,
        )
        return list(self._persistence.query(stmt))


__all__ = [
    "Base",
    "SCHEMA",
    "WorkforceMembershipORM",
    "WorkplaceOperationsRepository",
    "WorkplaceORM",
]
