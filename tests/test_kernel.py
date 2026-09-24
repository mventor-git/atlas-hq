"""Kernel boot: discovery -> validation -> dependency check -> registration.

This is the D1 acceptance path. It proves the registries are seeded, a plugin
arriving through discovery lands in the right cluster with its capabilities,
contracts and events indexed, and a broken plugin is recorded as FAILED rather
than aborting the core (contract section 18).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from tests.synthetic import TEST_ENTRY_POINT_GROUP, refresh_metadata_cache, write_distribution

from atlas_core.infrastructure.persistence.unit_of_work import SqlUnitOfWork
from atlas_core.kernel import Kernel
from atlas_sdk import (
    CapabilityId,
    ContractId,
    EventId,
    PluginLifecycle,
)


def test_boot_seeds_the_initial_clusters(kernel: Kernel) -> None:
    result = kernel.boot()

    assert result.discovered == 0
    assert result.is_clean
    assert len(kernel.registries.clusters.all()) == 8


def test_boot_registers_a_discovered_plugin(kernel: Kernel, isolated_plugins: Path) -> None:
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-report-studio",
        module_name="synthetic_report_studio",
        class_name="ReportStudio",
        plugin_id="report.studio",
        plugin_name="Atlas Report Studio",
        cluster_id="cluster.information_and_documents",
        provides_capabilities=("report.dataset",),
        provides_contracts=(("report.dataset", "1.0"),),
        publishes_events=("report.generated",),
        subscribes_events=("employee.created",),
    )
    refresh_metadata_cache()

    result = kernel.boot()

    assert result.discovered == 1
    assert result.registered == 1
    assert result.is_clean

    plugins = kernel.registries.plugins
    assert plugins.exists("report.studio")
    assert plugins.lifecycle_state("report.studio") is PluginLifecycle.REGISTERED
    assert [m.plugin_id for m in plugins.list_by_cluster("cluster.information_and_documents")] == [
        "report.studio"
    ]


def test_registration_indexes_capabilities_contracts_and_events(
    kernel: Kernel,
    isolated_plugins: Path,
) -> None:
    """Gates D through H: everything the plugin declares becomes discoverable."""
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-attendance",
        module_name="synthetic_attendance",
        class_name="Attendance",
        plugin_id="attendance",
        plugin_name="Attendance",
        cluster_id="cluster.workforce_and_time",
        provides_capabilities=("attendance.read",),
        provides_contracts=(("attendance.daily_summary", "1.0"),),
        publishes_events=("attendance.checked_in",),
        subscribes_events=("employee.created",),
    )
    refresh_metadata_cache()

    kernel.boot()

    assert kernel.registries.capabilities.exists(CapabilityId("attendance.read"))
    assert "attendance" in kernel.registries.capabilities.providers_of(
        CapabilityId("attendance.read")
    )

    impl = kernel.registries.contracts.get(ContractId("attendance.daily_summary"))
    assert impl.plugin_id == "attendance"

    assert "attendance" in kernel.registries.events.publishers_of(EventId("attendance.checked_in"))
    assert "attendance" in kernel.registries.events.subscribers_of(EventId("employee.created"))


def test_a_plugin_whose_dependency_is_absent_fails_cleanly(
    kernel: Kernel,
    isolated_plugins: Path,
) -> None:
    """An unmet dependency marks the plugin FAILED and does not stop the boot."""
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-payroll",
        module_name="synthetic_payroll",
        class_name="Payroll",
        plugin_id="payroll",
        plugin_name="Payroll",
        cluster_id="cluster.employee_finance",
        requires_plugins=("attendance",),
    )
    refresh_metadata_cache()

    result = kernel.boot()

    assert result.discovered == 1
    assert result.registered == 0
    assert not result.is_clean

    plugins = kernel.registries.plugins
    assert plugins.lifecycle_state("payroll") is PluginLifecycle.FAILED
    assert plugins.failure_reason("payroll") is not None
    assert "attendance" in (plugins.failure_reason("payroll") or "")


def test_dependencies_are_satisfied_by_a_registered_plugin(
    kernel: Kernel,
    isolated_plugins: Path,
) -> None:
    """A consumer boots when its dependency is discovered in the same run."""
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-attendance",
        module_name="synthetic_attendance",
        class_name="Attendance",
        plugin_id="attendance",
        plugin_name="Attendance",
        cluster_id="cluster.workforce_and_time",
        publishes_events=("attendance.checked_in",),
    )
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-payroll",
        module_name="synthetic_payroll",
        class_name="Payroll",
        plugin_id="payroll",
        plugin_name="Payroll",
        cluster_id="cluster.employee_finance",
        requires_plugins=("attendance",),
    )
    refresh_metadata_cache()

    result = kernel.boot()

    assert result.discovered == 2
    assert result.registered == 2
    assert result.is_clean
    assert kernel.registries.plugins.lifecycle_state("payroll") is PluginLifecycle.REGISTERED


def test_boot_retries_a_dependency_discovered_before_its_provider(
    isolated_plugins: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payroll_metadata = isolated_plugins / "payroll-metadata"
    payroll_metadata.mkdir()
    write_distribution(
        payroll_metadata,
        distribution_name="synthetic-payroll",
        module_name="synthetic_payroll",
        class_name="Payroll",
        plugin_id="payroll",
        plugin_name="Payroll",
        cluster_id="cluster.employee_finance",
        requires_plugins=("attendance",),
    )
    attendance_metadata = isolated_plugins / "attendance-metadata"
    attendance_metadata.mkdir()
    write_distribution(
        attendance_metadata,
        distribution_name="synthetic-attendance",
        module_name="synthetic_attendance",
        class_name="Attendance",
        plugin_id="attendance",
        plugin_name="Attendance",
        cluster_id="cluster.workforce_and_time",
    )
    monkeypatch.syspath_prepend(str(attendance_metadata))
    monkeypatch.syspath_prepend(str(payroll_metadata))
    refresh_metadata_cache()

    result = Kernel(entry_point_group=TEST_ENTRY_POINT_GROUP).boot()

    assert result.discovered == 2
    assert result.registered == 2
    assert result.is_clean
    assert result.failed == []


def test_boot_isolates_a_conflicting_plugin_from_an_unrelated_plugin(
    isolated_plugins: Path,
) -> None:
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-conflict-a",
        module_name="synthetic_conflict_a",
        class_name="PluginA",
        plugin_id="duplicate.plugin",
    )
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-conflict-b",
        module_name="synthetic_conflict_b",
        class_name="PluginB",
        plugin_id="duplicate.plugin",
    )
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-unrelated",
        module_name="synthetic_unrelated",
        class_name="Unrelated",
        plugin_id="unrelated.plugin",
    )
    refresh_metadata_cache()

    kernel = Kernel(entry_point_group=TEST_ENTRY_POINT_GROUP)
    result = kernel.boot()

    assert result.discovered == 2
    assert result.registered == 1
    assert not result.is_clean
    assert (
        kernel.registries.plugins.lifecycle_state("unrelated.plugin") is PluginLifecycle.REGISTERED
    )
    assert kernel.registries.plugins.lifecycle_state("duplicate.plugin") is PluginLifecycle.FAILED
    reason = kernel.registries.plugins.failure_reason("duplicate.plugin") or ""
    assert "synthetic-conflict-a" in reason
    assert "synthetic-conflict-b" in reason


def test_an_orphan_plugin_is_rejected_with_a_clear_error(
    kernel: Kernel,
    isolated_plugins: Path,
) -> None:
    """Contract section 5: a manifest with no cluster_id never registers."""
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-orphan",
        module_name="synthetic_orphan",
        class_name="Orphan",
        plugin_id="orphan.plugin",
        plugin_name="Orphan",
        cluster_id="",
    )
    refresh_metadata_cache()

    result = kernel.boot()

    assert result.discovered == 1
    assert result.registered == 0
    assert not kernel.registries.plugins.exists("orphan.plugin")
    assert kernel.registries.plugins.lifecycle_state("orphan.plugin") is PluginLifecycle.FAILED
    reason = kernel.registries.plugins.failure_reason("orphan.plugin") or ""
    assert "cluster_id is required" in reason


def test_a_plugin_from_an_unknown_cluster_is_rejected(
    kernel: Kernel,
    isolated_plugins: Path,
) -> None:
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-lost",
        module_name="synthetic_lost",
        class_name="Lost",
        plugin_id="lost.plugin",
        plugin_name="Lost",
        cluster_id="cluster.does_not_exist",
    )
    refresh_metadata_cache()

    result = kernel.boot()

    assert result.registered == 0
    assert kernel.registries.plugins.lifecycle_state("lost.plugin") is PluginLifecycle.FAILED
    lost_reason = kernel.registries.plugins.failure_reason("lost.plugin") or ""
    assert "unknown cluster_id" in lost_reason


def test_booting_twice_is_idempotent(kernel: Kernel) -> None:
    """Clusters are seeded once; a second boot does not duplicate them."""
    kernel.boot()
    kernel.boot()

    assert len(kernel.registries.clusters.all()) == 8


def test_a_kernel_without_persistence_still_boots() -> None:
    """Registry boot does not depend on a database being configured."""
    kernel = Kernel(entry_point_group=TEST_ENTRY_POINT_GROUP)
    result = kernel.boot()

    assert result.discovered == 0
    assert len(kernel.registries.clusters.all()) == 8


def test_context_for_builds_a_plugin_context(
    uow_factory: Callable[[], SqlUnitOfWork],
) -> None:
    from atlas_sdk.context import PluginContext

    wired = Kernel(uow_factory=uow_factory)
    context = wired.context_for("report.studio")

    assert isinstance(context, PluginContext)
    assert context.plugin_id == "report.studio"
    assert context.people is not None
    assert context.events is not None
    assert context.contracts is wired.registries.contracts
    assert context.transactions is wired.context_for("report.studio").transactions
    assert not hasattr(context, "unit_of_work")


def test_plugin_persistence_hides_transaction_lifecycle(kernel: Kernel) -> None:
    context = kernel.context_for("report.studio")

    assert not hasattr(context, "sessions")
    persistence = context.persistence
    assert not hasattr(persistence, "begin")
    assert not hasattr(persistence, "commit")
    assert not hasattr(persistence, "rollback")
