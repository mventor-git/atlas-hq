"""Event registry behaviour: publishers, subscribers and cross-plugin wiring."""

from __future__ import annotations

from atlas_core.infrastructure.registry import InMemoryEventRegistry
from atlas_sdk import EventId


def test_register_publisher_and_subscriber() -> None:
    registry = InMemoryEventRegistry()
    registry.register_published(EventId("attendance.checked_in"), "attendance")
    registry.register_subscribed(EventId("attendance.checked_in"), "payroll")

    assert registry.exists(EventId("attendance.checked_in"))
    assert registry.publishers_of(EventId("attendance.checked_in")) == ["attendance"]
    assert registry.subscribers_of(EventId("attendance.checked_in")) == ["payroll"]


def test_published_by_and_subscribed_by() -> None:
    registry = InMemoryEventRegistry()
    registry.register_published(EventId("attendance.checked_in"), "attendance")
    registry.register_published(EventId("attendance.day_closed"), "attendance")
    registry.register_subscribed(EventId("attendance.checked_in"), "payroll")

    assert set(registry.published_by("attendance")) == {
        EventId("attendance.checked_in"),
        EventId("attendance.day_closed"),
    }
    assert registry.subscribed_by("payroll") == (EventId("attendance.checked_in"),)
    assert registry.published_by("ghost") == ()


def test_all_lists_union_of_publishers_and_subscribers() -> None:
    registry = InMemoryEventRegistry()
    registry.register_published(EventId("a.published"), "plugin.a")
    registry.register_subscribed(EventId("b.subscribed"), "plugin.b")

    assert set(registry.all()) == {EventId("a.published"), EventId("b.subscribed")}


def test_subscribers_and_publishers_are_sorted_and_deduplicated() -> None:
    registry = InMemoryEventRegistry()
    registry.register_subscribed(EventId("e"), "zeta")
    registry.register_subscribed(EventId("e"), "alpha")
    registry.register_subscribed(EventId("e"), "alpha")

    assert registry.subscribers_of(EventId("e")) == ["alpha", "zeta"]


def test_unknown_event_reports_absent() -> None:
    registry = InMemoryEventRegistry()

    assert not registry.exists(EventId("nope"))
    assert registry.publishers_of(EventId("nope")) == []
    assert registry.subscribers_of(EventId("nope")) == []
