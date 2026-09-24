"""The Attendance Operations domain types.

An attendance record is (employee, workplace, date, status) — the single source
of truth this plugin owns (contract section 10): check-in, check-out and
attendance status all belong to attendance. These value objects are the plugin's
published read models; the ORM rows in :mod:`.persistence` stay private to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from atlas_sdk import AttendanceStatus

__all__ = [
    "AttendanceRecord",
    "AttendanceStatus",
    "DailySummary",
    "DailySummaryEntry",
]


@dataclass(frozen=True)
class AttendanceRecord:
    """The response of recording one employee's status for one day."""

    attendance_id: str
    organization_id: str
    workplace_id: str
    employee_id: str
    date: date
    status: AttendanceStatus
    full_name: str = ""
    employee_number: str = ""


@dataclass(frozen=True)
class DailySummaryEntry:
    """One recorded attendance in a day's summary for a workplace."""

    employee_id: str
    employee_number: str
    full_name: str
    status: AttendanceStatus


@dataclass(frozen=True)
class DailySummary:
    """The day's recorded roster-status for one workplace (contract section 15).

    The roster itself belongs to Workplace Operations; this summary carries only
    what attendance owns — the statuses recorded for the day. A workforce member
    with no record yet simply has no entry here.
    """

    workplace_id: str
    date: date
    entries: tuple[DailySummaryEntry, ...] = ()

    @property
    def recorded_count(self) -> int:
        return len(self.entries)
