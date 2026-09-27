"""A real HTTP round trip: the standard-library server, a real socket, real PostgreSQL.

``test_web_api.py`` proves the boundary's rules by calling it. This suite proves
the wiring those rules travel through: the stdlib adapter serving on a loopback
socket, a real cookie jar round-tripping the opaque ``atlas_session`` cookie, and
a real isolated PostgreSQL schema holding every row the console reads and writes.

The server is started and stopped inside each test, in-process — no subprocess,
no shared fixture, no port to collide with. Each test therefore gets its own
schema and its own socket, and leaves nothing behind but a dropped schema.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from http.cookiejar import Cookie, CookieJar
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from atlas_core.domain.role import AUTHORIZATION_MANAGE
from atlas_core.kernel import Kernel
from atlas_plugins.self_reporting import SELF_REPORT_VIEWER_ROLE
from atlas_sdk import Scope
from atlas_web import COOKIE_NAME, DEV_LOGIN_ENV, OPERATOR_ENV, WebAppService
from atlas_web.http import WebRequestHandler

OPERATOR = "atlas.local.operator"
SUBJECT = "web.subject"
ORG = "org-web-live"


class HttpClient:
    """One cookie-jar browser against the loopback API.

    A refusal is a status and a body here, not an exception, because a 401 or a
    403 is a result this suite asserts on. The jar is a real one, so the
    ``HttpOnly`` cookie is stored and replayed exactly as a browser would.
    """

    def __init__(self, base: str) -> None:
        self.base = base
        self.jar = CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, body: Any = None) -> tuple[int, dict[str, Any]]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"} if data is not None else {},
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def session_cookie(self) -> Cookie:
        return next(cookie for cookie in self.jar if cookie.name == COOKIE_NAME)

    def session_value(self) -> str:
        return self.session_cookie().value or ""

    def send_raw_cookie(
        self,
        value: str,
        path: str = "/api/principals",
    ) -> tuple[int, dict[str, Any]]:
        """Send an arbitrary ``atlas_session`` value, bypassing the jar."""
        request = urllib.request.Request(
            f"{self.base}{path}",
            headers={"Cookie": f"{COOKIE_NAME}={value}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")


@dataclass(frozen=True)
class LiveApi:
    service: WebAppService
    client: HttpClient


@pytest.fixture
def live_api(
    real_kernel: Kernel,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[LiveApi]:
    """A booted kernel, a configured local operator, and a server on a real port."""
    monkeypatch.setenv(OPERATOR_ENV, OPERATOR)
    monkeypatch.setenv(DEV_LOGIN_ENV, "1")

    real_kernel.boot()
    real_kernel.enable("self_reporting")

    management = real_kernel.authorization_management
    for principal_id in (OPERATOR, SUBJECT):
        management.create_principal(principal_id, display_name=principal_id, actor="tests")
    management.grant_capability(
        OPERATOR,
        AUTHORIZATION_MANAGE,
        Scope(principal_id=OPERATOR),
        actor="tests",
    )
    management.assign_role(
        OPERATOR,
        SELF_REPORT_VIEWER_ROLE,
        Scope(principal_id=OPERATOR),
        actor="tests",
    )

    service = WebAppService(real_kernel)
    server = ThreadingHTTPServer(("127.0.0.1", 0), WebRequestHandler)
    server.service = service  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield LiveApi(service, HttpClient(f"http://127.0.0.1:{server.server_address[1]}"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def test_the_console_flow_works_over_a_real_socket(live_api: LiveApi) -> None:
    """Login, list, read and write the theme, self report, logout — all over HTTP."""
    client = live_api.client

    # Login: the body names nobody, and the only credential is an opaque cookie.
    status, payload = client.call("POST", "/api/session", {})
    assert (status, payload["principal_id"]) == (201, OPERATOR)
    cookie = client.session_cookie()
    assert cookie.has_nonstandard_attr("HttpOnly")
    session_value = cookie.value or ""
    assert session_value and session_value not in json.dumps(payload)

    # The principal directory, then the capability catalogue.
    status, payload = client.call("GET", "/api/principals")
    listed = [entry["principal_id"] for entry in payload["principals"]]
    assert status == 200
    assert listed == sorted(listed)
    assert {OPERATOR, SUBJECT} <= set(listed)

    status, payload = client.call("GET", "/api/capabilities")
    assert status == 200
    assert AUTHORIZATION_MANAGE in {entry["capability_id"] for entry in payload["capabilities"]}

    # The theme round-trips and lands in PostgreSQL, read back by a new unit of work.
    assert client.call("GET", "/api/session/theme") == (200, {"theme": "light"})
    assert client.call("PUT", "/api/session/theme", {"theme": "dark"}) == (200, {"theme": "dark"})
    assert client.call("GET", "/api/session/theme") == (200, {"theme": "dark"})
    with live_api.service.uow_factory() as uow:
        stored = uow.authorization.get_principal(OPERATOR)
    assert stored is not None
    assert stored.metadata == {"theme": "dark"}

    # The self report is the session principal's own, rendered by the plugin.
    status, payload = client.call("GET", "/api/self/monthly-report")
    assert status == 200
    assert payload["principal_id"] == OPERATOR
    assert payload["use_case"]["use_case_id"] == "self.monthly.report"
    assert payload["sections"][0]["dataset_id"] == "self.monthly.entries"

    # Logout revokes the session's Core handle and clears the cookie, so the
    # browser stops sending an id at all, while a replayed id is told the truth.
    assert client.call("DELETE", "/api/session") == (204, {})
    unknown = {"error": {"code": "session_unknown", "message": "authentication is required"}}
    assert client.call("GET", "/api/self/monthly-report") == (401, unknown)
    assert client.send_raw_cookie(session_value) == (
        401,
        {"error": {"code": "session_revoked", "message": "authentication is required"}},
    )


def test_an_anonymous_or_forged_session_is_refused_over_the_wire(live_api: LiveApi) -> None:
    client = live_api.client

    anonymous = client.call("GET", "/api/principals")
    forged = client.send_raw_cookie("not-a-real-session-id")
    login = client.call("POST", "/api/session", {})

    unknown = {"error": {"code": "session_unknown", "message": "authentication is required"}}
    assert anonymous == (401, unknown)
    assert forged == anonymous
    # The development login mints a session for the configured operator and
    # nothing else: the body is read by nobody.
    assert login == (
        201,
        {"authenticated": True, "development_only": True, "principal_id": OPERATOR},
    )


def test_a_second_session_is_isolated_from_the_first_over_the_wire(live_api: LiveApi) -> None:
    first = live_api.client
    first.call("POST", "/api/session", {})
    second = HttpClient(first.base)

    second.call("POST", "/api/session", {})
    first_value = first.session_value()
    second_value = second.session_value()
    assert first_value != second_value

    assert first.call("DELETE", "/api/session") == (204, {})
    # The revoked id is refused; the other session is untouched.
    assert first.send_raw_cookie(first_value)[0] == 401
    assert second.call("GET", "/api/principals")[0] == 200
    assert second.send_raw_cookie(second_value)[0] == 200
