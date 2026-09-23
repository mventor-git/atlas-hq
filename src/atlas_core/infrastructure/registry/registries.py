"""In-memory implementations of the five SDK registry ports.

These are the D1 backing store for platform truth. They are deliberately
in-memory: registries hold *declarations*, which are small and read constantly
at boot, while business state lives in the persistence layer. A durable backing
store can swap in behind these ports unchanged.

Every registry rejects duplicates and unknown lookups with the SDK error
hierarchy, so a plugin that mis-declares itself gets a precise error instead of
silently overwriting another plugin's entry.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from typing import Any

from atlas_sdk import (
    AlreadyRegisteredError,
    CapabilityId,
    ContractDeclaration,
    ContractId,
    ContractImplementation,
    EventId,
    NotFoundError,
    PluginLifecycle,
    PluginManifest,
)
from atlas_sdk.manifest import ClusterManifest

from ...domain.clusters import INITIAL_CLUSTERS


def _rollback_safely(commit: Callable[[], None]) -> None:
    """Roll back the unit of work behind a registered commit hook.

    A handler that raises must leave no half-applied state behind. The rollback
    lives on the same unit of work as ``commit`` (``uow.rollback``), reached
    through the bound method rather than a second registry entry.
    """
    rollback = getattr(getattr(commit, "__self__", None), "rollback", None)
    if callable(rollback):
        rollback()


class InMemoryClusterRegistry:
    """Adapts :class:`~atlas_sdk.registry.ClusterRegistryPort`.

    Seeded with the eight initial clusters (contract section 7). The map stays
    extensible: registering a new cluster uses exactly the same path as the
    seed.
    """

    def __init__(self) -> None:
        self._clusters: dict[str, ClusterManifest] = {}
        for manifest in INITIAL_CLUSTERS:
            self._clusters[manifest.cluster_id] = manifest

    def register(self, manifest: ClusterManifest) -> None:
        if manifest.cluster_id in self._clusters:
            raise AlreadyRegisteredError(
                f"cluster {manifest.cluster_id!r} is already registered",
                kind="cluster",
                key=manifest.cluster_id,
            )
        self._clusters[manifest.cluster_id] = manifest

    def get(self, cluster_id: str) -> ClusterManifest:
        found = self._clusters.get(cluster_id)
        if found is None:
            raise NotFoundError(
                f"no cluster registered as {cluster_id!r}",
                kind="cluster",
                key=cluster_id,
            )
        return found

    def all(self) -> list[ClusterManifest]:
        return list(self._clusters.values())

    def exists(self, cluster_id: str) -> bool:
        return cluster_id in self._clusters


class InMemoryPluginRegistry:
    """Adapts :class:`~atlas_sdk.registry.PluginRegistryPort`.

    Tracks the lifecycle of every plugin id it has ever seen, including ones
    that failed: a FAILED plugin stays visible in the registry with its reason,
    which is what makes "a broken plugin must not silently corrupt the core"
    (contract section 18) observable rather than invisible.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, PluginManifest] = {}
        self._states: dict[str, PluginLifecycle] = {}
        self._reasons: dict[str, str] = {}

    def register(self, manifest: PluginManifest) -> None:
        if manifest.plugin_id in self._plugins:
            raise AlreadyRegisteredError(
                f"plugin {manifest.plugin_id!r} is already registered",
                kind="plugin",
                key=manifest.plugin_id,
            )
        self._plugins[manifest.plugin_id] = manifest
        self._states[manifest.plugin_id] = PluginLifecycle.REGISTERED
        self._reasons.pop(manifest.plugin_id, None)

    def get(self, plugin_id: str) -> PluginManifest:
        found = self._plugins.get(plugin_id)
        if found is None:
            raise NotFoundError(
                f"no plugin registered as {plugin_id!r}",
                kind="plugin",
                key=plugin_id,
            )
        return found

    def all(self) -> list[PluginManifest]:
        return list(self._plugins.values())

    def list_by_cluster(self, cluster_id: str) -> list[PluginManifest]:
        return [m for m in self._plugins.values() if m.cluster_id == cluster_id]

    def exists(self, plugin_id: str) -> bool:
        return plugin_id in self._plugins

    def lifecycle_state(self, plugin_id: str) -> PluginLifecycle:
        state = self._states.get(plugin_id)
        if state is None:
            raise NotFoundError(
                f"no lifecycle recorded for plugin {plugin_id!r}",
                kind="plugin_lifecycle",
                key=plugin_id,
            )
        return state

    def mark(self, plugin_id: str, state: PluginLifecycle, reason: str | None = None) -> None:
        """Record a lifecycle transition.

        Pre-registration states (DISCOVERED, VALIDATED, DEPENDENCIES_CHECKED, and
        the FAILED terminal) belong to ids that are not registered yet, so
        marking is allowed for any id — that is what makes the boot path
        observable. ``register`` clears a stale reason when a plugin recovers.
        """
        self._states[plugin_id] = state
        if reason is not None:
            self._reasons[plugin_id] = reason
        elif state is not PluginLifecycle.FAILED:
            self._reasons.pop(plugin_id, None)

    def failure_reason(self, plugin_id: str) -> str | None:
        return self._reasons.get(plugin_id)


class InMemoryCapabilityRegistry:
    """Adapts :class:`~atlas_sdk.registry.CapabilityRegistryPort`."""

    def __init__(self) -> None:
        self._providers: dict[CapabilityId, list[str]] = {}

    def register(self, capability: CapabilityId, plugin_id: str) -> None:
        providers = self._providers.setdefault(capability, [])
        if plugin_id not in providers:
            providers.append(plugin_id)

    def all(self) -> list[CapabilityId]:
        return list(self._providers)

    def exists(self, capability: CapabilityId) -> bool:
        return capability in self._providers

    def providers_of(self, capability: CapabilityId) -> list[str]:
        return list(self._providers.get(capability, []))

    def provided_by(self, plugin_id: str) -> list[CapabilityId]:
        return [cap for cap, providers in self._providers.items() if plugin_id in providers]


class InMemoryContractRegistry:
    """Adapts :class:`~atlas_sdk.registry.ContractRegistryPort`.

    Every implementation of a contract is kept, not just the first: composability
    (contract section 13) depends on a consumer being able to ask "who provides
    this?" and learn there may be several.

    Binding is the runtime half that makes Gate I real: a declaration is indexed
    at boot, but the live handler is only attached when its plugin is enabled and
    detached when it is disabled. ``invoke`` on an unbound contract raises, so a
    disabled plugin's contracts are genuinely uncallable.
    """

    def __init__(self) -> None:
        self._declarations: list[ContractImplementation] = []
        self._bindings: dict[tuple[str, str], Any] = {}
        #: plugin_id -> commit callback. The kernel supplies one per enabled
        #: plugin; a contract invocation commits the provider's unit of work so
        #: the state change and its outbox event land together (contract section 21).
        #: A plugin that is not enabled has no entry, so its contracts cannot run.
        self._committers: dict[str, Callable[[], None]] = {}

    def register(self, declaration: ContractDeclaration, plugin_id: str) -> None:
        self._declarations.append(
            ContractImplementation(declaration=declaration, plugin_id=plugin_id),
        )

    def _view(self, impl: ContractImplementation) -> ContractImplementation:
        """The declaration with its bound instance attached, if the plugin is on."""
        instance = self._bindings.get((str(impl.declaration.contract_id), impl.plugin_id))
        if instance is None:
            return impl
        return replace(impl, instance=instance)

    def get(self, contract_id: ContractId) -> ContractImplementation:
        for impl in self._declarations:
            if impl.declaration.contract_id == contract_id:
                return self._view(impl)
        raise NotFoundError(
            f"no contract registered as {contract_id!r}",
            kind="contract",
            key=contract_id,
        )

    def all(self) -> list[ContractImplementation]:
        return [self._view(impl) for impl in self._declarations]

    def exists(self, contract_id: ContractId) -> bool:
        return any(impl.declaration.contract_id == contract_id for impl in self._declarations)

    def implementations_of(self, contract_id: ContractId) -> list[ContractImplementation]:
        return [
            self._view(impl)
            for impl in self._declarations
            if impl.declaration.contract_id == contract_id
        ]

    def provided_by(self, plugin_id: str) -> list[ContractImplementation]:
        return [self._view(impl) for impl in self._declarations if impl.plugin_id == plugin_id]

    # --- runtime half ------------------------------------------------------

    def register_committer(self, plugin_id: str, commit: Callable[[], None]) -> None:
        self._committers[plugin_id] = commit

    def bind(self, contract_id: ContractId, plugin_id: str, instance: object) -> None:
        key = (str(contract_id), plugin_id)
        if not any(
            impl.declaration.contract_id == contract_id and impl.plugin_id == plugin_id
            for impl in self._declarations
        ):
            raise NotFoundError(
                f"plugin {plugin_id!r} cannot bind {contract_id!r}: it declares no such contract",
                kind="contract",
                key=contract_id,
            )
        self._bindings[key] = instance

    def unbind(self, plugin_id: str) -> None:
        self._bindings = {
            key: value for key, value in self._bindings.items() if key[1] != plugin_id
        }
        self._committers.pop(plugin_id, None)

    def _bound(self, contract_id: ContractId) -> list[tuple[str, Any]]:
        return [
            (pid, value) for (cid, pid), value in self._bindings.items() if cid == str(contract_id)
        ]

    def invoke(self, contract_id: ContractId, request: object) -> object:
        bound = self._bound(contract_id)
        if not bound:
            raise NotFoundError(
                f"no enabled implementation of contract {contract_id!r}",
                kind="contract_binding",
                key=contract_id,
            )
        plugin_id, instance = bound[0]
        return self._invoke_one(contract_id, plugin_id, instance, request)

    def invoke_all(self, contract_id: ContractId, request: object) -> list[object]:
        return [
            self._invoke_one(contract_id, plugin_id, instance, request)
            for plugin_id, instance in self._bound(contract_id)
        ]

    def _invoke_one(
        self,
        contract_id: ContractId,
        plugin_id: str,
        instance: Any,
        request: object,
    ) -> object:
        """Run one handler inside its provider's transaction.

        Committing here — not inside the plugin — is deliberate. A plugin never
        manages the transaction itself; the platform guarantees that a state
        change and the event it published commit together or not at all
        (contract section 21).
        """
        commit = self._committers.get(plugin_id)
        try:
            result = instance.handle(request)
        except Exception:
            if commit is not None:
                _rollback_safely(commit)
            raise
        if commit is not None:
            commit()
        return result


class InMemoryEventRegistry:
    """Adapts :class:`~atlas_sdk.registry.EventRegistryPort`.

    Publishers and subscribers are indexed separately. A plugin may publish an
    event it does not subscribe to and vice versa; the registry keeps both
    directions so a consumer can find every interested party without a scan.
    """

    def __init__(self) -> None:
        self._publishers: dict[EventId, set[str]] = {}
        self._subscribers: dict[EventId, set[str]] = {}

    def register_published(self, event: EventId, plugin_id: str) -> None:
        self._publishers.setdefault(event, set()).add(plugin_id)

    def register_subscribed(self, event: EventId, plugin_id: str) -> None:
        self._subscribers.setdefault(event, set()).add(plugin_id)

    def all(self) -> list[EventId]:
        seen: dict[str, None] = {}
        for event in (*self._publishers, *self._subscribers):
            seen[event] = None
        return [EventId(e) for e in seen]

    def exists(self, event: EventId) -> bool:
        return event in self._publishers or event in self._subscribers

    def publishers_of(self, event: EventId) -> list[str]:
        return sorted(self._publishers.get(event, set()))

    def subscribers_of(self, event: EventId) -> list[str]:
        return sorted(self._subscribers.get(event, set()))

    def published_by(self, plugin_id: str) -> Sequence[EventId]:
        return tuple(e for e, plugins in self._publishers.items() if plugin_id in plugins)

    def subscribed_by(self, plugin_id: str) -> Sequence[EventId]:
        return tuple(e for e, plugins in self._subscribers.items() if plugin_id in plugins)


__all__ = [
    "InMemoryCapabilityRegistry",
    "InMemoryClusterRegistry",
    "InMemoryContractRegistry",
    "InMemoryEventRegistry",
    "InMemoryPluginRegistry",
]
