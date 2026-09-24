"""Gate O — composable reporting (contract sections 13 and 26).

The generic-render tests boot the real distribution and never import dataset
providers. Separate definition tests import the fixed construction plugin to
prove ownership, then reach real data only through registered contracts.
"""

from __future__ import annotations

import inspect
import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import cast

import pytest
from tests.synthetic import refresh_metadata_cache

from atlas_core.application.organization import OrganizationService
from atlas_core.application.people import PeopleService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.infrastructure.events import OutboxEventPublisher
from atlas_core.kernel import Kernel
from atlas_plugins.construction_reporting import CONSTRUCTION_DAILY_WORKFORCE
from atlas_plugins.report_studio import (
    REPORT_GENERATED,
    RenderedReport,
    ReportRequest,
    ReportStudioPlugin,
    ShapedDataset,
)
from atlas_sdk import (
    AuthorizationError,
    CapabilityId,
    ContractId,
    DomainEvent,
    NotFoundError,
    WorkplaceType,
)

ACTOR = "user.report_admin"
CONSTRUCTION_TEST_ENTRY_POINT_GROUP = "atlas.test.construction-reporting"


@pytest.fixture
def report_kernel(real_kernel: Kernel) -> Kernel:
    """Boot the real distribution with every plugin enabled."""
    real_kernel.boot()
    for plugin_id in ("report_studio", "workforce_summary", "attendance_summary"):
        real_kernel.enable(plugin_id)
    return real_kernel


@pytest.fixture
def org(uow_factory: Callable[[], UnitOfWorkPort]) -> str:
    with uow_factory() as uow:
        return (
            OrganizationService(uow).create_organization(name="Acme", code="ACME").organization_id
        )


def _grant(kernel: Kernel, org_id: str) -> None:
    context = kernel.context_for("report_studio")
    context.authorization.grant(ACTOR, "role.report_renderer", context.scope.resolve(org_id))


def test_report_studio_consumes_two_providers_without_knowing_them(
    report_kernel: Kernel,
    org: str,
) -> None:
    """Both installed providers contribute. No provider is named in code."""
    _grant(report_kernel, org)

    report = _render(report_kernel, org)

    titles = {dataset.title for dataset in report.datasets}
    assert len(report.datasets) == 2, titles
    # The two providers live in different plugins (contract section 26).
    assert "Workforce Summary" in titles
    assert "Attendance Summary" in titles


def test_disabling_one_provider_adapts_the_report(report_kernel: Kernel, org: str) -> None:
    """Disable one provider and Report Studio composes only what remains."""
    _grant(report_kernel, org)
    assert len(_render(report_kernel, org).datasets) == 2

    report_kernel.disable("attendance_summary")

    remaining = _render(report_kernel, org)
    assert len(remaining.datasets) == 1
    assert remaining.datasets[0].title == "Workforce Summary"


def test_no_providers_installed_still_renders(report_kernel: Kernel, org: str) -> None:
    """A report with no providers is empty, not an error."""
    _grant(report_kernel, org)
    report_kernel.disable("workforce_summary")
    report_kernel.disable("attendance_summary")

    report = _render(report_kernel, org)
    assert report.datasets == []
    assert "no dataset providers installed" in report.render()


def test_rendering_requires_the_capability(report_kernel: Kernel, org: str) -> None:
    """Gate M: without the grant the render is denied."""
    with pytest.raises(AuthorizationError):
        _render(report_kernel, org)


def test_render_is_scope_limited(report_kernel: Kernel, org: str) -> None:
    """Gate N: an actor granted in a different scope cannot render this org."""
    context = report_kernel.context_for("report_studio")
    foreign = context.scope.resolve("org_foreign_scope")
    context.authorization.grant(ACTOR, "role.report_renderer", foreign)

    with pytest.raises(AuthorizationError):
        _render(report_kernel, org)


def test_report_studio_source_has_no_construction_or_workplace_type_knowledge() -> None:
    source = Path(inspect.getfile(ReportStudioPlugin)).read_text(encoding="utf-8").lower()

    assert "construction" not in source
    assert "workplace" not in source
    assert "site" not in source


def _render(kernel: Kernel, org_id: str) -> RenderedReport:
    """Invoke Report Studio through the live plugin instance — never through a
    direct import of any dataset provider."""
    instance = kernel._instances["report_studio"]
    assert isinstance(instance, ReportStudioPlugin)
    return instance.render(ReportRequest(organization_id=org_id, actor_id=ACTOR))


def test_fixed_construction_reporting_entry_point_is_discovered_and_registered(
    uow_factory: Callable[[], UnitOfWorkPort],
    isolated_plugins: Path,
) -> None:
    pyproject = tomllib.loads(
        (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    )
    assert (
        pyproject["project"]["entry-points"]["atlas.plugins"]["construction_reporting"]
        == "atlas_plugins.construction_reporting:ConstructionReportingPlugin"
    )

    dist_info = isolated_plugins / "construction-reporting-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: construction-reporting\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        f"[{CONSTRUCTION_TEST_ENTRY_POINT_GROUP}]\n"
        "construction_reporting = "
        "atlas_plugins.construction_reporting:ConstructionReportingPlugin\n",
        encoding="utf-8",
    )
    refresh_metadata_cache()
    kernel = Kernel(
        uow_factory=uow_factory,
        entry_point_group=CONSTRUCTION_TEST_ENTRY_POINT_GROUP,
    )

    result = kernel.boot()

    assert result.registered == 1
    manifest = kernel.registries.plugins.get("construction_reporting")
    assert manifest.cluster_id == "cluster.information_and_documents"
    assert manifest.module_ids() == ("construction.reporting",)
    assert manifest.modules[0].provides == ("report.definition",)
    assert manifest.modules[0].supports == (CapabilityId("report.render"),)
    assert manifest.provides_capabilities == ()
    assert [declaration.contract_id for declaration in manifest.provides_contracts] == [
        ContractId("report.definition")
    ]
    response = cast(
        "Mapping[str, object]",
        manifest.provides_contracts[0].schema["response"],
    )
    properties = cast("Mapping[str, object]", response["properties"])
    filters = cast("Mapping[str, object]", properties["filters"])
    assert filters["items"] == {
        "type": "object",
        "properties": {"column": {"type": "string"}, "value": {"type": "string"}},
        "required": ["column", "value"],
    }


# --- contract section 28: construction daily workforce reporting ------------


@pytest.fixture
def construction_kernel(
    uow_factory: Callable[[], UnitOfWorkPort],
    isolated_plugins: Path,
) -> Kernel:
    """The three real plugins behind an isolated entry-point distribution.

    The test process may have an older editable-install metadata snapshot, so it
    advertises the same pyproject targets through its own group without changing
    the installed environment. Product discovery remains metadata-driven.
    """
    dist_info = isolated_plugins / "atlas-hq-construction-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: atlas-hq-construction\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        f"[{CONSTRUCTION_TEST_ENTRY_POINT_GROUP}]\n"
        "report_studio = atlas_plugins.report_studio:ReportStudioPlugin\n"
        "workplace_operations = "
        "atlas_plugins.workplace_operations:WorkplaceOperationsPlugin\n"
        "construction_reporting = "
        "atlas_plugins.construction_reporting:ConstructionReportingPlugin\n",
        encoding="utf-8",
    )
    refresh_metadata_cache()
    kernel = Kernel(
        uow_factory=uow_factory,
        entry_point_group=CONSTRUCTION_TEST_ENTRY_POINT_GROUP,
    )
    kernel.boot()
    kernel.enable("workplace_operations")
    kernel.enable("construction_reporting")
    kernel.enable("report_studio")
    return kernel


@pytest.fixture
def construction_org(
    construction_kernel: Kernel,
    uow_factory: Callable[[], UnitOfWorkPort],
) -> tuple[str, tuple[str, str]]:
    """One org, two employees, two workplaces: one site, one office."""
    with uow_factory() as uow:
        org = OrganizationService(uow).create_organization(name="Build", code="BUILD")
        people = PeopleService(uow, OutboxEventPublisher(uow, publisher="seed"))
        ada = people.create_employee(
            full_name="Ada Lovelace",
            employee_number="EMP-1",
            organization_id=org.organization_id,
        )
        grace = people.create_employee(
            full_name="Grace Hopper",
            employee_number="EMP-2",
            organization_id=org.organization_id,
        )
    # The actor must be able to both build the workforce and read the report.
    workplace_context = construction_kernel.context_for("workplace_operations")
    report_context = construction_kernel.context_for("report_studio")
    scope = report_context.scope.resolve(org.organization_id)
    workplace_context.authorization.grant("user.workplace_admin", "role.workplace_manager", scope)
    report_context.authorization.grant(ACTOR, "role.report_renderer", scope)

    from atlas_plugins.workplace_operations import (
        WorkforceMembershipRequest,
        WorkplaceOperationsPlugin,
        WorkplaceRequest,
    )

    workplace_admin = "user.workplace_admin"
    workplace = construction_kernel._instances["workplace_operations"]
    assert isinstance(workplace, WorkplaceOperationsPlugin)
    # A real construction site with two members.
    site = workplace.create_workplace(
        WorkplaceRequest(
            organization_id=org.organization_id,
            name="Riverside Tower",
            code="RT-01",
            kind=WorkplaceType.SITE,
            actor_id=workplace_admin,
        ),
    )
    for employee_id in (ada.employee_id, grace.employee_id):
        workplace.add_workforce_member(
            WorkforceMembershipRequest(
                workplace_id=site.workplace_id, employee_id=employee_id, actor_id=workplace_admin
            ),
        )
    # A non-site workplace with one member — must NOT appear in the site report.
    office = workplace.create_workplace(
        WorkplaceRequest(
            organization_id=org.organization_id,
            name="Headquarters",
            code="HQ-01",
            kind=WorkplaceType.OFFICE,
            actor_id=workplace_admin,
        ),
    )
    workplace.add_workforce_member(
        WorkforceMembershipRequest(
            workplace_id=office.workplace_id, employee_id=ada.employee_id, actor_id=workplace_admin
        ),
    )
    return org.organization_id, (ada.employee_id, grace.employee_id)


def _render_definition(kernel: Kernel, org_id: str) -> RenderedReport:
    instance = kernel._instances["report_studio"]
    assert isinstance(instance, ReportStudioPlugin)
    return instance.render_definition(
        ReportRequest(organization_id=org_id, actor_id=ACTOR),
        CONSTRUCTION_DAILY_WORKFORCE.definition_id,
    )


def test_the_daily_workforce_report_renders_real_site_data(
    construction_kernel: Kernel,
    construction_org: tuple[str, tuple[str, str]],
) -> None:
    """Contract section 28: the report composes real HR + workplace data."""
    org_id, _employees = construction_org

    report = _render_definition(construction_kernel, org_id)

    assert report.organization_id == org_id
    assert len(report.sections) == 1
    section = report.sections[0]
    assert isinstance(section, ShapedDataset)
    assert section.installed is True
    assert section.dataset_id == "workplace.workforce"
    assert section.title == "Construction Daily Workforce Report"
    assert CONSTRUCTION_DAILY_WORKFORCE.group_by == ("workplace_code", "workplace_name")
    assert CONSTRUCTION_DAILY_WORKFORCE.detail_columns == ("employee_number", "full_name")
    # Only the site survives the filter; the office does not.
    assert len(section.groups) == 1
    group = section.groups[0]
    assert group.key == ("RT-01", "Riverside Tower")
    assert group.count == 2, group.rows
    names = {row[1] for row in group.rows}
    assert names == {"Ada Lovelace", "Grace Hopper"}


def test_fixed_definition_handler_is_read_only_at_the_contract_seam(
    construction_kernel: Kernel,
    construction_org: tuple[str, tuple[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id, _employees = construction_org
    provider_context = construction_kernel.context_for("construction_reporting")

    def forbidden_run(operation: Callable[[], object]) -> object:
        raise AssertionError("a bound definition handler must not open a transaction")

    monkeypatch.setattr(provider_context.transactions, "run", forbidden_run)

    assert _render_definition(construction_kernel, org_id).audit_id is not None


def test_unknown_definition_has_a_clear_not_found_error(
    construction_kernel: Kernel,
    construction_org: tuple[str, tuple[str, str]],
) -> None:
    org_id, _employees = construction_org
    instance = construction_kernel._instances["report_studio"]
    assert isinstance(instance, ReportStudioPlugin)

    with pytest.raises(NotFoundError, match="missing.definition") as caught:
        instance.render_definition(
            ReportRequest(organization_id=org_id, actor_id=ACTOR),
            "missing.definition",
        )

    assert caught.value.kind == "report_definition"
    assert caught.value.key == "missing.definition"


def test_disabling_the_fixed_plugin_makes_the_definition_unavailable(
    construction_kernel: Kernel,
    construction_org: tuple[str, tuple[str, str]],
) -> None:
    org_id, _employees = construction_org

    construction_kernel.disable("construction_reporting")

    with pytest.raises(NotFoundError, match="construction.daily_workforce"):
        _render_definition(construction_kernel, org_id)


def test_the_daily_workforce_report_filters_to_sites_only(
    construction_kernel: Kernel,
    construction_org: tuple[str, tuple[str, str]],
) -> None:
    """``workplace_kind == 'site'`` keeps the site and drops the office."""
    org_id, _employees = construction_org

    section = _render_definition(construction_kernel, org_id).sections[0]

    assert {group.key[0] for group in section.groups} == {"RT-01"}
    assert sum(group.count for group in section.groups) == 2
    # The office's member is real, but it is not a construction site.
    assert all("HQ-01" not in group.key[0] for group in section.groups)


def test_the_daily_workforce_report_counts_headcount_correctly(
    construction_kernel: Kernel,
    construction_org: tuple[str, tuple[str, str]],
) -> None:
    """Headcount is the per-group aggregation over real memberships."""
    org_id, _employees = construction_org

    section = _render_definition(construction_kernel, org_id).sections[0]

    assert section.groups[0].count == len(section.groups[0].rows)
    assert section.groups[0].count == 2
    assert section.columns == ("employee_number", "full_name")
    assert {row[0] for row in section.groups[0].rows} == {"EMP-1", "EMP-2"}


def test_the_daily_workforce_report_records_audit(
    construction_kernel: Kernel,
    construction_org: tuple[str, tuple[str, str]],
) -> None:
    """Gate L: rendering the definition writes a real audit record."""
    org_id, _employees = construction_org

    report = _render_definition(construction_kernel, org_id)

    assert report.audit_id is not None
    context = construction_kernel.context_for("report_studio")
    records = context.audit.list_records(organization_id=org_id, limit=20)
    assert any(
        r.action == "report.rendered"
        and r.details.get("definition_id") == CONSTRUCTION_DAILY_WORKFORCE.definition_id
        for r in records
    )


def test_the_daily_workforce_report_publishes_report_generated(
    construction_kernel: Kernel,
    construction_org: tuple[str, tuple[str, str]],
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    """``report.generated`` is published for every definition render."""
    org_id, _employees = construction_org

    _render_definition(construction_kernel, org_id)

    # The event is registered (Gate H) and committed to the outbox (§21).
    assert construction_kernel.registries.events.publishers_of(REPORT_GENERATED) == [
        "report_studio"
    ]
    with uow_factory() as uow:
        pending = uow.outbox.pending(limit=20)
    assert any(e.event_id == REPORT_GENERATED for e in pending)
    assert any(
        e.event.payload.get("definition_id") == CONSTRUCTION_DAILY_WORKFORCE.definition_id
        for e in pending
    )


def test_a_definition_whose_dataset_is_not_installed_degrades_gracefully(
    construction_kernel: Kernel,
    construction_org: tuple[str, tuple[str, str]],
) -> None:
    """The fixed definition remains available when its dataset provider is not."""
    org_id, _employees = construction_org
    construction_kernel.disable("workplace_operations")

    report = _render_definition(construction_kernel, org_id)

    assert len(report.sections) == 1
    section = report.sections[0]
    assert section.installed is False
    assert "not installed" in (section.note or "")
    rendered = report.render()
    assert "dataset workplace.workforce is not installed" in rendered
    assert report.audit_id is not None  # the attempt is still auditable.


def test_rendering_a_definition_requires_the_capability(
    construction_kernel: Kernel,
    construction_org: tuple[str, tuple[str, str]],
) -> None:
    """Gate M applies to shaped reports too — an un-granted actor is denied."""
    org_id, _employees = construction_org

    with pytest.raises(AuthorizationError):
        instance = construction_kernel._instances["report_studio"]
        assert isinstance(instance, ReportStudioPlugin)
        instance.render_definition(
            ReportRequest(organization_id=org_id, actor_id="user.unauthorized"),
            CONSTRUCTION_DAILY_WORKFORCE.definition_id,
        )


def test_definition_rendering_is_scope_limited(
    construction_kernel: Kernel,
    construction_org: tuple[str, tuple[str, str]],
) -> None:
    org_id, _employees = construction_org
    context = construction_kernel.context_for("report_studio")
    foreign_actor = "user.foreign_scope"
    context.authorization.grant(
        foreign_actor,
        "role.report_renderer",
        context.scope.resolve("org_foreign_scope"),
    )
    instance = construction_kernel._instances["report_studio"]
    assert isinstance(instance, ReportStudioPlugin)

    with pytest.raises(AuthorizationError):
        instance.render_definition(
            ReportRequest(organization_id=org_id, actor_id=foreign_actor),
            CONSTRUCTION_DAILY_WORKFORCE.definition_id,
        )


def test_definition_render_failure_rolls_back_audit_and_outbox(
    construction_kernel: Kernel,
    construction_org: tuple[str, tuple[str, str]],
    uow_factory: Callable[[], UnitOfWorkPort],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id, _employees = construction_org
    context = construction_kernel.context_for("report_studio")
    original_publish = context.events.publish

    def publish_then_fail(event: DomainEvent) -> None:
        original_publish(event)
        raise RuntimeError("report publication failed")

    monkeypatch.setattr(context.events, "publish", publish_then_fail)

    with pytest.raises(RuntimeError, match="report publication failed"):
        _render_definition(construction_kernel, org_id)

    with uow_factory() as uow:
        audits = uow.audit.all(organization_id=org_id, limit=50)
        pending = uow.outbox.pending(limit=50)

    assert not any(
        record.action == "report.rendered"
        and record.details.get("definition_id") == CONSTRUCTION_DAILY_WORKFORCE.definition_id
        for record in audits
    )
    assert not any(
        envelope.event_id == REPORT_GENERATED
        and envelope.event.payload.get("definition_id")
        == CONSTRUCTION_DAILY_WORKFORCE.definition_id
        for envelope in pending
    )
