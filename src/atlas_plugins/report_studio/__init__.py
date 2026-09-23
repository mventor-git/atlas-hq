"""Atlas Report Studio — the first Composable Plugin (contract sections 13, 26).

Report Studio renders a report from every ``reporting.dataset`` implementation
that happens to be installed and enabled. It does not import, name, or know the
plugin id of any dataset provider. Adding a provider is an installation, not a
code change here — that is Gate O.

Discovery is deterministic and metadata-driven (contract section 14): the
contract registry is asked for implementations of the contract id, the invoker
calls each bound handler, and the responses are rendered as-is.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from atlas_sdk import (
    CapabilityId,
    DomainEvent,
    EventId,
    ModuleDeclaration,
    Plugin,
    PluginManifest,
)
from atlas_sdk.reporting import REPORT_DATASET_CONTRACT, DatasetRequest, DatasetResponse

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
    actor_id: str


@dataclass
class RenderedReport:
    """The assembled report: a section per contributing dataset provider."""

    organization_id: str
    datasets: list[DatasetResponse] = field(default_factory=list)
    audit_id: str | None = None

    def render(self) -> str:
        lines = [f"Report for organization {self.organization_id}"]
        if not self.datasets:
            lines.append("  (no dataset providers installed)")
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
                consumes=("reporting.dataset",),
                publishes=(REPORT_GENERATED,),
            ),
        ),
        provides_capabilities=(REPORT_RENDER,),
        consumes_contracts=(REPORT_DATASET_CONTRACT,),
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
        # Studio consumes datasets; it provides no contract of its own.
        pass

    def render(self, request: ReportRequest) -> RenderedReport:
        """Compose every installed dataset into one report.

        Gate O lives in the single ``invoke_all`` call: the registry decides how
        many providers answer, and this method never names one.
        """
        scope = self.context.scope.resolve(request.organization_id)

        # Gate M — rendering is a privileged action.
        if not self.context.authorization.check(REPORT_RENDER, scope, request.actor_id):
            from atlas_sdk import AuthorizationError

            raise AuthorizationError(
                f"{request.actor_id!r} lacks capability {REPORT_RENDER} in scope {scope}",
            )

        responses = self.context.invoker.invoke_all(
            REPORT_DATASET_CONTRACT,
            DatasetRequest(organization_id=request.organization_id),
        )
        datasets = [r for r in responses if isinstance(r, DatasetResponse)]

        audit_id = self.context.audit.record(
            action="report.rendered",
            actor=request.actor_id,
            scope=scope,
            details={
                "organization_id": request.organization_id,
                "datasets": [d.dataset_id for d in datasets],
            },
        )

        self.context.events.publish(
            DomainEvent(
                event_id=REPORT_GENERATED,
                payload={
                    "organization_id": request.organization_id,
                    "actor_id": request.actor_id,
                    "datasets": [d.dataset_id for d in datasets],
                    "audit_id": audit_id,
                },
            ),
        )

        return RenderedReport(
            organization_id=request.organization_id,
            datasets=datasets,
            audit_id=audit_id,
        )


__all__ = [
    "REPORT_GENERATED",
    "REPORT_RENDER",
    "ReportRequest",
    "ReportStudioPlugin",
    "RenderedReport",
]
