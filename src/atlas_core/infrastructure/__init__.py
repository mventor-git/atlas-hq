"""Atlas infrastructure adapters.

Every adapter in this package sits behind a port declared in
``atlas_core.application`` or ``atlas_sdk``: persistence behind the repository
ports, the event bus behind the publisher/dispatcher ports, plugin discovery
behind the kernel, and the five registries behind the SDK registry ports. The
core's application layer never imports this package directly — the kernel wires
adapters to ports, and that is the only place the two meet.
"""

from __future__ import annotations
