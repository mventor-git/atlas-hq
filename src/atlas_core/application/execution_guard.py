"""Shared fail-closed guard for every public Core/plugin boundary."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from atlas_sdk import AuthorizationError, ExecutionHandle, Scope

if TYPE_CHECKING:
    from .authorization import AuthorizationService
    from .unit_of_work import UnitOfWorkPort


def authorization_for_uow(uow: UnitOfWorkPort) -> AuthorizationService:
    """Build the Core evaluator for direct application-service construction.

    The denial audit gets the unit of work's *independent* factory, so a denial
    still leaves a durable Audit record when the business transaction rolls
    back. Without it, authorization fails closed with a hard error.
    """
    from .authorization import AuthorizationService
    from .policy import PolicyService

    return AuthorizationService(
        uow=uow,
        policy=PolicyService(uow=uow),
        uow_factory=uow.independent_uow_factory,
        initialize=False,
    )


def require_execution_handle(
    handle: ExecutionHandle | None,
    requested_scope: Scope | None = None,
    *,
    resolver: Callable[[ExecutionHandle], object] | None = None,
) -> object:
    """Require a real handle and optionally resolve it against Core state."""
    if not isinstance(handle, ExecutionHandle):
        raise AuthorizationError("a server-issued ExecutionHandle is required")
    if resolver is not None:
        try:
            facts = resolver(handle)
        except (AuthorizationError, TypeError, ValueError) as exc:
            raise AuthorizationError("a Core-resolved ExecutionHandle is required") from exc
    else:
        facts = None
    if requested_scope is not None:
        resolved_scope = getattr(facts, "scope", None)
        if resolved_scope is None or not _contains(resolved_scope, requested_scope):
            raise AuthorizationError("requested scope is outside the execution handle")
    return facts


def _contains(broader: Scope, narrower: Scope) -> bool:
    if broader.is_empty or narrower.is_empty:
        return False
    if broader.principal_id is not None and broader.principal_id != narrower.principal_id:
        return False
    if narrower.principal_id is not None and broader.principal_id is None:
        return False
    if broader.organization_id != narrower.organization_id:
        return False
    return broader.workplace_id is None or broader.workplace_id == narrower.workplace_id


__all__ = ["authorization_for_uow", "require_execution_handle"]
