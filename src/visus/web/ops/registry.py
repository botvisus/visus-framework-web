"""The tool <-> op inventory both frontends are checked against.

An MCP tool and a `visus` command are two frontends over one op. This module is
where that claim is written down, so a tool added to one surface and forgotten on
the other fails a test instead of shipping as a silent capability gap (D3: four
tools existed only on MCP, and nothing in the repo noticed).

Two exemptions are allowed and both must be declared:

* :data:`SESSIONLESS_TOOLS` — the tool touches no browser at all, so there is
  nothing for a daemon to own.
* :data:`LOCAL_ONLY_TOOLS` — the tool acts on *this process*, not on a page, so
  sending it across to another process would be meaningless.
"""

from __future__ import annotations

TOOL_OPS: dict[str, str] = {
    # Navigation
    "browser_navigate": "goto",
    "browser_navigate_back": "back",
    "browser_navigate_forward": "forward",
    "browser_reload": "reload",
    # Inspect
    "browser_snapshot": "snapshot",
    "browser_list_fields": "list_fields",
    "browser_clear_highlights": "clear_highlights",
    "browser_title": "title",
    "browser_url": "url",
    "browser_get_text": "get_text",
    "browser_get_attribute": "get_attribute",
    "browser_count": "count",
    # Actions
    "browser_click": "click",
    "browser_dblclick": "dblclick",
    "browser_fill": "fill",
    "browser_press": "press",
    "browser_hover": "hover",
    "browser_check": "check",
    "browser_uncheck": "uncheck",
    "browser_select_option": "select",
    "browser_drag": "drag",
    "browser_focus": "focus",
    "browser_clear": "clear_input",
    "browser_set_input_files": "upload",
    # Wait / expect
    "browser_wait_for": "wait",
    "browser_expect_text": "expect_text",
    # Tabs
    "browser_tab_list": "tabs",
    "browser_tab_new": "tab_new",
    "browser_tab_select": "tab",
    "browser_tab_activate": "tab_activate",
    "browser_tab_close": "tab_close",
    "browser_set_tab_follow": "tab_follow",
    # Dialogs
    "browser_handle_dialog": "dialog",
    # Network / console capture
    "browser_network_requests": "network_requests",
    "browser_console_messages": "console_messages",
    # Cookies
    "browser_get_cookies": "cookies",
    "browser_add_cookies": "add_cookies",
    "browser_clear_cookies": "clear_cookies",
    # Media / JavaScript
    "browser_screenshot": "screenshot",
    "browser_evaluate": "eval",
    # Vision
    "browser_read_text": "read_text",
    "browser_solve_captcha": "solve_captcha",
    "browser_find_image": "find_image",
}

SESSIONLESS_TOOLS: frozenset[str] = frozenset(
    {
        # Pure HTML parsing — `visus translate` is its CLI twin and is likewise the
        # only command in either CLI that works with no browser running at all.
        "browser_translate_element",
    }
)

LOCAL_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        # Owns THIS server's browser lifetime. The shell's session lifetime belongs
        # to `visus session stop`; sending `shutdown` across would kill a browser
        # the user is still using.
        "browser_close",
    }
)

INDEXABLE_TOOLS: frozenset[str] = frozenset(
    {
        # Every tool that resolves an element. `index` re-resolves a cached field
        # through its iframe chain and shadow `deep` flag, which no combination of
        # selector/role/text can express from outside the frame (D12).
        "browser_click",
        "browser_dblclick",
        "browser_fill",
        "browser_press",
        "browser_hover",
        "browser_check",
        "browser_uncheck",
        "browser_select_option",
        "browser_drag",
        "browser_focus",
        "browser_clear",
        "browser_set_input_files",
        "browser_get_text",
        "browser_get_attribute",
        "browser_count",
        "browser_wait_for",
        "browser_expect_text",
        "browser_screenshot",
        "browser_read_text",
        "browser_solve_captcha",
        "browser_find_image",
    }
)
