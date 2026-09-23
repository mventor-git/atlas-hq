"""Typed contracts — the only sanctioned plugin-to-plugin channel (contract section 9).

A :class:`ContractDeclaration` is *metadata*: it says that some plugin provides
an implementation of contract ``payroll.attendance_input`` with a given version
and request/response schema. The registry indexes declarations so a consumer
can ask "who provides this?" without importing any implementation.

A :class:`Contract` is the runtime half: a handler bound to a request type and
a response type. Plugins publish contracts; other plugins consume them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, NewType, Protocol, TypeVar

ContractId = NewType("ContractId", str)

#: Sentinel: a contract id declared by another plugin. Plugins publish the
#: *literal string* of any contract id they did not declare themselves, so a
#: consumer and a provider spell the same id without sharing a module. This
#: constant exists only as the documentation of that rule; it is never required.
SHARED = "shared"


def shared_contract_id(value: str) -> ContractId:
    """Spell another plugin's contract id without importing its module.

    Contract section 9 forbids implementation coupling between plugins. Two
    plugins that must agree on a contract id agree on the *string*, typed here
    so the compiler still sees a :data:`ContractId`.
    """
    return ContractId(value)


RequestT = TypeVar("RequestT")
ResponseT = TypeVar("ResponseT")


@dataclass(frozen=True)
class ContractDeclaration:
    """Static declaration of a contract a plugin provides."""

    contract_id: ContractId
    version: str = "1.0"
    #: JSON-schema-ish descriptor of the request shape. Not validated at runtime in D1.
    schema: Mapping[str, object] = field(default_factory=dict)
    description: str = ""


class Contract(Protocol[RequestT, ResponseT]):
    """Runtime handler satisfying a :class:`ContractDeclaration`."""

    contract_id: ContractId

    def handle(self, request: RequestT) -> ResponseT: ...


@dataclass(frozen=True)
class ContractImplementation:
    """A registry record: which plugin provides which contract declaration.

    ``instance`` is the live contract object for ENABLED plugins (bound at
    enable time); it is ``None`` for a plugin that is not enabled, which is how
    Gate I makes a disabled plugin's contracts uncallable.
    """

    declaration: ContractDeclaration
    plugin_id: str
    instance: Contract[Any, Any] | None = None

    @property
    def is_bound(self) -> bool:
        return self.instance is not None


__all__ = [
    "Contract",
    "ContractDeclaration",
    "ContractId",
    "ContractImplementation",
]
