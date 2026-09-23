"""Atlas-HQ — the administrative control surface for the Atlas platform.

D1 ships a CLI that boots the kernel and prints registry state. Every later
admin feature lands behind the same boot path, so an action such as "enable
plugin" will reach the real registry rather than a UI-only facade
(contract section 24).
"""

from __future__ import annotations

__version__ = "0.1.0"
