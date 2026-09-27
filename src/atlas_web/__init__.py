"""The Atlas-HQ web API: a server boundary over the Core Roles Engine.

The whole surface is :class:`WebAppService`, a framework-agnostic dispatch of
``(method, path, body)`` to a status and a JSON-safe payload. :mod:`atlas_web.http`
is a standard-library adapter over it. The browser never receives an
``ExecutionHandle``; it receives an opaque, server-side session id.
"""

from __future__ import annotations

from .service import (
    CATALOGUE_ACTION,
    COOKIE_NAME,
    DEV_LOGIN_ENV,
    OPERATOR_ENV,
    THEME_KEY,
    THEMES,
    ApiError,
    WebAppService,
    WebResponse,
    status_for_code,
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
