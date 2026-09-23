"""Atlas HR Core — the platform itself.

The core owns platform-wide truth and infrastructure (contract section 2) and
exposes everything through the ports declared in :mod:`atlas_sdk`. Plugins never
import this package directly; they receive a
:class:`atlas_sdk.context.PluginContext`.
"""

from __future__ import annotations

__version__ = "0.1.0"
