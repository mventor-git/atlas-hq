"""Attendance Summary — the *second* ``reporting.dataset`` provider (Gate O).

This is deliberately a separate, independently-installable plugin from
:mod:`workforce_summary`. Report Studio composes both datasets at render time
without naming either, which is the acceptance test for contract section 13.

It imports the *contract vocabulary* from the SDK, never the other plugin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlas_sdk import Contract, ModuleDeclaration, Plugin, PluginManifest
from atlas_sdk.reporting import (
    REPORT_DATASET_CONTRACT,
    REPORT_DATASET_DECLARATION,
    DatasetRequest,
    DatasetResponse,
)

if TYPE_CHECKING:
    from atlas_sdk import PluginContext


class AttendanceSummaryContract(Contract[DatasetRequest, DatasetResponse]):
    """Attendance presence summary, derived from real core state.

    The dataset is built from core assignments rather than stored attendance
    rows, so the demo needs no persistence of its own; attendance as a
    first-class domain arrives in a later phase.
    """

    contract_id = REPORT_DATASET_CONTRACT

    def __init__(self, context: PluginContext) -> None:
        self._context = context

    def handle(self, request: DatasetRequest) -> DatasetResponse:
        employees = self._context.people.list_employees(request.organization_id)
        rows: list[tuple[str, ...]] = []
        for employee in employees:
            assignments = self._context.assignments.assignments_for(employee.employee_id)
            if assignments:
                rows.append((employee.employee_number, "present", str(len(assignments))))
            else:
                rows.append((employee.employee_number, "no_assignment", "0"))
        return DatasetResponse(
            dataset_id="attendance.summary",
            title="Attendance Summary",
            columns=("employee_number", "attendance_status", "assignment_count"),
            rows=tuple(rows),
        )


class AttendanceSummaryPlugin(Plugin):
    manifest = PluginManifest(
        plugin_id="attendance_summary",
        name="Attendance Summary",
        version="0.1.0",
        # Attendance is a workforce-and-time concern.
        cluster_id="cluster.workforce_and_time",
        requires_core="0.1.0",
        modules=(
            ModuleDeclaration(
                module_id="attendance.summary",
                provides=("reporting.dataset",),
                consumes=("people.employee.read", "employee.assignment"),
            ),
        ),
        provides_contracts=(REPORT_DATASET_DECLARATION,),
    )

    context: PluginContext

    def initialize(self, context: PluginContext) -> None:
        self.context = context
        self._handler = AttendanceSummaryContract(context)

    def bind_contracts(self) -> None:
        self.context.contracts.bind(
            REPORT_DATASET_CONTRACT,
            self.manifest.plugin_id,
            self._handler,
        )


__all__ = ["AttendanceSummaryPlugin"]
