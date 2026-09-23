"""Manifest and dependency validation (contract sections 5, 16 and 18)."""

from __future__ import annotations

import pytest

from atlas_core.domain.clusters import INITIAL_CLUSTERS
from atlas_core.infrastructure.registry import (
    assert_dependencies,
    assert_valid,
    check_dependencies,
    validate_cluster,
    validate_manifest,
)
from atlas_sdk import PluginDependencyError, PluginManifest, PluginValidationError

KNOWN_CLUSTERS = [c.cluster_id for c in INITIAL_CLUSTERS]


def _manifest(**overrides: object) -> PluginManifest:
    fields: dict[str, object] = {
        "plugin_id": "demo.plugin",
        "name": "Demo Plugin",
        "version": "0.1.0",
        "cluster_id": "cluster.information_and_documents",
    }
    fields.update(overrides)
    return PluginManifest(**fields)  # type: ignore[arg-type]


def test_a_valid_manifest_has_no_errors() -> None:
    assert validate_manifest(_manifest()) == []


def test_orphan_plugin_is_rejected() -> None:
    """Contract section 5: no plugin may exist without a cluster."""
    errors = validate_manifest(_manifest(cluster_id=""))

    assert any("cluster_id is required" in e for e in errors)


def test_missing_identity_fields_are_reported_together() -> None:
    errors = validate_manifest(
        _manifest(plugin_id="", name="", version="", cluster_id=""),
    )

    joined = " ".join(errors)
    assert "plugin_id is required" in joined
    assert "name is required" in joined
    assert "version is required" in joined
    assert "cluster_id is required" in joined


def test_duplicate_module_ids_are_rejected() -> None:
    from atlas_sdk import ModuleDeclaration

    errors = validate_manifest(
        _manifest(
            modules=(
                ModuleDeclaration(module_id="demo.one"),
                ModuleDeclaration(module_id="demo.one"),
            ),
        ),
    )

    assert any("duplicate module ids" in e for e in errors)


def test_a_capability_cannot_be_both_provided_and_consumed() -> None:
    from atlas_sdk import CapabilityId

    errors = validate_manifest(
        _manifest(
            provides_capabilities=(CapabilityId("demo.thing"),),
            consumes_capabilities=(CapabilityId("demo.thing"),),
        ),
    )

    assert any("both provided and consumed" in e for e in errors)


def test_requires_core_is_checked() -> None:
    assert validate_manifest(_manifest(requires_core="0.1.0")) == []
    assert validate_manifest(_manifest(requires_core="0.1.*")) == []
    errors = validate_manifest(_manifest(requires_core="9.9.9"))
    assert any("requires_core" in e for e in errors)


def test_unknown_cluster_is_rejected() -> None:

    errors = validate_cluster("cluster.nope", KNOWN_CLUSTERS)
    assert any("unknown cluster_id" in e for e in errors)

    assert validate_cluster("cluster.information_and_documents", KNOWN_CLUSTERS) == []


def test_assert_valid_raises_on_orphan() -> None:
    with pytest.raises(PluginValidationError) as exc_info:
        assert_valid(_manifest(cluster_id=""), KNOWN_CLUSTERS)

    assert exc_info.value.plugin_id == "demo.plugin"
    assert any("cluster_id is required" in e for e in exc_info.value.errors)


def test_dependency_check_reports_missing_requirements() -> None:
    from atlas_sdk import PluginManifest

    manifest = PluginManifest(
        plugin_id="payroll",
        name="Payroll",
        version="0.1.0",
        cluster_id="cluster.employee_finance",
        requires_plugins=("attendance", "leave"),
    )

    errors = check_dependencies(manifest, available=["leave"])
    assert errors == ["requires plugin 'attendance', which is not registered"]


def test_dependency_check_passes_when_requirements_are_present() -> None:
    from atlas_sdk import PluginManifest

    manifest = PluginManifest(
        plugin_id="payroll",
        name="Payroll",
        version="0.1.0",
        cluster_id="cluster.employee_finance",
        requires_plugins=("attendance",),
    )

    assert check_dependencies(manifest, available=["attendance", "payroll"]) == []


def test_assert_dependencies_raises_when_unmet() -> None:
    from atlas_sdk import PluginManifest

    manifest = PluginManifest(
        plugin_id="payroll",
        name="Payroll",
        version="0.1.0",
        cluster_id="cluster.employee_finance",
        requires_plugins=("attendance",),
    )

    with pytest.raises(PluginDependencyError) as exc_info:
        assert_dependencies(manifest, available=[])

    assert exc_info.value.plugin_id == "payroll"
