"""Self Reporting — the first on-demand, self-scoped report (contract §38.6).

``self.monthly.report`` is a fixed reporting plugin (contract §12) in the
information and documents cluster. It owns the use case *and* the self-scoped
dataset behind it; Report Studio stays generic and learns about both through the
published contracts (contract §13). Nothing about "self" exists in Core or in
Report Studio.

How the self boundary is kept, in order:

1. **A request carries no identity.** :class:`SelfReportRequest` holds only an
   organization that may narrow, never a principal, an actor, or a free-form
   scope. There is nothing in the payload to trust.
2. **Core says who is asking.** The only fact a self-scoped read needs is
   *whose* rows it may return, so it asks Core through
   ``context.authorization.resolve_principal`` and gets ``None`` for a missing,
   unknown, expired, or revoked handle. That identifier is a *narrowing* input
   to the decision below, never a substitute for one.
3. **Core decides.** The self scope built from that principal is authorized
   through the ordinary Core path: handle containment, capability, effective
   grant, policy, channel, and default deny (§38.5). A handle scoped to an
   organization can never widen into somebody's self scope.
4. **The plugin's own table is filtered by that principal.** No other plugin's
   tables are read and no scheduler exists: the first release is on demand.

The same dataset is exposed as a ``reporting.dataset`` provider so Report Studio
can discover it without knowing this plugin. A caller whose scope does not cover
a self read gets an empty contribution rather than an exception: one provider
must not abort a whole organization-wide report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from atlas_sdk import (
    AuthorizationError,
    CapabilityId,
    CapabilityKind,
    Contract,
    ExecutionHandle,
    ModuleDeclaration,
    Plugin,
    PluginManifest,
)
from atlas_sdk.reporting import (
    REPORT_DATASET_CONTRACT,
    REPORT_DATASET_DECLARATION,
    REPORT_DEFINITION_CONTRACT,
    REPORT_DEFINITION_DECLARATION,
    DatasetRequest,
    DatasetResponse,
    ReportDefinition,
    ReportDefinitionRequest,
    ShapedDataset,
    UseCaseMetadata,
    shape_dataset,
)

from .persistence import SelfMonthlyEntryORM, SelfReportingRepository

if TYPE_CHECKING:
    from atlas_sdk import PluginContext

#: The stable use-case / module / definition id (contract §38.6).
USE_CASE_ID = "self.monthly.report"

#: Three non-interchangeable capability kinds (contract §38.3). Only ``view`` is
#: ever granted by default; ``schedule`` and ``manage`` are declared metadata
#: until their surfaces exist.
SELF_REPORT_VIEW = CapabilityId("self.monthly.report.view")
SELF_REPORT_SCHEDULE = CapabilityId("self.monthly.report.schedule")
SELF_REPORT_MANAGE = CapabilityId("self.monthly.report.manage")

#: The Core-owned action a caller is issued a handle for.
SELF_REPORT_ACTION = "self.monthly.report.view"

#: The one role bundle a normal user is given. It carries view and nothing else.
SELF_REPORT_VIEWER_ROLE = "role.self_report_viewer"

#: The logical dataset id Report Studio discovers this plugin's data under.
SELF_MONTHLY_DATASET_ID = "self.monthly.entries"

#: The published column vocabulary, in order.
SELF_MONTHLY_COLUMNS = ("month", "entry_date", "status", "comment")

SELF_MONTHLY_USE_CASE = UseCaseMetadata(
    use_case_id=USE_CASE_ID,
    title="My Monthly Report",
    summary=(
        "A principal reads their own monthly self-report entries, grouped by month. "
        "It returns only the requesting principal's own rows."
    ),
    owner="self_reporting",
    audience="employee",
    scope="self",
    date_grain="month",
    required_capabilities=(SELF_REPORT_VIEW,),
    surfaces=("web", "bot", "ai"),
    review_status="accepted",
    version="1.0",
)

SELF_MONTHLY_REPORT = ReportDefinition(
    definition_id=USE_CASE_ID,
    title=SELF_MONTHLY_USE_CASE.title,
    dataset_ids=(SELF_MONTHLY_DATASET_ID,),
    group_by=("month",),
    detail_columns=("entry_date", "status", "comment"),
    use_case=SELF_MONTHLY_USE_CASE,
)


@dataclass(frozen=True)
class SelfReportRequest:
    """A request for the caller's own monthly report.

    The only field is an organization, which may narrow the report further. A
    principal is never accepted here: the handle is the identity.
    """

    organization_id: str | None = None


@dataclass
class SelfReport:
    """The rendered self report: the caller's own data and nothing else."""

    principal_id: str
    use_case: UseCaseMetadata
    sections: tuple[ShapedDataset, ...] = ()
    audit_id: str | None = None

    def render(self) -> str:
        lines = [self.use_case.title]
        for section in self.sections:
            lines.append(f"  {section.title} [{section.dataset_id}]")
            if not section.installed:
                lines.append(f"    ({section.note})")
                continue
            for group in section.groups:
                label = " | ".join(group.key)
                heading = f"{label} (count {group.count})" if label else f"(count {group.count})"
                lines.append(f"    {heading}")
                lines.append("      " + " | ".join(section.columns))
                for row in group.rows:
                    lines.append("      " + " | ".join(row))
        return "\n".join(lines)


def _require_principal(context: PluginContext, execution_handle: ExecutionHandle) -> str:
    """The Core-resolved principal of a valid handle, or a fail-closed error."""
    principal_id = context.authorization.resolve_principal(execution_handle)
    if principal_id is None:
        raise AuthorizationError("self report access requires a resolvable ExecutionHandle")
    return principal_id


def _self_dataset(
    context: PluginContext,
    principal_id: str,
    organization_id: str | None,
    execution_handle: ExecutionHandle,
) -> DatasetResponse | None:
    """One principal's own rows, or ``None`` when this execution may not read them.

    The organization may only narrow. Nothing here widens: the self scope is
    built from the principal Core resolved, and the ordinary Core decision —
    not this function — decides whether the read is allowed.
    """
    scope = context.scope.resolve(organization_id, principal_id=principal_id)
    decision = context.authorization.authorize(execution_handle, SELF_REPORT_VIEW, scope)
    if not decision.allowed:
        return None
    entries = SelfReportingRepository(context.persistence).list_for_principal(
        principal_id,
        decision.scope.organization_id,
    )
    return DatasetResponse(
        dataset_id=SELF_MONTHLY_DATASET_ID,
        title=SELF_MONTHLY_REPORT.title,
        columns=SELF_MONTHLY_COLUMNS,
        rows=tuple(
            (entry.month, entry.entry_date, entry.status, entry.comment) for entry in entries
        ),
    )


class SelfReportDefinitionContract(Contract[ReportDefinitionRequest, ReportDefinition]):
    """Read-only provider for this plugin's one use-case definition (§38.1)."""

    contract_id = REPORT_DEFINITION_CONTRACT

    def __init__(self) -> None:
        self._definition = SELF_MONTHLY_REPORT

    def handle(
        self,
        request: ReportDefinitionRequest,
        *,
        execution_handle: ExecutionHandle,
    ) -> ReportDefinition:
        return self._definition


class SelfMonthlyDatasetContract(Contract[DatasetRequest, DatasetResponse]):
    """The self-scoped dataset, discoverable by Report Studio (contract §13).

    Rows are filtered by the principal Core resolved from the handle, so a
    caller can only ever receive their own entries. An execution that may not
    read a self scope contributes no rows instead of raising: one provider must
    not abort an organization-wide report, and no rows means no disclosure.
    """

    contract_id = REPORT_DATASET_CONTRACT

    def __init__(self, context: PluginContext) -> None:
        self._context = context

    def handle(
        self,
        request: DatasetRequest,
        *,
        execution_handle: ExecutionHandle,
    ) -> DatasetResponse:
        principal_id = _require_principal(self._context, execution_handle)
        dataset = _self_dataset(
            self._context,
            principal_id,
            request.organization_id,
            execution_handle,
        )
        if dataset is not None:
            return dataset
        return DatasetResponse(
            dataset_id=SELF_MONTHLY_DATASET_ID,
            title=SELF_MONTHLY_REPORT.title,
            columns=SELF_MONTHLY_COLUMNS,
        )


class SelfReportingPlugin(Plugin):
    manifest = PluginManifest(
        plugin_id="self_reporting",
        name="Self Reporting",
        version="0.1.0",
        # Contract §38.6: an information & documents reporting capability.
        cluster_id="cluster.information_and_documents",
        requires_core="0.1.0",
        modules=(
            ModuleDeclaration(
                module_id=USE_CASE_ID,
                provides=("report.definition", "reporting.dataset"),
                supports=(
                    SELF_REPORT_VIEW,
                    SELF_REPORT_SCHEDULE,
                    SELF_REPORT_MANAGE,
                ),
            ),
        ),
        provides_capabilities=(
            SELF_REPORT_VIEW,
            SELF_REPORT_SCHEDULE,
            SELF_REPORT_MANAGE,
        ),
        capability_kinds={
            SELF_REPORT_VIEW: CapabilityKind.VIEW,
            SELF_REPORT_SCHEDULE: CapabilityKind.SCHEDULE,
            SELF_REPORT_MANAGE: CapabilityKind.MANAGE,
        },
        provides_contracts=(
            REPORT_DEFINITION_DECLARATION,
            REPORT_DATASET_DECLARATION,
        ),
        owned_tables=(SelfMonthlyEntryORM.__tablename__,),
    )

    context: PluginContext

    def initialize(self, context: PluginContext) -> None:
        self.context = context
        # The plugin owns its table and creates it in its own transaction (§22).
        SelfReportingRepository(context.persistence).create_schema()
        # Declaring a role is metadata; Core still decides who is assigned it.
        context.authorization.register_role(
            SELF_REPORT_VIEWER_ROLE,
            "Self Report Viewer",
            frozenset({SELF_REPORT_VIEW}),
        )

    def bind_contracts(self) -> None:
        contracts = self.context.contracts
        contracts.bind(
            REPORT_DEFINITION_CONTRACT,
            self.manifest.plugin_id,
            SelfReportDefinitionContract(),
        )
        contracts.bind(
            REPORT_DATASET_CONTRACT,
            self.manifest.plugin_id,
            SelfMonthlyDatasetContract(self.context),
        )

    def render(
        self,
        request: SelfReportRequest,
        *,
        execution_handle: ExecutionHandle,
    ) -> SelfReport:
        """Render the caller's own monthly report, on demand (contract §38.6)."""
        return self.context.transactions.run(
            lambda: self._render(request, execution_handle=execution_handle)
        )

    def _render(
        self,
        request: SelfReportRequest,
        *,
        execution_handle: ExecutionHandle,
    ) -> SelfReport:
        """Uncommitted implementation used by the direct compatibility surface."""
        principal_id = _require_principal(self.context, execution_handle)
        dataset = _self_dataset(
            self.context,
            principal_id,
            request.organization_id,
            execution_handle,
        )
        if dataset is None:
            raise AuthorizationError("the self monthly report is not available to this execution")
        audit_id = self.context.audit.record(
            action=f"{USE_CASE_ID}.rendered",
            details={
                "use_case_id": SELF_MONTHLY_USE_CASE.use_case_id,
                "definition_id": SELF_MONTHLY_REPORT.definition_id,
                "dataset_id": dataset.dataset_id,
                "rows": dataset.row_count,
            },
            execution_handle=execution_handle,
        )
        return SelfReport(
            principal_id=principal_id,
            use_case=SELF_MONTHLY_USE_CASE,
            sections=(shape_dataset(dataset, SELF_MONTHLY_REPORT),),
            audit_id=audit_id,
        )


__all__ = [
    "SELF_MONTHLY_COLUMNS",
    "SELF_MONTHLY_DATASET_ID",
    "SELF_MONTHLY_REPORT",
    "SELF_MONTHLY_USE_CASE",
    "SELF_REPORT_ACTION",
    "SELF_REPORT_MANAGE",
    "SELF_REPORT_SCHEDULE",
    "SELF_REPORT_VIEW",
    "SELF_REPORT_VIEWER_ROLE",
    "USE_CASE_ID",
    "SelfMonthlyDatasetContract",
    "SelfReport",
    "SelfReportDefinitionContract",
    "SelfReportRequest",
    "SelfReportingPlugin",
]
