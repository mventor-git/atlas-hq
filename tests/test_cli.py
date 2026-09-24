"""The atlas-hq CLI boots the kernel and prints registry state (contract §24)."""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.synthetic import TEST_ENTRY_POINT_GROUP, refresh_metadata_cache, write_distribution

from atlas_hq.cli import build_parser, main, render_audit, render_json, render_state


def test_parser_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.entry_point_group == "atlas.plugins"
    assert args.json is False


def test_main_with_no_plugins_reports_the_seeded_clusters(
    isolated_plugins: Path,
    capsys: object,
) -> None:
    exit_code = main(["--entry-point-group", TEST_ENTRY_POINT_GROUP])

    assert exit_code == 0
    output = capsys.readouterr().out  # type: ignore[attr-defined]
    assert "Clusters (8):" in output
    assert "cluster.workforce_and_time" in output
    assert "Plugins (0):" in output


def test_main_reports_a_registered_plugin(
    isolated_plugins: Path,
    capsys: object,
) -> None:
    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-report-studio",
        module_name="synthetic_report_studio",
        class_name="ReportStudio",
        plugin_id="report.studio",
        plugin_name="Atlas Report Studio",
        cluster_id="cluster.information_and_documents",
        provides_capabilities=("report.dataset",),
        publishes_events=("report.generated",),
    )
    refresh_metadata_cache()

    exit_code = main(["--entry-point-group", TEST_ENTRY_POINT_GROUP])
    output = capsys.readouterr().out  # type: ignore[attr-defined]

    assert exit_code == 0
    assert "report.studio" in output
    assert "provides capabilities: report.dataset" in output
    assert "publishes events: report.generated" in output
    assert "[registered]" in output
    assert "Capabilities (1):" in output
    assert "Contracts (1):" in output
    assert "synthetic.dataset v1.0 <- report.studio" in output


def test_main_reports_a_failed_plugin(
    isolated_plugins: Path,
    capsys: object,
) -> None:
    """A broken plugin is visible in the report, not hidden."""
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

    exit_code = main(["--entry-point-group", TEST_ENTRY_POINT_GROUP])
    output = capsys.readouterr().out  # type: ignore[attr-defined]

    assert exit_code == 1
    assert "Failed plugins (1):" in output
    assert "orphan.plugin" in output
    assert "cluster_id is required" in output


def test_json_output_is_valid(isolated_plugins: Path) -> None:
    import json

    write_distribution(
        isolated_plugins,
        distribution_name="synthetic-report-studio",
        module_name="synthetic_report_studio",
        class_name="ReportStudio",
        plugin_id="report.studio",
        plugin_name="Atlas Report Studio",
        cluster_id="cluster.information_and_documents",
    )
    refresh_metadata_cache()

    parser = build_parser()
    parser.parse_args(["--json"])
    from atlas_core.kernel import Kernel

    kernel = Kernel(entry_point_group=TEST_ENTRY_POINT_GROUP)
    result = kernel.boot()

    payload = json.loads(render_json(kernel, result))

    assert payload["registered"] == 1
    assert payload["plugins"][0]["plugin_id"] == "report.studio"
    assert payload["plugins"][0]["state"] == "registered"
    assert len(payload["clusters"]) == 8
    assert "report.studio" not in payload["capabilities"]


def test_render_state_names_every_registry() -> None:
    from atlas_core.kernel import Kernel

    kernel = Kernel()
    result = kernel.boot()

    report = render_state(kernel, result)

    assert "Clusters" in report
    assert "Plugins" in report
    assert "Capabilities" in report
    assert "Contracts" in report
    assert "Events" in report


def test_audit_command_requires_database_backed_kernel() -> None:
    from atlas_core.kernel import Kernel

    with pytest.raises(RuntimeError, match="PostgreSQL-backed"):
        render_audit(Kernel(), limit=10)
