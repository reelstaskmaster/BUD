from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import socket
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from mcp import Client, StdioServerParameters

from app.services.capability_registry import RiskLevel

logger = logging.getLogger(__name__)

_MAX_TOOL_OUTPUT = 20_000
_MAX_SERVERS = 16
_ALLOWED_HTTP_SCHEMES = {"https", "http"}
_BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}


@dataclass(frozen=True)
class MCPTool:
    exposed_name: str
    server_name: str
    tool_name: str
    description: str
    parameters: dict[str, Any]
    risk: RiskLevel


@dataclass
class _ConnectedServer:
    name: str
    client: Client
    tools: dict[str, MCPTool]


class MCPManager:
    """Controlled MCP host for BUD.

    MCP is configuration-driven and never discovers arbitrary servers.
    Servers must be explicitly listed in MCP_SERVERS_JSON. Tools are exposed
    through namespaced capability names and therefore still pass through the
    normal BUD CapabilityExecutor authorization boundary.
    """

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self.enabled = bool(getattr(settings, "mcp_enabled", True))
        self.servers_json = str(getattr(settings, "mcp_servers_json", "") or "")
        self.timeout_s = float(getattr(settings, "mcp_timeout_s", 30.0))
        self.max_output_chars = min(
            int(getattr(settings, "mcp_max_output_chars", _MAX_TOOL_OUTPUT)),
            _MAX_TOOL_OUTPUT,
        )
        self._exit_stack = AsyncExitStack()
        self._servers: dict[str, _ConnectedServer] = {}
        self._tools: dict[str, MCPTool] = {}
        self._started = False
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if not self.enabled or self._started:
            return
        async with self._lock:
            if self._started:
                return
            configs = self._parse_configs()
            for config in configs:
                try:
                    await self._connect_one(config)
                except Exception:
                    logger.exception("MCP server %s was rejected/unavailable", config.get("name"))
            self._started = True
            logger.info("MCP manager started: %d server(s), %d tool(s)", len(self._servers), len(self._tools))

    async def stop(self) -> None:
        async with self._lock:
            if not self._started:
                return
            await self._exit_stack.aclose()
            self._exit_stack = AsyncExitStack()
            self._servers.clear()
            self._tools.clear()
            self._started = False

    def tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": tool.exposed_name,
                "description": tool.description,
                "parameters": tool.parameters,
                "strict": True,
            }
            for tool in self._tools.values()
        ]

    def tools(self) -> tuple[MCPTool, ...]:
        return tuple(self._tools.values())

    def get_tool(self, exposed_name: str) -> MCPTool | None:
        return self._tools.get(exposed_name)

    async def call_tool(self, exposed_name: str, arguments: dict[str, Any]) -> str:
        tool = self._tools.get(exposed_name)
        if tool is None:
            raise KeyError(f"Unknown MCP capability: {exposed_name}")
        server = self._servers.get(tool.server_name)
        if server is None:
            raise RuntimeError(f"MCP server is not connected: {tool.server_name}")

        result = await asyncio.wait_for(
            server.client.call_tool(tool.tool_name, arguments),
            timeout=self.timeout_s,
        )
        return self._render_result(result)

    def _parse_configs(self) -> list[dict[str, Any]]:
        if not self.servers_json.strip():
            return []
        try:
            payload = json.loads(self.servers_json)
        except json.JSONDecodeError as exc:
            raise ValueError("MCP_SERVERS_JSON is not valid JSON") from exc
        if not isinstance(payload, list):
            raise ValueError("MCP_SERVERS_JSON must be a JSON array")
        if len(payload) > _MAX_SERVERS:
            raise ValueError(f"MCP_SERVERS_JSON contains more than {_MAX_SERVERS} servers")

        configs: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in payload:
            if not isinstance(item, dict):
                raise ValueError("Each MCP server config must be an object")
            name = str(item.get("name") or "").strip()
            if not name or name in seen:
                raise ValueError(f"Invalid or duplicate MCP server name: {name!r}")
            if not _safe_name(name):
                raise ValueError(f"Unsafe MCP server name: {name!r}")
            seen.add(name)
            configs.append(item)
        return configs

    async def _connect_one(self, config: dict[str, Any]) -> None:
        name = str(config["name"])
        allowed, read_tools, write_tools, destructive_tools = _validate_tool_policy(config)

        transport = str(config.get("transport") or "streamable_http").strip().lower()

        if transport in {"streamable_http", "http"}:
            url = str(config.get("url") or "").strip()
            _validate_http_endpoint(url)
            headers = _resolve_env_map(config.get("headers_env"), "headers_env")
            if headers:
                # The high-level Client accepts a URL but does not expose custom
                # headers. Use the SDK transport directly when auth is configured.
                from mcp.client.streamable_http import streamable_http_client
                import httpx2

                http_client = httpx2.AsyncClient(
                    headers=headers,
                    timeout=httpx2.Timeout(
                        self.timeout_s,
                        connect=min(self.timeout_s, 30.0),
                        read=max(self.timeout_s, 30.0),
                    ),
                )
                transport_cm = streamable_http_client(
                    url,
                    http_client=http_client,
                    terminate_on_close=True,
                )
                client = Client(transport_cm)
            else:
                client = Client(url)
        elif transport == "stdio":
            command = str(config.get("command") or "").strip()
            allowed = {
                item.strip()
                for item in str(getattr(self.settings, "mcp_stdio_allowed_commands", "") or "").split(",")
                if item.strip()
            }
            if not command or command not in allowed:
                raise ValueError(
                    f"MCP stdio command is not allow-listed: {command!r}"
                )
            args = config.get("args") or []
            if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
                raise ValueError(f"MCP stdio args for {name} must be a string array")
            env = _resolve_env_map(config.get("env_from"), "env_from")
            client = Client(
                StdioServerParameters(
                    command=command,
                    args=args,
                    env=env or None,
                    cwd=config.get("cwd"),
                )
            )
        else:
            raise ValueError(f"Unsupported MCP transport: {transport}")

        await self._exit_stack.enter_async_context(client)
        discovered = await asyncio.wait_for(client.list_tools(), timeout=self.timeout_s)
        remote_names = {str(remote.name) for remote in discovered.tools}
        missing = allowed - remote_names
        if missing:
            raise ValueError(f"MCP server {name!r} did not expose allowed tools: {sorted(missing)}")

        tool_map: dict[str, MCPTool] = {}
        for remote in discovered.tools:
            remote_name = str(remote.name)
            if remote_name not in allowed:
                continue
            if not _safe_name(remote_name):
                raise ValueError(f"Unsafe allowed MCP tool name: {remote_name!r}")
            exposed = f"mcp__{name}__{remote_name}"
            if exposed in self._tools:
                raise ValueError(f"MCP tool name collision: {exposed}")
            parameters = dict(remote.input_schema or {})
            if parameters.get("type") != "object":
                logger.warning("Skipping MCP tool %s: input schema is not an object", exposed)
                continue
            risk = _tool_risk(read_tools, write_tools, destructive_tools, remote_name)
            item = MCPTool(
                exposed_name=exposed,
                server_name=name,
                tool_name=remote_name,
                description=_tool_description(name, remote_name, remote.description),
                parameters=parameters,
                risk=risk,
            )
            tool_map[remote_name] = item
            self._tools[exposed] = item

        self._servers[name] = _ConnectedServer(name=name, client=client, tools=tool_map)

    def _render_result(self, result: Any) -> str:
        if getattr(result, "is_error", False):
            prefix = "MCP tool reported an error."
        else:
            prefix = ""

        structured = getattr(result, "structured_content", None)
        if structured is not None:
            rendered = json.dumps(structured, ensure_ascii=False, default=str)
        else:
            chunks: list[str] = []
            for item in getattr(result, "content", []) or []:
                text = getattr(item, "text", None)
                if text is not None:
                    chunks.append(str(text))
            rendered = "\n".join(chunks).strip()
            if not rendered:
                rendered = str(result)

        rendered = rendered[: self.max_output_chars]
        return f"{prefix} {rendered}".strip()


def _safe_name(value: str) -> bool:
    return bool(value) and len(value) <= 80 and all(
        char.isalnum() or char in "._-" for char in value
    )


def _string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("MCP tool allow/risk lists must be string arrays")
    return {item.strip() for item in value if item.strip()}


def _validate_http_endpoint(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_HTTP_SCHEMES or not parsed.hostname:
        raise ValueError("MCP HTTP endpoint must use http:// or https:// with a hostname")
    if parsed.username or parsed.password:
        raise ValueError("MCP endpoint credentials must not be embedded in the URL")

    host = parsed.hostname.lower()
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        if parsed.scheme == "http" and literal.is_loopback:
            return
        if (
            literal.is_private
            or literal.is_loopback
            or literal.is_link_local
            or literal.is_multicast
            or literal.is_reserved
            or literal.is_unspecified
        ):
            raise ValueError("MCP endpoint uses a non-public network address")
        if parsed.scheme == "http":
            raise ValueError("MCP public HTTP endpoints must use HTTPS")
        return

    if parsed.scheme == "http" and host not in _BLOCKED_HOSTS:
        raise ValueError("MCP public HTTP endpoints must use HTTPS")

    if host in _BLOCKED_HOSTS:
        return

    # Prevent DNS rebinding/SSRF through an HTTPS hostname that resolves to
    # loopback, private, link-local, multicast, reserved, or unspecified IPs.
    try:
        addresses = {
            ipaddress.ip_address(item[4][0])
            for item in socket.getaddrinfo(
                host,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        }
    except socket.gaierror as exc:
        raise ValueError("MCP endpoint hostname could not be resolved") from exc
    if not addresses:
        raise ValueError("MCP endpoint hostname resolved to no addresses")
    if any(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
        for address in addresses
    ):
        raise ValueError("MCP endpoint resolves to a non-public network address")

def _resolve_env_map(value: Any, field_name: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"MCP {field_name} must be an object mapping names to environment variables")
    result: dict[str, str] = {}
    for target, source in value.items():
        if not isinstance(target, str) or not isinstance(source, str):
            raise ValueError(f"MCP {field_name} entries must map strings to strings")
        if not _safe_name(target) or not _safe_name(source):
            raise ValueError(f"MCP {field_name} contains an unsafe name")
        value = os.environ.get(source)
        if value:
            result[target] = value
    return result


def _validate_tool_policy(config: dict[str, Any]) -> tuple[set[str], set[str], set[str], set[str]]:
    allowed = _string_set(config.get("allowed_tools"))
    read_tools = _string_set(config.get("read_tools"))
    write_tools = _string_set(config.get("write_tools"))
    destructive_tools = _string_set(config.get("destructive_tools"))
    if not allowed:
        raise ValueError(f"MCP server {config.get('name')!r} must define a non-empty allowed_tools list")
    classified = read_tools | write_tools | destructive_tools
    if classified != allowed:
        raise ValueError(f"MCP server {config.get('name')!r} must classify every allowed tool exactly once")
    if (read_tools & write_tools) or (read_tools & destructive_tools) or (write_tools & destructive_tools):
        raise ValueError(f"MCP server {config.get('name')!r} has overlapping tool risk classifications")
    return allowed, read_tools, write_tools, destructive_tools


def _tool_risk(
    read: set[str],
    write: set[str],
    destructive: set[str],
    tool_name: str,
) -> RiskLevel:
    if tool_name in destructive:
        return RiskLevel.DESTRUCTIVE
    if tool_name in write:
        return RiskLevel.WRITE
    if tool_name in read:
        return RiskLevel.READ
    raise ValueError(f"MCP tool has no explicit risk classification: {tool_name}")


def _tool_description(server: str, tool: str, description: Any) -> str:
    base = str(description or f"MCP tool {tool} exposed by {server}.")
    return f"[MCP:{server}] {base}"[:4000]
