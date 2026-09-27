"""Organization application service with mandatory handle-bound authorization."""

from __future__ import annotations

from typing import TYPE_CHECKING

from atlas_sdk import (
    AuthorizationError,
    CapabilityId,
    DuplicateError,
    ExecutionHandle,
    NotFoundError,
    Scope,
    WorkplaceType,
)
from atlas_sdk import Organization as SdkOrganization
from atlas_sdk import Workplace as SdkWorkplace
from atlas_sdk.context import OrganizationPort

from ..domain.execution import ExecutionFacts
from ..domain.identifiers import OrganizationId
from ..domain.organization import Organization, Workplace
from ..domain.role import ORGANIZATION_MANAGE
from .execution_guard import authorization_for_uow, require_execution_handle
from .unit_of_work import UnitOfWorkPort

if TYPE_CHECKING:
    from .authorization import AuthorizationService
    from .execution import ExecutionHandleResolver


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
    def __init__(
        self,
        uow: UnitOfWorkPort,
        *,
        resolver: ExecutionHandleResolver | None = None,
        authorization: AuthorizationService | None = None,
    ) -> None:
        self._uow = uow
        if resolver is None or authorization is None:
            bound = authorization_for_uow(uow)
            resolver = resolver or bound._handle_resolver  # type: ignore[attr-defined]
            authorization = authorization or bound
        self._resolver = resolver
        self._authorization = authorization

    def _check(
        self,
        handle: ExecutionHandle,
        capability: CapabilityId,
        scope: Scope | None,
    ) -> ExecutionFacts | None:
        facts = require_execution_handle(
            handle,
            scope,
            resolver=self._resolver.resolve if self._resolver is not None else None,
        )
        if not isinstance(facts, ExecutionFacts):
            return None
        effective_scope = scope or facts.scope
        if self._authorization is not None:
            decision = self._authorization.authorize(handle, capability, effective_scope)
            if not decision.allowed:
                raise AuthorizationError(f"organization operation denied: {decision.code}")
        return facts

    def create_organization(
        self,
        name: str,
        code: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> SdkOrganization:
        self._check(execution_handle, ORGANIZATION_MANAGE, None)
        if not name.strip() or not code.strip():
            raise ValueError("organization name and code are required")
        if self._uow.organizations.get_by_code(code) is not None:
            raise DuplicateError(f"organization code {code!r} already exists")
        organization = Organization(name=name, code=code)
        self._uow.organizations.add(organization)
        return _org_to_read_model(organization)

    def get_organization(
        self,
        organization_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> SdkOrganization | None:
        found = self._uow.organizations.get(OrganizationId(organization_id))
        scope = Scope(organization_id=organization_id)
        self._check(execution_handle, ORGANIZATION_MANAGE, scope)
        return _org_to_read_model(found) if found else None

    def add_workplace(
        self,
        organization_id: str,
        name: str,
        kind: WorkplaceType = WorkplaceType.OFFICE,
        *,
        execution_handle: ExecutionHandle,
    ) -> SdkWorkplace:
        self._check(execution_handle, ORGANIZATION_MANAGE, Scope(organization_id=organization_id))
        if self._uow.organizations.get(OrganizationId(organization_id)) is None:
            raise NotFoundError(
                f"organization {organization_id!r} does not exist",
                kind="organization",
                key=organization_id,
            )
        workplace = Workplace(
            organization_id=OrganizationId(organization_id),
            name=name,
            kind=kind,
        )
        self._uow.workplaces.add(workplace)
        return _workplace_to_read_model(workplace)

    def list_workplaces(
        self,
        organization_id: str,
        *,
        execution_handle: ExecutionHandle,
    ) -> list[SdkWorkplace]:
        self._check(execution_handle, ORGANIZATION_MANAGE, Scope(organization_id=organization_id))
        return [
            _workplace_to_read_model(w)
            for w in self._uow.workplaces.all(OrganizationId(organization_id))
        ]


__all__ = ["OrganizationService"]
