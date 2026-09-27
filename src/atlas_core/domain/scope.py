"""Scope — the context in which records and operations live (contract section 35).

The core adopts the SDK's :class:`atlas_sdk.Scope` as its scope type rather than
redefining it: scope is part of the published language both sides must agree on.
The behaviour that belongs to the core — containment and narrowing — lives here.
"""

from __future__ import annotations

from atlas_sdk import Scope

__all__ = ["Scope", "covers", "narrow", "resolve"]


def covers(broader: Scope, narrower: Scope) -> bool:
    """True if ``broader`` authorises seeing ``narrower``.

    Organization/workplace containment keeps its existing behaviour. A
    principal dimension is a strict self boundary: a self grant never widens
    into an organization grant, and another principal's self scope never
    matches.
    """
    if broader.principal_id is not None and broader.principal_id != narrower.principal_id:
        return False
    if narrower.principal_id is not None and broader.principal_id is None:
        return False
    if broader.organization_id != narrower.organization_id:
        return False
    if broader.workplace_id is None:
        return True
    return broader.workplace_id == narrower.workplace_id


def narrow(requested: Scope, subject: Scope) -> Scope:
    """The most permissive scope an actor may actually use for a request.

    ``requested`` is what the operation wants, ``subject`` is what the actor may
    see. The result is never wider than ``subject``; disjoint scopes collapse to
    an empty scope (``organization_id is None``), which queries read as "nothing
    visible".
    """
    if subject.is_empty:
        return Scope()
    if requested.is_empty:
        return Scope()
    if not covers(subject, requested):
        return Scope()
    return requested


def resolve(
    organization_id: str | None,
    workplace_id: str | None = None,
    principal_id: str | None = None,
) -> Scope:
    """Build a scope from raw ids. Empty dimensions mean no access."""
    if organization_id is None and principal_id is None:
        return Scope()
    return Scope(
        organization_id=organization_id,
        workplace_id=workplace_id,
        principal_id=principal_id,
    )
