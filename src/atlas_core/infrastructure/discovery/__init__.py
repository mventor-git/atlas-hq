"""Plugin discovery via ``importlib.metadata`` entry points (contract §17)."""

from __future__ import annotations

from .entry_points import PLUGIN_ENTRY_POINT_GROUP, DiscoveredPlugin, discover_plugins

__all__ = ["PLUGIN_ENTRY_POINT_GROUP", "DiscoveredPlugin", "discover_plugins"]
