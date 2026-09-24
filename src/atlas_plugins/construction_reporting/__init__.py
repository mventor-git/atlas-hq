"""Construction Reporting — the fixed Construction Daily Workforce definition.

This plugin is deliberately domain-specific (contract §12). It owns the
construction definition while Report Studio remains a composable, domain-neutral
renderer (contract §13). Cross-plugin knowledge stops at SDK vocabulary and the
literal ``reporting.dataset`` contract id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlas_sdk import (
    CapabilityId,
    Contract,
    ContractId,
    ModuleDeclaration,
    Plugin,
    PluginManifest,
    WorkplaceType,
)
from atlas_sdk.reporting import (
    REPORT_DEFINITION_CONTRACT,
    REPORT_DEFINITION_DECLARATION,
    ColumnFilter,
    ReportDefinition,
    ReportDefinitionRequest,
)

if TYPE_CHECKING:
    from atlas_sdk import PluginContext

REPORT_RENDER_CAPABILITY = CapabilityId("report.render")

CONSTRUCTION_DAILY_WORKFORCE = ReportDefinition(
    definition_id="construction.daily_workforce",
    title="Construction Daily Workforce Report",
    dataset_ids=("workplace.workforce",),
    filters=(ColumnFilter(column="workplace_kind", value=WorkplaceType.SITE.value),),
    group_by=("workplace_code", "workplace_name"),
    detail_columns=("employee_number", "full_name"),
)


class ConstructionReportDefinitionContract(Contract[ReportDefinitionRequest, ReportDefinition]):
    """Read-only provider for this plugin's one fixed report definition.

    Every enabled provider advertises its definition; Report Studio matches the
    requested id after ``invoke_all`` so unrelated providers do not abort lookup.
    """

    contract_id = REPORT_DEFINITION_CONTRACT

    def __init__(self) -> None:
        self._definition = CONSTRUCTION_DAILY_WORKFORCE

    def handle(self, request: ReportDefinitionRequest) -> ReportDefinition:
        return self._definition


class ConstructionReportingPlugin(Plugin):
    manifest = PluginManifest(
        plugin_id="construction_reporting",
        name="Construction Reporting",
        version="0.1.0",
        cluster_id="cluster.information_and_documents",
        requires_core="0.1.0",
        modules=(
            ModuleDeclaration(
                module_id="construction.reporting",
                provides=("report.definition",),
                consumes=("reporting.dataset",),
                supports=(REPORT_RENDER_CAPABILITY,),
            ),
        ),
        provides_contracts=(REPORT_DEFINITION_DECLARATION,),
        consumes_contracts=(ContractId("reporting.dataset"),),
    )

    context: PluginContext

    def initialize(self, context: PluginContext) -> None:
        self.context = context
        self._handler = ConstructionReportDefinitionContract()

    def bind_contracts(self) -> None:
        self.context.contracts.bind(
            REPORT_DEFINITION_CONTRACT,
            self.manifest.plugin_id,
            self._handler,
        )


__all__ = [
    "CONSTRUCTION_DAILY_WORKFORCE",
    "REPORT_RENDER_CAPABILITY",
    "ConstructionReportDefinitionContract",
    "ConstructionReportingPlugin",
]
