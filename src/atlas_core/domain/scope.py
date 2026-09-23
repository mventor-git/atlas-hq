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

    An org-wide scope covers every record of that org, including workplace
    records. A workplace-scoped view covers only its own workplace. Different
    orgs never cover each other.
    """
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


def resolve(organization_id: str | None, workplace_id: str | None = None) -> Scope:
    """Build a scope from raw ids. ``None`` organization means "no scope"."""
    if organization_id is None:
        return Scope()
    return Scope(organization_id=organization_id, workplace_id=workplace_id)
