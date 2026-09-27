"""Workforce Summary — a ``reporting.dataset`` provider (Gate O, one of two).

This plugin exists to be *installed or not*. Report Studio never imports it,
never names it, and never knows its plugin id. It discovers the dataset only
because this plugin provides the shared ``reporting.dataset`` contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlas_sdk import (
    AuthorizationError,
    CapabilityId,
    Contract,
    ExecutionHandle,
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

if TYPE_CHECKING:
    from atlas_sdk import PluginContext


class WorkforceSummaryContract(Contract[DatasetRequest, DatasetResponse]):
    contract_id = REPORT_DATASET_CONTRACT

    def __init__(self, context: PluginContext) -> None:
        self._context = context

    def handle(
        self,
        request: DatasetRequest,
        *,
        execution_handle: ExecutionHandle,
    ) -> DatasetResponse:
        requested_scope = self._context.scope.resolve(request.organization_id)
        decision = self._context.authorization.authorize(
            execution_handle,
            CapabilityId("report.render"),
            requested_scope,
        )
        if not decision.allowed:
            raise AuthorizationError(f"dataset read denied: {decision.code}")
        employees = self._context.people.list_employees(
            request.organization_id,
            execution_handle=execution_handle,
        )
        rows = tuple((e.employee_number, e.full_name, e.status) for e in employees)
        return DatasetResponse(
            dataset_id="workforce.summary",
            title="Workforce Summary",
            columns=("employee_number", "full_name", "status"),
            rows=rows,
        )


class WorkforceSummaryPlugin(Plugin):
    manifest = PluginManifest(
        plugin_id="workforce_summary",
        name="Workforce Summary",
        version="0.1.0",
        # Workforce reporting over people data belongs with the workforce cluster.
        cluster_id="cluster.workforce_and_time",
        requires_core="0.1.0",
        modules=(
            ModuleDeclaration(
                module_id="workforce.summary",
                provides=("reporting.dataset",),
                consumes=("people.employee.read",),
            ),
        ),
        provides_contracts=(REPORT_DATASET_DECLARATION,),
    )

    context: PluginContext

    def initialize(self, context: PluginContext) -> None:
        self.context = context
        self._handler = WorkforceSummaryContract(context)

    def bind_contracts(self) -> None:
        self.context.contracts.bind(
            REPORT_DATASET_CONTRACT,
            self.manifest.plugin_id,
            self._handler,
        )


__all__ = ["WorkforceSummaryPlugin"]
