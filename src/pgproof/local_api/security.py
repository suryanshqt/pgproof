"""Loopback security: origin checks, response security headers, and the session token.

`docs/ARCHITECTURE.md` section 9's forbidden list and `docs/TECHNICAL_DESIGN.md`
section 27: "Security headers deny framing and remote resources. CORS is
disabled except the exact local origin. Session token is required."
"""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from typing import Final

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp
from typing_extensions import override

SECURITY_HEADERS: Final[dict[str, str]] = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; connect-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Applied outermost, so every response carries these headers, including a rejection."""

    @override
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        return response


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Rejects a request whose `Origin` header names a different origin.

    A same-origin request either omits `Origin` or sends this exact value; a
    mismatch means another site's page is trying to reach the loopback API.
    """

    def __init__(self, app: ASGIApp, *, allowed_origin: str) -> None:
        super().__init__(app)
        self._allowed_origin = allowed_origin

    @override
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        origin = request.headers.get("origin")
        if origin is not None and origin != self._allowed_origin:
            return PlainTextResponse("origin rejected", status_code=403)
        return await call_next(request)


def require_session_token(request: Request) -> None:
    """FastAPI dependency: every `/api/v1/*` route requires this, per section 27."""
    expected: str = request.app.state.session_token
    supplied = request.headers.get("x-pgproof-session-token") or request.query_params.get("token")
    if supplied is None or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="missing or invalid session token")
