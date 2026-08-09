"""Every MCP tool that resolves a target offers `nth`, like the CLI does.

``ops/targeting.make_locator`` grew ``nth`` so BOTH frontends would get the way
out of a strict-mode violation from one change — that is the whole reason the
shared layer exists. Plumbing it without exposing it would have left MCP clients
facing "locator resolved to 5 elements" with no parameter to answer it, which is
the exact wall the CLI work removed.

`browser_snapshot` is excluded on purpose: its `selector` SCOPES a walk, it does
not name one element, so picking an nth of it means nothing.
"""

from __future__ import annotations

from typing import Any

SCOPE_ONLY = {"browser_snapshot"}


def _targeting_tools() -> list[Any]:
    from visus.web.mcp import server

    return [
        tool
        for tool in server.mcp._tool_manager.list_tools()
        if "selector" in tool.parameters.get("properties", {}) and tool.name not in SCOPE_ONLY
    ]


def test_there_are_targeting_tools_to_check() -> None:
    """Guard against a filter that silently matches nothing."""
    assert len(_targeting_tools()) > 15


def test_every_targeting_tool_exposes_nth() -> None:
    missing = [t.name for t in _targeting_tools() if "nth" not in t.parameters["properties"]]
    assert not missing, f"MCP tools that can hit strict mode with no way out: {missing}"


def test_nth_is_an_optional_integer() -> None:
    for tool in _targeting_tools():
        schema = tool.parameters["properties"]["nth"]
        assert "nth" not in tool.parameters.get("required", []), tool.name
        rendered = str(schema)
        assert "integer" in rendered, f"{tool.name}: nth is not an integer ({schema})"


def test_the_payload_carries_nth_to_the_daemon() -> None:
    """The remote path must send it too, not only the in-process resolver."""
    from visus.web.mcp import server

    assert server._target_payload(selector="li", nth=2)["nth"] == 2
    assert server._target_payload(selector="li")["nth"] is None
