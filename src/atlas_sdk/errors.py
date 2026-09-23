"""Atlas SDK error hierarchy.

Every error a plugin can expect from the platform derives from :class:`AtlasError`.
"""

from __future__ import annotations


class AtlasError(Exception):
    """Root of the Atlas error hierarchy."""


# --- plugin level ---------------------------------------------------------


class PluginError(AtlasError):
    """Any problem related to a plugin's declaration or lifecycle."""


class PluginDiscoveryError(PluginError):
    """A distribution failed to load as a plugin."""


class PluginValidationError(PluginError):
    """A plugin manifest failed validation."""

    def __init__(self, plugin_id: str | None, errors: list[str]) -> None:
        self.plugin_id = plugin_id
        self.errors = errors
        whom = repr(plugin_id) if plugin_id else "<unknown plugin>"
        super().__init__(f"manifest rejected for {whom}: {'; '.join(errors)}")


class PluginDependencyError(PluginError):
    """A plugin's declared dependencies are not satisfied."""

    def __init__(self, plugin_id: str | None, errors: list[str]) -> None:
        self.plugin_id = plugin_id
        self.errors = errors
        whom = repr(plugin_id) if plugin_id else "<unknown plugin>"
        super().__init__(f"dependencies unmet for {whom}: {'; '.join(errors)}")


class PluginRegistrationError(PluginError):
    """A validated plugin could not be registered."""


class PluginLifecycleError(PluginError):
    """An illegal lifecycle transition was attempted."""


# --- registry level -------------------------------------------------------


class RegistryError(AtlasError):
    """A registry operation violated its invariants."""

    def __init__(self, message: str, *, kind: str, key: str) -> None:
        self.kind = kind
        self.key = key
        super().__init__(message)


class NotFoundError(RegistryError):
    """No entity is registered under the given key."""


class AlreadyRegisteredError(RegistryError):
    """An entity is already registered under the given key."""


class DuplicateError(AtlasError):
    """A business value that must be unique already exists."""


# --- runtime services -----------------------------------------------------


class AuthorizationError(AtlasError):
    """A capability check failed for an explicitly guarded operation."""


class ScopeError(AtlasError):
    """A scope is malformed or cannot be resolved."""


class PolicyError(AtlasError):
    """A policy evaluation could not be completed."""


class OutboxError(AtlasError):
    """The event outbox could not accept or dispatch an event."""


__all__ = [
    "AlreadyRegisteredError",
    "AtlasError",
    "AuthorizationError",
    "DuplicateError",
    "NotFoundError",
    "OutboxError",
    "PluginDependencyError",
    "PluginDiscoveryError",
    "PluginError",
    "PluginLifecycleError",
    "PluginRegistrationError",
    "PluginValidationError",
    "PolicyError",
    "RegistryError",
    "ScopeError",
]
