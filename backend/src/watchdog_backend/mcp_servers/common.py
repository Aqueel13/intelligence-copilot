"""What every WatchDog MCP server shares: static bearer tokens, running work on a fresh
connection with the requested pack active, and the transport settings."""

import secrets
import time
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
from pydantic import ValidationError

from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import UnknownDomainError, current_domain, use_domain
from watchdog_backend.observability.recorder import record

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


def _error_text(exc: ToolError) -> str:
    """What to store for a failed call: the server's own message, never the caller's data."""
    if isinstance(exc.__cause__, ValidationError):  # field names only: values are caller data
        fields = sorted({".".join(map(str, e["loc"])) for e in exc.__cause__.errors()})
        return f"invalid arguments: {', '.join(fields)}"
    if type(exc) is not ToolError:  # UnexpectedToolError: a crash, details stay in the logs
        return type(exc.__cause__ or exc).__name__
    return str(exc)


class RecordedMCPServer(MCPServer):
    """Records every tool call in observability.mcp_calls: server, tool, client, pack,
    outcome and latency. Arguments are not stored (they can hold a client's SQL or search
    text); an error is stored as its message only when it is a ToolError, which the server
    wrote for the client anyway, otherwise as its class name."""

    def __init__(self, *args: Any, server_key: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.server_key = server_key

    async def call_tool(self, name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        started = time.perf_counter()
        status, error = "ok", None
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as exc:
            status, error = "error", _error_text(exc)
            raise
        except Exception as exc:
            status, error = "error", type(exc).__name__
            raise
        finally:
            schema = self._tool_input_schema(name) or {}
            takes_pack = "domain" in schema.get("properties", {})
            record(
                "mcp_calls",
                {
                    "server": self.server_key,
                    "tool": name,
                    "client": client_name(),
                    "domain": (arguments.get("domain") or current_domain()) if takes_pack else None,
                    "status": status,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                    "error": error[:300] if error else None,
                },
            )


def make_server(
    name: str, title: str, instructions: str, port: int, scope: str, tokens: Callable[[], dict]
) -> MCPServer:
    return RecordedMCPServer(
        server_key=scope,
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
