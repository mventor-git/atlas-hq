"""Organization application service (contract section 2: Organization).

Organizations own workplaces. A workplace's ``kind`` is one of the
:class:`atlas_sdk.WorkplaceType` values — "site" is a type, not the identity of
the platform (contract section 8).
"""

from __future__ import annotations

from atlas_sdk import (
    DuplicateError,
    NotFoundError,
    WorkplaceType,
)
from atlas_sdk import (
    Organization as SdkOrganization,
)
from atlas_sdk import (
    Workplace as SdkWorkplace,
)
from atlas_sdk.context import OrganizationPort

from ..domain.identifiers import OrganizationId
from ..domain.organization import Organization, Workplace
from .unit_of_work import UnitOfWorkPort


def _org_to_read_model(organization: Organization) -> SdkOrganization:
    return SdkOrganization(
        organization_id=organization.organization_id,
        name=organization.name,
        code=organization.code,
    )


def _workplace_to_read_model(workplace: Workplace) -> SdkWorkplace:
    return SdkWorkplace(
        workplace_id=workplace.workplace_id,
        organization_id=workplace.organization_id,
        name=workplace.name,
        kind=workplace.kind,
    )


class OrganizationService(OrganizationPort):
    def __init__(self, uow: UnitOfWorkPort) -> None:
        self._uow = uow

    def create_organization(self, name: str, code: str) -> SdkOrganization:
        if not name.strip() or not code.strip():
            msg = "organization name and code are required"
            raise ValueError(msg)
        if self._uow.organizations.get_by_code(code) is not None:
            msg = f"organization code {code!r} already exists"
            raise DuplicateError(msg)

        organization = Organization(name=name, code=code)
        self._uow.organizations.add(organization)
        return _org_to_read_model(organization)

    def get_organization(self, organization_id: str) -> SdkOrganization | None:
        found = self._uow.organizations.get(OrganizationId(organization_id))
        return _org_to_read_model(found) if found else None

    def add_workplace(
        self,
        organization_id: str,
        name: str,
        kind: WorkplaceType = WorkplaceType.OFFICE,
    ) -> SdkWorkplace:
        if self._uow.organizations.get(OrganizationId(organization_id)) is None:
            msg = f"organization {organization_id!r} does not exist"
            raise NotFoundError(msg, kind="organization", key=organization_id)

        workplace = Workplace(
            organization_id=OrganizationId(organization_id),
            name=name,
            kind=kind,
        )
        self._uow.workplaces.add(workplace)
        return _workplace_to_read_model(workplace)

    def list_workplaces(self, organization_id: str) -> list[SdkWorkplace]:
        return [
            _workplace_to_read_model(w)
            for w in self._uow.workplaces.all(OrganizationId(organization_id))
        ]


__all__ = ["OrganizationService"]
