"""Capability registry behaviour."""

from __future__ import annotations

from atlas_core.infrastructure.registry import InMemoryCapabilityRegistry
from atlas_sdk import CapabilityId


def test_register_and_query_providers() -> None:
    registry = InMemoryCapabilityRegistry()
    registry.register(CapabilityId("report.dataset"), "report.studio")
    registry.register(CapabilityId("report.dataset"), "other.plugin")

    assert registry.exists(CapabilityId("report.dataset"))
    assert registry.providers_of(CapabilityId("report.dataset")) == [
        "report.studio",
        "other.plugin",
    ]


def test_providers_are_deduplicated() -> None:
    registry = InMemoryCapabilityRegistry()
    registry.register(CapabilityId("report.dataset"), "report.studio")
    registry.register(CapabilityId("report.dataset"), "report.studio")

    assert registry.providers_of(CapabilityId("report.dataset")) == ["report.studio"]


def test_provided_by_lists_a_plugins_capabilities() -> None:
    registry = InMemoryCapabilityRegistry()
    registry.register(CapabilityId("report.dataset"), "report.studio")
    registry.register(CapabilityId("report.render"), "report.studio")
    registry.register(CapabilityId("attendance.read"), "attendance")

    assert set(registry.provided_by("report.studio")) == {
        CapabilityId("report.dataset"),
        CapabilityId("report.render"),
    }
    assert registry.provided_by("ghost") == []


def test_unregistered_capability_is_absent() -> None:
    registry = InMemoryCapabilityRegistry()

    assert not registry.exists(CapabilityId("nope"))
    assert registry.providers_of(CapabilityId("nope")) == []
    assert registry.all() == []
