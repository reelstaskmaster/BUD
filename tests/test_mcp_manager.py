from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.services.mcp_manager import MCPManager, _tool_risk, _validate_http_endpoint, _validate_tool_policy
from app.services.capability_registry import RiskLevel


class Settings:
    mcp_enabled = True
    mcp_servers_json = ""
    mcp_timeout_s = 5.0
    mcp_max_output_chars = 1000
    mcp_stdio_allowed_commands = ""


def test_empty_manager_has_no_tools():
    manager = MCPManager(Settings())
    assert manager.tool_definitions() == []


def test_http_endpoint_rejects_embedded_credentials():
    with pytest.raises(ValueError):
        _validate_http_endpoint("https://user:pass@example.com/mcp")


def test_http_endpoint_rejects_public_plain_http():
    with pytest.raises(ValueError):
        _validate_http_endpoint("http://example.com/mcp")


def test_loopback_http_is_allowed_for_local_testing():
    _validate_http_endpoint("http://127.0.0.1:8000/mcp")


def test_tool_risk_is_explicit():
    read = {"read"}
    write = {"write"}
    destructive = {"delete"}
    assert _tool_risk(read, write, destructive, "read") == RiskLevel.READ
    assert _tool_risk(read, write, destructive, "write") == RiskLevel.WRITE
    assert _tool_risk(read, write, destructive, "delete") == RiskLevel.DESTRUCTIVE
    with pytest.raises(ValueError):
        _tool_risk(read, write, destructive, "unknown")


def test_config_is_explicit_and_bounded():
    settings = Settings()
    settings.mcp_servers_json = json.dumps([{"name": "github", "transport": "streamable_http", "url": "https://example.com/mcp"}])
    manager = MCPManager(settings)
    assert manager._parse_configs()[0]["name"] == "github"


def test_tool_description_is_namespaced():
    from app.services.mcp_manager import _tool_description
    assert _tool_description("github", "search", "Find repos") == "[MCP:github] Find repos"


@pytest.mark.asyncio
async def test_render_result_prefers_structured_content():
    manager = MCPManager(Settings())
    result = SimpleNamespace(
        is_error=False,
        structured_content={"ok": True},
        content=[],
    )
    assert json.loads(manager._render_result(result)) == {"ok": True}


@pytest.mark.asyncio
async def test_render_result_sanitizes_length():
    manager = MCPManager(Settings())
    result = SimpleNamespace(
        is_error=False,
        structured_content=None,
        content=[SimpleNamespace(text="x" * 5000)],
    )
    assert len(manager._render_result(result)) == 1000


def test_server_config_requires_explicit_allowlist_and_classification():
    manager = MCPManager(Settings())
    with pytest.raises(ValueError, match="allowed_tools"):
        from app.services.mcp_manager import _validate_tool_policy
        _validate_tool_policy({"name": "demo"})


@pytest.mark.asyncio
async def test_server_connect_accepts_explicit_policy():
    manager = MCPManager(Settings())
    config = {
        "name": "demo",
        "transport": "streamable_http",
        "url": "https://example.com/mcp",
        "allowed_tools": ["search"],
        "read_tools": ["search"],
        "write_tools": [],
        "destructive_tools": [],
    }
    # Policy validation happens before any network connection.
    from app.services.mcp_manager import _validate_tool_policy
    assert _validate_tool_policy(config)[0] == {"search"}
