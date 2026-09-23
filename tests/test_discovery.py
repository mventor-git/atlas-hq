"""Plugin discovery via entry points (contract sections 17 and 30).

Each test writes a real distribution (module + ``.dist-info`` with an
``atlas.plugins`` entry point) onto ``sys.path``. ``importlib.metadata`` finds
it exactly as it finds any installed package — no core file is edited and no
folder is scanned.
"""

from __future__ import annotations

from pathlib import Path

from tests.synthetic import TEST_ENTRY_POINT_GROUP, refresh_metadata_cache, write_distribution

from atlas_core.infrastructure.discovery import (
    PLUGIN_ENTRY_POINT_GROUP,
    discover_plugins,
)
from atlas_sdk import Plugin, PluginDiscoveryError, PluginManifest


def test_group_name_matches_the_contract() -> None:
    assert PLUGIN_ENTRY_POINT_GROUP == "atlas.plugins"


def test_discovers_an_installed_distribution(
    isolated_plugins: Path,
) -> None:
    """A plugin exposing the entry point is found without touching core."""
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-report-studio",
        module_name="synthetic_report_studio",
        class_name="ReportStudioPlugin",
        plugin_id="report.studio",
        plugin_name="Atlas Report Studio",
        cluster_id="cluster.information_and_documents",
        provides_capabilities=("report.dataset",),
        publishes_events=("report.generated",),
    )
    refresh_metadata_cache()

    discovered = discover_plugins(TEST_ENTRY_POINT_GROUP)

    assert len(discovered) == 1
    found = discovered[0]
    assert found.plugin_id == "report.studio"
    assert found.distribution == "synthetic-report-studio"
    assert found.entry_point == "synthetic_report_studio:ReportStudioPlugin"
    assert issubclass(found.plugin_class, Plugin)

    manifest = found.manifest
    assert isinstance(manifest, PluginManifest)
    assert manifest.plugin_id == "report.studio"
    assert manifest.cluster_id == "cluster.information_and_documents"
    assert "report.dataset" in manifest.provides_capabilities
    assert "report.generated" in manifest.publishes_events


def test_discovered_manifest_carries_modules_and_contracts(
    isolated_plugins: Path,
) -> None:
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-attendance",
        module_name="synthetic_attendance",
        class_name="AttendancePlugin",
        plugin_id="attendance",
        plugin_name="Attendance",
        cluster_id="cluster.workforce_and_time",
        modules=("attendance.daily",),
        provides_contracts=(("attendance.daily_summary", "1.0"),),
        consumes_contracts=("employee.assignment",),
        publishes_events=("attendance.checked_in", "attendance.day_closed"),
        subscribes_events=("employee.assigned",),
    )
    refresh_metadata_cache()

    found = discover_plugins(TEST_ENTRY_POINT_GROUP)[0]
    manifest = found.manifest

    assert manifest.module_ids() == ("attendance.daily",)
    assert [c.contract_id for c in manifest.provides_contracts] == ["attendance.daily_summary"]
    assert list(manifest.consumes_contracts) == ["employee.assignment"]
    assert set(manifest.publishes_events) == {
        "attendance.checked_in",
        "attendance.day_closed",
    }
    assert list(manifest.subscribes_events) == ["employee.assigned"]


def test_discovering_two_distributions(isolated_plugins: Path) -> None:
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-a",
        module_name="synthetic_a",
        class_name="PluginA",
        plugin_id="alpha.plugin",
    )
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-b",
        module_name="synthetic_b",
        class_name="PluginB",
        plugin_id="beta.plugin",
    )
    refresh_metadata_cache()

    ids = sorted(p.plugin_id for p in discover_plugins(TEST_ENTRY_POINT_GROUP))
    assert ids == ["alpha.plugin", "beta.plugin"]


def test_a_distribution_without_the_group_is_ignored(
    isolated_plugins: Path,
) -> None:
    """A package that does not advertise the group simply is not a plugin."""
    (isolated_plugins / "plain_module.py").write_text("value = 1\n", encoding="utf-8")
    dist_info = isolated_plugins / "plain-package-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: plain-package\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    refresh_metadata_cache()

    assert discover_plugins(TEST_ENTRY_POINT_GROUP) == []


def test_an_unloadable_entry_point_raises_discovery_error(
    isolated_plugins: Path,
) -> None:
    """A broken distribution is reported loudly, not silently skipped (§18)."""
    dist_info = isolated_plugins / "broken-plugin-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: broken-plugin\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        "[" + TEST_ENTRY_POINT_GROUP + "]\nbroken = nonexistent_module:NoSuchClass\n",
        encoding="utf-8",
    )
    refresh_metadata_cache()

    try:
        discover_plugins(TEST_ENTRY_POINT_GROUP)
    except PluginDiscoveryError as exc:
        assert "broken" in str(exc)
        assert "synthetic" not in str(exc) or "broken" in str(exc)
    else:
        raise AssertionError("expected PluginDiscoveryError for an unloadable entry point")


def test_an_entry_point_that_is_not_a_plugin_raises(
    isolated_plugins: Path,
) -> None:
    (isolated_plugins / "not_a_plugin.py").write_text(
        "class Widget:\n    pass\n",
        encoding="utf-8",
    )
    dist_info = isolated_plugins / "not-a-plugin-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: not-a-plugin\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        f"[{TEST_ENTRY_POINT_GROUP}]\nwidget = not_a_plugin:Widget\n",
        encoding="utf-8",
    )
    refresh_metadata_cache()

    try:
        discover_plugins(TEST_ENTRY_POINT_GROUP)
    except PluginDiscoveryError as exc:
        assert "atlas_sdk.Plugin" in str(exc)
    else:
        raise AssertionError("expected PluginDiscoveryError for a non-Plugin entry point")


def test_discovery_reads_no_core_plugin_folder() -> None:
    """Contract section 30: discovery must not be a folder scanner.

    The ``src`` tree contains no ``plugins`` directory, and discovery never
    globs the filesystem — it reads distribution metadata only.
    """
    import atlas_core

    core_pkg = Path(atlas_core.__file__).parent
    assert not (core_pkg / "plugins").exists()
    assert not list(core_pkg.glob("**/plugins"))
