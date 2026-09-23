"""Manifest and dependency validation (contract sections 5, 16 and 18).

Validation runs *before* a plugin touches the registry, so a malformed
declaration never becomes visible to other plugins. The checks are deliberately
plain data introspection — deterministic, no magic (contract section 14).
"""

from __future__ import annotations

from collections.abc import Iterable

from atlas_sdk import PluginDependencyError, PluginManifest, PluginValidationError

#: The core version this build advertises to ``requires_core`` checks.
CORE_VERSION = "0.1.0"


def validate_manifest(manifest: PluginManifest) -> list[str]:
    """Return the reasons a manifest is rejected, or an empty list if it is sound.

    The caller decides whether an empty list means "register" or "next stage";
    raising here would lose the ability to report every problem at once.
    """
    errors: list[str] = []

    # contract section 5 — no orphan plugins. This is the hard rule.
    if not manifest.cluster_id or not manifest.cluster_id.strip():
        errors.append(
            "cluster_id is required: a plugin may not exist without a cluster (contract section 5)",
        )

    if not manifest.plugin_id or not manifest.plugin_id.strip():
        errors.append("plugin_id is required")
    if not manifest.name or not manifest.name.strip():
        errors.append("name is required")
    if not manifest.version or not manifest.version.strip():
        errors.append("version is required")

    module_ids = [m.module_id for m in manifest.modules]
    if len(set(module_ids)) != len(module_ids):
        duplicates = sorted({m for m in module_ids if module_ids.count(m) > 1})
        errors.append(f"duplicate module ids: {', '.join(duplicates)}")

    provided = {c for c in manifest.provides_capabilities}
    conflicting = provided & set(manifest.consumes_capabilities)
    if conflicting:
        errors.append(
            f"a capability cannot be both provided and consumed: {', '.join(sorted(conflicting))}",
        )

    for declaration in manifest.provides_contracts:
        if not declaration.contract_id or not declaration.contract_id.strip():
            errors.append("a provided contract must declare a contract_id")

    required_core = manifest.requires_core
    if (
        required_core is not None
        and required_core.strip()
        and not _core_satisfies(
            required_core,
        )
    ):
        errors.append(
            f"requires_core {manifest.requires_core!r} is not satisfied by core {CORE_VERSION!r}",
        )
    return errors


def _core_satisfies(requirement: str) -> bool:
    """Minimal ``requires_core`` handling: exact match or same major series.

    ponytail: a full PEP 440 resolver is out of scope for D1; no installed
    plugin exercises ranges yet. Upgrade here when a real requirement appears.
    """
    requirement = requirement.strip()
    if requirement == CORE_VERSION:
        return True
    if requirement.endswith(".*"):
        return CORE_VERSION.startswith(requirement[:-2])
    return False


def validate_cluster(manifest_cluster_id: str, known_clusters: Iterable[str]) -> list[str]:
    """Reject a plugin whose declared cluster is not a registered cluster."""
    known = set(known_clusters)
    if manifest_cluster_id and manifest_cluster_id not in known:
        return [
            f"unknown cluster_id {manifest_cluster_id!r}; known clusters are: "
            f"{', '.join(sorted(known)) or '<none>'}",
        ]
    return []


def check_dependencies(
    manifest: PluginManifest,
    available: Iterable[str],
) -> list[str]:
    """Return the reasons a plugin's declared dependencies are unmet.

    ``available`` is the set of plugin ids already registered (or about to be).
    Cluster membership is deliberately *not* treated as a dependency
    (contract section 19).
    """
    available = set(available)
    errors: list[str] = []
    for required in manifest.requires_plugins:
        if required not in available:
            errors.append(f"requires plugin {required!r}, which is not registered")
    return errors


def assert_valid(manifest: PluginManifest, known_clusters: Iterable[str]) -> None:
    """Raise unless ``manifest`` passes every validation stage."""
    errors = validate_manifest(manifest)
    errors.extend(validate_cluster(manifest.cluster_id, known_clusters))
    if errors:
        raise PluginValidationError(manifest.plugin_id, errors)


def assert_dependencies(manifest: PluginManifest, available: Iterable[str]) -> None:
    errors = check_dependencies(manifest, available)
    if errors:
        raise PluginDependencyError(manifest.plugin_id, errors)


__all__ = [
    "CORE_VERSION",
    "assert_dependencies",
    "assert_valid",
    "check_dependencies",
    "validate_cluster",
    "validate_manifest",
]
