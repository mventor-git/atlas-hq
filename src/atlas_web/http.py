"""A standard-library HTTP adapter over :class:`~atlas_web.service.WebAppService`.

Nothing here makes a decision. It turns a request line, a cookie header, and a
JSON body into one :meth:`WebAppService.handle` call, and turns the result back
into bytes. Adding a framework later means adding an adapter, not a second
authorization path.

Run it with ``python -m atlas_web``. It binds to the loopback interface by
default: this is a development server, and the dev login route is off unless
``ATLAS_WEB_DEV_LOGIN`` says otherwise. When that switch is on, a non-loopback
host is refused outright — see :func:`require_loopback_dev_login`.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
from collections.abc import Sequence
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from atlas_core.infrastructure.persistence.unit_of_work import create_sql_uow_factory
from atlas_core.kernel import Kernel

from .service import DEV_LOGIN_ENV, WebAppService, WebResponse

#: A request body larger than this is refused rather than buffered.
MAX_BODY_BYTES = 64 * 1024
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def dev_login_enabled(environ: dict[str, str] | None = None) -> bool:
    """Whether the development login route is switched on."""
    source = os.environ if environ is None else environ
    return source.get(DEV_LOGIN_ENV, "").strip().lower() in _TRUTHY


def is_loopback_host(host: str) -> bool:
    """Whether a bind address is a loopback address of this machine.

    A name that does not parse as an address is not loopback: ``localhost`` is
    answered separately because it is the one name that always means this
    machine, and anything else has to prove itself.
    """
    candidate = host.strip().strip("[]")
    if candidate.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def require_loopback_dev_login(host: str, environ: dict[str, str] | None = None) -> None:
    """Refuse a development login on a bind address that is not loopback.

    ``ATLAS_WEB_DEV_LOGIN`` mints a session for a fixed principal and nobody
    else, with no credential of the caller's own. That is only a development
    convenience while the listener is reachable from this machine alone, so the
    switch and a routable address are refused together rather than allowed to
    meet. The refusal happens before the socket is bound, so there is never a
    window in which the route is live on another interface.
    """
    if dev_login_enabled(environ) and not is_loopback_host(host):
        raise SystemExit(
            f"refusing to serve the development login on {host!r}: "
            f"{DEV_LOGIN_ENV} is on and that address is not loopback. "
            f"Bind 127.0.0.1, or unset {DEV_LOGIN_ENV}."
        )


def _cookies(header: str | None) -> dict[str, str]:
    if not header:
        return {}
    jar = SimpleCookie()
    try:
        jar.load(header)
    except Exception:  # noqa: BLE001 - a malformed cookie is simply no session
        return {}
    return {name: morsel.value for name, morsel in jar.items()}


class WebRequestHandler(BaseHTTPRequestHandler):
    """One HTTP request -> one :class:`WebAppService` call."""

    server_version = "atlas-hq-web"
    sys_version = ""

    @property
    def service(self) -> WebAppService:
        # Set by :func:`serve` on the server instance.
        return self.server.service  # type: ignore[attr-defined,no-any-return]

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY_BYTES:
            raise ValueError("request body is too large")
        raw = self.rfile.read(length)
        if not raw.strip():
            return {}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}

    def _respond(self, response: WebResponse) -> None:
        payload = b"" if response.status == 204 else json.dumps(response.payload).encode("utf-8")
        self.send_response(response.status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if response.set_cookie:
            self.send_header("Set-Cookie", response.set_cookie)
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def _dispatch(self) -> None:
        parsed = urlparse(self.path)
        try:
            body = self._read_body()
        except (ValueError, json.JSONDecodeError):
            self._respond(
                WebResponse(400, {"error": {"code": "body_invalid", "message": "malformed body"}})
            )
            return
        self._respond(
            self.service.handle(
                self.command,
                parsed.path,
                query={key: values[0] for key, values in parse_qs(parsed.query).items() if values},
                json_body=body,
                cookies=_cookies(self.headers.get("Cookie")),
            )
        )

    # ``BaseHTTPRequestHandler`` dispatches on exactly these names, so the mixed
    # case is the standard library's contract, not a style choice.
    do_GET = _dispatch  # noqa: N815
    do_POST = _dispatch  # noqa: N815
    do_PUT = _dispatch  # noqa: N815
    do_DELETE = _dispatch  # noqa: N815


def serve(service: WebAppService, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    """Serve the API until interrupted. One thread per request."""
    server = ThreadingHTTPServer((host, port), WebRequestHandler)
    server.service = service  # type: ignore[attr-defined]
    try:
        server.serve_forever()
    finally:
        server.server_close()


def build_service(*, kernel: Kernel | None = None) -> WebAppService:
    """Build the service over a persistent kernel, booting the plugins if needed."""
    if kernel is None:
        kernel = Kernel(uow_factory=create_sql_uow_factory())
        kernel.boot()
        kernel.enable_all()
    return WebAppService(kernel)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas-web",
        description="Serve the Atlas-HQ web API over the standard library.",
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)
    # Before the kernel is built and before the socket is bound: a refusal here
    # has not created anything.
    require_loopback_dev_login(args.host)
    service = build_service()
    print(f"atlas-web listening on http://{args.host}:{args.port}")  # noqa: T201
    serve(service, args.host, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
