"""Core-owned issuance, persistence, resolution, and expiry of execution handles."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from weakref import WeakKeyDictionary

from atlas_sdk import AuthorizationError, CapabilityId, Channel, ExecutionHandle, Scope

from ..domain.execution import ExecutionFacts, PersistedExecution, freeze_policy_context
from .unit_of_work import UnitOfWorkPort

DEFAULT_HANDLE_TTL_SECONDS = 15 * 60
_ISSUED_HANDLE_TOKENS: WeakKeyDictionary[ExecutionHandle, str] = WeakKeyDictionary()


def _new_core_handle(token: str) -> ExecutionHandle:
    """Create a handle without exposing a construction seal in the SDK."""
    handle = object.__new__(ExecutionHandle)
    object.__setattr__(handle, "_ExecutionHandle__token", token)
    _ISSUED_HANDLE_TOKENS[handle] = token
    return handle


def _core_handle_token(handle: ExecutionHandle) -> str:
    """Read a handle's bearer token inside Core; the SDK exposes no reader."""
    if not isinstance(handle, ExecutionHandle):
        raise TypeError("a server-issued ExecutionHandle is required")
    try:
        token = _ISSUED_HANDLE_TOKENS[handle]
    except (KeyError, TypeError) as exc:
        raise TypeError("a server-issued ExecutionHandle is required") from exc
    if not isinstance(token, str) or not token:
        raise TypeError("a server-issued ExecutionHandle is required")
    return token


def _scope_contains(broader: Scope, narrower: Scope) -> bool:
    if broader.is_empty or narrower.is_empty:
        return False
    if broader.principal_id is not None and broader.principal_id != narrower.principal_id:
        return False
    if narrower.principal_id is not None and broader.principal_id is None:
        return False
    return broader.organization_id == narrower.organization_id and (
        broader.workplace_id is None or broader.workplace_id == narrower.workplace_id
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ExecutionHandleStore:
    """The only component that translates a bearer handle to Core facts."""

    def __init__(self, uow: UnitOfWorkPort) -> None:
        if getattr(uow, "executions", None) is None:
            raise RuntimeError("execution handles require a persistent PostgreSQL UoW")
        self._uow = uow

    def issue(self, facts: ExecutionFacts) -> ExecutionHandle:
        token = secrets.token_urlsafe(48)
        now = datetime.now(UTC)
        expires_at = facts.expires_at or (now + timedelta(seconds=DEFAULT_HANDLE_TTL_SECONDS))
        if expires_at <= now:
            raise AuthorizationError("an execution handle must expire in the future")
        self._uow.executions.add(
            PersistedExecution(
                token_hash=_token_hash(token),
                facts=ExecutionFacts(
                    principal_id=facts.principal_id,
                    capability_id=facts.capability_id,
                    allowed_capability_ids=frozenset(facts.allowed_capability_ids),
                    action=facts.action,
                    scope=facts.scope,
                    channel=facts.channel,
                    resource_id=facts.resource_id,
                    identity_id=facts.identity_id,
                    policy_context=freeze_policy_context(dict(facts.policy_context)),
                    expires_at=expires_at,
                ),
                created_at=now,
            )
        )
        return _new_core_handle(token)

    def resolve(self, handle: ExecutionHandle) -> ExecutionFacts:
        record = self._uow.executions.get(_token_hash(_core_handle_token(handle)))
        now = datetime.now(UTC)
        if record is None:
            raise AuthorizationError("unknown ExecutionHandle")
        if record.revoked_at is not None:
            raise AuthorizationError("ExecutionHandle has been revoked")
        if record.facts.expires_at is not None and record.facts.expires_at <= now:
            token_hash = _token_hash(_core_handle_token(handle))
            self._mark_expired(token_hash)
            raise AuthorizationError("ExecutionHandle has expired")
        return record.facts

    def _mark_expired(self, token_hash: str) -> None:
        def mark() -> None:
            self._uow.executions.revoke(token_hash)

        if getattr(self._uow, "in_transaction", False):
            mark()
            return
        self._uow.begin()
        try:
            mark()
            self._uow.commit()
        except BaseException:
            self._uow.rollback()
            raise

    def revoke(self, handle: ExecutionHandle) -> bool:
        return self._uow.executions.revoke(_token_hash(_core_handle_token(handle)))

    def expire_due(self, now: datetime | None = None) -> int:
        return self._uow.executions.expire_due(now or datetime.now(UTC))


class ExecutionHandleIssuer:
    """Trusted boundary that authenticates a principal before issuing a handle."""

    def __init__(self, uow: UnitOfWorkPort, store: ExecutionHandleStore) -> None:
        self._uow = uow
        self._store = store

    def issue(
        self,
        *,
        principal_id: str,
        capability: CapabilityId,
        action: str,
        scope: Scope,
        channel: Channel | str,
        resource_id: str | None = None,
        identity_id: str | None = None,
        policy_context: Mapping[str, Any] | None = None,
        additional_capabilities: Iterable[CapabilityId] = (),
        ttl_seconds: int = DEFAULT_HANDLE_TTL_SECONDS,
    ) -> ExecutionHandle:
        if not principal_id.strip() or not action.strip() or scope.is_empty:
            raise AuthorizationError("principal, action, and a non-empty scope are required")
        if ttl_seconds <= 0 or ttl_seconds > 86_400:
            raise ValueError("execution handle TTL must be between 1 second and 24 hours")
        selected_channel = Channel(channel)
        principal = self._uow.authorization.get_principal(principal_id)
        if principal is None or not principal.active:
            raise AuthorizationError("an active Core principal is required")
        if scope.principal_id is not None and scope.principal_id != principal_id:
            raise AuthorizationError("handle scope does not belong to the authenticated principal")
        if identity_id is not None:
            identity = self._uow.authorization.get_identity(identity_id)
            if (
                identity is None
                or identity.channel != selected_channel.value
                or not identity.active
                or not identity.trusted
                or identity.principal_id != principal_id
            ):
                raise AuthorizationError("the linked channel identity is not valid")
        elif selected_channel is Channel.TELEGRAM:
            raise AuthorizationError("Telegram requires a linked identity")
        issued_capability = CapabilityId(capability)
        additional = frozenset(CapabilityId(value) for value in additional_capabilities)
        if any(not str(value).strip() for value in additional):
            raise AuthorizationError("additional capabilities must be non-empty")
        return self._store.issue(
            ExecutionFacts(
                principal_id=principal_id,
                capability_id=issued_capability,
                allowed_capability_ids=frozenset({issued_capability, *additional}),
                action=action,
                scope=scope,
                channel=selected_channel,
                resource_id=resource_id,
                identity_id=identity_id,
                policy_context=freeze_policy_context(dict(policy_context or {})),
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
            )
        )


class ExecutionHandleResolver:
    """Resolve a handle and recheck persistent identity/principal state."""

    def __init__(self, uow: UnitOfWorkPort, store: ExecutionHandleStore) -> None:
        self._uow = uow
        self._store = store

    def resolve(
        self,
        handle: ExecutionHandle,
        *,
        requested_scope: Scope | None = None,
        requested_channel: Channel | str | None = None,
        requested_action: str | None = None,
        requested_resource_id: str | None = None,
    ) -> ExecutionFacts:
        facts = self._store.resolve(handle)
        principal = self._uow.authorization.get_principal(facts.principal_id)
        if principal is None or not principal.active:
            raise AuthorizationError("the execution principal is no longer active")
        if facts.identity_id is not None:
            identity = self._uow.authorization.get_identity(facts.identity_id)
            if (
                identity is None
                or identity.channel != facts.channel.value
                or not identity.active
                or not identity.trusted
                or identity.principal_id != facts.principal_id
            ):
                raise AuthorizationError("the execution identity is no longer valid")
        elif facts.channel is Channel.TELEGRAM:
            raise AuthorizationError("Telegram requires a linked identity")
        if requested_scope is not None and not _scope_contains(facts.scope, requested_scope):
            raise AuthorizationError("requested scope is outside the issued execution")
        if requested_channel is not None and Channel(requested_channel) is not facts.channel:
            raise AuthorizationError("requested channel is outside the issued execution")
        if requested_action is not None and requested_action != facts.action:
            raise AuthorizationError("requested action is outside the issued execution")
        if requested_resource_id is not None and requested_resource_id != facts.resource_id:
            raise AuthorizationError("requested resource is outside the issued execution")
        return facts


__all__ = [
    "DEFAULT_HANDLE_TTL_SECONDS",
    "ExecutionHandleIssuer",
    "ExecutionHandleResolver",
    "ExecutionHandleStore",
]
