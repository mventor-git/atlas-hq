"""The plugin base class and its lifecycle (contract section 18).

Plugins subclass :class:`Plugin` and declare a :class:`~atlas_sdk.manifest.PluginManifest`
as a class attribute. The core discovers the class through an ``atlas.plugins``
entry point, reads the manifest, validates it, and only then touches the plugin
object itself.

The lifecycle is an explicit state machine. D1 wires the boot path as far as
``REGISTERED``; ``INITIALIZED``..``RUNNING`` and the terminal transitions are
defined now and exercised in D2.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import Enum
from typing import TYPE_CHECKING, ClassVar

from .event import DomainEvent, EventId
from .manifest import PluginManifest

if TYPE_CHECKING:
    from .context import PluginContext


class PluginLifecycle(Enum):
    """Explicit plugin lifecycle (contract section 18)."""

    DISCOVERED = "discovered"
    VALIDATED = "validated"
    DEPENDENCIES_CHECKED = "dependencies_checked"
    REGISTERED = "registered"
    # --- reached from D2 onwards -------------------------------------------
    INITIALIZED = "initialized"
    ENABLED = "enabled"
    RUNNING = "running"
    DISABLED = "disabled"
    STOPPED = "stopped"
    UPGRADED = "upgraded"
    FAILED = "failed"

    @property
    def label(self) -> str:
        return self.value


class Plugin:
    """Base class for every Atlas plugin.

    Subclasses set :attr:`manifest` and may override the lifecycle hooks.
    """

    manifest: ClassVar[PluginManifest]

    def initialize(self, context: PluginContext) -> None:
        """Called once after registration, before the plugin may be enabled."""

    def bind_contracts(self) -> None:
        """Register contract handlers against ``self.context.contracts``.

        Called on enable. A plugin binds handlers for the contracts its manifest
        declares it provides; unbinding happens automatically when the plugin is
        disabled, which is what makes a disabled plugin's contracts uncallable.
        """

    def bind_subscriptions(self) -> Mapping[EventId, Callable[[DomainEvent], None]]:
        """Event subscriptions this plugin wants while enabled.

        Return a mapping of another plugin's published event id to a handler.
        The ids are literal strings (contract section 9); the publisher's module
        is never imported.
        """
        return {}

    def on_enable(self) -> None:
        """Called when the plugin transitions to ENABLED."""

    def on_disable(self) -> None:
        """Called when the plugin transitions away from ENABLED."""

    def shutdown(self) -> None:
        """Called when the plugin is stopped."""


__all__ = ["Plugin", "PluginLifecycle"]
