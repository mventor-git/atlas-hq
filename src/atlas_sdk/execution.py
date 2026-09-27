"""Opaque execution handles shared by Core and plugins.

A handle is only a bearer reference.  It carries no principal, channel, action,
resource, scope, capability, or policy data, and Core validates its token against
the persisted execution record at every public boundary.
"""

from __future__ import annotations


class ExecutionHandle:
    """An opaque, immutable reference created only by the Core issuer."""

    __slots__ = ("__token", "__weakref__")

    def __init__(self) -> None:
        raise TypeError("ExecutionHandle is issued by Core")

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("ExecutionHandle is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("ExecutionHandle is immutable")

    def __repr__(self) -> str:
        return "ExecutionHandle(<redacted>)"

    __str__ = __repr__


__all__ = ["ExecutionHandle"]
