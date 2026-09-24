"""In-memory registries behind the SDK registry ports (contract section 2)."""

from __future__ import annotations

from .registries import (
    InMemoryCapabilityRegistry,
    InMemoryClusterRegistry,
    InMemoryContractRegistry,
    InMemoryEventRegistry,
    InMemoryPluginRegistry,
    TransactionOwner,
)
from .validation import (
    CORE_VERSION,
    assert_dependencies,
    assert_valid,
    check_dependencies,
    validate_cluster,
    validate_manifest,
)

__all__ = [
    "CORE_VERSION",
    "InMemoryCapabilityRegistry",
    "InMemoryClusterRegistry",
    "InMemoryContractRegistry",
    "InMemoryEventRegistry",
    "InMemoryPluginRegistry",
    "TransactionOwner",
    "assert_dependencies",
    "assert_valid",
    "check_dependencies",
    "validate_cluster",
    "validate_manifest",
]
