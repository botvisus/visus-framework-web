"""visus-web MCP server — comprehensive FastMCP wrapper over the full visus.web API.

Playwright-MCP parity + frames + OCR/vision extras.
Run via: uv run visus-web-mcp   (or python -m visus.web.mcp.server)
"""

from __future__ import annotations

import os
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP, Image

from visus.web.api.assertions import expect
from visus.web.mcp.session import Session
from visus.web.ops.remote import RemoteDispatcher
from visus.web.ops.targeting import any_match_visible as _any_match_visible

# `make_locator` is deliberately NOT imported here any more: every tool resolves
# through `_session.target()`, so one payload dict works locally and across the
# daemon socket alike. `mcp.session` still re-exports it for Task 1's identity test.

mcp = FastMCP("visus-web")
_session = Session()

# Set by browser_attach_session (Task 7). While None, every op runs in this
# process against this server's own browser.
_remote: RemoteDispatcher | None = None


def _target_payload(
    *,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> dict[str, Any]:
    """This tool's targeting parameters as the DAEMON's payload.

    One payload shape serves the in-process resolver (``Session.target``) and the
    remote one (``RemoteDispatcher``), so a tool body never has to know which is
    in play. The locator-TEXT target is renamed ``text`` -> ``target_text``
    because the daemon reserves ``text`` for fill's VALUE payload.
    """
    return {
        "index": index,
        "selector": selector,
        "role": role,
        "name": name,
        "target_text": text,
        "exact": exact,
        "frame": frame,
        "nth": nth,
    }


def _run(op: str, args: dict[str, Any], local: Callable[[], Any]) -> dict[str, Any]:
    """Execute one op and return a daemon-shaped envelope.

    Attached (``browser_attach_session``): the op crosses to the `visus` session
    daemon, so it drives the SAME browser the shell is driving and comes back
    with the envelope ``SessionHandler.handle`` builds — ``result`` plus, for a
    mutating op, ``page`` state and the generated ``code`` line. Detached:
    *local* runs here against this server's own browser and the envelope is
    built here. Either way there is exactly one op vocabulary.

    *local* is a callable, not a value, so the local path — which would launch a
    browser — is never executed while attached.
    """
    if _remote is None:
        return {"ok": True, "result": local()}
    env = _remote.handle(op, args)
    if not env.get("ok"):
        raise RuntimeError(str(env.get("error", "unknown error")))
    return env


def _acted(env: dict[str, Any], message: str) -> str:
    """An action's result plus the page state the agent needs for its next step.

    Without this an agent is blind after every action and must spend a whole extra
    tool call on browser_url/browser_title, or act on a stale mental model. When
    attached, the state comes from the daemon's own envelope (PLAN 4's ``page``
    key), so it describes the page the action actually produced — no second
    round-trip, and no chance of reading a different browser.
    """
    state = env.get("page")
    if isinstance(state, dict) and state.get("url") is not None:
        footer = f"\n\n### Page\n- URL: {state['url']}\n- Title: {state.get('title', '')}"
        if state.get("fields_stale"):
            footer += "\n- Fields: stale (run browser_list_fields again)"
        return message + footer
    if _remote is not None:
        return message  # attached but the daemon sent no footer: do not guess
    try:
        page = _session.page()
        return f"{message}\n\n### Page\n- URL: {page.url}\n- Title: {page.title()}"
    except Exception:  # noqa: BLE001 — page state is telemetry, never the result
        return message


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_navigate(url: str) -> str:
    """Navigate the browser to a URL and return the resulting title."""

    def _local() -> str:
        page = _session.page()
        page.goto(url)
        _session.invalidate_fields()  # cached indexes belonged to the previous page
        return page.url

    env = _run("goto", {"url": url}, _local)
    return _acted(env, f"navigated to {env['result']!r}")


@mcp.tool()
def browser_navigate_back() -> str:
    """Navigate back in browser history."""

    def _local() -> str:
        page = _session.page()
        page.go_back()
        _session.invalidate_fields()  # cached indexes belonged to the previous page
        return page.url

    env = _run("back", {}, _local)
    return _acted(env, f"went back → {env['result']!r}")


@mcp.tool()
def browser_navigate_forward() -> str:
    """Navigate forward in browser history."""

    def _local() -> str:
        page = _session.page()
        page.go_forward()
        _session.invalidate_fields()  # cached indexes belonged to the previous page
        return page.url

    env = _run("forward", {}, _local)
    return _acted(env, f"went forward → {env['result']!r}")


@mcp.tool()
def browser_reload() -> str:
    """Reload the current page."""

    def _local() -> str:
        page = _session.page()
        page.reload()
        _session.invalidate_fields()  # cached indexes belonged to the previous page
        return page.url

    env = _run("reload", {}, _local)
    return _acted(env, f"reloaded {env['result']!r}")


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_snapshot(
    selector: str | None = None,
    depth: int | None = None,
) -> list[dict]:  # type: ignore[type-arg]
    """Return the page's interactive elements as a list of {role, name, depth} dicts.

    Use role/name to target action tools without needing CSS selectors. depth is
    how many element levels below <body> the element sits; pass *depth* to keep
    only elements at most that many levels below the root, and *selector* to
    scope the walk to one subtree. Each row's ``ref`` is a live browser_list_fields
    index, so it can be passed straight to an action tool as ``index``.
    """
    args: dict[str, Any] = {"selector": selector, "depth": depth}

    def _local() -> dict[str, Any]:
        return {"elements": _session.page().snapshot(selector, depth=depth)}

    elements: list[dict[str, Any]] = _run("snapshot", args, _local)["result"]["elements"]
    return elements


@mcp.tool()
def browser_list_fields(
    kind: str | None = None,
    include_hidden: bool = False,
    highlight: bool = False,
    clickables: bool = True,
) -> list[dict]:  # type: ignore[type-arg]
    """List all RPA-relevant interactive fields on the current page.

    Enumerates buttons, inputs, textareas, links, selects, checkboxes/radios,
    custom dropdowns, and contenteditable elements — framework-agnostically,
    across open shadow DOM and same-origin iframes. Each returned dict carries a
    ready-to-use locator plus the frame chain and a deep flag.

    Each returned dict carries an ``index``: pass it as the ``index`` argument of
    any action tool (browser_click, browser_fill, …) and the element is
    re-resolved through its iframe chain and open shadow roots for you. Do NOT
    rebuild that chain by hand — a bare css/xpath cannot reach inside a frame.
    Indexes are void after a navigation; run this tool again.

    kind is an optional comma-separated filter (e.g. "button,input") restricting
    the result to those kinds; omit it to list every kind. include_hidden also
    returns hidden/disabled fields (flagged). highlight draws the numbered
    overlay on the page (default off; a no-op when headless). clickables (default on)
    also lists elements only a click handler makes interactive — a menu item, a
    calendar day — as kind "clickable".
    """
    parsed = [k.strip() for k in kind.split(",") if k.strip()] if kind else None
    args: dict[str, Any] = {
        "kinds": parsed,
        "include_hidden": include_hidden,
        "highlight": highlight,
        "clickables": clickables,
    }

    def _local() -> dict[str, Any]:
        fields = _session.page().list_fields(
            kinds=parsed, include_hidden=include_hidden, highlight=highlight, clickables=clickables
        )
        _session.cache_fields(fields)  # so the action tools can target by `index`
        return {"fields": [f.to_dict() for f in fields]}

    rows: list[dict[str, Any]] = _run("list_fields", args, _local)["result"]["fields"]
    return rows


@mcp.tool()
def browser_clear_highlights() -> str:
    """Remove the numbered field-highlight overlay drawn by browser_list_fields."""

    def _local() -> str:
        _session.page().clear_highlights()
        return "cleared"

    cleared: str = _run("clear_highlights", {}, _local)["result"]
    return cleared


@mcp.tool()
def browser_translate_element(html: str) -> dict[str, object]:
    """Translate a pasted DevTools element (Copy element) into selectors.

    Given an element's outerHTML, returns the recommended id / css / xpath / class
    selectors plus the full ordered candidate list the smart locator tries. Pure
    parsing — no live page needed. The same css/xpath also works directly via
    page.locator("<the pasted html>").
    """
    from visus.web.api._htmlsel import translate

    return translate(html)


@mcp.tool()
def browser_title() -> str:
    """Return the current page title."""
    title: str = _run("title", {}, lambda: _session.page().title())["result"]
    return title


@mcp.tool()
def browser_url() -> str:
    """Return the current page URL."""
    url: str = _run("url", {}, lambda: _session.page().url)["result"]
    return url


@mcp.tool()
def browser_get_text(
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str | None:
    """Return the visible text content of an element (None when it does not exist)."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )

    def _local() -> dict[str, Any]:
        loc = _session.target(args).first()  # tolerate multi-match (agent-friendly read)
        return {"value": loc.text_content(), "present": loc.count() > 0}

    result: dict[str, Any] = _run("get_text", args, _local)["result"]
    value: str | None = result["value"]
    return value


@mcp.tool()
def browser_get_attribute(
    attr_name: str,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str | None:
    """Return the value of an HTML attribute on an element."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    args["attr_name"] = attr_name

    def _local() -> dict[str, Any]:
        loc = _session.target(args).first()  # tolerate multi-match
        return {"value": loc.get_attribute(attr_name), "present": loc.count() > 0}

    result: dict[str, Any] = _run("get_attribute", args, _local)["result"]
    value: str | None = result["value"]
    return value


@mcp.tool()
def browser_count(
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> int:
    """Return the count of elements matching the given target."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    count: int = _run("count", args, lambda: _session.target(args).count())["result"]
    return count


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_click(
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Click an element targeted by role+name, text, or css/xpath selector."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    return _acted(_run("click", args, lambda: _session.target(args).click()), "clicked")


@mcp.tool()
def browser_dblclick(
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Double-click an element."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    env = _run("dblclick", args, lambda: _session.target(args).dblclick())
    return _acted(env, "double-clicked")


@mcp.tool()
def browser_fill(
    text_value: str,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Fill an input/textarea with the given text_value."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    args["text"] = text_value
    env = _run("fill", args, lambda: _session.target(args).fill(text_value))
    return _acted(env, f"filled with {text_value!r}")


@mcp.tool()
def browser_press(
    key: str,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Press a key (e.g. 'Enter', 'Tab', 'Control+a') on the focused element."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    args["key"] = key
    return _acted(_run("press", args, lambda: _session.target(args).press(key)), f"pressed {key!r}")


@mcp.tool()
def browser_hover(
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Hover over an element."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    return _acted(_run("hover", args, lambda: _session.target(args).hover()), "hovered")


@mcp.tool()
def browser_check(
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Check a checkbox or radio button."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    return _acted(_run("check", args, lambda: _session.target(args).check()), "checked")


@mcp.tool()
def browser_uncheck(
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Uncheck a checkbox."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    return _acted(_run("uncheck", args, lambda: _session.target(args).uncheck()), "unchecked")


@mcp.tool()
def browser_select_option(
    value: str,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Select an option from a <select> element by value."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    args["value"] = value
    env = _run("select", args, lambda: _session.target(args).select_option(value=value))
    return _acted(env, f"selected option {value!r}")


@mcp.tool()
def browser_pick_date(
    start: str,
    end: str | None = None,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Pick a date (YYYY-MM-DD), or a range with ``end``, in any date field: a native date
    input, a text field, or a calendar that opens on click — it steps through the months
    with the arrows and clicks the day. Reads the field back and fails if it did not stick."""
    from visus.web.ops import dates

    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    args["start"] = start
    if end:
        args["end"] = end

    def _local() -> str:
        first = dates.parse_iso(start)
        last = dates.parse_iso(end) if end else None
        return dates.pick_date(_session.page(), _session.target(args), first, last)

    env = _run("pick_date", args, _local)
    return _acted(env, str(env.get("result", "")))


@mcp.tool()
def browser_drag(
    target_selector: str | None = None,
    target_index: int | None = None,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Drag the source element onto a target (a CSS/XPath selector, or a field index)."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    args["target_selector"] = target_selector
    args["target_index"] = target_index

    def _local() -> None:
        src = _session.target(args)
        if target_selector is not None:
            src.drag_to(_session.page().locator(target_selector))
        elif target_index is not None:
            src.drag_to(_session.field_locator(target_index))
        else:
            raise ValueError("provide a drag target: target_selector or target_index")

    where = target_selector if target_selector is not None else f"field {target_index}"
    return _acted(_run("drag", args, _local), f"dragged to {where!r}")


@mcp.tool()
def browser_focus(
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Focus an element."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    return _acted(_run("focus", args, lambda: _session.target(args).focus()), "focused")


@mcp.tool()
def browser_clear(
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Clear the value of an input field."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    return _acted(_run("clear_input", args, lambda: _session.target(args).clear()), "cleared")


@mcp.tool()
def browser_set_input_files(
    paths: list[str],
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Set file(s) on a file input element. Provide absolute paths."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    args["paths"] = paths
    env = _run("upload", args, lambda: _session.target(args).set_input_files(paths))
    return _acted(env, f"set {len(paths)} file(s)")


# ---------------------------------------------------------------------------
# Wait / Expect
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_wait_for(
    state: str = "visible",
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    timeout: int | None = None,
    nth: int | None = None,
) -> str:
    """Wait for an element to reach a state: 'visible' or 'hidden'."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    args["state"] = state
    args["timeout"] = timeout

    def _local() -> str:
        loc = _session.target(args)
        ms = 5000 if timeout is None else timeout
        want_visible = state != "hidden"
        deadline = time.monotonic() + ms / 1000.0
        while True:
            if _any_match_visible(loc) == want_visible:
                return f"element is {state}"
            if time.monotonic() >= deadline:
                raise AssertionError(f"wait_for: no element became {state} within {ms}ms")
            time.sleep(0.1)

    waited: str = _run("wait", args, _local)["result"]
    return waited


@mcp.tool()
def browser_expect_text(
    expected_text: str,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    timeout: int | None = None,
    nth: int | None = None,
) -> str:
    """Assert that an element contains the expected text. Returns 'PASSED' or 'FAILED: ...'."""
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    args["expected_text"] = expected_text
    args["timeout"] = timeout

    def _local() -> str:
        loc = _session.target(args)
        try:
            expect(loc.first()).to_have_text(expected_text, timeout=timeout)
            return "PASSED"
        except AssertionError as exc:
            return f"FAILED: {exc}"

    verdict: str = _run("expect_text", args, _local)["result"]
    return verdict


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_tab_list() -> list[dict]:  # type: ignore[type-arg]
    """List all open tabs as [{index, handle, title, url, active}].

    Reflects every open tab — including ones opened by a link or window.open —
    by reconciling against the live window handles. ``handle`` is a stable id you
    can pass to browser_tab_activate, and ``active`` marks the tab every other
    tool is currently acting on.
    """

    def _local() -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for i, p in enumerate(_session.pages()):
            try:
                title, url = p.title(), p.url
            except Exception:  # noqa: BLE001 — one dead tab must not hide the live ones
                title, url = "", ""
            rows.append(
                {
                    "index": i,
                    "handle": p.handle,
                    "title": title,
                    "url": url,
                    "active": i == _session._current_idx,
                }
            )
        return {"tabs": rows, "active": _session._current_idx}

    tabs: list[dict[str, Any]] = _run("tabs", {}, _local)["result"]["tabs"]
    return tabs


@mcp.tool()
def browser_tab_new(url: str | None = None) -> str:
    """Open a new browser tab, optionally navigating to url. Returns new tab index."""

    def _local() -> dict[str, Any]:
        p = _session.new_page(url)
        return {"index": len(_session.pages()) - 1, "title": p.title()}

    env = _run("tab_new", {"url": url}, _local)
    return f"opened tab {env['result']['index']}"


@mcp.tool()
def browser_tab_select(index: int) -> str:
    """Switch to a tab by its 0-based index."""

    def _local() -> dict[str, Any]:
        p = _session.select(index)
        return {"active": index, "title": p.title()}

    env = _run("tab", {"index": index}, _local)
    return f"switched to tab {env['result']['active']}"


@mcp.tool()
def browser_tab_activate(handle: str) -> str:
    """Focus a tab by its stable handle (from browser_tab_list). Survives reordering."""

    def _local() -> dict[str, Any]:
        p = _session.activate(handle)
        return {"active": _session._current_idx, "handle": handle, "title": p.title()}

    env = _run("tab_activate", {"handle": handle}, _local)
    return f"activated tab {env['result']['handle']} (index {env['result']['active']})"


@mcp.tool()
def browser_tab_close(index: int | None = None) -> str:
    """Close a tab by index (default: current tab)."""

    def _local() -> dict[str, Any]:
        _session.close_tab(index)
        return {"closed": index, "remaining": len(_session._pages)}

    env = _run("tab_close", {"index": index}, _local)
    return f"closed tab {env['result']['closed']} ({env['result']['remaining']} remaining)"


@mcp.tool()
def browser_set_tab_follow(enabled: bool) -> str:
    """Choose how new tabs/popups are handled — the agent picks the mode.

    enabled=False (DEFAULT, recommended): MANUAL. A click that opens a new
    tab/popup does NOT change your context; you stay where you are and steer
    explicitly with browser_tab_list / browser_tab_select. Predictable — no
    silent context switches.

    enabled=True: AUTO-FOLLOW. Subsequent operations target the most recently
    opened tab/popup window automatically (handy for "open in new tab" flows).
    """

    def _local() -> dict[str, Any]:
        return {"follow": _session.set_follow(enabled)}

    env = _run("tab_follow", {"enabled": enabled}, _local)
    on = env["result"]["follow"]
    return f"tab-follow {'enabled (auto)' if on else 'disabled (manual)'}"


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_handle_dialog(accept: bool = True, prompt_text: str | None = None) -> str:
    """Handle the next browser dialog (alert/confirm/prompt).

    Accepts or dismisses it and returns the dialog message.
    NOTE: The action that triggers the dialog must be called BEFORE this tool,
    as this tool handles the PENDING dialog immediately.
    """

    def _local() -> str:
        page = _session.page()
        msg, typ = page._delegate.handle_next_dialog(
            accept=accept, prompt_text=prompt_text, timeout_ms=5000
        )
        action = "accepted" if accept else "dismissed"
        return f"{action} {typ!r} dialog: {msg!r}"

    env = _run("dialog", {"accept": accept, "prompt_text": prompt_text}, _local)
    return _acted(env, str(env["result"]))


# ---------------------------------------------------------------------------
# Network / console capture (Chromium)
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_network_requests(url_filter: str = "") -> list[dict]:  # type: ignore[type-arg]
    """List network responses captured so far (document, XHR/fetch, assets).

    Each entry has url, method, status, resource_type. Pass *url_filter* to keep
    only URLs containing that substring (e.g. "/api/"). Chromium engines only.
    Use it to verify that the API call behind a UI action really happened.
    """

    def _local() -> dict[str, Any]:
        out: list[dict[str, Any]] = [
            {
                "url": r.url,
                "method": r.method,
                "status": r.status,
                "resource_type": r.resource_type,
            }
            for r in _session.page().network_requests()
        ]
        if url_filter:
            out = [r for r in out if url_filter in str(r["url"])]
        return {"requests": out}

    requests: list[dict[str, Any]] = _run("network_requests", {"url_filter": url_filter}, _local)[
        "result"
    ]["requests"]
    return requests


@mcp.tool()
def browser_console_messages(level: str = "") -> list[dict]:  # type: ignore[type-arg]
    """List browser console messages captured so far (console.*, uncaught errors).

    Each entry has level (SEVERE/WARNING/INFO) and text. Pass *level* to filter
    (e.g. "SEVERE" for errors only). Chromium engines only. Check this first
    when a page misbehaves with no visible cause.
    """

    def _local() -> dict[str, Any]:
        out: list[dict[str, Any]] = [
            {"level": m.level, "text": m.text} for m in _session.page().console_messages()
        ]
        if level:
            out = [m for m in out if m["level"] == level.upper()]
        return {"messages": out}

    messages: list[dict[str, Any]] = _run("console_messages", {"level": level}, _local)["result"][
        "messages"
    ]
    return messages


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_get_cookies() -> list[dict]:  # type: ignore[type-arg]
    """Return all cookies for the current context."""

    def _local() -> dict[str, Any]:
        return {"cookies": _session.context().cookies()}

    env = _run("cookies", {}, _local)
    cookies: list[dict[str, Any]] = env["result"]["cookies"]
    return cookies


@mcp.tool()
def browser_add_cookies(cookies: list[dict]) -> str:  # type: ignore[type-arg]
    """Add cookies to the current context. Each cookie must have at least 'name', 'value', 'url'."""

    def _local() -> str:
        _session.context().add_cookies(cookies)
        return f"added {len(cookies)} cookie(s)"

    env = _run("add_cookies", {"cookies": cookies}, _local)
    return _acted(env, str(env["result"]))


@mcp.tool()
def browser_clear_cookies() -> str:
    """Clear all cookies in the current context."""

    def _local() -> str:
        _session.context().clear_cookies()
        return "cookies cleared"

    env = _run("clear_cookies", {}, _local)
    return _acted(env, str(env["result"]))


# ---------------------------------------------------------------------------
# Media / JavaScript
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_screenshot(
    full_page: bool = False,
    index: int | None = None,
    selector: str | None = None,
    nth: int | None = None,
) -> Image:
    """Take a screenshot of the page or a specific element. Returns a PNG image."""
    args = _target_payload(index=index, selector=selector, nth=nth)
    args["full_page"] = full_page
    if _remote is not None:
        # The daemon writes PNGs to disk and returns the path. It is discovered
        # through `.visus/` beside this process's cwd, so both processes are on
        # the same filesystem and a temp-file hand-off is sound.
        tmp = Path(tempfile.gettempdir()) / f"visus-mcp-{uuid.uuid4().hex}.png"
        args["path"] = str(tmp)
        _run("screenshot", args, lambda: None)
        try:
            return Image(data=tmp.read_bytes(), format="png")
        finally:
            tmp.unlink(missing_ok=True)
    if index is not None or selector is not None:
        return Image(data=_session.target(args).screenshot(), format="png")
    return Image(data=_session.page().screenshot(full_page=full_page), format="png")


@mcp.tool()
def browser_evaluate(
    expression: str,
    arg: object = None,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> object:
    """Evaluate a JavaScript function in the browser and return the result.

    With no target the function runs on the page and is called as
    '(expression)(arg)', e.g. '() => document.title'.

    With a target (index / selector / role+name / text) it runs on that ELEMENT
    and is called as '(expression)(element, arg)', e.g. '(el) => el.value' — this
    is how you read id/class/dataset or any property list_fields does not return.
    """
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    args["expression"] = expression
    args["arg"] = arg

    def _local() -> dict[str, Any]:
        if all(args.get(key) is None for key in ("index", "selector", "role", "target_text")):
            return {"result": _session.page().evaluate(expression, arg)}
        return {"result": _session.target(args).first().evaluate(expression, arg)}

    result: dict[str, Any] = _run("eval", args, _local)["result"]
    return result["result"]


# ---------------------------------------------------------------------------
# Vision (OCR / image matching)
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_read_text(
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """OCR the screenshot of an element and return the recognized text.

    Requires the [vision] extra (rapidocr-onnxruntime + opencv).
    """
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    read: str = _run("read_text", args, lambda: _session.target(args).ocr_text())["result"]
    return read


@mcp.tool()
def browser_solve_captcha(
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
    provider: str | None = None,
) -> str:
    """Solve the page's CAPTCHA.

    With no target: the reCAPTCHA (v2/v3/Enterprise), Cloudflare Turnstile or hCaptcha on
    the page is solved by a captcha service with the key in VISUS_CAPTCHA_KEY —
    ``provider`` "capsolver" (default) or "2captcha" — and the token applied; returns
    what it did ("no captcha on this page" when there is none). With a target: OCR the
    text CAPTCHA image shown in it and return the text.
    """
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    if index is None and not any((selector, role, name, text)):
        args = {
            "provider": provider or os.environ.get("VISUS_CAPTCHA_PROVIDER") or None,
            "api_key": os.environ.get("VISUS_CAPTCHA_KEY") or None,
        }

        def _token() -> str:
            return _session.page().solve_captcha(provider=args["provider"], api_key=args["api_key"])

        token_result: str = _run("solve_captcha", args, _token)["result"]
        return token_result

    def _local() -> str:
        return _session.page().solve_captcha(_session.target(args))

    solved: str = _run("solve_captcha", args, _local)["result"]
    return solved


@mcp.tool()
def browser_find_image(
    template_path: str,
    confidence: float = 0.8,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> dict:  # type: ignore[type-arg]
    """Find a template image inside the screenshot of the targeted element (or full page).

    Returns a dict with {found, x, y, confidence} or {found: False}.
    Requires the [vision] extra.
    """
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    args["template_path"] = template_path
    args["confidence"] = confidence

    def _local() -> dict[str, Any]:
        import io

        import numpy as np
        from PIL import Image as PILImage

        from visus.web.vision import find_image

        page = _session.page()
        if any(args.get(key) is not None for key in ("index", "selector", "role", "target_text")):
            screenshot_bytes = _session.target(args).screenshot()
        else:
            screenshot_bytes = page.screenshot()
        source_img = np.array(PILImage.open(io.BytesIO(screenshot_bytes)).convert("RGB"))
        template_img = np.array(PILImage.open(template_path).convert("RGB"))
        match = find_image(source_img, template_img, confidence=confidence)
        if match is None:
            return {"found": False}
        return {"found": True, "x": match.x, "y": match.y, "confidence": match.confidence}

    found: dict[str, Any] = _run("find_image", args, _local)["result"]
    return found


def _click_vision_match(args: dict[str, Any], *, kind: str) -> dict[str, Any]:
    """Locate a template image or rendered text in this process's browser and click it.

    The detached twin of the daemon's ``_op_click_image`` / ``_op_click_ocr_text``:
    same coordinate maths (screenshot pixels -> CSS pixels via devicePixelRatio,
    plus the scoping element's own box), so a flow behaves identically whether the
    MCP server is attached or running its own browser.
    """
    from visus.web.vision import find_image, find_text

    page = _session.page()
    origin_x = origin_y = 0.0
    scoped = any(args.get(key) is not None for key in ("index", "selector", "role", "target_text"))
    if scoped:
        loc = _session.target(args)
        shot = loc.screenshot()
        box = loc.bounding_box()
        if box is not None:
            origin_x, origin_y = float(box["x"]), float(box["y"])
    else:
        shot = page.screenshot()

    try:
        ratio = float(page.evaluate("() => window.devicePixelRatio"))  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 — an unreadable ratio is 1:1
        ratio = 1.0
    if ratio <= 0:
        ratio = 1.0

    if kind == "image":
        match = find_image(shot, args["template_path"], confidence=args["confidence"])
        if match is None:
            raise LookupError(
                f"template {args['template_path']!r} not found on the page "
                f"at confidence >= {args['confidence']}"
            )
        x = origin_x + match.center_x / ratio
        y = origin_y + match.center_y / ratio
        page.mouse.click(x, y)
        return {"x": round(x, 1), "y": round(y, 1), "confidence": round(match.confidence, 4)}

    found_text = find_text(shot, args["ocr_text"], exact=bool(args.get("exact_text", False)))
    if found_text is None:
        raise LookupError(f"no rendered text matching {args['ocr_text']!r} was found on the page")
    x = origin_x + found_text.center_x / ratio
    y = origin_y + found_text.center_y / ratio
    page.mouse.click(x, y)
    return {
        "x": round(x, 1),
        "y": round(y, 1),
        "text": found_text.text,
        "confidence": round(found_text.confidence, 4),
    }


@mcp.tool()
def browser_click_image(
    template_path: str,
    confidence: float = 0.8,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Click the centre of a template image found on the page (or in an element).

    Use when the thing to press has no accessibility tree: a canvas app, an
    embedded PDF viewer, a chart, an image map. Give a target (index / selector /
    role / text) to scope the search to one element. Requires the [vision] extra.
    """
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    args["template_path"] = template_path
    args["confidence"] = confidence

    def _local() -> dict[str, Any]:
        return _click_vision_match(args, kind="image")

    result: dict[str, Any] = _run("click_image", args, _local)["result"]
    return f"clicked image at ({result['x']}, {result['y']}) confidence={result['confidence']:.3f}"


@mcp.tool()
def browser_click_ocr_text(
    ocr_text: str,
    exact_text: bool = False,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    nth: int | None = None,
) -> str:
    """Click rendered text located by OCR — text that exists as pixels, not as a node.

    For canvas-drawn labels, embedded PDFs, chart legends and image buttons.
    Substring and case-insensitive by default; set exact_text to require the whole
    recognised run. Requires the [vision] extra.
    """
    args = _target_payload(
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
        exact=exact,
        frame=frame,
        nth=nth,
    )
    args["ocr_text"] = ocr_text
    args["exact_text"] = exact_text

    def _local() -> dict[str, Any]:
        return _click_vision_match(args, kind="text")

    result: dict[str, Any] = _run("click_ocr_text", args, _local)["result"]
    return (
        f"clicked text {result['text']!r} at ({result['x']}, {result['y']}) "
        f"confidence={result['confidence']:.3f}"
    )


# ---------------------------------------------------------------------------
# Tracing: the single-file HTML report
# ---------------------------------------------------------------------------


def _refuse_while_attached(cli_command: str) -> None:
    """Refuse a this-process-only operation while the browser lives elsewhere."""
    if _remote is not None:
        raise RuntimeError(
            "attached to a visus session — the browser runs in the daemon, so this "
            f"server would record nothing. Run `{cli_command}` against that session "
            "instead, or call browser_detach_session first."
        )


@mcp.tool()
def browser_tracing_start() -> str:
    """Start recording every action with a screenshot, timing and correlated logs.

    Recording continues until browser_tracing_stop, which writes a trace zip and a
    SINGLE-FILE HTML report — every screenshot embedded as a data URI, a KPI band,
    per-step logs and, on any failure, the ARIA snapshot of the page at that
    moment. That file needs no viewer: attach it to a ticket, a PR or a CI job.
    """
    from visus.web import tracing

    _refuse_while_attached("visus tracing-start")
    recorder = tracing.start_recording()
    return f"tracing started (run {recorder.run_id})"


@mcp.tool()
def browser_tracing_stop(zip_path: str = "run.zip", report: str = "report.html") -> dict[str, str]:
    """Stop recording; write the trace zip and the single-file HTML report.

    Returns the absolute paths of both, e.g. {"zip": "...", "report": "..."}.
    Give the report path to the human — it is self-contained.
    """
    from visus.web import tracing

    _refuse_while_attached("visus tracing-stop --report")
    return tracing.stop_recording(zip_path, report)


@mcp.tool()
def browser_tracing_report(zip_path: str, output: str = "report.html") -> str:
    """Render the single-file HTML report from an existing trace zip.

    Works on any zip written by browser_tracing_stop, `visus tracing-stop` or the
    library's tracing.record() — no browser and no session needed. Returns the
    absolute path of the written HTML.
    """
    from visus.web import tracing

    return tracing.render_report(zip_path, output)


# ---------------------------------------------------------------------------
# Attach: one browser instead of two
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_attach_session(project_dir: str | None = None) -> str:
    """Attach to the `visus` CLI session daemon and drive ITS browser from now on.

    Unattached, this server and the `visus` shell run two independent browsers —
    different windows, different cookies, different logins — and nothing in the
    tool output says so. Attached, every tool crosses to the daemon, so the model
    and the human share one page, one session and one field-index vocabulary.

    `project_dir` is where the search for `.visus/sessions/<name>.json` starts
    (default: this process's working directory); the search walks upward,
    git-style. Start the session first with `visus session start <url>`.
    """
    global _remote
    dispatcher = RemoteDispatcher(start_dir=project_dir)
    info = dispatcher.session()
    if info is None:
        where = project_dir or "the current directory"
        raise RuntimeError(
            f"no live visus session found (searched upward from {where}) — "
            "run `visus session start <url>` there first"
        )
    _session.close()  # a second live browser would be invisible and unreachable
    _remote = dispatcher
    return (
        f"attached to the visus session (pid {info['pid']}, port {info['port']}) — "
        "every tool now drives that browser"
    )


@mcp.tool()
def browser_detach_session() -> str:
    """Detach from the `visus` CLI session; later tools use this server's own browser.

    The `visus` session keeps running — detaching never closes the user's browser.
    """
    global _remote
    if _remote is None:
        return "not attached"
    _remote = None
    return "detached — subsequent tools use this server's own browser"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_close() -> str:
    """Close this server's browser and reset the session.

    While attached to a `visus` session (browser_attach_session) this DETACHES
    instead: the shell's browser is not ours to close, and killing it would
    destroy whatever state the user built up. `visus session stop` owns that
    lifetime.
    """
    global _remote
    if _remote is not None:
        _remote = None
        return "detached from the visus session (it is still running — use `visus session stop`)"
    _session.close()
    return "browser closed"


# ---------------------------------------------------------------------------
# Skill delivery — an MCP client with no shell can still read the skill
# ---------------------------------------------------------------------------


def _bundled_skill_text() -> str:
    """The bundled SKILL.md, read from the installed package."""
    from visus.web.cli.skills import bundled_skill_dir

    return (bundled_skill_dir() / "SKILL.md").read_text(encoding="utf-8")


def _bundled_skill_reference_text(name: str) -> str:
    """One reference file of the bundled skill. ``name`` is basenamed, never a path."""
    from pathlib import Path

    from visus.web.cli.skills import bundled_skill_dir

    return (bundled_skill_dir() / "references" / Path(name).name).read_text(encoding="utf-8")


@mcp.resource("visus://skill/SKILL.md", mime_type="text/markdown")
def visus_web_skill() -> str:
    """The visus-web agent skill — the same file `visus install --skills` writes."""
    return _bundled_skill_text()


@mcp.resource("visus://skill/references/{name}", mime_type="text/markdown")
def visus_web_skill_reference(name: str) -> str:
    """One reference file of the visus-web skill, e.g. `cli-commands.md`."""
    return _bundled_skill_reference_text(name)


@mcp.prompt()
def visus_web_quickstart() -> str:
    """Teach the caller the visus session loop and where the full skill lives."""
    return (
        "You are driving a real browser with visus-web.\n\n"
        "Read the resource `visus://skill/SKILL.md` for the full skill, and\n"
        "`visus://skill/references/<file>.md` for a specific topic\n"
        "(cli-session, cli-targeting, cli-commands, cli-json-and-piping, cli-repl,\n"
        "windows-shell, mcp-tools, vision, tracing-reports, pytest-plugin,\n"
        "troubleshooting, library-api).\n\n"
        "With shell access, prefer the CLI — it is far cheaper in tokens:\n"
        "  visus session start <url>\n"
        "  visus list-fields\n"
        "  visus fill 1 <text>\n"
        "  visus click --role button --name Submit\n"
        "  visus expect-text --role heading '<expected>'\n"
        "  visus session stop\n\n"
        "Without shell access, use the browser_* tools here. Field indexes are a\n"
        "cache: re-run list-fields after any navigation.\n"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the visus-web MCP server over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
