"""tests/test_mcp_server.py â€” MCP server registration smoke test (no browser required).

Verifies that the FastMCP app registers all expected tool names without launching a browser.
"""

from __future__ import annotations

import importlib

import pytest


def _get_tool_names() -> list[str]:
    """Import the server module and return registered tool names (synchronous)."""
    # Import the module â€” the @mcp.tool() decorators run at import time
    server = importlib.import_module("visus.web.mcp.server")
    mcp_app = server.mcp
    # _tool_manager.list_tools() is synchronous
    tools = mcp_app._tool_manager.list_tools()
    return [t.name for t in tools]


# ---------------------------------------------------------------------------
# The expected complete tool inventory
# ---------------------------------------------------------------------------

_EXPECTED_TOOLS = [
    # Navigation
    "browser_navigate",
    "browser_navigate_back",
    "browser_navigate_forward",
    "browser_reload",
    # Inspect
    "browser_snapshot",
    "browser_list_fields",
    "browser_clear_highlights",
    "browser_translate_element",
    "browser_title",
    "browser_url",
    "browser_get_text",
    "browser_get_attribute",
    "browser_count",
    # Actions
    "browser_click",
    "browser_dblclick",
    "browser_fill",
    "browser_press",
    "browser_hover",
    "browser_check",
    "browser_uncheck",
    "browser_select_option",
    "browser_pick_date",
    "browser_drag",
    "browser_focus",
    "browser_clear",
    "browser_set_input_files",
    # Wait / expect
    "browser_wait_for",
    "browser_expect_text",
    # Tabs
    "browser_tab_list",
    "browser_tab_new",
    "browser_tab_select",
    "browser_tab_activate",
    "browser_tab_close",
    "browser_set_tab_follow",
    # Dialogs
    "browser_handle_dialog",
    # Network / console capture
    "browser_network_requests",
    "browser_console_messages",
    # Cookies
    "browser_get_cookies",
    "browser_add_cookies",
    "browser_clear_cookies",
    # Media / JS
    "browser_screenshot",
    "browser_evaluate",
    # Vision
    "browser_read_text",
    "browser_solve_captcha",
    "browser_find_image",
    "browser_click_image",
    "browser_click_ocr_text",
    # Lifecycle
    "browser_close",
    # Tracing
    "browser_tracing_start",
    "browser_tracing_stop",
    "browser_tracing_report",
    # Attach
    "browser_attach_session",
    "browser_detach_session",
]


def test_all_expected_tools_registered() -> None:
    """Every tool in the inventory must be registered by the FastMCP app."""
    registered = _get_tool_names()
    missing = [name for name in _EXPECTED_TOOLS if name not in registered]
    assert not missing, (
        f"Missing tools ({len(missing)}): {missing}\n"
        f"Registered tools ({len(registered)}): {sorted(registered)}"
    )


def test_at_least_35_tools_registered() -> None:
    """Ensure at minimum 35 tools are registered (guards against partial implementations)."""
    registered = _get_tool_names()
    assert len(registered) >= 35, (
        f"Expected â‰¥35 tools, found {len(registered)}: {sorted(registered)}"
    )


def test_tool_count_matches_inventory() -> None:
    """Registered count should equal the full inventory."""
    registered = _get_tool_names()
    assert len(registered) == len(_EXPECTED_TOOLS), (
        f"Expected {len(_EXPECTED_TOOLS)} tools, found {len(registered)}.\n"
        f"Registered: {sorted(registered)}\n"
        f"Expected: {sorted(_EXPECTED_TOOLS)}"
    )


def test_translate_element_tool_returns_selectors() -> None:
    """browser_translate_element parses a pasted element into selectors (no browser)."""
    from visus.web.mcp import server

    r = server.browser_translate_element('<input id="x" name="y" type="text">')
    assert r["id"] == "#x"
    assert r["css"] == "#x"
    assert r["name"] == "y"
    assert r["xpath"] == '//input[@name="y"]'


@pytest.mark.parametrize("tool_name", _EXPECTED_TOOLS)
def test_tool_registered(tool_name: str) -> None:
    """Each individual tool name must be in the registry."""
    registered = _get_tool_names()
    assert tool_name in registered, (
        f"Tool {tool_name!r} not found. Registered: {sorted(registered)}"
    )


# ---------------------------------------------------------------------------
# Skill delivery (resources + prompt) — closes the last distribution channel
# ---------------------------------------------------------------------------


def test_skill_resource_returns_the_bundled_skill() -> None:
    from visus.web.cli.skills import bundled_skill_dir
    from visus.web.mcp import server

    text = server._bundled_skill_text()
    assert text == (bundled_skill_dir() / "SKILL.md").read_text(encoding="utf-8")
    assert "visus session start" in text


def test_skill_reference_resource_reads_a_reference_file() -> None:
    from visus.web.mcp import server

    assert "visus list-fields" in server._bundled_skill_reference_text("cli-commands.md")


def test_skill_reference_resource_cannot_escape_the_references_dir() -> None:
    from visus.web.mcp import server

    with pytest.raises(FileNotFoundError):
        server._bundled_skill_reference_text("../SKILL.md")


def test_quickstart_prompt_teaches_the_session_loop() -> None:
    from visus.web.mcp import server

    text = server.visus_web_quickstart()
    assert "visus session start" in text
    assert "visus://skill/SKILL.md" in text


async def test_skill_resource_and_prompt_are_registered() -> None:
    server = importlib.import_module("visus.web.mcp.server")

    uris = [str(r.uri) for r in await server.mcp.list_resources()]
    assert any("SKILL.md" in u for u in uris), uris

    prompts = [p.name for p in await server.mcp.list_prompts()]
    assert "visus_web_quickstart" in prompts, prompts


def test_registering_the_skill_did_not_change_the_tool_count() -> None:
    assert len(_get_tool_names()) == 53

