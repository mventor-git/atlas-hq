"""Public service proxies that keep Core-owned objects out of plugin hands."""

from __future__ import annotations

from typing import Any
from weakref import WeakKeyDictionary

_DELEGATES: WeakKeyDictionary[PublicServiceProxy, Any] = WeakKeyDictionary()
_OVERRIDES: WeakKeyDictionary[PublicServiceProxy, dict[str, Any]] = WeakKeyDictionary()


class PublicServiceProxy:
    """Expose only public service methods; never expose the delegate itself."""

    __slots__ = ("__weakref__",)

    def __init__(self, delegate: Any) -> None:
        _DELEGATES[self] = delegate
        _OVERRIDES[self] = {}

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            overrides = _OVERRIDES[self]
            if name in overrides:
                return overrides[name]
            delegate = _DELEGATES[self]
        except KeyError as exc:  # pragma: no cover - only after interpreter teardown
            raise AttributeError(name) from exc
        return getattr(delegate, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            raise AttributeError(name)
        _OVERRIDES[self][name] = value

    @property
    def __class__(self) -> type[Any]:
        try:
            return type(_DELEGATES[self])
        except KeyError:  # pragma: no cover
            return PublicServiceProxy

    def __dir__(self) -> list[str]:
        try:
            delegate = _DELEGATES[self]
        except KeyError:  # pragma: no cover
            return []
        return [name for name in dir(delegate) if not name.startswith("_")]

    def __repr__(self) -> str:
        try:
            delegate = _DELEGATES[self]
        except KeyError:  # pragma: no cover
            return "PublicServiceProxy(<detached>)"
        return f"PublicServiceProxy({type(delegate).__name__})"


def public_service(delegate: Any) -> Any:
    """Return a proxy typed loosely for SDK port assignment."""
    return PublicServiceProxy(delegate)


__all__ = ["PublicServiceProxy", "public_service"]
