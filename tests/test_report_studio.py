"""Gate O — composable reporting (contract sections 13 and 26).

The acceptance test the contract demands: install a dataset provider, Report
Studio finds it; install a second, it finds both; disable one, it adapts — with
no change to Report Studio source. The proof is that this file never imports
the provider plugins; it only boots the real distribution and toggles plugins
through the lifecycle.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from atlas_core.application.organization import OrganizationService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.kernel import Kernel
from atlas_plugins.report_studio import RenderedReport, ReportRequest, ReportStudioPlugin
from atlas_sdk import AuthorizationError

ACTOR = "user.report_admin"


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


def _render(kernel: Kernel, org_id: str) -> RenderedReport:
    """Invoke Report Studio through the live plugin instance — never through a
    direct import of any dataset provider."""
    instance = kernel._instances["report_studio"]
    assert isinstance(instance, ReportStudioPlugin)
    return instance.render(ReportRequest(organization_id=org_id, actor_id=ACTOR))
