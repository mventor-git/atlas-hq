"""Plugin lifecycle: DISCOVERED -> ... -> RUNNING, DISABLED, STOPPED, FAILED.

Gate I. An enabled plugin's contracts are callable through the registry; a
disabled plugin's are not, because its handlers were unbound. A plugin that
fails is marked FAILED and the rest of the platform keeps working (contract
section 18).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.synthetic import (
    TEST_ENTRY_POINT_GROUP,
    refresh_metadata_cache,
    write_distribution,
)

from atlas_core.kernel import Kernel
from atlas_sdk import (
    ContractId,
    NotFoundError,
    PluginLifecycle,
    PluginLifecycleError,
)

GOVERNANCE = "cluster.governance_and_management"


def _write_broken_init(directory: Path) -> None:
    """A plugin whose ``initialize`` raises, in the test-only group."""
    (directory / "synthetic_broken_init.py").write_text(
        "from atlas_sdk import Plugin, PluginManifest\n"
        "class BrokenInitPlugin(Plugin):\n"
        "    manifest = PluginManifest(\n"
        "        plugin_id='broken.init',\n"
        "        name='Broken Init',\n"
        "        version='0.1.0',\n"
        f"        cluster_id={GOVERNANCE!r},\n"
        "    )\n"
        "    def initialize(self, context):\n"
        "        raise RuntimeError('initialize exploded')\n",
        encoding="utf-8",
    )
    dist_info = directory / "broken-init-0.1.0.dist-info"
    dist_info.mkdir(exist_ok=True)
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: broken-init\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        f"[{TEST_ENTRY_POINT_GROUP}]\nbroken-init = synthetic_broken_init:BrokenInitPlugin\n",
        encoding="utf-8",
    )


def _write_attendance(directory: Path, *, contract: bool = False) -> None:
    write_distribution(
        directory,
        distribution_name="synthetic-attendance",
        module_name="synthetic_attendance",
        class_name="Attendance",
        plugin_id="attendance",
        plugin_name="Attendance",
        cluster_id="cluster.workforce_and_time",
        provides_contracts=(("attendance.daily_summary", "1.0"),) if contract else (),
    )


def test_boot_leaves_plugins_registered_but_not_running(
    kernel: Kernel,
    isolated_plugins: Path,
) -> None:
    """Boot reaches REGISTERED; the rest is a deliberate, separate act."""
    _write_attendance(isolated_plugins)
    refresh_metadata_cache()

    result = kernel.boot()

    assert result.registered == 1
    assert kernel.registries.plugins.lifecycle_state("attendance") is PluginLifecycle.REGISTERED


def test_enable_moves_a_plugin_to_enabled(kernel: Kernel, isolated_plugins: Path) -> None:
    _write_attendance(isolated_plugins)
    refresh_metadata_cache()
    kernel.boot()

    kernel.enable("attendance")

    assert kernel.registries.plugins.lifecycle_state("attendance") is PluginLifecycle.ENABLED


def test_mark_running_completes_the_declared_path(
    kernel: Kernel,
    isolated_plugins: Path,
) -> None:
    _write_attendance(isolated_plugins)
    refresh_metadata_cache()
    kernel.boot()
    kernel.enable("attendance")

    kernel.registries.plugins.mark("attendance", PluginLifecycle.RUNNING)

    assert kernel.registries.plugins.lifecycle_state("attendance") is PluginLifecycle.RUNNING


def test_enabling_an_unknown_plugin_is_a_clear_error(kernel: Kernel) -> None:
    with pytest.raises(NotFoundError) as excinfo:
        kernel.enable("no.such.plugin")

    assert "not a registered plugin" in str(excinfo.value)


def test_enabling_a_plugin_that_failed_at_boot_reports_the_reason(
    kernel: Kernel,
    isolated_plugins: Path,
) -> None:
    """A plugin rejected at boot cannot be enabled, and the error says why."""
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
    kernel.boot()

    with pytest.raises(NotFoundError) as excinfo:
        kernel.enable("orphan.plugin")

    assert "rejected at boot" in str(excinfo.value)
    assert "cluster_id is required" in str(excinfo.value)


def test_a_plugin_that_fails_initialize_is_marked_failed_and_isolated(
    kernel: Kernel,
    isolated_plugins: Path,
) -> None:
    """A broken initialize leaves no live instance behind (contract section 18)."""
    _write_broken_init(isolated_plugins)
    refresh_metadata_cache()
    kernel.boot()

    with pytest.raises(PluginLifecycleError) as excinfo:
        kernel.enable("broken.init")

    assert "initialize exploded" in str(excinfo.value)
    assert kernel.registries.plugins.lifecycle_state("broken.init") is PluginLifecycle.FAILED
    assert "broken.init" not in kernel._instances


def test_a_failing_plugin_does_not_stop_the_others(
    kernel: Kernel,
    isolated_plugins: Path,
) -> None:
    """The broken plugin fails; the healthy one still enables."""
    _write_broken_init(isolated_plugins)
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-healthy",
        module_name="synthetic_healthy",
        class_name="Healthy",
        plugin_id="healthy.plugin",
        plugin_name="Healthy",
        cluster_id=GOVERNANCE,
    )
    refresh_metadata_cache()
    kernel.boot()

    with pytest.raises(PluginLifecycleError):
        kernel.enable("broken.init")
    kernel.enable("healthy.plugin")

    assert kernel.registries.plugins.lifecycle_state("broken.init") is PluginLifecycle.FAILED
    assert kernel.registries.plugins.lifecycle_state("healthy.plugin") is PluginLifecycle.ENABLED


def test_disable_unbinds_contracts_so_they_stop_being_callable(
    kernel: Kernel,
    isolated_plugins: Path,
) -> None:
    """The Gate I guarantee: a disabled plugin's contracts are uncallable."""
    _write_attendance(isolated_plugins, contract=True)
    refresh_metadata_cache()
    kernel.boot()
    kernel.enable("attendance")
    contract_id = ContractId("attendance.daily_summary")

    assert kernel.registries.contracts.get(contract_id).is_bound

    kernel.disable("attendance")

    assert kernel.registries.plugins.lifecycle_state("attendance") is PluginLifecycle.DISABLED
    assert not kernel.registries.contracts.get(contract_id).is_bound
    with pytest.raises(NotFoundError):
        kernel.registries.contracts.invoke(contract_id, object())


def test_stop_marks_a_plugin_stopped(kernel: Kernel, isolated_plugins: Path) -> None:
    _write_attendance(isolated_plugins)
    refresh_metadata_cache()
    kernel.boot()
    kernel.enable("attendance")

    kernel.stop("attendance")

    assert kernel.registries.plugins.lifecycle_state("attendance") is PluginLifecycle.STOPPED


def test_enable_all_brings_up_every_bootable_plugin(
    kernel: Kernel,
    isolated_plugins: Path,
) -> None:
    _write_broken_init(isolated_plugins)
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-healthy",
        module_name="synthetic_healthy",
        class_name="Healthy",
        plugin_id="healthy.plugin",
        plugin_name="Healthy",
        cluster_id=GOVERNANCE,
    )
    refresh_metadata_cache()
    kernel.boot()

    assert kernel.registries.plugins.lifecycle_state("broken.init") is PluginLifecycle.REGISTERED
    kernel.enable_all()

    assert kernel.registries.plugins.lifecycle_state("healthy.plugin") is PluginLifecycle.RUNNING
    assert kernel.registries.plugins.lifecycle_state("broken.init") is PluginLifecycle.FAILED


def test_failed_plugins_are_reported_with_reasons(
    kernel: Kernel,
    isolated_plugins: Path,
) -> None:
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

    kernel.boot()

    failed = kernel.failed_plugins()
    assert [plugin_id for plugin_id, _reason in failed] == ["orphan.plugin"]
    assert "cluster_id is required" in failed[0][1]


def test_enabling_twice_is_idempotent(kernel: Kernel, isolated_plugins: Path) -> None:
    _write_attendance(isolated_plugins)
    refresh_metadata_cache()
    kernel.boot()

    kernel.enable("attendance")
    kernel.enable("attendance")

    assert kernel.registries.plugins.lifecycle_state("attendance") is PluginLifecycle.ENABLED
