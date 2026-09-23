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
from typing import NewType, Protocol, TypeVar

ContractId = NewType("ContractId", str)

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
    """A registry record: which plugin provides which contract declaration."""

    declaration: ContractDeclaration
    plugin_id: str


__all__ = [
    "Contract",
    "ContractDeclaration",
    "ContractId",
    "ContractImplementation",
]
