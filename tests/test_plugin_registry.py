"""Plugin registry behaviour: registration, lookup, lifecycle and failure."""

from __future__ import annotations

import pytest

from atlas_core.infrastructure.registry import InMemoryPluginRegistry
from atlas_sdk import (
    AlreadyRegisteredError,
    NotFoundError,
    PluginLifecycle,
    PluginManifest,
)


def _manifest(
    plugin_id: str, cluster_id: str = "cluster.information_and_documents"
) -> PluginManifest:
    return PluginManifest(
        plugin_id=plugin_id,
        name=plugin_id,
        version="0.1.0",
        cluster_id=cluster_id,
    )


def test_register_and_read_back() -> None:
    registry = InMemoryPluginRegistry()
    registry.register(_manifest("report.studio"))

    assert registry.exists("report.studio")
    assert registry.get("report.studio").plugin_id == "report.studio"
    assert [m.plugin_id for m in registry.all()] == ["report.studio"]


def test_registration_records_the_registered_state() -> None:
    registry = InMemoryPluginRegistry()
    registry.register(_manifest("report.studio"))

    assert registry.lifecycle_state("report.studio") is PluginLifecycle.REGISTERED
    assert registry.failure_reason("report.studio") is None


def test_duplicate_registration_is_rejected() -> None:
    registry = InMemoryPluginRegistry()
    registry.register(_manifest("report.studio"))

    with pytest.raises(AlreadyRegisteredError):
        registry.register(_manifest("report.studio"))


def test_unknown_lookup_raises_not_found() -> None:
    registry = InMemoryPluginRegistry()

    with pytest.raises(NotFoundError):
        registry.get("nope")
    with pytest.raises(NotFoundError):
        registry.lifecycle_state("nope")


def test_list_by_cluster_groups_membership() -> None:
    registry = InMemoryPluginRegistry()
    registry.register(_manifest("report.studio", cluster_id="cluster.information_and_documents"))
    registry.register(_manifest("attendance", cluster_id="cluster.workforce_and_time"))
    registry.register(_manifest("leave", cluster_id="cluster.workforce_and_time"))

    ids = {m.plugin_id for m in registry.list_by_cluster("cluster.workforce_and_time")}
    assert ids == {"attendance", "leave"}


def test_lifecycle_transitions_are_recorded_with_reasons() -> None:
    registry = InMemoryPluginRegistry()
    registry.register(_manifest("report.studio"))

    registry.mark("report.studio", PluginLifecycle.FAILED, "boom")
    assert registry.lifecycle_state("report.studio") is PluginLifecycle.FAILED
    assert registry.failure_reason("report.studio") == "boom"


def test_marking_records_pre_registration_states() -> None:
    """The boot path marks DISCOVERED before a plugin is registered."""
    registry = InMemoryPluginRegistry()

    registry.mark("incoming", PluginLifecycle.DISCOVERED)

    assert registry.lifecycle_state("incoming") is PluginLifecycle.DISCOVERED
    assert not registry.exists("incoming")


def test_a_failed_plugin_stays_visible() -> None:
    """Contract section 18: a broken plugin is recorded, not silently dropped."""
    registry = InMemoryPluginRegistry()
    registry.register(_manifest("report.studio"))
    registry.mark("report.studio", PluginLifecycle.FAILED, "bad manifest")

    assert registry.exists("report.studio")
    assert registry.lifecycle_state("report.studio") is PluginLifecycle.FAILED
