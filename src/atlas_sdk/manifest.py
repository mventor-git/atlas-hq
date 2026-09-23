"""Plugin, module and cluster manifests (contract sections 15, 16 and 19).

These dataclasses are the *declarative* surface of the platform. The core
inspects a manifest before a plugin is ever enabled (contract section 16), so
manifests must be introspectable plain data — no behaviour, no imports of core
internals.

The mandatory ``cluster_id`` on every plugin enforces contract section 5:
no orphan plugins.
"""

from __future__ import annotations

from dataclasses import dataclass

from .capability import CapabilityId
from .contract import ContractDeclaration, ContractId
from .event import EventId


@dataclass(frozen=True)
class ModuleDeclaration:
    """A functional component inside a plugin (contract section 15).

    A module declares what it provides, consumes, publishes and subscribes to.
    """

    module_id: str
    provides: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    publishes: tuple[EventId, ...] = ()
    subscribes: tuple[EventId, ...] = ()
    requires: tuple[str, ...] = ()
    supports: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginManifest:
    """The complete declaration of one plugin (contract sections 5 and 16).

    ``cluster_id`` is mandatory: a manifest without it is rejected during
    validation (no orphan plugins).
    """

    plugin_id: str
    name: str
    version: str
    cluster_id: str
    requires_core: str | None = None
    #: Plugins this plugin cannot run without. Section 5 calls these ``dependencies``.
    requires_plugins: tuple[str, ...] = ()
    modules: tuple[ModuleDeclaration, ...] = ()
    provides_capabilities: tuple[CapabilityId, ...] = ()
    consumes_capabilities: tuple[CapabilityId, ...] = ()
    provides_contracts: tuple[ContractDeclaration, ...] = ()
    consumes_contracts: tuple[ContractId, ...] = ()
    publishes_events: tuple[EventId, ...] = ()
    subscribes_events: tuple[EventId, ...] = ()

    def module_ids(self) -> tuple[str, ...]:
        return tuple(m.module_id for m in self.modules)


@dataclass(frozen=True)
class ClusterManifest:
    """The declaration of a cluster (contract section 19).

    Cluster membership is *business coherence*, not a hard dependency: an
    optional plugin is listed in ``optional_plugins`` and may be absent without
    breaking the cluster.
    """

    cluster_id: str
    name: str
    description: str = ""
    shared_capabilities: tuple[CapabilityId, ...] = ()
    shared_contracts: tuple[ContractId, ...] = ()
    optional_plugins: tuple[str, ...] = ()
    anchor_plugins: tuple[str, ...] = ()


__all__ = ["ClusterManifest", "ModuleDeclaration", "PluginManifest"]
