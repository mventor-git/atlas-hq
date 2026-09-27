"""The Atlas-HQ web API slice — server-side sessions over the Core boundary.

The web layer is a *server boundary*, not a second evaluator. Every request is
authenticated by an opaque server-side session that maps to one Core-issued
``ExecutionHandle``; the browser only ever holds an opaque session cookie. The
Core Roles Engine issues, resolves, and rechecks authorization exactly as it does
for the CLI, the contract handlers, and the plugins (contract §§38.8, 38.9, 38.13).

What this suite pins down:

* the session id is the only credential, and it is never a handle;
* a caller cannot name an actor, and identity comes only from Core;
* checkbox state is advisory — the server rechecks through Core;
* ``self.monthly.report`` takes no principal from the body;
* the theme preference is self-scoped, persisted through Core, and grants nothing;
* report definitions are discovered through the published contract;
* Core decision codes map to 401/403/404/409/422 without leaking internals;
* logout revokes the session's handle, so that id stops working immediately.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import date
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from tests.synthetic import refresh_metadata_cache

from atlas_core.application.unit_of_work import UnitOfWorkPort
from atlas_core.domain.role import AUTHORIZATION_MANAGE
from atlas_core.infrastructure.persistence.migrations import apply_migrations
from atlas_core.kernel import Kernel
from atlas_plugins.construction_reporting import CONSTRUCTION_DAILY_WORKFORCE
from atlas_plugins.report_studio import REPORT_RENDER
from atlas_plugins.self_reporting import (
    SELF_REPORT_VIEW,
    SELF_REPORT_VIEWER_ROLE,
)
from atlas_sdk import Channel, Scope
from atlas_web import COOKIE_NAME, DEV_LOGIN_ENV, OPERATOR_ENV, WebAppService
from atlas_web.http import WebRequestHandler

OPERATOR = "atlas.local.operator"
ORG = "org-web"
WEB_TEST_ENTRY_POINT_GROUP = "atlas.test.web"


# --- fixtures --------------------------------------------------------------


@pytest.fixture
def web_kernel(
    uow_factory: Callable[[], UnitOfWorkPort],
    isolated_plugins: Path,
) -> Kernel:
    """Boot the reporting plugin trio behind an isolated entry-point group."""
    dist_info = isolated_plugins / "atlas-hq-web-0.1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: atlas-hq-web\nVersion: 0.1.0\n",
        encoding="utf-8",
    )
    (dist_info / "entry_points.txt").write_text(
        f"[{WEB_TEST_ENTRY_POINT_GROUP}]\n"
        "report_studio = atlas_plugins.report_studio:ReportStudioPlugin\n"
        "self_reporting = atlas_plugins.self_reporting:SelfReportingPlugin\n"
        "construction_reporting = atlas_plugins.construction_reporting:"
        "ConstructionReportingPlugin\n",
        encoding="utf-8",
    )
    refresh_metadata_cache()
    kernel = Kernel(uow_factory=uow_factory, entry_point_group=WEB_TEST_ENTRY_POINT_GROUP)
    kernel.boot()
    kernel.enable("self_reporting")
    kernel.enable("report_studio")
    kernel.enable("construction_reporting")
    return kernel


@pytest.fixture
def web_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """The two pieces of server configuration the dev login route requires."""
    monkeypatch.setenv(OPERATOR_ENV, OPERATOR)
    monkeypatch.setenv(DEV_LOGIN_ENV, "1")


@pytest.fixture
def service(web_kernel: Kernel, web_config: None) -> WebAppService:
    return WebAppService(web_kernel)


# --- helpers ---------------------------------------------------------------


def _operator(app: WebAppService) -> None:
    app.kernel.authorization_management.create_principal(OPERATOR, actor="tests")


def _login(app: WebAppService) -> str:
    """Log the configured local operator in and return the opaque session id."""
    response = app.handle("POST", "/api/session", json_body={})
    assert response.status == 201, response.payload
    return app.session_id_from_set_cookie(response.set_cookie or "")


def _subject(app: WebAppService) -> str:
    subject = f"user.{uuid.uuid4().hex[:8]}"
    app.kernel.authorization_management.create_principal(subject, actor="tests")
    return subject


def _grant_manage(app: WebAppService, scope: Scope) -> None:
    app.kernel.authorization_management.grant_capability(
        OPERATOR,
        AUTHORIZATION_MANAGE,
        scope,
        actor="tests",
    )


def _grant_self_report(app: WebAppService, scope: Scope) -> None:
    app.kernel.authorization_management.assign_role(
        OPERATOR,
        SELF_REPORT_VIEWER_ROLE,
        scope,
        actor="tests",
    )


def _grant_render(app: WebAppService, scope: Scope) -> None:
    app.kernel.authorization_management.grant_capability(
        OPERATOR,
        REPORT_RENDER,
        scope,
        actor="tests",
    )


# --- development-only login ------------------------------------------------


def test_login_is_disabled_unless_it_is_explicitly_enabled(
    web_kernel: Kernel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(OPERATOR_ENV, OPERATOR)
    monkeypatch.delenv(DEV_LOGIN_ENV, raising=False)
    _operator(WebAppService(web_kernel))

    response = WebAppService(web_kernel).handle("POST", "/api/session", json_body={})

    assert response.status == 404
    assert response.payload["error"]["code"] == "login_disabled"


def test_login_fails_closed_when_no_operator_is_configured(
    web_kernel: Kernel,
    web_config: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(OPERATOR_ENV, raising=False)
    _operator(WebAppService(web_kernel))

    response = WebAppService(web_kernel).handle("POST", "/api/session", json_body={})

    assert response.status == 503
    assert response.payload["error"]["code"] == "operator_not_configured"


def test_login_fails_closed_when_the_configured_principal_does_not_exist(
    web_kernel: Kernel,
    web_config: None,
) -> None:
    response = WebAppService(web_kernel).handle("POST", "/api/session", json_body={})

    assert response.status == 503
    assert response.payload["error"]["code"] == "operator_not_configured"


def test_login_fails_closed_when_the_operator_is_not_active(
    web_kernel: Kernel,
    web_config: None,
) -> None:
    _operator(WebAppService(web_kernel))
    WebAppService(web_kernel).kernel.authorization_management.set_principal_active(
        OPERATOR,
        False,
        actor="tests",
    )

    response = WebAppService(web_kernel).handle("POST", "/api/session", json_body={})

    assert response.status == 503
    assert response.payload["error"]["code"] == "operator_not_configured"


# --- sessions --------------------------------------------------------------


def test_a_login_returns_only_an_opaque_session_cookie(service: WebAppService) -> None:
    _operator(service)

    response = service.handle("POST", "/api/session", json_body={})

    assert response.status == 201
    assert response.payload == {
        "authenticated": True,
        "development_only": True,
        "principal_id": OPERATOR,
    }
    cookie = response.set_cookie or ""
    assert cookie.startswith(f"{COOKIE_NAME}=")
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    # Nothing handle-shaped, and not even the id, reaches the body.
    body = json.dumps(response.payload)
    assert "ExecutionHandle" not in body
    assert service.session_id_from_set_cookie(cookie) not in body


def test_the_session_response_never_carries_a_handle_or_a_session_id(
    service: WebAppService,
) -> None:
    _operator(service)
    session = _login(service)

    response = service.handle("GET", "/api/session", cookies={COOKIE_NAME: session})

    assert response.status == 200
    assert response.payload["principal_id"] == OPERATOR
    serialized = json.dumps(response.payload)
    assert "ExecutionHandle" not in serialized
    assert session not in serialized


def test_a_caller_cannot_name_an_actor_and_identity_comes_only_from_core(
    service: WebAppService,
) -> None:
    _operator(service)
    session = _login(service)

    forged = service.handle(
        "POST",
        "/api/session",
        json_body={"actor": "someone.else", "principal_id": "someone.else"},
    )
    read_back = service.handle(
        "GET",
        "/api/session",
        cookies={COOKIE_NAME: session},
        json_body={"principal_id": "someone.else"},
    )

    # The request's opinion about who is asking is not an identity.
    assert forged.status == 201
    assert forged.payload["principal_id"] == OPERATOR
    assert read_back.status == 200
    assert read_back.payload["principal_id"] == OPERATOR


def test_sessions_are_isolated_from_one_another(service: WebAppService) -> None:
    _operator(service)
    first = _login(service)
    second = _login(service)
    assert first != second

    logout = service.handle("DELETE", "/api/session", cookies={COOKIE_NAME: first})
    after_first = service.handle("GET", "/api/session", cookies={COOKIE_NAME: first})
    after_second = service.handle("GET", "/api/session", cookies={COOKIE_NAME: second})

    assert logout.status == 204
    assert f"{COOKIE_NAME}=" in (logout.set_cookie or "")
    assert after_first.status == 401
    assert after_first.payload["error"]["code"] == "session_revoked"
    assert after_second.status == 200


def test_an_unknown_or_forged_session_id_is_unauthorized(service: WebAppService) -> None:
    _operator(service)

    for session_id in ("", "not-a-session", f"sess_{uuid.uuid4().hex}"):
        response = service.handle("GET", "/api/session", cookies={COOKIE_NAME: session_id})
        assert response.status == 401, session_id
        assert response.payload["error"]["code"] == "session_unknown"


def test_logout_revokes_the_session_handle(service: WebAppService) -> None:
    _operator(service)
    session = _login(service)
    assert service.handle("GET", "/api/session", cookies={COOKIE_NAME: session}).status == 200

    logout = service.handle("DELETE", "/api/session", cookies={COOKIE_NAME: session})

    assert logout.status == 204
    after = service.handle("GET", "/api/session", cookies={COOKIE_NAME: session})
    assert after.status == 401
    assert after.payload["error"]["code"] == "session_revoked"


def test_a_second_logout_stays_unauthorized(service: WebAppService) -> None:
    _operator(service)
    session = _login(service)
    assert service.handle("DELETE", "/api/session", cookies={COOKIE_NAME: session}).status == 204

    again = service.handle("DELETE", "/api/session", cookies={COOKIE_NAME: session})

    assert again.status == 401
    assert again.payload["error"]["code"] == "session_revoked"


# --- capabilities and roles ------------------------------------------------


def test_the_capability_catalogue_lists_core_owned_kinds(service: WebAppService) -> None:
    _operator(service)
    _grant_manage(service, Scope(principal_id=OPERATOR))
    session = _login(service)

    response = service.handle("GET", "/api/capabilities", cookies={COOKIE_NAME: session})

    assert response.status == 200
    entries = response.payload["capabilities"]
    ids = {entry["capability_id"] for entry in entries}
    assert AUTHORIZATION_MANAGE in ids
    assert SELF_REPORT_VIEW in ids
    kinds = {entry["capability_id"]: entry["kind"] for entry in entries}
    assert kinds[AUTHORIZATION_MANAGE] == "manage"
    assert kinds[SELF_REPORT_VIEW] == "view"


def test_the_role_catalogue_is_discoverable(service: WebAppService) -> None:
    _operator(service)
    _grant_manage(service, Scope(principal_id=OPERATOR))
    session = _login(service)

    response = service.handle("GET", "/api/roles", cookies={COOKIE_NAME: session})

    assert response.status == 200
    role_ids = {entry["role_id"] for entry in response.payload["roles"]}
    assert SELF_REPORT_VIEWER_ROLE in role_ids


def test_the_catalogue_is_not_readable_without_the_management_grant(
    service: WebAppService,
) -> None:
    _operator(service)
    session = _login(service)

    response = service.handle("GET", "/api/capabilities", cookies={COOKIE_NAME: session})

    assert response.status == 403
    assert response.payload["error"]["code"] == "capability_denied"


def test_the_principal_list_is_the_core_directory_and_nothing_else(
    service: WebAppService,
) -> None:
    _operator(service)
    subject = _subject(service)
    retired = _subject(service)
    service.kernel.authorization_management.set_principal_active(
        retired,
        False,
        actor="tests",
    )
    service.kernel.authorization_management.set_principal_metadata(
        subject,
        "theme",
        "dark",
        actor="tests",
    )
    _grant_manage(service, Scope(principal_id=OPERATOR))
    session = _login(service)

    response = service.handle("GET", "/api/principals", cookies={COOKIE_NAME: session})

    assert response.status == 200
    entries = response.payload["principals"]
    by_id = {entry["principal_id"]: entry for entry in entries}
    assert set(by_id) == {OPERATOR, subject, retired}
    assert by_id[retired]["active"] is False
    assert by_id[subject]["active"] is True
    # A directory of selectable principals, not a dump of principal rows: the
    # principal's stored metadata (the theme preference) is never projected out.
    assert set(by_id[subject]) == {"principal_id", "display_name", "active"}
    assert "theme" not in json.dumps(response.payload)


def test_the_principal_list_is_not_readable_without_the_management_grant(
    service: WebAppService,
) -> None:
    _operator(service)
    session = _login(service)

    response = service.handle("GET", "/api/principals", cookies={COOKIE_NAME: session})

    assert response.status == 403
    assert response.payload["error"]["code"] == "capability_denied"


def test_the_principal_list_is_authorized_in_the_operators_own_scope(
    service: WebAppService,
) -> None:
    """A grant held by somebody else, or for somebody else, is not this one."""
    _operator(service)
    other = _subject(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=other))
    session = _login(service)

    response = service.handle("GET", "/api/principals", cookies={COOKIE_NAME: session})

    assert response.status == 403
    assert response.payload["error"]["code"] == "capability_denied"


def test_the_principal_list_accepts_no_principal_from_the_caller(
    service: WebAppService,
) -> None:
    """The list is Core's directory; a caller cannot ask for a slice of it."""
    _operator(service)
    _grant_manage(service, Scope(principal_id=OPERATOR))
    session = _login(service)

    for query in ({"principal_id": "someone.else"}, {"actor": "someone.else"}):
        response = service.handle(
            "GET",
            "/api/principals",
            cookies={COOKIE_NAME: session},
            query=query,
        )
        assert response.status == 422, query
        assert response.payload["error"]["code"] == "principal_not_accepted"


def test_the_principal_list_needs_a_live_session(service: WebAppService) -> None:
    _operator(service)
    _grant_manage(service, Scope(principal_id=OPERATOR))
    session = _login(service)

    anonymous = service.handle("GET", "/api/principals")
    assert service.handle("DELETE", "/api/session", cookies={COOKIE_NAME: session}).status == 204
    revoked = service.handle("GET", "/api/principals", cookies={COOKIE_NAME: session})

    assert anonymous.status == 401
    assert anonymous.payload["error"]["code"] == "session_unknown"
    assert revoked.status == 401
    assert revoked.payload["error"]["code"] == "session_revoked"


def test_effective_permissions_are_read_for_the_requested_scope(
    service: WebAppService,
) -> None:
    _operator(service)
    subject = _subject(service)
    service.kernel.authorization_management.grant_capability(
        subject,
        SELF_REPORT_VIEW,
        Scope(organization_id=ORG),
        actor="tests",
    )
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    session = _login(service)

    response = service.handle(
        "GET",
        f"/api/principals/{subject}/permissions",
        cookies={COOKIE_NAME: session},
        query={"organization_id": ORG},
    )

    assert response.status == 200
    assert response.payload["principal_id"] == subject
    # The reported scope is the organization the caller named, with no principal
    # dimension: a management view, never a peek at somebody's self scope.
    assert response.payload["scope"] == {
        "organization_id": ORG,
        "workplace_id": None,
        "principal_id": None,
    }
    assert SELF_REPORT_VIEW in response.payload["capabilities"]
    assert response.payload["role_ids"] == []


# --- grant state ------------------------------------------------------------


def test_the_grant_state_route_hydrates_direct_roles_and_mixed_sources(
    service: WebAppService,
) -> None:
    """The Roles UI reads checkbox state from here, and only from here."""
    _operator(service)
    subject = _subject(service)
    service.kernel.authorization_management.set_principal_metadata(
        subject,
        "theme",
        "dark",
        actor="tests",
    )
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    management = service.kernel.authorization_management
    # Directly granted *and* carried by a role: both sources must be reported,
    # or the view would offer to untick something a role still provides.
    management.grant_capability(
        subject,
        SELF_REPORT_VIEW,
        Scope(organization_id=ORG),
        actor="tests",
    )
    management.assign_role(
        subject,
        SELF_REPORT_VIEWER_ROLE,
        Scope(organization_id=ORG),
        actor="tests",
    )
    session = _login(service)

    response = service.handle(
        "GET",
        f"/api/principals/{subject}/grants",
        cookies={COOKIE_NAME: session},
        query={"organization_id": ORG},
    )

    assert response.status == 200
    assert response.payload["principal_id"] == subject
    assert response.payload["scope"] == {
        "organization_id": ORG,
        "workplace_id": None,
        "principal_id": None,
    }
    capabilities = {item["capability_id"]: item for item in response.payload["capabilities"]}
    assert capabilities[str(SELF_REPORT_VIEW)] == {
        "capability_id": str(SELF_REPORT_VIEW),
        "direct": True,
        "role_ids": [SELF_REPORT_VIEWER_ROLE],
    }
    assert capabilities[str(AUTHORIZATION_MANAGE)]["direct"] is False
    assert capabilities[str(AUTHORIZATION_MANAGE)]["role_ids"] == []
    roles = {item["role_id"]: item["assigned"] for item in response.payload["roles"]}
    assert roles[SELF_REPORT_VIEWER_ROLE] is True
    assert roles["role.manager"] is False
    assert response.payload["effective_capability_ids"] == [str(SELF_REPORT_VIEW)]
    # The whole catalogue is answered, so the view renders every checkbox, and
    # the principal's stored preferences stay off the wire.
    assert str(AUTHORIZATION_MANAGE) in capabilities
    assert "theme" not in json.dumps(response.payload)


def test_the_grant_state_route_needs_an_explicit_scope_and_never_widens(
    service: WebAppService,
) -> None:
    _operator(service)
    subject = _subject(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    service.kernel.authorization_management.grant_capability(
        subject,
        SELF_REPORT_VIEW,
        Scope(organization_id=ORG, workplace_id="wp-1"),
        actor="tests",
    )
    session = _login(service)

    # No scope at all would answer every scope at once, so it is refused.
    unscoped = service.handle(
        "GET",
        f"/api/principals/{subject}/grants",
        cookies={COOKIE_NAME: session},
    )
    at_workplace = service.handle(
        "GET",
        f"/api/principals/{subject}/grants",
        cookies={COOKIE_NAME: session},
        query={"organization_id": ORG, "workplace_id": "wp-1"},
    )
    at_org = service.handle(
        "GET",
        f"/api/principals/{subject}/grants",
        cookies={COOKIE_NAME: session},
        query={"organization_id": ORG},
    )

    assert unscoped.status == 422
    assert unscoped.payload["error"]["code"] == "scope_invalid"
    inside = {item["capability_id"]: item for item in at_workplace.payload["capabilities"]}
    assert inside[str(SELF_REPORT_VIEW)]["direct"] is True
    # A workplace grant is not an organization grant: the wider question is
    # answered for the wider scope, not widened from the narrower grant.
    outside = {item["capability_id"]: item for item in at_org.payload["capabilities"]}
    assert outside[str(SELF_REPORT_VIEW)]["direct"] is False
    assert at_org.payload["effective_capability_ids"] == []


def test_the_grant_state_route_refuses_an_unknown_or_foreign_principal(
    service: WebAppService,
) -> None:
    _operator(service)
    subject = _subject(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    session = _login(service)

    unknown = service.handle(
        "GET",
        "/api/principals/principal.nobody/grants",
        cookies={COOKIE_NAME: session},
        query={"organization_id": ORG},
    )
    # The operator's own grant is scoped to one organization, so another one is
    # not this operator's to read.
    foreign = service.handle(
        "GET",
        f"/api/principals/{subject}/grants",
        cookies={COOKIE_NAME: session},
        query={"organization_id": "org-somewhere-else"},
    )
    anonymous = service.handle(
        "GET",
        f"/api/principals/{subject}/grants",
        query={"organization_id": ORG},
    )

    assert unknown.status == 404
    assert unknown.payload["error"]["code"] == "principal_unknown"
    assert foreign.status == 403
    assert foreign.payload["error"]["code"] == "capability_denied"
    assert anonymous.status == 401
    assert anonymous.payload["error"]["code"] == "session_unknown"


def test_the_grant_state_route_accepts_no_principal_fact_from_the_caller(
    service: WebAppService,
) -> None:
    """The subject is in the path; naming one in the query is refused."""
    _operator(service)
    subject = _subject(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    session = _login(service)

    for extra in ({"principal_id": "someone.else"}, {"actor": "someone.else"}, {"scope": "{}"}):
        response = service.handle(
            "GET",
            f"/api/principals/{subject}/grants",
            cookies={COOKIE_NAME: session},
            query={"organization_id": ORG, **extra},
        )
        assert response.status == 422, extra
        assert response.payload["error"]["code"] == "principal_not_accepted"


def test_checking_a_capability_creates_an_explicit_audited_grant(
    service: WebAppService,
) -> None:
    _operator(service)
    subject = _subject(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    session = _login(service)

    response = service.handle(
        "PUT",
        f"/api/principals/{subject}/capabilities/{SELF_REPORT_VIEW}",
        cookies={COOKIE_NAME: session},
        json_body={"checked": True, "scope": {"organization_id": ORG}},
    )

    assert response.status == 200
    assert response.payload == {"capability_id": str(SELF_REPORT_VIEW), "checked": True}
    granted = service.kernel.authorization_management.effective_permissions(
        subject,
        Scope(organization_id=ORG),
    )
    assert SELF_REPORT_VIEW in granted
    with service.uow_factory() as uow:
        actions = {record.action for record in uow.audit.all(limit=200)}
    assert "authorization.capability.granted" in actions


def test_unchecking_a_capability_revokes_it_and_is_idempotent(service: WebAppService) -> None:
    _operator(service)
    subject = _subject(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    session = _login(service)
    path = f"/api/principals/{subject}/capabilities/{SELF_REPORT_VIEW}"
    scope = {"organization_id": ORG}
    assert (
        service.handle(
            "PUT",
            path,
            cookies={COOKIE_NAME: session},
            json_body={"checked": True, "scope": scope},
        ).status
        == 200
    )

    first = service.handle(
        "PUT",
        path,
        cookies={COOKIE_NAME: session},
        json_body={"checked": False, "scope": scope},
    )
    repeated = service.handle(
        "PUT",
        path,
        cookies={COOKIE_NAME: session},
        json_body={"checked": False, "scope": scope},
    )

    assert first.status == 200
    assert first.payload == {"capability_id": str(SELF_REPORT_VIEW), "checked": False}
    assert repeated.status == 200
    remaining = service.kernel.authorization_management.effective_permissions(
        subject,
        Scope(organization_id=ORG),
    )
    assert SELF_REPORT_VIEW not in remaining
    with service.uow_factory() as uow:
        actions = {record.action for record in uow.audit.all(limit=200)}
    assert "authorization.capability.revoked" in actions


def test_ticking_a_role_checkbox_assigns_and_unticking_revokes_the_bundle(
    service: WebAppService,
) -> None:
    _operator(service)
    subject = _subject(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    session = _login(service)
    path = f"/api/principals/{subject}/roles/{SELF_REPORT_VIEWER_ROLE}"
    target = {"scope": {"organization_id": ORG}, "principal_id": subject}
    subject_scope = Scope(organization_id=ORG, principal_id=subject)

    assigned = service.handle(
        "PUT",
        path,
        cookies={COOKIE_NAME: session},
        json_body={"checked": True, **target},
    )
    assert assigned.status == 200
    assert assigned.payload == {"role_id": SELF_REPORT_VIEWER_ROLE, "checked": True}
    assert SELF_REPORT_VIEW in service.kernel.authorization_management.effective_permissions(
        subject,
        subject_scope,
    )

    revoked = service.handle(
        "PUT",
        path,
        cookies={COOKIE_NAME: session},
        json_body={"checked": False, **target},
    )
    assert revoked.status == 200
    assert SELF_REPORT_VIEW not in service.kernel.authorization_management.effective_permissions(
        subject,
        subject_scope,
    )


def test_the_server_rechecks_and_a_lying_checkbox_changes_nothing(
    service: WebAppService,
) -> None:
    """A checked box is advisory: the operator's own grant is still required."""
    _operator(service)
    subject = _subject(service)
    session = _login(service)  # no authorization.manage grant for the operator

    response = service.handle(
        "PUT",
        f"/api/principals/{subject}/capabilities/{SELF_REPORT_VIEW}",
        cookies={COOKIE_NAME: session},
        json_body={"checked": True, "scope": {"organization_id": ORG}},
    )

    assert response.status == 403
    assert response.payload["error"]["code"] == "capability_denied"
    assert SELF_REPORT_VIEW not in service.kernel.authorization_management.effective_permissions(
        subject,
        Scope(organization_id=ORG),
    )


def test_an_unknown_capability_or_role_is_a_404(service: WebAppService) -> None:
    _operator(service)
    subject = _subject(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    session = _login(service)
    body = {"checked": True, "scope": {"organization_id": ORG}}

    capability = service.handle(
        "PUT",
        f"/api/principals/{subject}/capabilities/does.not.exist",
        cookies={COOKIE_NAME: session},
        json_body=body,
    )
    role = service.handle(
        "PUT",
        f"/api/principals/{subject}/roles/role.does_not_exist",
        cookies={COOKIE_NAME: session},
        json_body=body,
    )

    assert capability.status == 404
    assert capability.payload["error"]["code"] == "capability_unknown"
    assert role.status == 404
    assert role.payload["error"]["code"] == "role_unknown"


def test_a_scope_a_caller_cannot_name_for_itself_is_still_self_scoped(
    service: WebAppService,
) -> None:
    _operator(service)
    subject = _subject(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    session = _login(service)

    response = service.handle(
        "PUT",
        f"/api/principals/{subject}/capabilities/{SELF_REPORT_VIEW}",
        cookies={COOKIE_NAME: session},
        json_body={
            "checked": True,
            "scope": {"organization_id": ORG},
            "principal_id": subject,
        },
    )

    # The named principal is the *resource* the grant is about; the execution is
    # still the operator's own, and the grant lands on the subject.
    assert response.status == 200
    self_scoped = service.kernel.authorization_management.effective_permissions(
        subject,
        Scope(organization_id=ORG, principal_id=subject),
    )
    org_wide = service.kernel.authorization_management.effective_permissions(
        subject,
        Scope(organization_id=ORG),
    )
    assert SELF_REPORT_VIEW in self_scoped
    assert SELF_REPORT_VIEW not in org_wide


def test_a_principal_nested_inside_the_scope_is_refused(service: WebAppService) -> None:
    """The grant's principal dimension is a top-level field, never nested."""
    _operator(service)
    subject = _subject(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    session = _login(service)

    response = service.handle(
        "PUT",
        f"/api/principals/{subject}/capabilities/{SELF_REPORT_VIEW}",
        cookies={COOKIE_NAME: session},
        json_body={"checked": True, "scope": {"organization_id": ORG, "principal_id": subject}},
    )

    assert response.status == 422
    assert response.payload["error"]["code"] == "scope_invalid"


def test_an_empty_management_scope_is_unprocessable(service: WebAppService) -> None:
    _operator(service)
    subject = _subject(service)
    _grant_manage(service, Scope(principal_id=OPERATOR))
    session = _login(service)

    response = service.handle(
        "PUT",
        f"/api/principals/{subject}/capabilities/{SELF_REPORT_VIEW}",
        cookies={COOKIE_NAME: session},
        json_body={"checked": True, "scope": {}},
    )

    assert response.status == 422
    assert response.payload["error"]["code"] == "scope_invalid"


def test_a_malformed_checkbox_body_is_unprocessable(service: WebAppService) -> None:
    _operator(service)
    subject = _subject(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    session = _login(service)
    path = f"/api/principals/{subject}/capabilities/{SELF_REPORT_VIEW}"

    missing = service.handle(
        "PUT",
        path,
        cookies={COOKIE_NAME: session},
        json_body={"scope": {"organization_id": ORG}},
    )
    not_boolean = service.handle(
        "PUT",
        path,
        cookies={COOKIE_NAME: session},
        json_body={"checked": "yes", "scope": {"organization_id": ORG}},
    )

    assert missing.status == 422
    assert missing.payload["error"]["code"] == "body_invalid"
    assert not_boolean.status == 422
    assert not_boolean.payload["error"]["code"] == "body_invalid"


# --- self report -----------------------------------------------------------


def test_the_self_report_takes_no_principal_from_the_body(service: WebAppService) -> None:
    _operator(service)
    _grant_self_report(service, Scope(principal_id=OPERATOR))
    session = _login(service)

    for body in (
        {"principal_id": "someone.else"},
        {"actor": "admin"},
        {"scope": {"principal_id": "someone.else"}},
    ):
        response = service.handle(
            "GET",
            "/api/self/monthly-report",
            cookies={COOKIE_NAME: session},
            json_body=body,
        )
        assert response.status == 422, body
        assert response.payload["error"]["code"] == "principal_not_accepted"


def test_the_self_report_is_rendered_for_the_session_principal_only(
    service: WebAppService,
) -> None:
    _operator(service)
    _grant_self_report(service, Scope(principal_id=OPERATOR))
    session = _login(service)

    response = service.handle(
        "GET",
        "/api/self/monthly-report",
        cookies={COOKIE_NAME: session},
    )

    assert response.status == 200
    assert response.payload["principal_id"] == OPERATOR
    use_case = response.payload["use_case"]
    assert use_case["use_case_id"] == "self.monthly.report"
    assert use_case["scope"] == "self"
    assert use_case["surfaces"] == ["web", "bot", "ai"]
    assert "sections" in response.payload


def test_the_self_report_is_denied_without_the_core_grant(service: WebAppService) -> None:
    _operator(service)
    session = _login(service)

    response = service.handle(
        "GET",
        "/api/self/monthly-report",
        cookies={COOKIE_NAME: session},
    )

    assert response.status == 403
    assert response.payload["error"]["code"] == "capability_denied"


def test_a_principal_query_parameter_is_refused_too(service: WebAppService) -> None:
    _operator(service)
    _grant_self_report(service, Scope(principal_id=OPERATOR))
    session = _login(service)

    response = service.handle(
        "GET",
        "/api/self/monthly-report",
        cookies={COOKIE_NAME: session},
        query={"principal_id": "someone.else"},
    )

    assert response.status == 422
    assert response.payload["error"]["code"] == "principal_not_accepted"


# --- reports ---------------------------------------------------------------


def test_report_definitions_are_discovered_through_the_published_contract(
    service: WebAppService,
) -> None:
    _operator(service)
    _grant_manage(service, Scope(principal_id=OPERATOR))
    session = _login(service)

    response = service.handle("GET", "/api/reports", cookies={COOKIE_NAME: session})

    assert response.status == 200
    entries = response.payload["reports"]
    definition_ids = {entry["definition_id"] for entry in entries}
    assert "self.monthly.report" in definition_ids
    assert CONSTRUCTION_DAILY_WORKFORCE.definition_id in definition_ids
    self_report = next(e for e in entries if e["definition_id"] == "self.monthly.report")
    assert self_report["use_case"]["required_capabilities"] == [str(SELF_REPORT_VIEW)]
    assert self_report["dataset_ids"] == ["self.monthly.entries"]


def test_rendering_a_definition_goes_through_report_studio(service: WebAppService) -> None:
    _operator(service)
    _grant_manage(service, Scope(organization_id=ORG))
    _grant_render(service, Scope(organization_id=ORG))
    session = _login(service)

    response = service.handle(
        "POST",
        "/api/reports/self.monthly.report/render",
        cookies={COOKIE_NAME: session},
        json_body={"organization_id": ORG},
    )

    assert response.status == 200
    assert response.payload["definition_id"] == "self.monthly.report"
    assert response.payload["organization_id"] == ORG
    assert response.payload["sections"][0]["dataset_id"] == "self.monthly.entries"
    assert response.payload["audit_id"]


def test_rendering_without_the_render_capability_is_forbidden(
    service: WebAppService,
) -> None:
    """The render capability is Core's to grant, not the route's to assume."""
    _operator(service)
    _grant_manage(service, Scope(organization_id=ORG))
    session = _login(service)

    response = service.handle(
        "POST",
        "/api/reports/self.monthly.report/render",
        cookies={COOKIE_NAME: session},
        json_body={"organization_id": ORG},
    )

    assert response.status == 403
    assert response.payload["error"]["code"] == "capability_denied"
    assert REPORT_RENDER


def test_an_organization_render_never_includes_self_scoped_rows(
    service: WebAppService,
) -> None:
    """An organization execution is not a self execution, even for the operator."""
    _operator(service)
    _grant_manage(service, Scope(organization_id=ORG))
    _grant_render(service, Scope(organization_id=ORG))
    _grant_self_report(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    session = _login(service)

    response = service.handle(
        "POST",
        "/api/reports/self.monthly.report/render",
        cookies={COOKIE_NAME: session},
        json_body={"organization_id": ORG},
    )

    assert response.status == 200
    assert response.payload["sections"][0]["groups"] == []


def test_an_unknown_definition_is_a_404(service: WebAppService) -> None:
    _operator(service)
    _grant_manage(service, Scope(organization_id=ORG))
    session = _login(service)

    response = service.handle(
        "POST",
        "/api/reports/no.such.report/render",
        cookies={COOKIE_NAME: session},
        json_body={"organization_id": ORG},
    )

    assert response.status == 404
    assert response.payload["error"]["code"] == "report_definition_unknown"


def test_a_render_without_an_organization_is_unprocessable(service: WebAppService) -> None:
    _operator(service)
    _grant_manage(service, Scope(organization_id=ORG))
    session = _login(service)

    response = service.handle(
        "POST",
        "/api/reports/self.monthly.report/render",
        cookies={COOKIE_NAME: session},
        json_body={},
    )

    assert response.status == 422
    assert response.payload["error"]["code"] == "body_invalid"


# --- theme -----------------------------------------------------------------


def test_the_theme_preference_is_persisted_through_core(service: WebAppService) -> None:
    _operator(service)
    session = _login(service)

    default = service.handle(
        "GET",
        "/api/session/theme",
        cookies={COOKIE_NAME: session},
    )
    stored = service.handle(
        "PUT",
        "/api/session/theme",
        cookies={COOKIE_NAME: session},
        json_body={"theme": "dark"},
    )
    reread = service.handle(
        "GET",
        "/api/session/theme",
        cookies={COOKIE_NAME: session},
    )
    # The value lives in PostgreSQL, read back through a brand new unit of work.
    with service.uow_factory() as uow:
        row = uow.authorization.get_principal(OPERATOR)

    assert default.status == 200
    assert default.payload == {"theme": "light"}
    assert stored.status == 200
    assert stored.payload == {"theme": "dark"}
    assert reread.payload == {"theme": "dark"}
    assert row is not None
    assert row.metadata == {"theme": "dark"}


def test_an_unknown_theme_is_unprocessable(service: WebAppService) -> None:
    _operator(service)
    session = _login(service)

    response = service.handle(
        "PUT",
        "/api/session/theme",
        cookies={COOKIE_NAME: session},
        json_body={"theme": "neon"},
    )

    assert response.status == 422
    assert response.payload["error"]["code"] == "theme_invalid"


def test_the_theme_is_self_scoped_and_grants_nothing(service: WebAppService) -> None:
    _operator(service)
    other = _subject(service)
    session = _login(service)

    assert (
        service.handle(
            "PUT",
            "/api/session/theme",
            cookies={COOKIE_NAME: session},
            json_body={"theme": "dark"},
        ).status
        == 200
    )
    untouched = service.kernel.authorization_management.get_principal(other)
    denied = service.handle(
        "PUT",
        f"/api/principals/{other}/capabilities/{SELF_REPORT_VIEW}",
        cookies={COOKIE_NAME: session},
        json_body={"checked": True, "scope": {"organization_id": ORG}},
    )

    assert untouched is not None
    assert "theme" not in untouched.metadata
    assert denied.status == 403


# --- typed confirmations ---------------------------------------------------


def test_a_typed_confirmation_requires_a_valid_session_handle(
    service: WebAppService,
) -> None:
    _operator(service)
    _grant_self_report(service, Scope(principal_id=OPERATOR))
    session = _login(service)
    body = {"capability": str(SELF_REPORT_VIEW), "action": "self.monthly.report.view"}

    unauthorized = service.handle("POST", "/api/confirmations", json_body=body)
    created = service.handle(
        "POST",
        "/api/confirmations",
        cookies={COOKIE_NAME: session},
        json_body=body,
    )

    assert unauthorized.status == 401
    assert created.status == 201
    assert created.payload["confirmation_id"]
    assert "ExecutionHandle" not in json.dumps(created.payload)


def test_a_confirmation_for_a_capability_the_session_lacks_is_forbidden(
    service: WebAppService,
) -> None:
    _operator(service)
    session = _login(service)

    response = service.handle(
        "POST",
        "/api/confirmations",
        cookies={COOKIE_NAME: session},
        json_body={"capability": str(SELF_REPORT_VIEW), "action": "self.monthly.report.view"},
    )

    assert response.status == 403
    assert response.payload["error"]["code"] == "capability_denied"


def test_a_confirmation_is_bound_to_one_action_and_is_not_replayable(
    service: WebAppService,
) -> None:
    """A typed confirmation is Core state, bound to the canonical facts."""
    _operator(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    for action in ("authorization.capability.set", "authorization.role.set"):
        service.kernel.authorization_management.register_policy(
            f"web.confirm.{action}",
            date.min,
            condition={"confirmation_required": "true"},
            capability=str(AUTHORIZATION_MANAGE),
            action=action,
            channel=Channel.WEB,
        )
    subject = _subject(service)
    session = _login(service)
    path = f"/api/principals/{subject}/capabilities/{SELF_REPORT_VIEW}"
    target = {
        "scope": {"organization_id": ORG},
        "principal_id": subject,
    }
    confirm_body = {
        "capability": str(AUTHORIZATION_MANAGE),
        "action": "authorization.capability.set",
        "scope": {"organization_id": ORG},
        # A confirmation is bound to the target it was issued for, so it has to
        # name the subject the mutation is about.
        "resource_id": subject,
    }

    def confirm(action: str) -> str:
        created = service.handle(
            "POST",
            "/api/confirmations",
            cookies={COOKIE_NAME: session},
            json_body={**confirm_body, "action": action},
        )
        assert created.status == 201, created.payload
        return str(created.payload["confirmation_id"])

    # Bound to another action: Core refuses it, and nothing is granted.
    wrong_action = service.handle(
        "PUT",
        path,
        cookies={COOKIE_NAME: session},
        json_body={**target, "checked": True, "confirmation_id": confirm("authorization.role.set")},
    )
    assert wrong_action.status == 403
    assert wrong_action.payload["error"]["code"] == "confirmation_required"
    assert SELF_REPORT_VIEW not in service.kernel.authorization_management.effective_permissions(
        subject,
        Scope(organization_id=ORG, principal_id=subject),
    )

    # No confirmation at all is refused too.
    missing = service.handle(
        "PUT",
        path,
        cookies={COOKIE_NAME: session},
        json_body={**target, "checked": True},
    )
    assert missing.status == 403
    assert missing.payload["error"]["code"] == "confirmation_required"

    # The bound action proceeds exactly once.
    spent = confirm("authorization.capability.set")
    first = service.handle(
        "PUT",
        path,
        cookies={COOKIE_NAME: session},
        json_body={**target, "checked": True, "confirmation_id": spent},
    )
    assert first.status == 200
    assert SELF_REPORT_VIEW in service.kernel.authorization_management.effective_permissions(
        subject,
        Scope(organization_id=ORG, principal_id=subject),
    )

    # A one-time confirmation cannot be replayed, for the same action or another.
    replay = service.handle(
        "PUT",
        path,
        cookies={COOKIE_NAME: session},
        json_body={**target, "checked": False, "confirmation_id": spent},
    )
    assert replay.status == 403
    assert replay.payload["error"]["code"] == "confirmation_required"
    still_granted = service.kernel.authorization_management.effective_permissions(
        subject,
        Scope(organization_id=ORG, principal_id=subject),
    )
    assert SELF_REPORT_VIEW in still_granted


def _require_confirmation_for_capability_set(
    service: WebAppService,
) -> None:
    """Make every web capability.set confirm, through Core policy only."""
    service.kernel.authorization_management.register_policy(
        "web.confirm.capability.set",
        date.min,
        condition={"confirmation_required": "true"},
        capability=str(AUTHORIZATION_MANAGE),
        action="authorization.capability.set",
        channel=Channel.WEB,
    )


def _confirm(
    service: WebAppService,
    session: str,
    *,
    capability: str,
    action: str,
    resource_id: str | None = None,
) -> str:
    body: dict[str, object] = {
        "capability": capability,
        "action": action,
        "scope": {"organization_id": ORG},
    }
    if resource_id is not None:
        body["resource_id"] = resource_id
    created = service.handle(
        "POST",
        "/api/confirmations",
        cookies={COOKIE_NAME: session},
        json_body=body,
    )
    assert created.status == 201, created.payload
    return str(created.payload["confirmation_id"])


def test_a_confirmation_is_bound_to_the_target_it_was_issued_for(
    service: WebAppService,
) -> None:
    """A confirmation for one user must not authorize a change to another."""
    _operator(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    _require_confirmation_for_capability_set(service)
    intended = _subject(service)
    other = _subject(service)
    session = _login(service)
    confirmation_id = _confirm(
        service,
        session,
        capability=str(AUTHORIZATION_MANAGE),
        action="authorization.capability.set",
        resource_id=intended,
    )

    wrong_target = service.handle(
        "PUT",
        f"/api/principals/{other}/capabilities/{SELF_REPORT_VIEW}",
        cookies={COOKIE_NAME: session},
        json_body={
            "checked": True,
            "scope": {"organization_id": ORG},
            "confirmation_id": confirmation_id,
        },
    )
    assert wrong_target.status == 403
    assert wrong_target.payload["error"]["code"] == "confirmation_required"
    assert SELF_REPORT_VIEW not in service.kernel.authorization_management.effective_permissions(
        other,
        Scope(organization_id=ORG),
    )

    # The principal the confirmation was issued for proceeds exactly once.
    bound = service.handle(
        "PUT",
        f"/api/principals/{intended}/capabilities/{SELF_REPORT_VIEW}",
        cookies={COOKIE_NAME: session},
        json_body={
            "checked": True,
            "scope": {"organization_id": ORG},
            "confirmation_id": confirmation_id,
        },
    )
    assert bound.status == 200
    assert SELF_REPORT_VIEW in service.kernel.authorization_management.effective_permissions(
        intended,
        Scope(organization_id=ORG),
    )

    replay = service.handle(
        "PUT",
        f"/api/principals/{intended}/capabilities/{SELF_REPORT_VIEW}",
        cookies={COOKIE_NAME: session},
        json_body={
            "checked": False,
            "scope": {"organization_id": ORG},
            "confirmation_id": confirmation_id,
        },
    )
    assert replay.status == 403
    assert replay.payload["error"]["code"] == "confirmation_required"
    # The replay changed nothing: the grant is still in place.
    assert SELF_REPORT_VIEW in service.kernel.authorization_management.effective_permissions(
        intended,
        Scope(organization_id=ORG),
    )


def test_a_confirmation_issued_without_a_target_authorizes_nothing(
    service: WebAppService,
) -> None:
    """Omitting the target must not produce a wildcard for any target."""
    _operator(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    _require_confirmation_for_capability_set(service)
    subject = _subject(service)
    session = _login(service)
    confirmation_id = _confirm(
        service,
        session,
        capability=str(AUTHORIZATION_MANAGE),
        action="authorization.capability.set",
    )

    response = service.handle(
        "PUT",
        f"/api/principals/{subject}/capabilities/{SELF_REPORT_VIEW}",
        cookies={COOKIE_NAME: session},
        json_body={
            "checked": True,
            "scope": {"organization_id": ORG},
            "confirmation_id": confirmation_id,
        },
    )

    assert response.status == 403
    assert response.payload["error"]["code"] == "confirmation_required"
    assert SELF_REPORT_VIEW not in service.kernel.authorization_management.effective_permissions(
        subject,
        Scope(organization_id=ORG),
    )


def test_a_malformed_confirmation_request_is_unprocessable(
    service: WebAppService,
) -> None:
    _operator(service)
    _grant_self_report(service, Scope(principal_id=OPERATOR))
    session = _login(service)

    missing_action = service.handle(
        "POST",
        "/api/confirmations",
        cookies={COOKIE_NAME: session},
        json_body={"capability": str(SELF_REPORT_VIEW)},
    )
    # An unregistered capability has no Core policy, so default deny applies.
    unknown_capability = service.handle(
        "POST",
        "/api/confirmations",
        cookies={COOKIE_NAME: session},
        json_body={"capability": "does.not.exist", "action": "x"},
    )

    assert missing_action.status == 422
    assert missing_action.payload["error"]["code"] == "body_invalid"
    assert unknown_capability.status == 403
    assert unknown_capability.payload["error"]["code"] == "policy_denied"


# --- error mapping and the no-leak rule ------------------------------------


def test_core_decision_codes_map_to_the_documented_statuses() -> None:
    from atlas_web.service import status_for_code

    assert status_for_code("handle_required") == 401
    assert status_for_code("handle_invalid") == 401
    assert status_for_code("persistence_required") == 401
    assert status_for_code("capability_denied") == 403
    assert status_for_code("capability_binding_mismatch") == 403
    assert status_for_code("policy_denied") == 403
    assert status_for_code("assistant_required") == 403
    assert status_for_code("confirmation_required") == 403
    assert status_for_code("confirmation_consumed") == 409
    assert status_for_code("request_invalid") == 422
    # Default deny: an unknown Core code is never treated as allowed.
    assert status_for_code("some_future_code") == 403
    assert status_for_code("allowed") == 403


def test_an_unknown_route_is_a_404_and_a_wrong_method_is_a_405(
    service: WebAppService,
) -> None:
    unknown = service.handle("GET", "/api/nope")
    wrong = service.handle("POST", "/api/capabilities", json_body={})

    assert unknown.status == 404
    assert unknown.payload["error"]["code"] == "route_unknown"
    assert wrong.status == 405
    assert wrong.payload["error"]["code"] == "method_not_allowed"


def test_an_error_body_never_leaks_internals(service: WebAppService) -> None:
    _operator(service)
    session = _login(service)

    denied = service.handle(
        "PUT",
        f"/api/principals/{_subject(service)}/capabilities/{SELF_REPORT_VIEW}",
        cookies={COOKIE_NAME: session},
        json_body={"checked": True, "scope": {"organization_id": ORG}},
    )
    leaked = json.dumps(denied.payload).lower()

    assert denied.status == 403
    for secret in ("executionhandle", "postgresql://", "uow", "sqlalchemy", "traceback", "denied:"):
        assert secret not in leaked


def test_a_denied_decision_leaves_a_durable_fail_closed_audit_record(
    service: WebAppService,
) -> None:
    """§38.11: the denial audit survives the rolled-back business transaction."""
    _operator(service)
    subject = _subject(service)
    session = _login(service)  # no management grant, so the decision is denied

    denied = service.handle(
        "PUT",
        f"/api/principals/{subject}/capabilities/{SELF_REPORT_VIEW}",
        cookies={COOKIE_NAME: session},
        json_body={"checked": True, "scope": {"organization_id": ORG}},
    )

    assert denied.status == 403
    with service.uow_factory() as uow:
        decisions = [
            record
            for record in uow.audit.all(limit=200)
            if record.action == "authorization.decision"
        ]
    assert decisions
    assert any(record.details.get("allowed") is False for record in decisions)
    assert any(record.details.get("code") == "capability_denied" for record in decisions)


def test_the_principal_theme_metadata_is_never_read_as_authorization(
    service: WebAppService,
) -> None:
    """Metadata is a preference store. It is not part of the authorization path."""
    _operator(service)
    session = _login(service)
    service.handle(
        "PUT",
        "/api/session/theme",
        cookies={COOKIE_NAME: session},
        json_body={"theme": "dark"},
    )
    management = service.kernel.authorization_management

    permissions = management.effective_permissions(OPERATOR, Scope(principal_id=OPERATOR))
    principal = management.get_principal(OPERATOR)

    assert principal is not None
    assert principal.metadata == {"theme": "dark"}
    assert AUTHORIZATION_MANAGE not in permissions
    # The capability is registered and grantable, but it is not granted.
    assert AUTHORIZATION_MANAGE in management.list_capability_ids()


# --- the slice boundaries --------------------------------------------------


def test_the_web_layer_adds_no_backend_dependency_and_no_frontend_assets() -> None:
    import ast

    import atlas_web

    module_path = Path(atlas_web.__file__ or "atlas_web/__init__.py")
    root = module_path.parent
    assert sorted(path.name for path in root.glob("*.py")) == [
        "__init__.py",
        "__main__.py",
        "http.py",
        "service.py",
    ]
    assert list(root.rglob("*.tsx")) == []
    assert list(root.rglob("*.css")) == []

    forbidden = {"fastapi", "flask", "django", "starlette", "uvicorn", "aiohttp", "tornado"}
    imported: set[str] = set()
    for path in root.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden)

    pyproject = (module_path.parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    for name in sorted(forbidden):
        assert name not in pyproject.lower()


def test_the_theme_column_reaches_a_deployed_database_through_the_migration(
    test_engine: Engine,
) -> None:
    """§38.15: a deployed schema gets the column from a migration, not create_all."""
    with test_engine.begin() as connection:
        connection.execute(text("ALTER TABLE principal DROP COLUMN IF EXISTS metadata"))
        connection.execute(
            text("DELETE FROM schema_migrations WHERE version = '004_principal_metadata'")
        )

    apply_migrations(test_engine)

    with test_engine.begin() as connection:
        columns = {
            str(row[0])
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'principal'"
                )
            )
        }
        applied = {
            str(row[0]) for row in connection.execute(text("SELECT version FROM schema_migrations"))
        }
    assert "metadata" in columns
    assert "004_principal_metadata" in applied


def test_the_standard_library_adapter_serves_the_api(
    web_kernel: Kernel,
    web_config: None,
) -> None:
    """The stdlib handler is a real adapter, exercised over a real socket."""
    import threading
    import urllib.error
    import urllib.request

    _operator(WebAppService(web_kernel))
    server = ThreadingHTTPServer(("127.0.0.1", 0), WebRequestHandler)
    server.service = WebAppService(web_kernel)  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urllib.request.urlopen(
            urllib.request.Request(f"{base}/api/session", method="POST", data=b"{}")
        ) as response:
            assert response.status == 201
            cookie = response.headers.get("Set-Cookie") or ""
        assert "HttpOnly" in cookie
        assert "SameSite=Strict" in cookie
        session = cookie.split(";", 1)[0]

        with urllib.request.urlopen(
            urllib.request.Request(f"{base}/api/session", headers={"Cookie": session})
        ) as response:
            assert response.status == 200

        with pytest.raises(urllib.error.HTTPError) as unknown:
            urllib.request.urlopen(urllib.request.Request(f"{base}/api/nope"))
        assert unknown.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_the_web_layer_never_builds_a_decision_itself() -> None:
    """Authorization is Core's: the web layer only maps a decision to a status."""
    import atlas_web.service as service_module

    source = Path(service_module.__file__ or "service.py").read_text(encoding="utf-8")
    for forbidden in ("def evaluate(", "def is_allowed(", "def check_permission("):
        assert forbidden not in source
    assert "status_for_code" in source


def test_the_confirming_policy_is_registered_through_core_only(
    service: WebAppService,
) -> None:
    """A typed confirmation is Core state; the web layer can only ask for one."""
    _operator(service)
    _grant_manage(service, Scope(organization_id=ORG, principal_id=OPERATOR))
    session = _login(service)

    created = service.handle(
        "POST",
        "/api/confirmations",
        cookies={COOKIE_NAME: session},
        json_body={
            "capability": str(AUTHORIZATION_MANAGE),
            "action": "authorization.capability.set",
            "scope": {"organization_id": ORG},
        },
    )

    assert created.status == 201
    with service.uow_factory() as uow:
        assert uow.authorization.get_confirmation(created.payload["confirmation_id"]) is not None
        actions = {record.action for record in uow.audit.all(limit=200)}
    assert "authorization.confirmed" in actions


def test_the_web_layer_runs_on_a_configured_postgres_uow_only(web_kernel: Kernel) -> None:
    """§38.11: no UoW, no service. The web surface fails closed without PostgreSQL."""
    from atlas_core.kernel import Kernel as KernelType

    registry_only = KernelType(uow_factory=None, entry_point_group=WEB_TEST_ENTRY_POINT_GROUP)

    with pytest.raises(RuntimeError):
        WebAppService(registry_only)

    assert WebAppService(web_kernel).kernel is web_kernel


def test_a_channel_action_still_goes_through_core_policy(service: WebAppService) -> None:
    """The web channel is one channel among several, with no privileged shortcut."""
    _operator(service)
    _grant_manage(service, Scope(principal_id=OPERATOR))
    _grant_self_report(service, Scope(principal_id=OPERATOR))
    session = _login(service)

    service.kernel.authorization_management.register_policy(
        "web.disable.self_report",
        date.min,
        enabled=False,
        capability=str(SELF_REPORT_VIEW),
        action="self.monthly.report.view",
        channel=Channel.WEB,
    )

    response = service.handle(
        "GET",
        "/api/self/monthly-report",
        cookies={COOKIE_NAME: session},
    )

    assert response.status == 403
    assert response.payload["error"]["code"] == "policy_denied"
