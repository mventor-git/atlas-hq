"""Scope: resolution, containment and narrowing (contract section 35, N)."""

from __future__ import annotations

from atlas_core.application.scope import ScopeService
from atlas_sdk import Scope

service = ScopeService()


def test_resolve_from_ids() -> None:
    assert service.resolve("org-1") == Scope(organization_id="org-1")
    assert service.resolve("org-1", "wp-1") == Scope(
        organization_id="org-1",
        workplace_id="wp-1",
    )


def test_resolve_without_an_organization_is_empty() -> None:
    assert service.resolve(None).is_empty
    assert service.resolve(None, "wp-1").is_empty


def test_empty_scope_stays_empty() -> None:
    assert Scope().is_empty


def test_narrow_returns_the_requested_scope_when_covered() -> None:
    subject = Scope(organization_id="org-1")
    requested = Scope(organization_id="org-1", workplace_id="wp-1")

    assert service.narrow(requested, subject) == requested


def test_narrow_never_grants_more_than_the_subject() -> None:
    """The defining property of narrowing: the actor's reach is the ceiling.

    An actor scoped to one workplace cannot be granted org-level visibility —
    that would expose the other workplaces — so the result collapses to empty
    rather than widening to the request.
    """
    subject = Scope(organization_id="org-1", workplace_id="wp-1")
    requested = Scope(organization_id="org-1")

    assert service.narrow(requested, subject).is_empty


def test_narrow_of_disjoint_organizations_is_empty() -> None:
    subject = Scope(organization_id="org-1")
    requested = Scope(organization_id="org-2")

    assert service.narrow(requested, subject).is_empty


def test_narrow_of_disjoint_workplaces_is_empty() -> None:
    subject = Scope(organization_id="org-1", workplace_id="wp-1")
    requested = Scope(organization_id="org-1", workplace_id="wp-2")

    assert service.narrow(requested, subject).is_empty


def test_narrow_with_an_empty_subject_is_empty() -> None:
    assert service.narrow(Scope(organization_id="org-1"), Scope()).is_empty


def test_narrow_with_an_empty_request_is_empty() -> None:
    """Asking for nothing yields nothing, even for a privileged actor."""
    assert service.narrow(Scope(), Scope(organization_id="org-1")).is_empty


def test_org_scope_covers_its_workplaces() -> None:
    from atlas_core.domain.scope import covers

    assert covers(
        Scope(organization_id="org-1"), Scope(organization_id="org-1", workplace_id="wp-1")
    )
    assert covers(Scope(organization_id="org-1"), Scope(organization_id="org-1"))


def test_different_organizations_never_cover_each_other() -> None:
    from atlas_core.domain.scope import covers

    assert not covers(Scope(organization_id="org-1"), Scope(organization_id="org-2"))
