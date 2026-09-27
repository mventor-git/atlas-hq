"""Authorization: context-bound capability checks scoped by role assignment."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from atlas_core.application.authorization import AuthorizationService
from atlas_core.application.management import AuthorizationManagementService
from atlas_core.application.policy import PolicyService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.domain.role import (
    AUDIT_READ,
    PEOPLE_EMPLOYEE_CREATE,
    PEOPLE_EMPLOYEE_READ,
    PLUGIN_ADMIN,
    RoleId,
)
from atlas_sdk import AuthorizationError, CapabilityId, Channel, NotFoundError, Scope

ORG_A = Scope(organization_id="org-a")
ORG_B = Scope(organization_id="org-b")
WP_A1 = Scope(organization_id="org-a", workplace_id="wp-1")
WP_A2 = Scope(organization_id="org-a", workplace_id="wp-2")


def _services(
    uow: UnitOfWorkPort,
) -> tuple[AuthorizationService, AuthorizationManagementService]:
    authorization = AuthorizationService(
        uow=uow,
        policy=PolicyService(uow=uow),
        uow_factory=uow.independent_uow_factory,
    )
    return authorization, AuthorizationManagementService(uow, authorization=authorization)


def _assign(
    authorization: AuthorizationService,
    management: AuthorizationManagementService,
    subject: str,
    role: str,
    scope: Scope,
) -> None:
    management.create_principal(subject)
    management.assign_role(subject, role, scope)


def _allowed(
    authorization: AuthorizationService,
    principal_id: str,
    capability: CapabilityId,
    scope: Scope,
) -> bool:
    try:
        context = authorization.issue_handle(
            principal_id=principal_id,
            capability=capability,
            action=str(capability),
            scope=scope,
            channel=Channel.WEB,
        )
    except AuthorizationError:
        return False
    return authorization.authorize(context, capability, scope).allowed


def test_no_role_denies_everything(uow_factory: Callable[[], UnitOfWorkPort]) -> None:
    with uow_factory() as uow:
        authorization, management = _services(uow)
        management.create_principal("alice")
        assert not _allowed(authorization, "alice", PEOPLE_EMPLOYEE_READ, ORG_A)


def test_granted_capability_is_allowed_in_scope(uow_factory: Callable[[], UnitOfWorkPort]) -> None:
    with uow_factory() as uow:
        authorization, management = _services(uow)
        _assign(authorization, management, "alice", RoleId.HR_ADMIN, ORG_A)
        assert _allowed(authorization, "alice", PEOPLE_EMPLOYEE_CREATE, ORG_A)
        assert _allowed(authorization, "alice", PEOPLE_EMPLOYEE_READ, ORG_A)
        assert _allowed(authorization, "alice", AUDIT_READ, ORG_A)


def test_a_capability_the_role_lacks_is_denied(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        authorization, management = _services(uow)
        _assign(authorization, management, "bob", RoleId.EMPLOYEE, ORG_A)
        assert _allowed(authorization, "bob", PEOPLE_EMPLOYEE_READ, ORG_A)
        assert not _allowed(authorization, "bob", PEOPLE_EMPLOYEE_CREATE, ORG_A)


def test_another_organizations_scope_is_denied(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        authorization, management = _services(uow)
        _assign(authorization, management, "alice", RoleId.HR_ADMIN, ORG_A)
        assert not _allowed(authorization, "alice", PEOPLE_EMPLOYEE_CREATE, ORG_B)


def test_org_scope_covers_its_workplaces(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        authorization, management = _services(uow)
        _assign(authorization, management, "alice", RoleId.HR_ADMIN, ORG_A)
        assert _allowed(authorization, "alice", PEOPLE_EMPLOYEE_CREATE, WP_A1)
        assert _allowed(authorization, "alice", PEOPLE_EMPLOYEE_CREATE, WP_A2)


def test_workplace_scope_does_not_cover_another_workplace(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        authorization, management = _services(uow)
        _assign(authorization, management, "manager", RoleId.MANAGER, WP_A1)
        assert _allowed(authorization, "manager", PEOPLE_EMPLOYEE_READ, WP_A1)
        assert not _allowed(authorization, "manager", PEOPLE_EMPLOYEE_READ, WP_A2)


def test_platform_role_covers_plugin_admin(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        authorization, management = _services(uow)
        _assign(authorization, management, "system", RoleId.PLATFORM, ORG_A)
        assert _allowed(authorization, "system", PLUGIN_ADMIN, ORG_A)
        assert not _allowed(authorization, "system", PEOPLE_EMPLOYEE_CREATE, ORG_A)


def test_granting_an_unknown_role_raises(
    uow_factory: Callable[[], UnitOfWorkPort],
) -> None:
    with uow_factory() as uow:
        authorization, management = _services(uow)
        with pytest.raises(NotFoundError):
            _assign(authorization, management, "alice", "role.does_not_exist", ORG_A)


def test_subjects_are_independent(uow_factory: Callable[[], UnitOfWorkPort]) -> None:
    with uow_factory() as uow:
        authorization, management = _services(uow)
        _assign(authorization, management, "alice", RoleId.HR_ADMIN, ORG_A)
        assert not _allowed(authorization, "eve", PEOPLE_EMPLOYEE_CREATE, ORG_A)
