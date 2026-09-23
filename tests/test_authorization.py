"""Authorization: capability checks scoped by role assignment (contract section 35)."""

from __future__ import annotations

import pytest

from atlas_core.application.authorization import AuthorizationService
from atlas_core.domain.role import (
    AUDIT_READ,
    PEOPLE_EMPLOYEE_CREATE,
    PEOPLE_EMPLOYEE_READ,
    PLUGIN_ADMIN,
    RoleId,
)
from atlas_sdk import NotFoundError, Scope

ORG_A = Scope(organization_id="org-a")
ORG_B = Scope(organization_id="org-b")
WP_A1 = Scope(organization_id="org-a", workplace_id="wp-1")
WP_A2 = Scope(organization_id="org-a", workplace_id="wp-2")


def test_no_role_denies_everything() -> None:
    service = AuthorizationService()

    assert not service.check(PEOPLE_EMPLOYEE_READ, ORG_A, "alice")


def test_granted_capability_is_allowed_in_scope() -> None:
    service = AuthorizationService()
    service.grant("alice", RoleId.HR_ADMIN, ORG_A)

    assert service.check(PEOPLE_EMPLOYEE_CREATE, ORG_A, "alice")
    assert service.check(PEOPLE_EMPLOYEE_READ, ORG_A, "alice")
    assert service.check(AUDIT_READ, ORG_A, "alice")


def test_a_capability_the_role_lacks_is_denied() -> None:
    service = AuthorizationService()
    service.grant("bob", RoleId.EMPLOYEE, ORG_A)

    assert service.check(PEOPLE_EMPLOYEE_READ, ORG_A, "bob")
    assert not service.check(PEOPLE_EMPLOYEE_CREATE, ORG_A, "bob")


def test_another_organizations_scope_is_denied() -> None:
    """Scope is a boundary, not a formality."""
    service = AuthorizationService()
    service.grant("alice", RoleId.HR_ADMIN, ORG_A)

    assert not service.check(PEOPLE_EMPLOYEE_CREATE, ORG_B, "alice")


def test_org_scope_covers_its_workplaces() -> None:
    service = AuthorizationService()
    service.grant("alice", RoleId.HR_ADMIN, ORG_A)

    assert service.check(PEOPLE_EMPLOYEE_CREATE, WP_A1, "alice")
    assert service.check(PEOPLE_EMPLOYEE_CREATE, WP_A2, "alice")


def test_workplace_scope_does_not_cover_another_workplace() -> None:
    service = AuthorizationService()
    service.grant("manager", RoleId.MANAGER, WP_A1)

    assert service.check(PEOPLE_EMPLOYEE_READ, WP_A1, "manager")
    assert not service.check(PEOPLE_EMPLOYEE_READ, WP_A2, "manager")


def test_platform_role_covers_plugin_admin() -> None:
    service = AuthorizationService()
    service.grant("system", RoleId.PLATFORM, ORG_A)

    assert service.check(PLUGIN_ADMIN, ORG_A, "system")
    assert not service.check(PEOPLE_EMPLOYEE_CREATE, ORG_A, "system")


def test_granting_an_unknown_role_raises() -> None:

    service = AuthorizationService()

    with pytest.raises(NotFoundError):
        service.grant("alice", "role.does_not_exist", ORG_A)


def test_subjects_are_independent() -> None:
    service = AuthorizationService()
    service.grant("alice", RoleId.HR_ADMIN, ORG_A)

    assert not service.check(PEOPLE_EMPLOYEE_CREATE, ORG_A, "eve")
