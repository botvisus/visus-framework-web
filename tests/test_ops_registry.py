"""The tool <-> op inventory: MCP and the CLI daemon must not drift apart."""

from __future__ import annotations

from visus.web.cli.session_server import SessionHandler
from visus.web.ops import registry


def _registered_tool_names() -> set[str]:
    """Registered FastMCP tool names (same accessor as test_mcp_server._get_tool_names)."""
    from visus.web.mcp import server

    return {t.name for t in server.mcp._tool_manager.list_tools()}


def test_every_mcp_tool_maps_to_a_daemon_op() -> None:
    """The headline invariant: no capability may exist on MCP alone.

    D3 was exactly this — browser_network_requests / browser_console_messages /
    browser_tab_activate / browser_set_tab_follow gave MCP agents strictly more
    power than shell agents, with no reason stated anywhere.
    """
    registered = _registered_tool_names()
    accounted = set(registry.TOOL_OPS) | registry.SESSIONLESS_TOOLS | registry.LOCAL_ONLY_TOOLS
    unaccounted = sorted(registered - accounted)
    assert not unaccounted, (
        f"{len(unaccounted)} MCP tool(s) have no declared daemon op and no declared "
        f"exemption: {unaccounted}"
    )


def test_the_registry_never_names_a_tool_that_is_not_registered() -> None:
    registered = _registered_tool_names()
    accounted = set(registry.TOOL_OPS) | registry.SESSIONLESS_TOOLS | registry.LOCAL_ONLY_TOOLS
    ghosts = sorted(accounted - registered)
    assert not ghosts, f"registry names tool(s) the MCP server does not register: {ghosts}"


def test_every_mapped_op_exists_on_the_daemon() -> None:
    missing = sorted(
        f"{tool} -> _op_{op}"
        for tool, op in registry.TOOL_OPS.items()
        if not hasattr(SessionHandler, f"_op_{op}")
    )
    assert not missing, f"mapped op(s) with no SessionHandler handler: {missing}"


def test_the_exemption_sets_are_disjoint_from_the_map() -> None:
    assert not (set(registry.TOOL_OPS) & registry.SESSIONLESS_TOOLS)
    assert not (set(registry.TOOL_OPS) & registry.LOCAL_ONLY_TOOLS)
    assert not (registry.SESSIONLESS_TOOLS & registry.LOCAL_ONLY_TOOLS)


def test_the_four_mcp_only_holes_are_closed() -> None:
    """D3 by name, so a regression names itself in the failure message."""
    for tool in (
        "browser_network_requests",
        "browser_console_messages",
        "browser_tab_activate",
        "browser_set_tab_follow",
    ):
        op = registry.TOOL_OPS[tool]
        assert hasattr(SessionHandler, f"_op_{op}"), f"{tool} is still MCP-only (needs _op_{op})"


def test_every_indexable_tool_accepts_an_index_parameter() -> None:
    """D12: index targeting is the product's best ergonomics idea, CLI-only until now."""
    import inspect

    from visus.web.mcp import server

    problems: list[str] = []
    for name in sorted(registry.INDEXABLE_TOOLS):
        params = inspect.signature(getattr(server, name)).parameters
        if "index" not in params:
            problems.append(f"{name}: no `index` parameter")
            continue
        p = params["index"]
        if p.default is not None:
            problems.append(f"{name}: `index` must default to None, got {p.default!r}")
        # mcp/server.py uses `from __future__ import annotations`, so this is a string.
        if str(p.annotation) != "int | None":
            problems.append(f"{name}: `index` must be `int | None`, got {p.annotation!r}")
    assert not problems, problems


def test_indexable_tools_are_all_registered_and_daemon_backed() -> None:
    assert registry.INDEXABLE_TOOLS <= set(registry.TOOL_OPS)
