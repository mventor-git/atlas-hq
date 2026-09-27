"""The API refuses a development login on anything but loopback.

``ATLAS_WEB_DEV_LOGIN`` is a switch, not a credential: it mints a session for a
fixed local principal for anybody who can reach the listener. That is a
development convenience and only while the listener is reachable from this
machine, so ``atlas_web.http`` refuses the two together. This file needs no
database, no kernel and no socket - it is the guard, called directly.
"""

from __future__ import annotations

import pytest

from atlas_web.http import (
    DEFAULT_HOST,
    dev_login_enabled,
    is_loopback_host,
    require_loopback_dev_login,
)

#: The four values ``WebAppService`` treats as on. One host loopback here, one
#: not: an off switch is checked against the same list as an on one.
ON = {value: {"ATLAS_WEB_DEV_LOGIN": value} for value in ("1", "true", "yes", "on")}

LOOPBACK = ("127.0.0.1", "127.0.0.53", "localhost", "LOCALHOST", "::1", "[::1]")
ROUTABLE = ("0.0.0.0", "192.168.1.10", "10.0.0.5", "example.internal", "", "127.0.0.1.example")


@pytest.mark.parametrize("host", LOOPBACK)
def test_loopback_addresses_are_loopback(host: str) -> None:
    assert is_loopback_host(host)


@pytest.mark.parametrize("host", ROUTABLE)
def test_everything_else_is_not(host: str) -> None:
    # Including 0.0.0.0: it is a wildcard, so a listener on it answers on the
    # routable interfaces too. And a name that does not parse as an address has
    # to prove it is this machine, and only `localhost` is taken at its word.
    assert not is_loopback_host(host)


@pytest.mark.parametrize("environ", list(ON.values()), ids=list(ON))
def test_the_switch_reads_the_same_truthy_set_the_service_uses(environ: dict[str, str]) -> None:
    assert dev_login_enabled(environ)
    assert not dev_login_enabled({})
    assert not dev_login_enabled({"ATLAS_WEB_DEV_LOGIN": ""})
    assert not dev_login_enabled({"ATLAS_WEB_DEV_LOGIN": "0"})


@pytest.mark.parametrize("host", LOOPBACK)
@pytest.mark.parametrize("environ", list(ON.values()), ids=list(ON))
def test_the_launcher_topology_is_never_refused(host: str, environ: dict[str, str]) -> None:
    # start-demo.ps1 binds 127.0.0.1 with the switch on. That must keep working,
    # or the guard has broken the demo instead of protecting it.
    require_loopback_dev_login(host, environ)


def test_the_default_host_is_loopback() -> None:
    assert is_loopback_host(DEFAULT_HOST)


@pytest.mark.parametrize("host", ("0.0.0.0", "192.168.1.10", "example.internal", "::"))
def test_a_routable_bind_with_the_switch_on_is_refused(host: str) -> None:
    with pytest.raises(SystemExit) as refusal:
        require_loopback_dev_login(host, {"ATLAS_WEB_DEV_LOGIN": "1"})

    message = str(refusal.value)
    assert host in message
    assert "not loopback" in message
    # The message has to name both halves of the way out, or it is not an
    # instruction an operator can follow.
    assert "ATLAS_WEB_DEV_LOGIN" in message
    assert "127.0.0.1" in message


@pytest.mark.parametrize("host", ("0.0.0.0", "192.168.1.10", "::"))
def test_a_routable_bind_with_the_switch_off_is_allowed(host: str) -> None:
    # The guard is about the development login, not about binding a public
    # address. Without the switch there is no anonymous session to hand out, so
    # this is not the guard's business to refuse.
    require_loopback_dev_login(host, {})
    require_loopback_dev_login(host, {"ATLAS_WEB_DEV_LOGIN": "0"})


def test_the_guard_reads_the_process_environment_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The real path: `python -m atlas_web` passes no environ, so the guard has to
    # see the same switch `WebAppService` sees.
    monkeypatch.setenv("ATLAS_WEB_DEV_LOGIN", "1")
    require_loopback_dev_login("127.0.0.1")
    with pytest.raises(SystemExit):
        require_loopback_dev_login("0.0.0.0")

    monkeypatch.delenv("ATLAS_WEB_DEV_LOGIN")
    require_loopback_dev_login("0.0.0.0")
