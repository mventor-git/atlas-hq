"""The Atlas boot kernel: builds registries, discovers, validates, registers.

The boot path implements the first half of the plugin lifecycle (contract
section 18)::

    DISCOVERED -> VALIDATED -> DEPENDENCIES_CHECKED -> REGISTERED

and defines the rest (INITIALIZED, ENABLED, RUNNING, plus DISABLED, STOPPED,
UPGRADED, FAILED) so D2's enable/disable work has a state machine to move
through rather than a new one to invent.

A failing plugin is marked FAILED with a recorded reason and the boot continues:
one broken distribution must not stop the core (contract section 18).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from atlas_sdk import (
    ContractId,
    EventId,
    NotFoundError,
    Plugin,
    PluginLifecycle,
    PluginLifecycleError,
    PluginRegistrationError,
)
from atlas_sdk.context import PluginContext

from .application.assignments import AssignmentsService
from .application.audit import AuditService
from .application.authorization import AuthorizationService
from .application.jobs import JobsService
from .application.notification import NotificationService
from .application.organization import OrganizationService
from .application.people import PeopleService
from .application.policy import PolicyService
from .application.scheduling import SchedulingService
from .application.scope import ScopeService
from .application.unit_of_work import UnitOfWorkPort
from .application.workflow import WorkflowService
from .domain.clusters import INITIAL_CLUSTERS
from .infrastructure.discovery import PLUGIN_ENTRY_POINT_GROUP, DiscoveredPlugin, discover_plugins
from .infrastructure.events import EventDispatcher, EventSubscriber, OutboxEventPublisher
from .infrastructure.registry import (
    InMemoryCapabilityRegistry,
    InMemoryClusterRegistry,
    InMemoryContractRegistry,
    InMemoryEventRegistry,
    InMemoryPluginRegistry,
    assert_dependencies,
    assert_valid,
)


@dataclass
class RegistryBundle:
    """The five registries, held together so they boot and report as one unit."""

    clusters: InMemoryClusterRegistry = field(default_factory=InMemoryClusterRegistry)
    plugins: InMemoryPluginRegistry = field(default_factory=InMemoryPluginRegistry)
    capabilities: InMemoryCapabilityRegistry = field(default_factory=InMemoryCapabilityRegistry)
    contracts: InMemoryContractRegistry = field(default_factory=InMemoryContractRegistry)
    events: InMemoryEventRegistry = field(default_factory=InMemoryEventRegistry)


@dataclass
class BootResult:
    """What happened during one boot, for the CLI and tests to report."""

    discovered: int = 0
    registered: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not self.failed


class Kernel:
    """Boots the core and exposes the running registries and services."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWorkPort] | None = None,
        registries: RegistryBundle | None = None,
        entry_point_group: str = PLUGIN_ENTRY_POINT_GROUP,
    ) -> None:
        self.uow_factory = uow_factory
        self.registries = registries if registries is not None else RegistryBundle()
        self.entry_point_group = entry_point_group
        self.dispatcher = (
            EventDispatcher(uow_factory) if uow_factory is not None else EventDispatcher(_noop_uow)
        )
        self.boot_result = BootResult()
        #: plugin_id -> discovered class. Kept so the lifecycle can instantiate
        #: a plugin on enable without re-reading entry points.
        self._plugins: dict[str, DiscoveredPlugin] = {}
        #: plugin_id -> live instance, present only while the plugin is enabled.
        self._instances: dict[str, Plugin] = {}
        #: plugin_id -> its context. One context per plugin so a plugin's
        #: stateful services share one unit of work (see context_for).
        self._contexts: dict[str, PluginContext] = {}
        #: Shared, stateful services. A plugin registers a role at initialize and
        #: a later context must see it, so these live on the kernel, not per call.
        self._authorization = AuthorizationService()
        self._scope = ScopeService()
        self._policy = PolicyService()
        self._workflow = WorkflowService()
        self._notification = NotificationService()
        self._scheduling = SchedulingService()

    # --- construction -----------------------------------------------------

    def context_for(self, plugin_id: str) -> PluginContext:
        """Build the plugin context a registered plugin will receive.

        The dispatcher and contract invoker are wired here so a plugin holds one
        handle (the context) through which it both subscribes to other plugins'
        events and calls their contracts — never their modules.

        One context per plugin, cached: a plugin's stateful services (grants it
        registers, the audit trail it writes) must all share one unit of work,
        and the platform's commit hook must point at that same unit of work.
        """
        cached = self._contexts.get(plugin_id)
        if cached is not None:
            return cached
        uow = self._require_uow_factory()()
        publisher = OutboxEventPublisher(uow, publisher=plugin_id)
        # The platform — not the plugin — owns the transaction (contract §21).
        # Register the commit hook so a contract invocation commits the plugin's
        # state change and its outbox events atomically, or not at all.
        self.registries.contracts.register_committer(plugin_id, uow.commit)
        context = PluginContext(
            plugin_id=plugin_id,
            people=PeopleService(uow, publisher),
            organization=OrganizationService(uow),
            jobs=JobsService(uow),
            assignments=AssignmentsService(uow, publisher),
            authorization=self._authorization,
            scope=self._scope,
            policy=self._policy,
            audit=AuditService(uow),
            workflow=self._workflow,
            notification=self._notification,
            scheduling=self._scheduling,
            events=publisher,
            dispatcher=self.dispatcher,
            invoker=_ContractInvoker(self.registries.contracts),
            capabilities=self.registries.capabilities,
            contracts=self.registries.contracts,
            events_registry=self.registries.events,
        )
        self._contexts[plugin_id] = context
        return context

    # --- boot -------------------------------------------------------------

    def boot(self) -> BootResult:
        """Discover installed plugins and register every one that validates."""
        self._seed_clusters()
        discovered = discover_plugins(self.entry_point_group)
        self.boot_result.discovered = len(discovered)

        registered_ids = {p.plugin_id for p in self.registries.plugins.all()}
        for candidate in discovered:
            try:
                self._advance_to_discovered(candidate)
                self._validate(candidate)
                self._check_dependencies(candidate, registered_ids)
                self._register(candidate)
                registered_ids.add(candidate.plugin_id)
                self._plugins[candidate.plugin_id] = candidate
                self.boot_result.registered += 1
            except Exception as exc:  # noqa: BLE001 - any failure marks the plugin
                self._mark_failed(candidate.plugin_id, exc)

        return self.boot_result

    # --- lifecycle (Gate I) ------------------------------------------------

    def initialize(self, plugin_id: str) -> None:
        """DISCOVERD -> ... -> REGISTERED -> INITIALIZED.

        Runs the plugin's ``initialize`` hook with its context. A plugin that
        raises here is marked FAILED and leaves no live instance behind.
        """
        candidate = self._require_candidate(plugin_id)
        instance = candidate.instance
        try:
            instance.initialize(self.context_for(plugin_id))
        except Exception as exc:  # noqa: BLE001 - the plugin's hook is arbitrary
            self._mark_failed(plugin_id, exc)
            raise PluginLifecycleError(f"plugin {plugin_id!r} failed to initialize: {exc}") from exc
        self._instances[plugin_id] = instance
        self.registries.plugins.mark(plugin_id, PluginLifecycle.INITIALIZED)

    def enable(self, plugin_id: str) -> None:
        """INITIALIZED (or REGISTERED) -> ENABLED.

        Binds the plugin's contracts and subscribes its event handlers, so an
        enabled plugin's contracts become callable through the registry. A
        failure at any point rolls the plugin back to FAILED with nothing bound.
        """
        self._require_candidate(plugin_id)
        instance = self._instances.get(plugin_id)
        if instance is None:
            self.initialize(plugin_id)
            instance = self._instances[plugin_id]

        subscriptions = instance.bind_subscriptions()
        for event_id, subscriber in subscriptions.items():
            self.dispatcher.subscribe(event_id, subscriber)

        try:
            instance.bind_contracts()
        except Exception as exc:  # noqa: BLE001 - binding is plugin code
            for event_id, subscriber in subscriptions.items():
                self.dispatcher.unsubscribe(event_id, subscriber)
            self._mark_failed(plugin_id, exc)
            raise PluginLifecycleError(
                f"plugin {plugin_id!r} failed to bind its contracts: {exc}"
            ) from exc

        try:
            instance.on_enable()
        except Exception as exc:  # noqa: BLE001 - on_enable is plugin code
            self._tear_down(plugin_id, subscriptions)
            self._mark_failed(plugin_id, exc)
            raise PluginLifecycleError(
                f"plugin {plugin_id!r} failed while enabling: {exc}"
            ) from exc

        self.registries.plugins.mark(plugin_id, PluginLifecycle.ENABLED)

    def disable(self, plugin_id: str) -> None:
        """ENABLED -> DISABLED.

        Unbinds contracts and unsubscribes events first, so the instant a plugin
        is disabled its contracts stop being callable through the registry.
        """
        instance = self._instances.get(plugin_id)
        subscriptions = instance.bind_subscriptions() if instance is not None else {}
        self._tear_down(plugin_id, subscriptions)
        if instance is not None:
            instance.on_disable()
        self.registries.plugins.mark(plugin_id, PluginLifecycle.DISABLED)

    def stop(self, plugin_id: str) -> None:
        """Any enabled/initialized state -> STOPPED."""
        if self.registries.plugins.lifecycle_state(plugin_id) in (
            PluginLifecycle.ENABLED,
            PluginLifecycle.RUNNING,
        ):
            self.disable(plugin_id)
        instance = self._instances.pop(plugin_id, None)
        if instance is not None:
            instance.shutdown()
        self.registries.plugins.mark(plugin_id, PluginLifecycle.STOPPED)

    def enable_all(self) -> None:
        """Convenience for the CLI: register then enable every bootable plugin.

        A plugin that fails is marked FAILED and skipped; the others still come
        up, which is the "broken plugin must not corrupt the core" guarantee.
        """
        for plugin_id in list(self._plugins):
            if self.registries.plugins.lifecycle_state(plugin_id) is not PluginLifecycle.FAILED:
                try:
                    self.enable(plugin_id)
                    self.registries.plugins.mark(plugin_id, PluginLifecycle.RUNNING)
                except PluginLifecycleError:
                    continue

    def failed_plugins(self) -> list[tuple[str, str]]:
        return list(self.boot_result.failed)

    def _tear_down(self, plugin_id: str, subscriptions: Mapping[EventId, EventSubscriber]) -> None:
        self.registries.contracts.unbind(plugin_id)
        for event_id, subscriber in subscriptions.items():
            self.dispatcher.unsubscribe(event_id, subscriber)

    # --- boot stages ------------------------------------------------------

    def _seed_clusters(self) -> None:
        for manifest in INITIAL_CLUSTERS:
            if not self.registries.clusters.exists(manifest.cluster_id):
                self.registries.clusters.register(manifest)

    def _advance_to_discovered(self, candidate: DiscoveredPlugin) -> None:
        self.registries.plugins.mark(
            candidate.plugin_id,
            PluginLifecycle.DISCOVERED,
        )

    def _validate(self, candidate: DiscoveredPlugin) -> None:
        cluster_ids = [cluster.cluster_id for cluster in self.registries.clusters.all()]
        assert_valid(candidate.manifest, cluster_ids)
        self.registries.plugins.mark(candidate.plugin_id, PluginLifecycle.VALIDATED)

    def _check_dependencies(self, candidate: DiscoveredPlugin, available: set[str]) -> None:
        assert_dependencies(candidate.manifest, available)
        self.registries.plugins.mark(
            candidate.plugin_id,
            PluginLifecycle.DEPENDENCIES_CHECKED,
        )

    def _register(self, candidate: DiscoveredPlugin) -> None:
        manifest = candidate.manifest
        try:
            self.registries.plugins.register(manifest)
        except Exception as exc:
            raise PluginRegistrationError(str(exc)) from exc

        for capability in manifest.provides_capabilities:
            self.registries.capabilities.register(capability, manifest.plugin_id)
        for declaration in manifest.provides_contracts:
            self.registries.contracts.register(declaration, manifest.plugin_id)
        for event in manifest.publishes_events:
            self.registries.events.register_published(event, manifest.plugin_id)
        for event in manifest.subscribes_events:
            self.registries.events.register_subscribed(event, manifest.plugin_id)

    def _mark_failed(self, plugin_id: str, exc: BaseException) -> None:
        reason = f"{type(exc).__name__}: {exc}"
        self.boot_result.failed.append((plugin_id, reason))
        self.registries.plugins.mark(plugin_id, PluginLifecycle.FAILED, reason)

    def _require_candidate(self, plugin_id: str) -> DiscoveredPlugin:
        found = self._plugins.get(plugin_id)
        if found is not None:
            return found

        if self.registries.plugins.exists(plugin_id):
            msg = (
                f"plugin {plugin_id!r} is registered but was not discovered by this kernel "
                "instance; a plugin must be booted before it can be enabled"
            )
            raise NotFoundError(msg, kind="plugin", key=plugin_id)

        try:
            state = self.registries.plugins.lifecycle_state(plugin_id)
        except NotFoundError:
            state = None

        if state is PluginLifecycle.FAILED:
            reason = self.registries.plugins.failure_reason(plugin_id) or ""
            msg = f"plugin {plugin_id!r} was rejected at boot: {reason}"
        else:
            msg = (
                f"plugin {plugin_id!r} is not a registered plugin; "
                "it was not discovered from any installed entry point"
            )
        raise NotFoundError(msg, kind="plugin", key=plugin_id)

    # --- helpers ----------------------------------------------------------

    def _require_uow_factory(self) -> Callable[[], UnitOfWorkPort]:
        if self.uow_factory is None:
            msg = "this kernel was built without a unit-of-work factory"
            raise RuntimeError(msg)
        return self.uow_factory


@dataclass(frozen=True)
class _ContractInvoker:
    """Adapts :class:`~atlas_sdk.context.ContractInvokerPort` over the registry.

    The indirection matters: a plugin calls ``context.invoker.invoke(...)`` and
    the registry decides which *bound* implementation answers. Neither side knows
    the other's module.
    """

    registry: InMemoryContractRegistry

    def invoke(self, contract_id: ContractId, request: object) -> object:
        return self.registry.invoke(contract_id, request)

    def invoke_all(self, contract_id: ContractId, request: object) -> list[object]:
        return self.registry.invoke_all(contract_id, request)


def _noop_uow() -> UnitOfWorkPort:
    raise NotImplementedError("this kernel has no persistence configured")
