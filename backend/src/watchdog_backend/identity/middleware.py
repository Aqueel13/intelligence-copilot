"""Authentication for /api: a session cookie resolves to the current principal. Everything
except health and sign-in requires one. Plain ASGI so the principal (and the user id on every
observability record) stays set through streamed responses."""

import json

from starlette.types import ASGIApp, Receive, Scope, Send

from watchdog_backend.db import get_engine
from watchdog_backend.identity.service import reset_principal, resolve, set_principal
from watchdog_backend.observability.context import traced

COOKIE = "wd_session"
PUBLIC = ("/api/health", "/api/auth/login", "/api/auth/logout", "/api/docs", "/api/openapi.json")


def session_token(scope: Scope) -> str | None:
    for name, value in scope.get("headers") or []:
        if name == b"cookie":
            for part in value.decode("latin-1").split(";"):
                k, _, v = part.strip().partition("=")
                if k == COOKIE and v:
                    return v
    return None


class AuthMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api") or path.startswith(PUBLIC):
            await self.app(scope, receive, send)
            return
        token = session_token(scope)
        principal = None
        if token:
            with get_engine().connect() as conn:
                principal = resolve(conn, token)
        if principal is None:
            body = json.dumps({"detail": "Sign in required"}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        reset = set_principal(principal)
        try:
            with traced(user_id=principal.user.user_id):
                await self.app(scope, receive, send)
        finally:
            reset_principal(reset)
