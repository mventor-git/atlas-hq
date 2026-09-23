"""Plugin discovery through ``importlib.metadata`` entry points (contract §17).

Installed distributions advertise plugins with an entry point in the
``atlas.plugins`` group::

    [project.entry-points."atlas.plugins"]
    my-plugin = "my_package.plugin:MyPlugin"

Discovery reads distribution metadata only — no folder scan (contract §30), no
core edit needed to add a plugin. Both a built-in distribution and an external
package look identical from here, which is the whole point of the mechanism.

The resolved object must be a :class:`~atlas_sdk.Plugin` subclass; its class-level
:attr:`~atlas_sdk.Plugin.manifest` is what the kernel validates next.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import EntryPoint, distributions

from atlas_sdk import Plugin, PluginDiscoveryError, PluginManifest

#: The entry-point group every Atlas plugin distribution must expose.
PLUGIN_ENTRY_POINT_GROUP = "atlas.plugins"


@dataclass(frozen=True)
class DiscoveredPlugin:
    """One plugin located by discovery, before validation or registration."""

    plugin_id: str
    distribution: str
    entry_point: str
    plugin_class: type[Plugin]
    manifest: PluginManifest

    @property
    def instance(self) -> Plugin:
        """A fresh instance of the plugin class (D1 inspects the manifest only)."""
        return self.plugin_class()


def discover_plugins(
    group: str = PLUGIN_ENTRY_POINT_GROUP,
) -> list[DiscoveredPlugin]:
    """Find every installed distribution exposing the ``atlas.plugins`` group.

    A broken or malformed entry point is reported as a
    :class:`~atlas_sdk.PluginDiscoveryError` naming the distribution, so one bad
    package is visible instead of silently vanishing from the registry.
    """
    discovered: list[DiscoveredPlugin] = []
    for point in _entry_points(group):
        discovered.append(_resolve(point))
    return discovered


def _entry_points(group: str) -> list[EntryPoint]:
    """Entry points for ``group`` across every installed distribution.

    Walks :func:`importlib.metadata.distributions` rather than the convenience
    ``entry_points(group=...)`` selector: on Python 3.12 the selector collapses
    same-named entry points across distributions into one, which would silently
    hide every plugin after the first that shares an entry-point name. Reading
    each distribution's own list keeps them all.
    """
    found: list[EntryPoint] = []
    for distribution in distributions():
        found.extend(point for point in distribution.entry_points if point.group == group)
    return found


def _resolve(point: EntryPoint) -> DiscoveredPlugin:
    distribution = point.dist.name if point.dist is not None else "<unknown>"
    try:
        resolved = point.load()
    except Exception as exc:  # noqa: BLE001 - import errors are discovery errors
        msg = f"entry point {point.name!r} in {distribution!r} could not be loaded: {exc}"
        raise PluginDiscoveryError(msg) from exc

    if not (isinstance(resolved, type) and issubclass(resolved, Plugin)):
        msg = (
            f"entry point {point.name!r} in {distribution!r} must resolve to an "
            f"atlas_sdk.Plugin subclass, got {resolved!r}"
        )
        raise PluginDiscoveryError(msg)

    manifest = getattr(resolved, "manifest", None)
    if manifest is None:
        msg = f"plugin {point.name!r} in {distribution!r} declares no manifest"
        raise PluginDiscoveryError(msg)

    return DiscoveredPlugin(
        plugin_id=manifest.plugin_id,
        distribution=distribution,
        entry_point=f"{point.value}",
        plugin_class=resolved,
        manifest=manifest,
    )


__all__ = ["PLUGIN_ENTRY_POINT_GROUP", "DiscoveredPlugin", "discover_plugins"]
