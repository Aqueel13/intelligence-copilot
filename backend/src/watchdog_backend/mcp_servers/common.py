"""What every WatchDog MCP server shares: static bearer tokens, running work on a fresh
connection with the requested pack active, and the transport settings."""

import secrets
from collections.abc import Callable
from typing import Any

import anyio
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import UnknownDomainError, current_domain, use_domain

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


class StaticTokenVerifier:
    """Bearer tokens from configuration ({"token": "client name"}), compared in constant
    time. `tokens` is read on every call, so tests and reloads see the current settings."""

    def __init__(self, tokens: Callable[[], dict[str, str]], scope: str) -> None:
        self.tokens = tokens
        self.scope = scope

    async def verify_token(self, token: str) -> AccessToken | None:
        for known, client in self.tokens().items():
            if known and secrets.compare_digest(token, known):
                return AccessToken(token=token, client_id=client, scopes=[self.scope])
        return None


def client_name() -> str:
    """The calling client's name (from its token). Read it in the request context, not in a
    worker thread."""
    token = get_access_token()
    return token.client_id if token else "unknown"


async def call(
    fn: Callable[..., Any],
    *args: Any,
    domain: str | None = None,
    errors: tuple[type[Exception], ...] = (),
) -> Any:
    """Run `fn(conn, *args)` in a worker thread on a fresh connection, with `domain` (default:
    the default pack) active. Exceptions listed in `errors`, and an unknown pack, become a
    ToolError so the client sees *why*; anything unexpected stays a generic error."""

    def work() -> Any:
        with use_domain(domain or current_domain()), get_engine().connect() as conn:
            return fn(conn, *args)

    try:
        return await anyio.to_thread.run_sync(work)
    except UnknownDomainError as exc:
        raise ToolError(str(exc)) from exc
    except errors as exc:
        raise ToolError(str(exc)) from exc


def make_server(
    name: str, title: str, instructions: str, port: int, scope: str, tokens: Callable[[], dict]
) -> MCPServer:
    return MCPServer(
        name=name,
        title=title,
        instructions=instructions,
        token_verifier=StaticTokenVerifier(tokens, scope),
        auth=AuthSettings(
            issuer_url=f"http://localhost:{port}",  # static tokens: no OAuth server involved
            resource_server_url=None,
            required_scopes=[scope],
        ),
    )


def build_asgi(server: MCPServer, port: int, service: str):
    """A fresh ASGI app (each has its own session manager, which can only start once)."""
    return server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[f"localhost:{port}", f"127.0.0.1:{port}", f"{service}:{port}"],
            allowed_origins=[f"http://localhost:{port}", f"http://127.0.0.1:{port}"],
        ),
    )
