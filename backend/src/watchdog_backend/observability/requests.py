"""Record every API request: route template, status, latency, pack (and user, once signed in)."""

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from watchdog_backend.domain.pack import current_domain
from watchdog_backend.observability.context import current_trace
from watchdog_backend.observability.recorder import record

SKIP = ("/api/health", "/api/observability")  # polling would drown everything else


class RequestMetricsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith(SKIP):
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        status = 500

        async def capture(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            route = getattr(scope.get("route"), "path", None) or "(unmatched)"
            record(
                "api_requests",
                {
                    "method": scope["method"],
                    "route": route,
                    "status": status,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "domain": current_domain(),
                    "user_id": current_trace().user_id,
                },
            )
