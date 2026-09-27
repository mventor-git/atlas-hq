"""Atlas Report Studio — the first Composable Plugin (contract sections 13, 26).

Report Studio renders a report from every ``reporting.dataset`` implementation
that happens to be installed and enabled. It does not import, name, or know the
plugin id of any dataset provider. Adding a provider is an installation, not a
code change here — that is Gate O.

Discovery is deterministic and metadata-driven (contract section 14): the
contract registry is asked for implementations of the contract id, the invoker
calls each bound handler, and the responses are rendered as-is.

On top of that discovery sits a *declarative* reporting layer (contract section
28): a :class:`ReportDefinition` names the logical dataset ids it consumes and a
tabular shape — filter predicates, grouping columns, a per-group count, and the
detail columns of each group. The shaping engine is column-generic and lives in
the SDK (``shape_dataset``), so every report — including one rendered by a
fixed reporting plugin — is shaped by the same deterministic code, which never
interprets the business meaning of a value. A definition degrades gracefully
when a declared dataset has no installed provider, because composability means
a report still renders with whatever is present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from atlas_sdk import (
    AuthorizationError,
    CapabilityId,
    DomainEvent,
    EventId,
    ExecutionHandle,
    ModuleDeclaration,
    NotFoundError,
    Plugin,
    PluginManifest,
    Scope,
)
from atlas_sdk.reporting import (
    REPORT_DATASET_CONTRACT,
    REPORT_DEFINITION_CONTRACT,
    DatasetRequest,
    DatasetResponse,
    ReportDefinition,
    ReportDefinitionRequest,
    ReportGroup,
    ShapedDataset,
    shape_dataset,
)

if TYPE_CHECKING:
    from atlas_sdk import PluginContext

#: Capability required to render a report (Gate M).
REPORT_RENDER = CapabilityId("report.render")

#: Published for every report rendered, carrying which datasets contributed.
REPORT_GENERATED = EventId("report.generated")


@dataclass(frozen=True)
class ReportRequest:
    """A request to render one report for one organization."""

    organization_id: str


@dataclass
class RenderedReport:
    """The assembled report: a section per contributing dataset provider."""

    organization_id: str
    datasets: list[DatasetResponse] = field(default_factory=list)
    #: The shaped view, populated by :meth:`ReportStudioPlugin.render_definition`.
    sections: list[ShapedDataset] = field(default_factory=list)
    audit_id: str | None = None

    def render(self) -> str:
        lines = [f"Report for organization {self.organization_id}"]
        if not self.datasets and not self.sections:
            lines.append("  (no dataset providers installed)")
        for section in self.sections:
            lines.append(f"  {section.title}")
            if not section.installed:
                lines.append(
                    f"    ({section.note})"
                    if section.note
                    else f"    (dataset {section.dataset_id} not installed)"
                )
                continue
            if section.note is not None:
                lines.append(f"    ({section.note})")
                continue
            for group in section.groups:
                label = " | ".join(group.key)
                heading = f"{label} (count {group.count})" if label else f"(count {group.count})"
                lines.append(f"    {heading}")
                if section.columns:
                    lines.append("      " + " | ".join(section.columns))
                    for row in group.rows:
                        lines.append("      " + " | ".join(row))
        for dataset in self.datasets:
            lines.append(f"  {dataset.title} [{dataset.row_count} rows]")
            if dataset.columns:
                lines.append("    " + " | ".join(dataset.columns))
                for row in dataset.rows:
                    lines.append("    " + " | ".join(row))
        return "\n".join(lines)


class ReportStudioPlugin(Plugin):
    manifest = PluginManifest(
        plugin_id="report_studio",
        name="Atlas Report Studio",
        version="0.1.0",
        # Report Studio is an information & documents capability (contract §8).
        cluster_id="cluster.information_and_documents",
        requires_core="0.1.0",
        modules=(
            ModuleDeclaration(
                module_id="report.compose",
                provides=("report.compose",),
                consumes=("report.definition", "reporting.dataset"),
                publishes=(REPORT_GENERATED,),
            ),
        ),
        provides_capabilities=(REPORT_RENDER,),
        consumes_contracts=(REPORT_DEFINITION_CONTRACT, REPORT_DATASET_CONTRACT),
        publishes_events=(REPORT_GENERATED,),
    )

    context: PluginContext

    def initialize(self, context: PluginContext) -> None:
        self.context = context
        context.authorization.register_role(
            "role.report_renderer",
            "Report Renderer",
            frozenset({REPORT_RENDER}),
        )

    def bind_contracts(self) -> None:
        # Studio consumes definition and dataset contracts; it provides neither.
        pass

    def _authorized(
        self,
        request: ReportRequest,
        execution_handle: ExecutionHandle,
    ) -> Scope:
        """Enforce the canonical handle; request organization data may only narrow it."""
        requested_scope = self.context.scope.resolve(request.organization_id)
        decision = self.context.authorization.authorize(
            execution_handle,
            REPORT_RENDER,
            requested_scope,
        )
        if not decision.allowed:
            raise AuthorizationError(f"report render denied: {decision.code}")
        return decision.scope

    def _definition(
        self,
        definition_id: str,
        execution_handle: ExecutionHandle,
    ) -> ReportDefinition:
        """Find one SDK definition returned by any enabled fixed plugin."""
        responses = self.context.invoker.invoke_all(
            REPORT_DEFINITION_CONTRACT,
            ReportDefinitionRequest(definition_id=definition_id),
            execution_handle=execution_handle,
        )
        definition = next(
            (
                response
                for response in responses
                if isinstance(response, ReportDefinition)
                and response.definition_id == definition_id
            ),
            None,
        )
        if definition is None:
            msg = f"no enabled provider returned report definition {definition_id!r}"
            raise NotFoundError(msg, kind="report_definition", key=definition_id)
        return definition

    def _installed_datasets(
        self,
        organization_id: str,
        execution_handle: ExecutionHandle,
    ) -> dict[str, DatasetResponse]:
        """Every dataset an enabled provider supplies, keyed by dataset id.

        Gate O lives in the single ``invoke_all`` call: the registry decides how
        many providers answer, and this method never names one.
        """
        responses = self.context.invoker.invoke_all(
            REPORT_DATASET_CONTRACT,
            DatasetRequest(organization_id=organization_id),
            execution_handle=execution_handle,
        )
        return {
            dataset.dataset_id: dataset
            for dataset in responses
            if isinstance(dataset, DatasetResponse)
        }

    def render(
        self,
        request: ReportRequest,
        *,
        execution_handle: ExecutionHandle,
    ) -> RenderedReport:
        """Compose every installed dataset into one flat report (Gate O)."""
        return self.context.transactions.run(lambda: self._render(request, execution_handle))

    def _render(
        self,
        request: ReportRequest,
        execution_handle: ExecutionHandle,
    ) -> RenderedReport:
        """Uncommitted implementation used by the direct compatibility surface."""
        self._authorized(request, execution_handle)
        datasets = list(
            self._installed_datasets(request.organization_id, execution_handle).values(),
        )

        audit_id = self.context.audit.record(
            action="report.rendered",
            details={
                "organization_id": request.organization_id,
                "datasets": [d.dataset_id for d in datasets],
            },
            execution_handle=execution_handle,
        )

        self.context.events.publish(
            DomainEvent(
                event_id=REPORT_GENERATED,
                payload={
                    "organization_id": request.organization_id,
                    "datasets": [d.dataset_id for d in datasets],
                    "audit_id": audit_id,
                },
            ),
            execution_handle=execution_handle,
        )

        return RenderedReport(
            organization_id=request.organization_id,
            datasets=datasets,
            audit_id=audit_id,
        )

    def render_definition(
        self,
        request: ReportRequest,
        definition_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> RenderedReport:
        """Render one named report definition (contract section 28).

        The requested SDK definition is discovered through ``report.definition``;
        its dataset ids are then resolved through the same generic discovery as
        :meth:`render`. No fixed or dataset provider is named here. A declared
        dataset whose provider is not installed renders as a clear "dataset not
        installed" section, because composability adapts rather than breaks when
        a plugin is absent.
        """
        return self.context.transactions.run(
            lambda: self._render_definition(request, definition_id, execution_handle)
        )

    def _render_definition(
        self,
        request: ReportRequest,
        definition_id: str,
        execution_handle: ExecutionHandle,
    ) -> RenderedReport:
        """Uncommitted implementation used by the direct compatibility surface."""
        self._authorized(request, execution_handle)
        definition = self._definition(definition_id, execution_handle)
        installed = self._installed_datasets(request.organization_id, execution_handle)

        sections: list[ShapedDataset] = []
        contributing: list[str] = []
        for dataset_id in definition.dataset_ids:
            dataset = installed.get(dataset_id)
            if dataset is None:
                sections.append(
                    ShapedDataset(
                        dataset_id=dataset_id,
                        title=definition.title,
                        installed=False,
                        note=f"dataset {dataset_id} is not installed",
                    ),
                )
                continue
            contributing.append(dataset_id)
            sections.append(shape_dataset(dataset, definition))

        audit_id = self.context.audit.record(
            action="report.rendered",
            details={
                "organization_id": request.organization_id,
                "definition_id": definition.definition_id,
                "datasets": contributing,
            },
            execution_handle=execution_handle,
        )

        self.context.events.publish(
            DomainEvent(
                event_id=REPORT_GENERATED,
                payload={
                    "organization_id": request.organization_id,
                    "definition_id": definition.definition_id,
                    "datasets": contributing,
                    "audit_id": audit_id,
                },
            ),
            execution_handle=execution_handle,
        )

        return RenderedReport(
            organization_id=request.organization_id,
            sections=sections,
            audit_id=audit_id,
        )


__all__ = [
    "REPORT_GENERATED",
    "REPORT_RENDER",
    "ReportGroup",
    "ReportRequest",
    "ReportStudioPlugin",
    "RenderedReport",
    "ShapedDataset",
]
