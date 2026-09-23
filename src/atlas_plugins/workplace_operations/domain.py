"""The Workplace Operations domain types.

A Workplace is a *typed* business location (contract section 27): ``Site`` is
one ``WorkplaceType`` among many, never the platform's identity. These value
objects are the plugin's published read models; the ORM rows in
:mod:`.persistence` stay private to this plugin.
"""

from __future__ import annotations

from dataclasses import dataclass

from atlas_sdk import WorkplaceType

__all__ = [
    "Workplace",
    "WorkplaceContext",
    "WorkplaceMember",
    "WorkplaceType",
]


@dataclass(frozen=True)
class Workplace:
    """A typed business location owned by an organization."""

    workplace_id: str
    organization_id: str
    name: str
    code: str
    kind: WorkplaceType = WorkplaceType.OFFICE
    parent_workplace_id: str | None = None


@dataclass(frozen=True)
class WorkplaceMember:
    """One member of a workplace's workforce."""

    membership_id: str
    workplace_id: str
    employee_id: str
    organization_id: str
    full_name: str
    employee_number: str


@dataclass(frozen=True)
class WorkplaceContext:
    """The resolved workplace context for a scope (contract section 15).

    Downstream plugins — attendance declares it consumes ``workplace.context`` —
    ask for this through the contract and never touch this plugin's tables.
    """

    workplace_id: str
    organization_id: str
    name: str
    code: str
    kind: WorkplaceType
    parent_workplace_id: str | None = None
    workforce_size: int = 0
