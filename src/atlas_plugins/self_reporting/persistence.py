"""Plugin-owned persistence for Self Reporting (contract section 22).

``self_monthly_entry`` belongs to this plugin alone. It holds one principal's
own monthly self-report entries, so the self-scoped read in
:mod:`atlas_plugins.self_reporting` filters by exactly one ``principal_id``.

No other plugin reads this table, and this plugin reads nobody else's: the
organization dimension is a narrowing filter only, never a source of rows. The
restricted ``context.persistence`` adapter shares the platform transaction, so
a rendered report commits or rolls back with the caller's transaction.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Index, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from atlas_sdk import PluginPersistencePort

#: Every table this plugin owns is prefixed so ownership is visible in the DDL
#: and no plugin can collide with another plugin's tables (contract section 22).
TABLE_PREFIX = "self_"


class Base(DeclarativeBase):
    """Declarative base for this plugin's tables — separate from the core's."""

    metadata = MetaData()


class SelfMonthlyEntryORM(Base):
    """One entry in one principal's monthly self report.

    ``principal_id`` is the Core principal the row belongs to. It is written by
    the owning plugin only and is never taken from a request.
    """

    __tablename__ = f"{TABLE_PREFIX}monthly_entry"
    __table_args__ = (Index(f"ix_{TABLE_PREFIX}monthly_entry_principal", "principal_id"),)

    entry_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    organization_id: Mapped[str | None] = mapped_column(String(40))
    principal_id: Mapped[str] = mapped_column(String(40), nullable=False)
    month: Mapped[str] = mapped_column(String(7), nullable=False)
    entry_date: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    comment: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    recorded_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class SelfReportingRepository:
    """Read access to this plugin's own table through the restricted adapter."""

    def __init__(self, persistence: PluginPersistencePort) -> None:
        self._persistence = persistence

    def create_schema(self) -> None:
        """Create this plugin's tables if they do not exist. Idempotent."""
        self._persistence.create_tables(SelfMonthlyEntryORM)

    def list_for_principal(
        self,
        principal_id: str,
        organization_id: str | None = None,
    ) -> list[SelfMonthlyEntryORM]:
        """One principal's entries; the organization may only narrow them."""
        if organization_id is None:
            return self._persistence.all(
                SelfMonthlyEntryORM,
                principal_id=principal_id,
            )
        return self._persistence.all(
            SelfMonthlyEntryORM,
            principal_id=principal_id,
            organization_id=organization_id,
        )


__all__ = [
    "TABLE_PREFIX",
    "Base",
    "SelfMonthlyEntryORM",
    "SelfReportingRepository",
]
