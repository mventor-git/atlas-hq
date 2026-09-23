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

from collections.abc import Callable
from dataclasses import dataclass, field

from atlas_sdk import PluginLifecycle, PluginRegistrationError
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
from .infrastructure.events import EventDispatcher, OutboxEventPublisher
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

    # --- construction -----------------------------------------------------

    def context_for(self, plugin_id: str) -> PluginContext:
        """Build the plugin context a registered plugin will receive (D2 wires
        the lifecycle hooks that consume it; D1 exposes the seam)."""
        uow = self._require_uow_factory()()
        publisher = OutboxEventPublisher(uow, publisher=plugin_id)
        return PluginContext(
            plugin_id=plugin_id,
            people=PeopleService(uow, publisher),
            organization=OrganizationService(uow),
            jobs=JobsService(uow),
            assignments=AssignmentsService(uow, publisher),
            authorization=AuthorizationService(),
            scope=ScopeService(),
            policy=PolicyService(),
            audit=AuditService(uow),
            workflow=WorkflowService(),
            notification=NotificationService(),
            scheduling=SchedulingService(),
            events=publisher,
            capabilities=self.registries.capabilities,
            contracts=self.registries.contracts,
            events_registry=self.registries.events,
        )

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
                self.boot_result.registered += 1
            except Exception as exc:  # noqa: BLE001 - any failure marks the plugin
                self._mark_failed(candidate.plugin_id, exc)

        return self.boot_result

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

    # --- helpers ----------------------------------------------------------

    def _require_uow_factory(self) -> Callable[[], UnitOfWorkPort]:
        if self.uow_factory is None:
            msg = "this kernel was built without a unit-of-work factory"
            raise RuntimeError(msg)
        return self.uow_factory


def _noop_uow() -> UnitOfWorkPort:
    raise NotImplementedError("this kernel has no persistence configured")
