"""Contract §38.6/§38.7 — the first on-demand, self-scoped report.

``self.monthly.report`` is a fixed reporting plugin in the information and
documents cluster. This suite proves it is discovered, declares complete
use-case metadata, holds only what the Core Roles Engine granted, returns
nothing but the caller's own rows, and fails closed on every bad handle — with
no scheduler, no other plugin's tables, and no non-PostgreSQL engine.

The plugin is discovered through a temporary distribution on ``sys.path`` (see
``isolated_plugins``) because the editable install's metadata snapshot predates
this entry point; product discovery itself stays metadata-driven.
"""

from __future__ import annotations

import inspect
import time
import tomllib
import uuid
from collections.abc import Callable
from dataclasses import fields
from datetime import date
from pathlib import Path
from typing import cast

import pytest
from tests.conftest import assign_role_for_test
from tests.synthetic import refresh_metadata_cache

from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.domain.role import ASSISTANT_USE
from atlas_core.kernel import Kernel
from atlas_plugins.construction_reporting import CONSTRUCTION_DAILY_WORKFORCE
from atlas_plugins.report_studio import REPORT_RENDER, ReportRequest, ReportStudioPlugin
from atlas_plugins.self_reporting import (
    SELF_MONTHLY_DATASET_ID,
    SELF_MONTHLY_REPORT,
    SELF_REPORT_ACTION,
    SELF_REPORT_MANAGE,
    SELF_REPORT_SCHEDULE,
    SELF_REPORT_VIEW,
    SELF_REPORT_VIEWER_ROLE,
    SelfReport,
    SelfReportingPlugin,
    SelfReportRequest,
)
from atlas_plugins.self_reporting.persistence import SelfMonthlyEntryORM
from atlas_sdk import (
    AuthorizationError,
    CapabilityId,
    CapabilityKind,
    Channel,
    ExecutionHandle,
    PluginLifecycle,
    Scope,
)
from atlas_sdk.reporting import (
    REPORT_DATASET_CONTRACT,
    REPORT_DEFINITION_CONTRACT,
    DatasetRequest,
    DatasetResponse,
    ReportDefinition,
    ReportDefinitionRequest,
    UseCaseMetadata,
)

ALICE = "self.alice"
BOB = "self.bob"
ORG = "org-self-reporting"
USE_CASE_ID = "self.monthly.report"
SELF_TEST_ENTRY_POINT_GROUP = "atlas.test.self-reporting"


@pytest.fixture
def self_kernel(
    uow_factory: Callable[[], UnitOfWorkPort],
    isolated_plugins: Path,
) -> Kernel:
    """Boot the real plugin pair behind an isolated entry-point distribution."""
    dist_info = isolated_plugins / "atlas-hq-self-reporting-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: atlas-hq-self-reporting\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        f"[{SELF_TEST_ENTRY_POINT_GROUP}]\n"
        "report_studio = atlas_plugins.report_studio:ReportStudioPlugin\n"
        "self_reporting = atlas_plugins.self_reporting:SelfReportingPlugin\n",
        encoding="utf-8",
    )
    refresh_metadata_cache()
    kernel = Kernel(
        uow_factory=uow_factory,
        entry_point_group=SELF_TEST_ENTRY_POINT_GROUP,
    )
    kernel.boot()
    kernel.enable("self_reporting")
    return kernel


# --- helpers ---------------------------------------------------------------


def _self_scope(principal_id: str, organization_id: str | None = None) -> Scope:
    return Scope(organization_id=organization_id, principal_id=principal_id)


def _grant_view(kernel: Kernel, principal_id: str) -> None:
    """Grant exactly what a normal user gets: the view capability, by role."""
    assign_role_for_test(kernel, principal_id, SELF_REPORT_VIEWER_ROLE, _self_scope(principal_id))


def _handle(
    kernel: Kernel,
    principal_id: str,
    *,
    organization_id: str | None = None,
    channel: Channel = Channel.WEB,
    ttl_seconds: int = 900,
) -> ExecutionHandle:
    kernel.authorization_management.create_principal(principal_id, actor="tests")
    return kernel.issue_execution_handle(
        principal_id=principal_id,
        capability=SELF_REPORT_VIEW,
        action=SELF_REPORT_ACTION,
        scope=_self_scope(principal_id, organization_id),
        channel=channel,
        ttl_seconds=ttl_seconds,
    )


def _seed(
    kernel: Kernel,
    principal_id: str,
    *,
    month: str = "2026-08",
    entry_date: str = "2026-08-04",
    status: str = "submitted",
    comment: str = "",
    organization_id: str | None = None,
) -> None:
    """Write one row into the plugin's own table through its own persistence.

    This slice ships the report provider, not a submission surface, so the rows
    are seeded the only way the platform allows: through the plugin-owned
    persistence adapter the manifest declares.
    """
    context = kernel.context_for("self_reporting")
    row = SelfMonthlyEntryORM(
        entry_id=f"self_{uuid.uuid4().hex[:16]}",
        organization_id=organization_id,
        principal_id=principal_id,
        month=month,
        entry_date=entry_date,
        status=status,
        comment=comment,
    )
    context.transactions.run(lambda: context.persistence.add(row))


def _plugin(kernel: Kernel) -> SelfReportingPlugin:
    instance = kernel._instances["self_reporting"]
    assert isinstance(instance, SelfReportingPlugin)
    return instance


def _render(
    kernel: Kernel,
    principal_id: str,
    *,
    organization_id: str | None = None,
    channel: Channel = Channel.WEB,
    handle: ExecutionHandle | None = None,
) -> SelfReport:
    return _plugin(kernel).render(
        SelfReportRequest(organization_id=organization_id),
        execution_handle=handle if handle is not None else _handle(kernel, principal_id),
    )


def _dataset(kernel: Kernel, principal_id: str, *, organization_id: str | None = None):
    response = kernel.registries.contracts.invoke(
        REPORT_DATASET_CONTRACT,
        DatasetRequest(organization_id=organization_id),
        execution_handle=_handle(kernel, principal_id),
    )
    return cast(DatasetResponse, response)


# --- discovery and declaration --------------------------------------------


def test_self_reporting_is_a_shipped_entry_point() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert (
        pyproject["project"]["entry-points"]["atlas.plugins"]["self_reporting"]
        == "atlas_plugins.self_reporting:SelfReportingPlugin"
    )


def test_the_plugin_is_discovered_in_the_information_and_documents_cluster(
    self_kernel: Kernel,
) -> None:
    manifest = self_kernel.registries.plugins.get("self_reporting")

    assert manifest.cluster_id == "cluster.information_and_documents"
    assert manifest.module_ids() == (USE_CASE_ID,)
    assert manifest.provides_capabilities == (
        SELF_REPORT_VIEW,
        SELF_REPORT_SCHEDULE,
        SELF_REPORT_MANAGE,
    )
    assert manifest.capability_kinds == {
        SELF_REPORT_VIEW: CapabilityKind.VIEW,
        SELF_REPORT_SCHEDULE: CapabilityKind.SCHEDULE,
        SELF_REPORT_MANAGE: CapabilityKind.MANAGE,
    }
    assert [declaration.contract_id for declaration in manifest.provides_contracts] == [
        REPORT_DEFINITION_CONTRACT,
        REPORT_DATASET_CONTRACT,
    ]
    assert self_kernel.registries.plugins.lifecycle_state("self_reporting") is (
        PluginLifecycle.ENABLED
    )


def test_the_three_capabilities_are_core_registered_with_their_own_kinds(
    self_kernel: Kernel,
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        stored = {c.capability_id: c for c in uow.authorization.list_capabilities()}

    assert self_kernel.registries.capabilities.provided_by("self_reporting") == [
        SELF_REPORT_VIEW,
        SELF_REPORT_SCHEDULE,
        SELF_REPORT_MANAGE,
    ]
    assert stored[SELF_REPORT_VIEW].provider_id == "self_reporting"
    assert stored[SELF_REPORT_VIEW].kind is CapabilityKind.VIEW
    assert stored[SELF_REPORT_SCHEDULE].kind is CapabilityKind.SCHEDULE
    assert stored[SELF_REPORT_MANAGE].kind is CapabilityKind.MANAGE


# --- use-case metadata (§38.1) --------------------------------------------


def test_the_definition_declares_complete_use_case_metadata(self_kernel: Kernel) -> None:
    response = self_kernel.registries.contracts.invoke(
        REPORT_DEFINITION_CONTRACT,
        ReportDefinitionRequest(definition_id=USE_CASE_ID),
        execution_handle=_handle(self_kernel, ALICE),
    )

    definition = cast(ReportDefinition, response)
    use_case = definition.use_case
    assert isinstance(use_case, UseCaseMetadata)
    assert definition.definition_id == USE_CASE_ID
    assert use_case.use_case_id == USE_CASE_ID
    assert use_case.title and use_case.summary
    assert use_case.owner == "self_reporting"
    assert use_case.audience
    assert use_case.scope == "self"
    assert use_case.date_grain == "month"
    assert use_case.required_capabilities == (SELF_REPORT_VIEW,)
    assert use_case.surfaces == ("web", "bot", "ai")
    assert use_case.review_status
    assert use_case.version
    assert definition.dataset_ids == (SELF_MONTHLY_DATASET_ID,)


def test_a_definition_without_use_case_metadata_still_works() -> None:
    """The metadata extension is additive: an older definition is unchanged."""
    assert CONSTRUCTION_DAILY_WORKFORCE.use_case is None
    assert CONSTRUCTION_DAILY_WORKFORCE.dataset_ids == ("workplace.workforce",)
    assert CONSTRUCTION_DAILY_WORKFORCE.definition_id == "construction.daily_workforce"


# --- capability kinds and the Core Roles Engine (§38.3) --------------------


def test_the_roles_engine_grants_a_normal_user_view_and_nothing_else(
    self_kernel: Kernel,
) -> None:
    _grant_view(self_kernel, ALICE)

    effective = self_kernel.authorization_management.effective_permissions(
        ALICE,
        _self_scope(ALICE),
    )

    assert SELF_REPORT_VIEW in effective
    assert SELF_REPORT_SCHEDULE not in effective
    assert SELF_REPORT_MANAGE not in effective


def test_rendering_without_the_grant_is_denied(self_kernel: Kernel) -> None:
    _seed(self_kernel, ALICE, comment="alice-only-marker")

    with pytest.raises(AuthorizationError):
        _render(self_kernel, ALICE)


def test_a_manage_grant_alone_does_not_open_the_view_path(self_kernel: Kernel) -> None:
    """§38.3: the kinds are not interchangeable, at runtime and not only in metadata."""
    _seed(self_kernel, ALICE, comment="alice-only-marker")
    self_kernel.authorization_management.create_principal(ALICE, actor="tests")
    self_kernel.authorization_management.grant_capability(
        ALICE,
        SELF_REPORT_MANAGE,
        _self_scope(ALICE),
        actor="tests",
    )

    with pytest.raises(AuthorizationError):
        _render(self_kernel, ALICE)


# --- self isolation (§38.7) ------------------------------------------------


def test_the_report_returns_only_the_callers_own_rows(self_kernel: Kernel) -> None:
    _seed(self_kernel, ALICE, month="2026-08", comment="alice-first")
    _seed(self_kernel, ALICE, month="2026-08", entry_date="2026-08-11", comment="alice-second")
    _seed(self_kernel, BOB, month="2026-07", entry_date="2026-07-02", comment="bob-only-marker")
    _grant_view(self_kernel, ALICE)
    _grant_view(self_kernel, BOB)

    alice = _render(self_kernel, ALICE)
    bob = _render(self_kernel, BOB)

    assert alice.principal_id == ALICE
    assert "alice-first" in alice.render()
    assert "alice-second" in alice.render()
    assert "bob-only-marker" not in alice.render()
    assert "bob-only-marker" in bob.render()
    assert "alice" not in bob.render()
    # The generic shaping engine groups the caller's rows by month.
    assert [group.key for group in alice.sections[0].groups] == [("2026-08",)]
    assert alice.sections[0].groups[0].count == 2
    assert [group.key for group in bob.sections[0].groups] == [("2026-07",)]


def test_the_dataset_contract_filters_by_the_core_resolved_principal(
    self_kernel: Kernel,
) -> None:
    _seed(self_kernel, ALICE, comment="alice-only-marker")
    _seed(self_kernel, BOB, comment="bob-only-marker")
    _grant_view(self_kernel, ALICE)
    _grant_view(self_kernel, BOB)

    dataset = _dataset(self_kernel, ALICE)

    assert dataset.dataset_id == SELF_MONTHLY_DATASET_ID
    assert "alice-only-marker" in " ".join(" ".join(row) for row in dataset.rows)
    assert "bob-only-marker" not in " ".join(" ".join(row) for row in dataset.rows)


def test_the_request_carries_no_principal_a_caller_could_trust() -> None:
    """The only input is an organization that may narrow, never widen."""
    assert tuple(f.name for f in fields(SelfReportRequest)) == ("organization_id",)


def test_a_foreign_organization_request_is_denied(self_kernel: Kernel) -> None:
    _seed(self_kernel, ALICE, organization_id=ORG, comment="alice-only-marker")
    _grant_view(self_kernel, ALICE)
    handle = _handle(self_kernel, ALICE, organization_id=ORG)

    with pytest.raises(AuthorizationError):
        _render(self_kernel, ALICE, organization_id="org-foreign", handle=handle)


# --- handle enforcement (§38.8, §38.9) ------------------------------------


def test_a_missing_forged_expired_or_revoked_handle_is_denied(self_kernel: Kernel) -> None:
    _seed(self_kernel, ALICE, comment="alice-only-marker")
    _grant_view(self_kernel, ALICE)

    with pytest.raises(AuthorizationError):
        _plugin(self_kernel).render(SelfReportRequest(), execution_handle=None)  # type: ignore[arg-type]
    with pytest.raises(AuthorizationError):
        _render(self_kernel, ALICE, handle=object.__new__(ExecutionHandle))  # type: ignore[arg-type]

    expired = _handle(self_kernel, ALICE, ttl_seconds=1)
    time.sleep(1.1)
    with pytest.raises(AuthorizationError):
        _render(self_kernel, ALICE, handle=expired)

    revoked = _handle(self_kernel, ALICE)
    assert self_kernel.revoke_execution_handle(revoked) is True
    with pytest.raises(AuthorizationError):
        _render(self_kernel, ALICE, handle=revoked)


# --- channel parity (§38.4) ------------------------------------------------


def test_ai_access_requires_core_policy_and_assistant_use(self_kernel: Kernel) -> None:
    _seed(self_kernel, ALICE, comment="alice-only-marker")
    _grant_view(self_kernel, ALICE)
    ai_handle = _handle(self_kernel, ALICE, channel=Channel.AI)

    with pytest.raises(AuthorizationError):
        _render(self_kernel, ALICE, handle=ai_handle)

    self_kernel.authorization_management.register_policy(
        "self.monthly.report.ai",
        date.min,
        capability=str(SELF_REPORT_VIEW),
        action=SELF_REPORT_ACTION,
        channel=Channel.AI,
    )
    with pytest.raises(AuthorizationError):
        _render(self_kernel, ALICE, handle=ai_handle)

    self_kernel.authorization_management.grant_capability(
        ALICE,
        ASSISTANT_USE,
        _self_scope(ALICE),
        actor="tests",
    )
    report = _render(self_kernel, ALICE, handle=ai_handle)

    assert "alice-only-marker" in report.render()


# --- composability with Report Studio (§13, §26, §38.6) ------------------


def _grant_org_render(kernel: Kernel, actor: str) -> ExecutionHandle:
    kernel.enable("report_studio")
    assign_role_for_test(kernel, actor, "role.report_renderer", Scope(organization_id=ORG))
    kernel.authorization_management.create_principal(actor, actor="tests")
    return kernel.issue_execution_handle(
        principal_id=actor,
        capability=REPORT_RENDER,
        action="report.render",
        scope=Scope(organization_id=ORG),
        channel=Channel.WEB,
    )


def _studio(kernel: Kernel) -> ReportStudioPlugin:
    instance = kernel._instances["report_studio"]
    assert isinstance(instance, ReportStudioPlugin)
    return instance


def test_an_organization_report_is_unaffected_by_the_self_scoped_dataset(
    self_kernel: Kernel,
) -> None:
    """A self-scoped dataset contributes nothing and breaks nothing (§13)."""
    _seed(self_kernel, ALICE, organization_id=ORG, comment="alice-only-marker")
    _grant_view(self_kernel, ALICE)
    handle = _grant_org_render(self_kernel, "org.report.reader")

    report = _studio(self_kernel).render(
        ReportRequest(organization_id=ORG),
        execution_handle=handle,
    )

    assert [dataset.dataset_id for dataset in report.datasets] == [SELF_MONTHLY_DATASET_ID]
    assert report.datasets[0].rows == ()
    assert "alice-only-marker" not in report.render()


def test_report_studio_discovers_the_self_definition_through_the_contract(
    self_kernel: Kernel,
) -> None:
    _seed(self_kernel, ALICE, organization_id=ORG, comment="alice-only-marker")
    _grant_view(self_kernel, ALICE)
    handle = _grant_org_render(self_kernel, "org.report.reader")

    report = _studio(self_kernel).render_definition(
        ReportRequest(organization_id=ORG),
        USE_CASE_ID,
        execution_handle=handle,
    )

    section = report.sections[0]
    assert section.dataset_id == SELF_MONTHLY_DATASET_ID
    assert section.title == SELF_MONTHLY_REPORT.title
    assert section.groups == ()
    assert report.audit_id is not None


def test_rendering_records_an_audit_record(
    self_kernel: Kernel,
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    _seed(self_kernel, ALICE, comment="alice-only-marker")
    _grant_view(self_kernel, ALICE)

    report = _render(self_kernel, ALICE)

    assert report.audit_id is not None
    with uow_factory() as uow:
        assert any(
            record.action == "self.monthly.report.rendered"
            and record.details.get("use_case_id") == USE_CASE_ID
            for record in uow.audit.all(limit=50)
        )


# --- the slice boundaries --------------------------------------------------


def test_the_first_release_is_on_demand_only() -> None:
    source = Path(inspect.getfile(SelfReportingPlugin)).read_text(encoding="utf-8")
    assert "context.scheduling" not in source
    assert "schedule(" not in source
    # §38.1: schedule metadata is optional and deferred, not declared.
    assert "schedule" not in {f.name for f in fields(UseCaseMetadata)}


def test_the_plugin_reads_no_foreign_table_and_no_sqlite_engine() -> None:
    source = Path(inspect.getfile(SelfReportingPlugin)).read_text(encoding="utf-8").lower()
    for foreign in ("sqlite", "att_", "workplace", "attendance", "construction", "payroll"):
        assert foreign not in source

    sources = Path(__file__).parents[1].joinpath("src").rglob("*.py")
    assert not [
        path.name for path in sources if "sqlite" in path.read_text(encoding="utf-8").lower()
    ]


def test_the_viewer_role_carries_only_the_view_capability(self_kernel: Kernel) -> None:
    viewer = next(
        role
        for role in self_kernel.authorization_management.list_roles()
        if role.role_id == SELF_REPORT_VIEWER_ROLE
    )

    assert viewer.capabilities == frozenset({SELF_REPORT_VIEW})
    assert viewer.owner_plugin_id == "self_reporting"


def test_capability_kinds_are_declared_separately_for_schedule_and_manage() -> None:
    """§38.3: view, schedule and manage are not interchangeable."""
    assert CapabilityKind.VIEW != CapabilityKind.SCHEDULE != CapabilityKind.MANAGE
    assert SELF_MONTHLY_REPORT.use_case is not None
    assert SELF_MONTHLY_REPORT.use_case.required_capabilities == (SELF_REPORT_VIEW,)
    assert CapabilityId("self.monthly.report.schedule") not in (
        SELF_MONTHLY_REPORT.use_case.required_capabilities
    )
