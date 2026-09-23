"""Organization and workplaces.

An organization owns workplaces. A workplace has a type (contract section 8) —
"site" is one type among many, never the platform's identity.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atlas_sdk import WorkplaceType

from .identifiers import OrganizationId, WorkplaceId, new_id


@dataclass(frozen=True)
class Organization:
    organization_id: OrganizationId = field(default_factory=lambda: OrganizationId(new_id("org")))
    name: str = ""
    code: str = ""


@dataclass(frozen=True)
class Workplace:
    workplace_id: WorkplaceId = field(default_factory=lambda: WorkplaceId(new_id("wp")))
    organization_id: OrganizationId = field(default_factory=lambda: OrganizationId(""))
    name: str = ""
    kind: WorkplaceType = WorkplaceType.OFFICE


__all__ = ["Organization", "Workplace"]
