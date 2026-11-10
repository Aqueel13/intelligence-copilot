"""Per-request domain pack: the `X-Domain` header (or `?domain=`) picks the pack a request
works on. Without either, the default pack (DOMAIN_PACK) is used.

A plain ASGI middleware, so the pack stays active for the whole request, including streamed
responses (their sync iterators run in worker threads that copy this context).
"""

import json
from urllib.parse import parse_qs

from starlette.types import ASGIApp, Receive, Scope, Send

from watchdog_backend.domain.pack import UnknownDomainError, use_domain

HEADER = b"x-domain"


class DomainMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        domain = (
            dict(scope.get("headers") or []).get(HEADER, b"").decode()
            or (parse_qs(scope.get("query_string", b"").decode()).get("domain", [""])[0])
        )
        if not domain:
            await self.app(scope, receive, send)
            return
        try:
            with use_domain(domain):
                await self.app(scope, receive, send)
        except UnknownDomainError as exc:
            body = json.dumps({"detail": str(exc)}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 400,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": body})
