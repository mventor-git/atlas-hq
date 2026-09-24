"""Attendance Operations — attendance as a first-class domain plugin (§8, §27).

An attendance record is (employee, workplace, date, status), and ownership of
that record lives here (contract section 10): check-in, check-out, attendance
status and attendance evidence are attendance's alone. ``AttendanceStatus`` is
published in the SDK so payroll, leave and Report Studio read the same values
without importing this plugin, exactly as ``WorkplaceType`` is published.

Four rules this plugin establishes and obeys:

1. **Contracts are the only cross-plugin channel.** Recording attendance
   consumes ``workplace.workforce`` — the employee must be a member of that
   workplace's workforce, proven through the contract (Gate K), never by
   importing Workplace Operations or reading its tables. The workspace's
   organization is resolved through ``workplace.context`` the same way.
2. **The platform owns the transaction.** Every write goes through the
   restricted ``context.persistence`` adapter and the public compatibility
   wrapper runs direct operations through ``context.transactions``, so an
   attendance record and its ``attendance.recorded`` event land in one
   transaction or not at all (contract section 21). A caller driving this
   plugin's service surface directly never has to know to commit.
3. **Recording is idempotent.** The same (workplace, employee, date) updates the
   status instead of adding a row, so a retry can never double-count a person.
4. **The summary is a composable dataset.** The daily summary is provided both as
   a typed contract and as a ``reporting.dataset`` with dataset_id
   ``attendance.daily_summary`` (Gate O), so Report Studio discovers it with no
   code change — the contract is the channel; the plugin id is not.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from atlas_sdk import (
    AttendanceStatus,
    CapabilityId,
    Contract,
    ContractDeclaration,
    ContractId,
    EventId,
    ModuleDeclaration,
    Plugin,
    PluginManifest,
)
from atlas_sdk.reporting import (
    REPORT_DATASET_CONTRACT,
    REPORT_DATASET_DECLARATION,
    DatasetRequest,
    DatasetResponse,
)

from .domain import AttendanceRecord, DailySummary, DailySummaryEntry
from .persistence import AttendanceOperationsRepository
from .services import AttendanceOperationsService

if TYPE_CHECKING:
    from atlas_sdk import PluginContext

#: Capabilities every mutating operation / query requires (Gates L/M/N).
ATTENDANCE_MANAGE = CapabilityId("attendance.manage")
ATTENDANCE_VIEW = CapabilityId("attendance.view")

#: Events this plugin publishes through the outbox (contract section 20).
ATTENDANCE_RECORDED = EventId("attendance.recorded")

#: The contracts this plugin provides (contract section 15).
ATTENDANCE_DAILY_SUMMARY_CONTRACT = ContractId("attendance.daily_summary")

#: The dataset id Report Studio discovers this plugin's summary under (Gate O).
ATTENDANCE_DATASET_ID = "attendance.daily_summary"


@dataclass(frozen=True)
class AttendanceRecordRequest:
    """Request shape of ``record_attendance`` — one employee, one day, one status."""

    employee_id: str
    workplace_id: str
    date: date
    status: AttendanceStatus = AttendanceStatus.PRESENT
    actor_id: str = ""


@dataclass(frozen=True)
class DailySummaryRequest:
    """Request shape of ``attendance.daily_summary`` — the roster-status of a day."""

    workplace_id: str
    date: date
    actor_id: str = ""


class AttendanceDailySummaryContract(Contract[DailySummaryRequest, DailySummary]):
    """``attendance.daily_summary``: the statuses recorded for a workplace on a date.

    The contract is the *only* sanctioned channel (contract section 9): a
    consumer that needs the day's attendance calls the contract; it never
    imports this plugin or reads ``att_attendance``.
    """

    contract_id = ATTENDANCE_DAILY_SUMMARY_CONTRACT

    def __init__(self, service: AttendanceOperationsService) -> None:
        self._service = service

    def handle(self, request: DailySummaryRequest) -> DailySummary:
        # Gates M/N live on the query too: the caller must be able to view
        # attendance in the workplace's organization.
        self._service.assert_summary_visible(request.workplace_id, request.actor_id)
        return self._service.daily_summary(request.workplace_id, request.date)


class AttendanceDailySummaryDatasetContract(Contract[DatasetRequest, DatasetResponse]):
    """The same summary, exposed as a ``reporting.dataset`` provider (Gate O).

    Report Studio discovers this dataset by asking the registry for
    ``reporting.dataset`` implementations and never names this plugin (contract
    section 13). One summary, two contracts: the typed one for domain consumers,
    this one for any reporting consumer.
    """

    contract_id = REPORT_DATASET_CONTRACT

    def __init__(self, service: AttendanceOperationsService) -> None:
        self._service = service

    def handle(self, request: DatasetRequest) -> DatasetResponse:
        return self._service.daily_summary_dataset(request.organization_id)


class AttendanceOperationsPlugin(Plugin):
    manifest = PluginManifest(
        plugin_id="attendance_operations",
        name="Attendance Operations",
        version="0.1.0",
        # Contract section 8: attendance is a workforce-and-time concern.
        cluster_id="cluster.workforce_and_time",
        requires_core="0.1.0",
        # Deliberately no requires_plugins: attendance composes with whatever
        # workplace provider is installed, and degrades to a clean NotFoundError
        # when none is (contract section 19 — cluster membership is not a
        # dependency, and section 13 — composable plugins adapt to what exists).
        modules=(
            ModuleDeclaration(
                module_id="attendance.daily",
                provides=("attendance.daily_summary", "reporting.dataset"),
                consumes=("workplace.workforce", "workplace.context", "people.employee.read"),
                publishes=(ATTENDANCE_RECORDED,),
            ),
        ),
        provides_capabilities=(ATTENDANCE_MANAGE, ATTENDANCE_VIEW),
        consumes_capabilities=(CapabilityId("people.employee.read"),),
        provides_contracts=(
            ContractDeclaration(
                contract_id=ATTENDANCE_DAILY_SUMMARY_CONTRACT,
                version="1.0",
                schema={
                    "request": {
                        "type": "object",
                        "properties": {
                            "workplace_id": {"type": "string"},
                            "date": {"type": "string", "format": "date"},
                            "actor_id": {"type": "string"},
                        },
                        "required": ["workplace_id", "date"],
                    },
                    "response": {
                        "type": "object",
                        "properties": {
                            "workplace_id": {"type": "string"},
                            "date": {"type": "string", "format": "date"},
                            "entries": {"type": "array"},
                        },
                    },
                },
                description="The attendance statuses recorded for one workplace on one date.",
            ),
            # Gate O — the daily summary is also a composable reporting dataset.
            REPORT_DATASET_DECLARATION,
        ),
        consumes_contracts=(
            # Spelled as literal ids, never imported from the provider (§9).
            ContractId("workplace.workforce"),
            ContractId("workplace.context"),
        ),
        publishes_events=(ATTENDANCE_RECORDED,),
    )

    context: PluginContext

    def initialize(self, context: PluginContext) -> None:
        self.context = context
        # The plugin owns its tables: create them from the plugin's own
        # metadata, in the plugin's own transaction (contract section 22).
        AttendanceOperationsRepository(context.persistence).create_schema()
        self._service = AttendanceOperationsService(context)
        # Publish the roles that carry this plugin's capabilities, so an
        # administrator can grant them (Gate M needs the grant to be possible).
        context.authorization.register_role(
            "role.attendance_manager",
            "Attendance Manager",
            frozenset({ATTENDANCE_MANAGE, ATTENDANCE_VIEW}),
        )
        context.authorization.register_role(
            "role.attendance_viewer",
            "Attendance Viewer",
            frozenset({ATTENDANCE_VIEW}),
        )

    def bind_contracts(self) -> None:
        contracts = self.context.contracts
        contracts.bind(
            ATTENDANCE_DAILY_SUMMARY_CONTRACT,
            self.manifest.plugin_id,
            AttendanceDailySummaryContract(self._service),
        )
        # The same summary, discoverable as a reporting dataset.
        contracts.bind(
            REPORT_DATASET_CONTRACT,
            self.manifest.plugin_id,
            AttendanceDailySummaryDatasetContract(self._service),
        )

    # --- the plugin's service surface -------------------------------------

    def record_attendance(self, request: AttendanceRecordRequest) -> AttendanceRecord:
        return self.context.transactions.run(
            lambda: self._service.record_attendance(
                employee_id=request.employee_id,
                workplace_id=request.workplace_id,
                date=request.date,
                status=request.status,
                actor=request.actor_id,
            )
        )

    def daily_summary(self, workplace_id: str, record_date: date) -> DailySummary:
        return self.context.transactions.run(
            lambda: self._service.daily_summary(workplace_id, record_date)
        )


__all__ = [
    "ATTENDANCE_DATASET_ID",
    "ATTENDANCE_DAILY_SUMMARY_CONTRACT",
    "ATTENDANCE_MANAGE",
    "ATTENDANCE_RECORDED",
    "ATTENDANCE_VIEW",
    "AttendanceOperationsPlugin",
    "AttendanceRecordRequest",
    "DailySummaryEntry",
    "DailySummaryRequest",
]
