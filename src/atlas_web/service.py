"""The Atlas-HQ web API slice: a server boundary over the Core Roles Engine.

This module is deliberately framework-agnostic. It takes a method, a path, and a
JSON body, and returns a status and a JSON-safe payload. ``atlas_web.http`` is a
thin standard-library adapter; a future framework adapter would call the same
:meth:`WebAppService.handle`. No FastAPI, no Flask, no Node backend.

Three rules define the whole design (contract §§38.8, 38.9, 38.13):

1. **The browser never holds an ``ExecutionHandle``.** A login mints an opaque,
   random, server-side session id; the browser only ever receives that id, in an
   ``HttpOnly`` cookie. The handle stays in the server's session store.
2. **The web layer is not an evaluator.** Every request resolves the session's
   Core handle, asks Core to issue *this request's* handle, and has Core decide.
   The service's only contribution to authorization is turning a Core decision
   code into an HTTP status through :func:`status_for_code`.
3. **A payload is never a fact.** Identity, channel, action, and the principal
   dimension of scope come from Core. A caller-supplied actor, principal,
   channel, or scope is refused, and the ``self.monthly.report`` route accepts no
   principal at all.

Session lifetimes are deliberately separate: a session outlives many requests,
and each request's handle lives for one request. Logout revokes the session's
Core handle, so the id stops working immediately rather than at its expiry.
"""

from __future__ import annotations

import os
import re
import secrets
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from threading import RLock
from typing import Any

from atlas_core.application.management import AuthorizationManagementService
from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.domain.role import AUTHORIZATION_MANAGE
from atlas_core.kernel import Kernel
from atlas_sdk import (
    AuthorizationError,
    CapabilityId,
    Channel,
    ExecutionHandle,
    NotFoundError,
    Scope,
    ScopeError,
)
from atlas_sdk.reporting import (
    REPORT_DEFINITION_CONTRACT,
    ReportDefinition,
    ReportDefinitionRequest,
    UseCaseMetadata,
)

#: The configured server-side principal the development login route may act as.
#: It is never read from a request, and the route fails closed without it.
OPERATOR_ENV = "ATLAS_WEB_OPERATOR_PRINCIPAL"
#: The dev login route is off unless this is explicitly switched on.
DEV_LOGIN_ENV = "ATLAS_WEB_DEV_LOGIN"

COOKIE_NAME = "atlas_session"
THEME_KEY = "theme"
THEMES: tuple[str, ...] = ("light", "dark")

#: The Core-owned actions this boundary can issue a handle for. A handle is bound
#: to exactly one action (contract §38.8), so these constants are the complete
#: list of actions the web surface can ever create.
CATALOGUE_ACTION = "authorization.catalogue.read"
PRINCIPAL_READ_ACTION = "authorization.principal.read"
CAPABILITY_ACTION = "authorization.capability.set"
ROLE_ACTION = "authorization.role.set"

DEFAULT_SESSION_TTL_SECONDS = 60 * 60
#: A request's own handle is used once, on the server, and never leaves it.
OPERATION_TTL_SECONDS = 60

_TRUTHY = frozenset({"1", "true", "yes", "on"})

#: Core decision code -> HTTP status. Anything not listed is a denial: default
#: deny means an unrecognised code can never be mistaken for an allow.
_STATUS_BY_CODE: Mapping[str, int] = {
    "handle_required": 401,
    "handle_invalid": 401,
    "persistence_required": 401,
    "session_unknown": 401,
    "session_revoked": 401,
    "session_expired": 401,
    "capability_denied": 403,
    "capability_binding_mismatch": 403,
    "policy_denied": 403,
    "assistant_required": 403,
    "confirmation_required": 403,
    "confirmation_consumed": 409,
    "request_invalid": 422,
}

#: One fixed message per status. Core's decision ``reason`` is never echoed, so an
#: error body cannot leak an internal message, a query, or a unit of work.
_PUBLIC_MESSAGE: Mapping[int, str] = {
    400: "the request could not be understood",
    401: "authentication is required",
    403: "this action is not permitted",
    404: "not found",
    405: "method not allowed",
    409: "the request conflicts with the current state",
    422: "the request is not valid",
    503: "the service is not configured",
}

#: Core's ``NotFoundError.kind`` -> the public code the client sees.
_CODE_BY_KIND: Mapping[str, str] = {
    "capability": "capability_unknown",
    "role": "role_unknown",
    "principal": "principal_unknown",
    "identity": "identity_unknown",
    "plugin": "plugin_unknown",
    "report_definition": "report_definition_unknown",
}

#: Facts a self-scoped read must never accept from a caller. The handle is the
#: identity, so naming one is refused rather than quietly ignored.
_PRINCIPAL_FACT_KEYS = frozenset(
    {
        "principal",
        "principal_id",
        "actor",
        "identity_id",
        "channel",
        "scope",
        "subject_id",
        "user_id",
    }
)


def status_for_code(code: str) -> int:
    """The HTTP status a Core decision code maps to. Default deny."""
    return _STATUS_BY_CODE.get(code, 403)


class ApiError(Exception):
    """A refusal the client is allowed to see, as a status and a public code."""

    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class WebResponse:
    status: int
    payload: Mapping[str, Any] = field(default_factory=dict)
    set_cookie: str | None = None


@dataclass(frozen=True)
class _Session:
    """One browser session: an opaque id, and the Core handle it stands for."""

    session_id: str
    principal_id: str
    handle: ExecutionHandle
    expires_at: datetime
    revoked: bool = False


# --- request body helpers --------------------------------------------------


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _scope(
    organization_id: str | None,
    workplace_id: str | None,
    principal_id: str | None,
) -> Scope:
    """Build a scope from ids. An empty result means no access at all."""
    return Scope(
        organization_id=organization_id or None,
        workplace_id=workplace_id or None,
        principal_id=principal_id or None,
    )


def _map_field(value: object, name: str, code: str = "body_invalid") -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ApiError(422, code)
    return value


def _use_case_payload(use_case: UseCaseMetadata | None) -> Mapping[str, Any]:
    if use_case is None:
        return {}
    return {
        "use_case_id": use_case.use_case_id,
        "title": use_case.title,
        "summary": use_case.summary,
        "owner": use_case.owner,
        "audience": use_case.audience,
        "scope": use_case.scope,
        "date_grain": use_case.date_grain,
        "required_capabilities": [str(item) for item in use_case.required_capabilities],
        "surfaces": list(use_case.surfaces),
        "review_status": use_case.review_status,
        "version": use_case.version,
    }


# --- the service -----------------------------------------------------------


class WebAppService:
    """The web API. One instance per server; sessions are process-local."""

    def __init__(
        self,
        kernel: Kernel,
        *,
        session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS,
    ) -> None:
        if kernel.uow_factory is None:
            # Contract §38.11: without a persistent PostgreSQL UoW there is no
            # Core decision, so the whole surface is refused rather than faked.
            msg = "the web surface requires a PostgreSQL unit-of-work factory"
            raise RuntimeError(msg)
        self._kernel = kernel
        self._uow_factory = kernel.uow_factory
        self._session_ttl = session_ttl_seconds
        self._sessions: dict[str, _Session] = {}
        self._lock = RLock()
        self._routes = _compile_routes()

    @property
    def kernel(self) -> Kernel:
        """The server-side kernel. Never reachable from an HTTP request."""
        return self._kernel

    @property
    def uow_factory(self) -> Any:
        return self._uow_factory

    @staticmethod
    def session_id_from_set_cookie(set_cookie: str) -> str:
        """Read the opaque session id back out of a ``Set-Cookie`` value."""
        return set_cookie.split(";", 1)[0].partition("=")[2].strip()

    # --- entry point -------------------------------------------------------

    def handle(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        json_body: Mapping[str, Any] | None = None,
        cookies: Mapping[str, str] | None = None,
    ) -> WebResponse:
        try:
            return self._dispatch(
                method.upper(),
                path,
                query or {},
                json_body,
                cookies or {},
            )
        except ApiError as error:
            return self._refusal(error.status, error.code)
        except NotFoundError as error:
            return self._refusal(404, _CODE_BY_KIND.get(error.kind, "not_found"))
        except ScopeError:
            return self._refusal(422, "scope_invalid")
        except AuthorizationError:
            return self._refusal(403, "access_denied")

    @staticmethod
    def _refusal(status: int, code: str) -> WebResponse:
        return WebResponse(status, {"error": {"code": code, "message": _PUBLIC_MESSAGE[status]}})

    def _dispatch(
        self,
        method: str,
        path: str,
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
        cookies: Mapping[str, str],
    ) -> WebResponse:
        path_seen = False
        for route_method, pattern, handler_name in self._routes:
            match = pattern.fullmatch(path)
            if match is None:
                continue
            path_seen = True
            if route_method != method:
                continue
            handler = getattr(self, handler_name)
            return handler(cookies, query, body, *match.groups())
        raise ApiError(
            405 if path_seen else 404,
            "method_not_allowed" if path_seen else "route_unknown",
        )

    # --- sessions ----------------------------------------------------------

    def _cookie(self, session_id: str, *, max_age: int | None = None) -> str:
        parts = [f"{COOKIE_NAME}={session_id}", "Path=/", "HttpOnly", "SameSite=Strict"]
        if max_age is not None:
            parts.append(f"Max-Age={max_age}")
        return "; ".join(parts)

    def _login(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
    ) -> WebResponse:
        """Development-only local operator login.

        The body is read by nobody. There is no field here that could name an
        actor, because the operator is server configuration: an environment
        variable naming an active Core principal. Both the switch and the
        principal are required, and either one missing fails closed.
        """
        if os.environ.get(DEV_LOGIN_ENV, "").strip().lower() not in _TRUTHY:
            raise ApiError(404, "login_disabled")
        principal_id = os.environ.get(OPERATOR_ENV, "").strip()
        if not principal_id:
            raise ApiError(503, "operator_not_configured")
        principal = self._kernel.authorization_management.get_principal(principal_id)
        if principal is None or not principal.active:
            raise ApiError(503, "operator_not_configured")

        # The session handle authenticates the session; it authorizes nothing.
        # Each request issues its own handle and Core decides on that.
        handle = self._kernel.issue_execution_handle(
            principal_id=principal_id,
            capability=AUTHORIZATION_MANAGE,
            action=CATALOGUE_ACTION,
            scope=_scope(None, None, principal_id),
            channel=Channel.WEB,
            ttl_seconds=self._session_ttl,
        )
        session = _Session(
            session_id=secrets.token_urlsafe(32),
            principal_id=principal_id,
            handle=handle,
            expires_at=datetime.now(UTC) + timedelta(seconds=self._session_ttl),
        )
        with self._lock:
            self._sessions[session.session_id] = session
        return WebResponse(
            201,
            {"authenticated": True, "principal_id": principal_id, "development_only": True},
            set_cookie=self._cookie(session.session_id),
        )

    def _session_info(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
    ) -> WebResponse:
        session = self._require_session(cookies)
        return WebResponse(
            200,
            {
                "authenticated": True,
                "principal_id": session.principal_id,
                "expires_at": session.expires_at.isoformat(),
            },
        )

    def _logout(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
    ) -> WebResponse:
        session_id = (cookies.get(COOKIE_NAME) or "").strip()
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ApiError(401, "session_unknown")
            if session.revoked:
                raise ApiError(401, "session_revoked")
            # A revoked session keeps its record so a replayed id is told the
            # truth. ponytail: the store only grows within one process run; evict
            # tombstones by expiry if a long-lived server ever needs the memory.
            self._sessions[session_id] = replace(session, revoked=True)
        # Revoke the Core handle too, so the id resolves to nothing even if the
        # session record were somehow restored.
        self._kernel.revoke_execution_handle(session.handle)
        return WebResponse(204, {}, set_cookie=self._cookie("", max_age=0))

    def _require_session(self, cookies: Mapping[str, str]) -> _Session:
        """Resolve the opaque cookie to a live session, or fail closed.

        The principal is re-read from Core on every request, so a deactivated
        principal, a revoked handle, or an expired handle all stop the session
        here rather than at some later check.
        """
        session_id = (cookies.get(COOKIE_NAME) or "").strip()
        if not session_id:
            raise ApiError(401, "session_unknown")
        with self._lock:
            session = self._sessions.get(session_id)
        if session is None:
            raise ApiError(401, "session_unknown")
        if session.revoked:
            raise ApiError(401, "session_revoked")
        if session.expires_at <= datetime.now(UTC):
            self._discard(session_id)
            raise ApiError(401, "session_expired")
        try:
            facts = self._kernel.resolve_execution_handle(session.handle)
        except (AuthorizationError, TypeError, ValueError):
            self._discard(session_id)
            raise ApiError(401, "session_revoked") from None
        return replace(session, principal_id=facts.principal_id)

    def _discard(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    # --- the Core boundary -------------------------------------------------

    def _authorization(self, uow: UnitOfWorkPort) -> Any:
        """The per-transaction Core authorization view.

        The Kernel owns policy registration and evaluation (contract §38.10);
        this is the same per-unit-of-work view the CLI's trusted boundary builds,
        and it is the only way this service can ask Core for a decision.
        """
        policy = self._kernel._policy.bind_uow(uow)
        return self._kernel._authorization.for_uow(uow, policy=policy)

    @contextmanager
    def _authorized(
        self,
        session: _Session,
        *,
        capability: CapabilityId,
        action: str,
        scope: Scope,
        resource_id: str | None = None,
        additional_capabilities: Sequence[CapabilityId] = (),
        confirmation_id: str | None = None,
        confirmation_request: bool = False,
        atomic: bool = True,
    ) -> Iterator[tuple[UnitOfWorkPort, ExecutionHandle, Any]]:
        """Issue this request's handle, have Core decide, and run the body.

        With ``atomic`` the handle, the decision, and the business mutation share
        one unit of work, so an allowed decision and its change commit or roll
        back together (contract §38.11). A denial rolls that transaction back; the
        durable denial audit is already committed by Core through its own
        independent unit of work.

        ``confirmation_request`` asks Core to authorize *issuing* a confirmation
        rather than consuming one, which is the only check that can succeed while
        the policy already demands a confirmation.

        ``atomic=False`` commits the handle and the decision *before* the body
        runs, which is what the plugin routes need: a plugin owns its own
        transaction and has to be able to resolve the handle Core just issued.
        """
        uow = self._uow_factory()
        committed = False
        try:
            uow.begin()
            authorization = self._authorization(uow)
            handle = authorization.issue_handle(
                principal_id=session.principal_id,
                capability=capability,
                action=action,
                scope=scope,
                channel=Channel.WEB,
                resource_id=resource_id,
                additional_capabilities=tuple(additional_capabilities),
                ttl_seconds=OPERATION_TTL_SECONDS,
            )
            decision = (
                authorization.authorize_confirmation_request(handle, capability, scope)
                if confirmation_request
                else authorization.authorize(
                    handle,
                    capability,
                    scope,
                    confirmation_id=confirmation_id,
                )
            )
            if not decision.allowed:
                uow.rollback()
                raise ApiError(status_for_code(decision.code), decision.code or "access_denied")
            if not atomic:
                uow.commit()
                committed = True
            yield uow, handle, authorization
            uow.commit()
            committed = True
        finally:
            if not committed:
                with suppress(BaseException):  # the request is failing anyway
                    uow.rollback()
            uow.close()

    def _management(
        self,
        uow: UnitOfWorkPort,
        authorization: Any,
    ) -> AuthorizationManagementService:
        """The Core-only administrative boundary over this request's transaction."""
        return AuthorizationManagementService(uow=uow, authorization=authorization)

    def _plugin(self, plugin_id: str) -> Any:
        """The live instance of an enabled plugin.

        The console reaches a plugin's own API only where a plugin owns the
        business operation, exactly as the CLI's ``report`` command does. Every
        other route uses Core services and the published contracts.
        """
        instances = getattr(self._kernel, "_instances", {})
        plugin = instances.get(plugin_id)
        if plugin is None:
            raise ApiError(503, "plugin_unavailable")
        return plugin

    # --- catalogue ---------------------------------------------------------

    def _capabilities(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
    ) -> WebResponse:
        session = self._require_session(cookies)
        with self._authorized(
            session,
            capability=AUTHORIZATION_MANAGE,
            action=CATALOGUE_ACTION,
            scope=_scope(None, None, session.principal_id),
        ) as (uow, _handle, authorization):
            definitions = self._management(uow, authorization).list_capabilities()
        return WebResponse(
            200,
            {
                "capabilities": [
                    {
                        "capability_id": str(item.capability_id),
                        "kind": item.kind.value,
                        "name": item.name,
                        "provider_id": item.provider_id,
                    }
                    for item in definitions
                ]
            },
        )

    def _roles(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
    ) -> WebResponse:
        session = self._require_session(cookies)
        with self._authorized(
            session,
            capability=AUTHORIZATION_MANAGE,
            action=CATALOGUE_ACTION,
            scope=_scope(None, None, session.principal_id),
        ) as (uow, _handle, authorization):
            roles = self._management(uow, authorization).list_roles()
        return WebResponse(
            200,
            {
                "roles": [
                    {
                        "role_id": item.role_id,
                        "name": item.name,
                        "capabilities": sorted(str(value) for value in item.capabilities),
                        "owner_plugin_id": item.owner_plugin_id,
                    }
                    for item in roles
                ]
            },
        )

    def _principals(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
    ) -> WebResponse:
        """The principal directory, exactly as Core holds it, for a picker.

        The same Core-owned read as the capability and role catalogues: a live
        session, one request handle, one Core decision on ``authorization.manage``
        in the caller's own scope. It names no principal, accepts none from the
        caller, and projects only the three fields a picker needs — never the
        principal's stored metadata, which is a preference rather than an
        identity fact. Inactive principals are listed, not hidden: a management
        view has to be able to see the principal it may reactivate.
        """
        session = self._require_session(cookies)
        _refuse_principal_facts(query, None)
        with self._authorized(
            session,
            capability=AUTHORIZATION_MANAGE,
            action=PRINCIPAL_READ_ACTION,
            scope=_scope(None, None, session.principal_id),
        ) as (uow, _handle, authorization):
            principals = self._management(uow, authorization).list_principals()
        return WebResponse(
            200,
            {
                "principals": [
                    {
                        "principal_id": item.principal_id,
                        "display_name": item.display_name,
                        "active": item.active,
                    }
                    for item in principals
                ]
            },
        )

    def _permissions(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
        principal_id: str,
    ) -> WebResponse:
        """The subject's effective permissions, as Core computed them.

        Three scopes, deliberately distinct. The *execution* is the operator's
        own. The *reported* scope is exactly the organization and workplace the
        caller named, with no principal dimension: a management view of an
        organization, never a peek at somebody's self scope. And the subject
        appears only as the resource being reported on, never as a scope.
        """
        session = self._require_session(cookies)
        organization_id = _text(query.get("organization_id"))
        workplace_id = _text(query.get("workplace_id"))
        execution_scope = _scope(organization_id, workplace_id, session.principal_id)
        reported_scope = _scope(organization_id, workplace_id, None)
        with self._authorized(
            session,
            capability=AUTHORIZATION_MANAGE,
            action=PRINCIPAL_READ_ACTION,
            scope=execution_scope,
            resource_id=principal_id,
        ) as (uow, _handle, authorization):
            management = self._management(uow, authorization)
            if management.get_principal(principal_id) is None:
                raise ApiError(404, "principal_unknown")
            permissions = management.effective_permissions(principal_id, reported_scope)
        return WebResponse(
            200,
            {
                "principal_id": principal_id,
                "scope": {
                    "organization_id": reported_scope.organization_id,
                    "workplace_id": reported_scope.workplace_id,
                    "principal_id": reported_scope.principal_id,
                },
                "capabilities": sorted(str(value) for value in permissions.capabilities),
                "direct_capabilities": sorted(
                    str(value) for value in permissions.direct_capability_ids
                ),
                "role_ids": sorted(permissions.role_ids),
            },
        )

    def _grants(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
        principal_id: str,
    ) -> WebResponse:
        """Every capability and role's state for one subject, in one scope.

        The same protections as the permissions route: a live session, one
        request handle, one Core decision on ``authorization.manage`` in the
        caller's own scope, and the subject only ever as the resource reported
        on. The reported scope is exactly the organization and workplace the
        caller named, with no principal dimension; a caller that names no scope
        is refused rather than answered for all of them at once.

        The payload is checkbox state and nothing else: no principal metadata,
        no theme, and no principal fact from the caller.
        """
        session = self._require_session(cookies)
        _refuse_principal_facts(query, None)
        organization_id = _text(query.get("organization_id"))
        workplace_id = _text(query.get("workplace_id"))
        execution_scope = _scope(organization_id, workplace_id, session.principal_id)
        reported_scope = _scope(organization_id, workplace_id, None)
        if reported_scope.is_empty:
            raise ApiError(422, "scope_invalid")
        with self._authorized(
            session,
            capability=AUTHORIZATION_MANAGE,
            action=PRINCIPAL_READ_ACTION,
            scope=execution_scope,
            resource_id=principal_id,
        ) as (uow, _handle, authorization):
            management = self._management(uow, authorization)
            if management.get_principal(principal_id) is None:
                raise ApiError(404, "principal_unknown")
            state = management.grant_state(principal_id, reported_scope)
        return WebResponse(
            200,
            {
                "principal_id": state.principal_id,
                "scope": {
                    "organization_id": reported_scope.organization_id,
                    "workplace_id": reported_scope.workplace_id,
                    "principal_id": reported_scope.principal_id,
                },
                "capabilities": [
                    {
                        "capability_id": str(item.capability_id),
                        "direct": item.direct,
                        "role_ids": list(item.role_ids),
                    }
                    for item in state.capabilities
                ],
                "roles": [
                    {"role_id": item.role_id, "assigned": item.assigned} for item in state.roles
                ],
                "effective_capability_ids": sorted(
                    str(value) for value in state.effective_capability_ids
                ),
            },
        )

    # --- the management checkboxes ----------------------------------------

    def _set_capability(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
        principal_id: str,
        capability_id: str,
    ) -> WebResponse:
        session = self._require_session(cookies)
        checked, target, confirmation_id = _checkbox(body)
        execution_scope = _scope(
            target.organization_id,
            target.workplace_id,
            session.principal_id,
        )
        with self._authorized(
            session,
            capability=AUTHORIZATION_MANAGE,
            action=CAPABILITY_ACTION,
            scope=execution_scope,
            resource_id=principal_id,
            confirmation_id=confirmation_id,
        ) as (uow, _handle, authorization):
            self._apply_capability(
                self._management(uow, authorization),
                session.principal_id,
                principal_id,
                CapabilityId(capability_id),
                target,
                checked,
            )
        return WebResponse(200, {"capability_id": capability_id, "checked": checked})

    @staticmethod
    def _apply_capability(
        management: AuthorizationManagementService,
        actor: str,
        principal_id: str,
        capability: CapabilityId,
        target: Scope,
        checked: bool,
    ) -> None:
        if checked:
            management.grant_capability(principal_id, capability, target, actor=actor)
        else:
            management.revoke_capability(principal_id, capability, target, actor=actor)

    def _set_role(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
        principal_id: str,
        role_id: str,
    ) -> WebResponse:
        session = self._require_session(cookies)
        checked, target, confirmation_id = _checkbox(body)
        execution_scope = _scope(
            target.organization_id,
            target.workplace_id,
            session.principal_id,
        )
        with self._authorized(
            session,
            capability=AUTHORIZATION_MANAGE,
            action=ROLE_ACTION,
            scope=execution_scope,
            resource_id=principal_id,
            confirmation_id=confirmation_id,
        ) as (uow, _handle, authorization):
            management = self._management(uow, authorization)
            if checked:
                management.assign_role(principal_id, role_id, target, actor=session.principal_id)
            else:
                management.revoke_role(principal_id, role_id, target, actor=session.principal_id)
        return WebResponse(200, {"role_id": role_id, "checked": checked})

    # --- self report -------------------------------------------------------

    def _self_report(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
    ) -> WebResponse:
        """The session principal's own monthly report, on demand.

        No principal, actor, channel, or scope is accepted here in any form. The
        handle is the identity, and the plugin asks Core who the handle belongs
        to before it reads a single row (contract §38.6).
        """
        from atlas_plugins.self_reporting import (  # imported lazily: plugin-owned
            SELF_REPORT_ACTION,
            SELF_REPORT_VIEW,
            SelfReportRequest,
        )

        session = self._require_session(cookies)
        _refuse_principal_facts(query, body)
        with self._authorized(
            session,
            capability=SELF_REPORT_VIEW,
            action=SELF_REPORT_ACTION,
            scope=_scope(None, None, session.principal_id),
            atomic=False,
        ) as (_uow, handle, _authorization):
            report = self._plugin("self_reporting").render(
                SelfReportRequest(),
                execution_handle=handle,
            )
        return WebResponse(
            200,
            {
                "principal_id": report.principal_id,
                "use_case": _use_case_payload(report.use_case),
                "sections": [
                    {
                        "dataset_id": section.dataset_id,
                        "title": section.title,
                        "installed": section.installed,
                        "note": section.note,
                        "columns": list(section.columns),
                        "groups": [
                            {
                                "key": list(group.key),
                                "count": group.count,
                                "rows": [list(row) for row in group.rows],
                            }
                            for group in section.groups
                        ],
                    }
                    for section in report.sections
                ],
                "audit_id": report.audit_id,
            },
        )

    # --- reports -----------------------------------------------------------

    def _reports(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
    ) -> WebResponse:
        session = self._require_session(cookies)
        with self._authorized(
            session,
            capability=AUTHORIZATION_MANAGE,
            action=CATALOGUE_ACTION,
            scope=_scope(None, None, session.principal_id),
            atomic=False,
        ) as (_uow, handle, _authorization):
            definitions = _discover_definitions(self._kernel, handle)
        return WebResponse(
            200,
            {
                "reports": [
                    {
                        "definition_id": definition.definition_id,
                        "title": definition.title,
                        "dataset_ids": list(definition.dataset_ids),
                        "use_case": _use_case_payload(definition.use_case),
                    }
                    for definition in definitions
                ]
            },
        )

    def _render_report(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
        definition_id: str,
    ) -> WebResponse:
        from atlas_plugins.report_studio import REPORT_RENDER, ReportRequest  # plugin-owned

        session = self._require_session(cookies)
        organization_id = _text(_map_field(body, "body_invalid").get("organization_id"))
        if not organization_id:
            raise ApiError(422, "body_invalid")
        # Report Studio asks for the organization itself, so the handle is issued
        # for the organization and nothing more. A self-scoped dataset inside an
        # organization render denies this execution, which is the correct answer
        # and not a gap in it.
        execution_scope = _scope(organization_id, None, None)

        # Two Core decisions, both through Core. The catalogue read finds the
        # definition and its declared use case; the render handle then binds
        # report.render *and* the use case's own capabilities, so the plugin
        # chain rechecks each one itself rather than trusting this route.
        with self._authorized(
            session,
            capability=AUTHORIZATION_MANAGE,
            action=CATALOGUE_ACTION,
            scope=execution_scope,
            atomic=False,
        ) as (_uow, handle, _authorization):
            definition = next(
                (
                    found
                    for found in _discover_definitions(self._kernel, handle)
                    if found.definition_id == definition_id
                ),
                None,
            )
        if definition is None:
            raise ApiError(404, "report_definition_unknown")

        required = (
            tuple(CapabilityId(str(value)) for value in definition.use_case.required_capabilities)
            if definition.use_case is not None
            else ()
        )
        with self._authorized(
            session,
            capability=REPORT_RENDER,
            action="report.render",
            scope=execution_scope,
            resource_id=organization_id,
            additional_capabilities=required,
            atomic=False,
        ) as (_uow, handle, _authorization):
            report = self._plugin("report_studio").render_definition(
                ReportRequest(organization_id=organization_id),
                definition_id,
                execution_handle=handle,
            )
        return WebResponse(
            200,
            {
                "definition_id": definition_id,
                "organization_id": report.organization_id,
                "sections": [
                    {
                        "dataset_id": section.dataset_id,
                        "title": section.title,
                        "installed": section.installed,
                        "note": section.note,
                        "columns": list(section.columns),
                        "groups": [
                            {
                                "key": list(group.key),
                                "count": group.count,
                                "rows": [list(row) for row in group.rows],
                            }
                            for group in section.groups
                        ],
                    }
                    for section in report.sections
                ],
                "audit_id": report.audit_id,
            },
        )

    # --- theme -------------------------------------------------------------

    def _get_theme(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
    ) -> WebResponse:
        """The session principal's own theme preference.

        A preference is not a protected action: it has no capability, no policy,
        and no scope beyond the session itself, and nothing in the authorization
        path ever reads it back (contract §38.3).
        """
        session = self._require_session(cookies)
        principal = self._kernel.authorization_management.get_principal(session.principal_id)
        stored = principal.metadata.get(THEME_KEY) if principal is not None else None
        return WebResponse(200, {"theme": stored if stored in THEMES else THEMES[0]})

    def _put_theme(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
    ) -> WebResponse:
        session = self._require_session(cookies)
        theme = _map_field(body, "theme_invalid").get("theme")
        if theme not in THEMES:
            raise ApiError(422, "theme_invalid")
        self._kernel.authorization_management.set_principal_metadata(
            session.principal_id,
            THEME_KEY,
            str(theme),
            actor=session.principal_id,
        )
        return WebResponse(200, {"theme": str(theme)})

    # --- typed confirmations -----------------------------------------------

    def _confirmations(
        self,
        cookies: Mapping[str, str],
        query: Mapping[str, str],
        body: Mapping[str, Any] | None,
    ) -> WebResponse:
        """Ask Core for a typed, one-time confirmation of a pending action.

        The request names the capability, the action, and the resource the
        action is about. None of that is authority: the handle is issued for
        exactly that triple, Core binds the confirmation to the canonical facts
        it resolved, and the confirmation is only ever consumed by a later Core
        decision that resolves the same target.
        """
        session = self._require_session(cookies)
        payload = _map_field(body, "body_invalid")
        capability_id = _text(payload.get("capability"))
        action = _text(payload.get("action"))
        if not capability_id or not action:
            raise ApiError(422, "body_invalid")
        raw_scope = payload.get("scope")
        requested = _map_field(raw_scope, "scope_invalid") if raw_scope is not None else {}
        scope = _scope(
            _text(requested.get("organization_id")),
            _text(requested.get("workplace_id")),
            session.principal_id,
        )
        if scope.is_empty:
            raise ApiError(422, "scope_invalid")
        with self._authorized(
            session,
            capability=CapabilityId(capability_id),
            action=action,
            scope=scope,
            resource_id=_text(payload.get("resource_id")) or None,
            confirmation_request=True,
        ) as (uow, handle, authorization):
            confirmation_id = self._management(uow, authorization).confirm(
                handle,
                CapabilityId(capability_id),
            )
        return WebResponse(201, {"confirmation_id": confirmation_id})


# --- module-level helpers --------------------------------------------------


def _checkbox(body: Mapping[str, Any] | None) -> tuple[bool, Scope, str | None]:
    """Read one management checkbox: its state, its grant scope, its confirmation.

    The grant scope is the organization and workplace, plus an *optional*
    top-level ``principal_id`` for a self-scoped grant. A ``principal_id``
    nested inside ``scope`` is refused rather than quietly dropped, so a client
    can never think it made a self grant when it made an organization-wide one.

    The checkbox state is advisory. It only selects which Core call to make; Core
    rechecks authorization, principal activity, and capability registration on
    both the grant and the revoke.
    """
    payload = _map_field(body, "body_invalid")
    checked = payload.get("checked")
    if not isinstance(checked, bool):
        raise ApiError(422, "body_invalid")
    raw = _map_field(payload.get("scope", {}), "body_invalid")
    if "principal_id" in raw:
        raise ApiError(422, "scope_invalid")
    target = _scope(
        *_requested_scope(raw),
        _text(payload.get("principal_id")) or None,
    )
    if target.is_empty:
        raise ApiError(422, "scope_invalid")
    return checked, target, _text(payload.get("confirmation_id")) or None


def _requested_scope(raw: Mapping[str, Any]) -> tuple[str | None, str | None]:
    return _text(raw.get("organization_id")) or None, _text(raw.get("workplace_id")) or None


def _refuse_principal_facts(
    query: Mapping[str, str],
    body: Mapping[str, Any] | None,
) -> None:
    """Refuse a self-scoped read that names its own identity in any form."""
    supplied = {key for key in (*query, *(body or ())) if key in _PRINCIPAL_FACT_KEYS}
    if supplied:
        raise ApiError(422, "principal_not_accepted")


def _discover_definitions(kernel: Kernel, handle: ExecutionHandle) -> list[ReportDefinition]:
    """Every enabled provider's report definition, through the public contract.

    Each provider answers with the one definition it owns, so an empty probe
    collects the whole catalogue. The web layer names no plugin and reads no
    plugin table (contract §13).
    """
    responses = kernel.registries.contracts.invoke_all(
        REPORT_DEFINITION_CONTRACT,
        ReportDefinitionRequest(definition_id=""),
        execution_handle=handle,
    )
    found: dict[str, ReportDefinition] = {}
    for response in responses:
        if isinstance(response, ReportDefinition):
            found.setdefault(response.definition_id, response)
    return [found[key] for key in sorted(found)]


def _compile_routes() -> tuple[tuple[str, re.Pattern[str], str], ...]:
    """(method, path pattern, bound handler name) for the whole surface."""
    return (
        ("POST", re.compile(r"/api/session"), "_login"),
        ("GET", re.compile(r"/api/session"), "_session_info"),
        ("DELETE", re.compile(r"/api/session"), "_logout"),
        ("GET", re.compile(r"/api/session/theme"), "_get_theme"),
        ("PUT", re.compile(r"/api/session/theme"), "_put_theme"),
        ("GET", re.compile(r"/api/capabilities"), "_capabilities"),
        ("GET", re.compile(r"/api/roles"), "_roles"),
        ("GET", re.compile(r"/api/principals"), "_principals"),
        (
            "GET",
            re.compile(r"/api/principals/(?P<principal>[^/]+)/permissions"),
            "_permissions",
        ),
        (
            "GET",
            re.compile(r"/api/principals/(?P<principal>[^/]+)/grants"),
            "_grants",
        ),
        (
            "PUT",
            re.compile(r"/api/principals/(?P<principal>[^/]+)/capabilities/(?P<capability>[^/]+)"),
            "_set_capability",
        ),
        (
            "PUT",
            re.compile(r"/api/principals/(?P<principal>[^/]+)/roles/(?P<role>[^/]+)"),
            "_set_role",
        ),
        ("GET", re.compile(r"/api/reports"), "_reports"),
        ("POST", re.compile(r"/api/reports/(?P<definition>[^/]+)/render"), "_render_report"),
        ("GET", re.compile(r"/api/self/monthly-report"), "_self_report"),
        ("POST", re.compile(r"/api/confirmations"), "_confirmations"),
    )


__all__ = [
    "CATALOGUE_ACTION",
    "COOKIE_NAME",
    "DEV_LOGIN_ENV",
    "OPERATOR_ENV",
    "THEMES",
    "THEME_KEY",
    "ApiError",
    "WebAppService",
    "WebResponse",
    "status_for_code",
]
