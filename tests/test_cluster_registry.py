"""Cluster registry: seeding, registration, and the extensible cluster map."""

from __future__ import annotations

import pytest

from atlas_core.domain.clusters import INITIAL_CLUSTERS
from atlas_core.infrastructure.registry import InMemoryClusterRegistry
from atlas_sdk import AlreadyRegisteredError, NotFoundError
from atlas_sdk.manifest import ClusterManifest


def test_initial_cluster_map_is_seeded() -> None:
    registry = InMemoryClusterRegistry()

    assert len(registry.all()) == len(INITIAL_CLUSTERS)
    assert registry.exists("cluster.workforce_and_time")
    assert registry.exists("cluster.governance_and_management")


def test_seeded_cluster_round_trips() -> None:
    registry = InMemoryClusterRegistry()

    cluster = registry.get("cluster.workplace_and_operations")
    assert cluster.cluster_id == "cluster.workplace_and_operations"
    assert cluster.name == "Workplace & Operations"


def test_a_new_cluster_registers_the_same_way_as_a_seed() -> None:
    """Contract section 7: the map stays extensible — no special-casing."""
    registry = InMemoryClusterRegistry()
    custom = ClusterManifest(
        cluster_id="cluster.custom_ops",
        name="Custom Operations",
        description="A company-specific cluster",
    )

    registry.register(custom)

    assert registry.exists("cluster.custom_ops")
    assert registry.get("cluster.custom_ops").name == "Custom Operations"
    assert len(registry.all()) == len(INITIAL_CLUSTERS) + 1


def test_duplicate_cluster_registration_is_rejected() -> None:
    registry = InMemoryClusterRegistry()

    with pytest.raises(AlreadyRegisteredError):
        registry.register(INITIAL_CLUSTERS[0])


def test_unknown_cluster_lookup_raises() -> None:
    registry = InMemoryClusterRegistry()

    assert not registry.exists("cluster.does_not_exist")
    with pytest.raises(NotFoundError):
        registry.get("cluster.does_not_exist")
