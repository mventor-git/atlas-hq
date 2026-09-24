"""Plugin-owned persistence for Attendance Operations (contract section 22).

``att_attendance`` belongs to this plugin alone. No other plugin and not the
core reads it; other plugins reach attendance through the contracts this plugin
provides (contract section 9). The workforce membership that *authorizes* a
record lives in Workplace Operations — this plugin reaches it through the
``workplace.workforce`` contract and never through that plugin's tables.

Restricted persistence comes from ``context.persistence`` — the platform's
transaction — so an attendance record and its ``attendance.recorded`` event
commit in one transaction or not at all (contract section 21).
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import MetaData, String, UniqueConstraint, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from atlas_sdk import PluginPersistencePort

#: The logical owner of every table here. The platform supplies the physical
#: PostgreSQL schema through the connection search path; table names remain
#: prefixed so ownership is visible in the DDL.
SCHEMA = "atlas"

#: Every table this plugin owns is prefixed so ownership is visible in the DDL
#: and no plugin can collide with another plugin's tables (contract section 22).
TABLE_PREFIX = "att_"


class Base(DeclarativeBase):
    """Declarative base for this plugin's tables — separate from the core's."""

    metadata = MetaData()


class AttendanceORM(Base):
    """One employee's attendance at one workplace on one date.

    The unique constraint is the idempotency contract: recording the same
    (workplace, employee, date) again updates the status rather than adding a
    second row, so a retry can never double-count a person on a day.
    """

    __tablename__ = f"{TABLE_PREFIX}attendance"
    __table_args__ = (
        UniqueConstraint(
            "workplace_id",
            "employee_id",
            "record_date",
            name=f"uq_{TABLE_PREFIX}attendance_workplace_employee_date",
        ),
    )

    attendance_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(40), nullable=False)
    workplace_id: Mapped[str] = mapped_column(String(40), nullable=False)
    employee_id: Mapped[str] = mapped_column(String(40), nullable=False)
    record_date: Mapped[date] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class AttendanceOperationsRepository:
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

    # --- records -----------------------------------------------------------

    def add(self, record: AttendanceORM) -> None:
        self._persistence.add(record)

    def find(
        self,
        workplace_id: str,
        employee_id: str,
        record_date: date,
    ) -> AttendanceORM | None:
        stmt = select(AttendanceORM).where(
            AttendanceORM.workplace_id == workplace_id,
            AttendanceORM.employee_id == employee_id,
            AttendanceORM.record_date == record_date,
        )
        return next(iter(self._persistence.query(stmt)), None)

    def list_for_workplace_and_date(
        self,
        workplace_id: str,
        record_date: date,
    ) -> list[AttendanceORM]:
        stmt = select(AttendanceORM).where(
            AttendanceORM.workplace_id == workplace_id,
            AttendanceORM.record_date == record_date,
        )
        return list(self._persistence.query(stmt))

    def list_for_organization(self, organization_id: str | None) -> list[AttendanceORM]:
        stmt = select(AttendanceORM)
        if organization_id is not None:
            stmt = stmt.where(AttendanceORM.organization_id == organization_id)
        return list(self._persistence.query(stmt))


__all__ = [
    "AttendanceOperationsRepository",
    "AttendanceORM",
    "Base",
    "SCHEMA",
    "TABLE_PREFIX",
]
