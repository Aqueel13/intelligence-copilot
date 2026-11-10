"""The backend's client for the Operations MCP server.

When a person clicks "Execute" in the web app, the backend does not call the enterprise
system itself: it calls the Operations MCP server's `execute_action` tool, exactly as any other
MCP client would. The server re-checks governance before anything happens.
"""

import json
from typing import Any

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from watchdog_backend.config import get_settings


class MCPToolError(RuntimeError):
    def __init__(self, tool: str, message: str):
        self.tool = tool
        super().__init__(message)


async def call_operations_tool(tool: str, arguments: dict[str, Any]) -> Any:
    s = get_settings()
    if not s.operations_mcp_backend_token:
        raise MCPToolError(tool, "OPERATIONS_MCP_BACKEND_TOKEN is not configured")
    headers = {"Authorization": f"Bearer {s.operations_mcp_backend_token}"}
    async with (
        httpx2.AsyncClient(headers=headers, timeout=httpx2.Timeout(30, read=60)) as http,
        streamable_http_client(s.operations_mcp_url, http_client=http) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool(tool, arguments)
    if result.is_error:
        text = " ".join(getattr(c, "text", "") for c in result.content).strip()
        raise MCPToolError(tool, text or f"{tool} failed")
    if result.structured_content is not None:
        content = result.structured_content
        return content.get("result", content) if isinstance(content, dict) else content
    text = " ".join(getattr(c, "text", "") for c in result.content)
    return json.loads(text) if text else None
