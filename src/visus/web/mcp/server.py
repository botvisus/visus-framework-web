"""visus-web MCP server — comprehensive FastMCP wrapper over the full visus.web API.

Playwright-MCP parity + frames + OCR/vision extras.
Run via: uv run visus-web-mcp   (or python -m visus.web.mcp.server)
"""

from __future__ import annotations

import time

from mcp.server.fastmcp import FastMCP, Image

from visus.web.api.assertions import expect
from visus.web.mcp.session import Session, make_locator
from visus.web.ops.targeting import any_match_visible as _any_match_visible

mcp = FastMCP("visus-web")
_session = Session()


def _acted(message: str) -> str:
    """An action's result plus the page state the agent needs for its next step.

    Without this an agent is blind after every action and must spend a whole extra
    tool call on browser_url/browser_title, or act on a stale mental model.
    """
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
    page = _session.page()
    page.goto(url)
    return f"navigated to {page.url!r} (title: {page.title()!r})"


@mcp.tool()
def browser_navigate_back() -> str:
    """Navigate back in browser history."""
    page = _session.page()
    page.go_back()
    return f"went back → {page.url!r}"


@mcp.tool()
def browser_navigate_forward() -> str:
    """Navigate forward in browser history."""
    page = _session.page()
    page.go_forward()
    return f"went forward → {page.url!r}"


@mcp.tool()
def browser_reload() -> str:
    """Reload the current page."""
    page = _session.page()
    page.reload()
    return f"reloaded {page.url!r}"


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_snapshot() -> list[dict]:  # type: ignore[type-arg]
    """Return the page's interactive elements as a list of {role, name, depth} dicts.

    Use role/name to target action tools without needing CSS selectors. depth is
    how many element levels below <body> the element sits.
    """
    return _session.page().snapshot()


@mcp.tool()
def browser_list_fields(
    kind: str | None = None,
    include_hidden: bool = False,
    highlight: bool = False,
) -> list[dict]:  # type: ignore[type-arg]
    """List all RPA-relevant interactive fields on the current page.

    Enumerates buttons, inputs, textareas, links, selects, checkboxes/radios,
    custom dropdowns, and contenteditable elements — framework-agnostically,
    across open shadow DOM and same-origin iframes. Each returned dict carries a
    ready-to-use locator plus the frame chain and a deep flag so the field can be
    re-resolved for an action (root = page; for sel in frame: root =
    root.frame_locator(sel); target = root.locator(locator, deep=deep)).

    kind is an optional comma-separated filter (e.g. "button,input") restricting
    the result to those kinds; omit it to list every kind. include_hidden also
    returns hidden/disabled fields (flagged). highlight draws the numbered
    overlay on the page (default off; a no-op when headless).
    """
    parsed = [k.strip() for k in kind.split(",") if k.strip()] if kind else None
    fields = _session.page().list_fields(
        kinds=parsed, include_hidden=include_hidden, highlight=highlight
    )
    _session.cache_fields(fields)  # so the action tools can target by `index`
    return [f.to_dict() for f in fields]


@mcp.tool()
def browser_clear_highlights() -> str:
    """Remove the numbered field-highlight overlay drawn by browser_list_fields."""
    _session.page().clear_highlights()
    return "cleared"


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
    return _session.page().title()


@mcp.tool()
def browser_url() -> str:
    """Return the current page URL."""
    return _session.page().url


@mcp.tool()
def browser_get_text(
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str | None:
    """Return the visible text content of an element."""
    page = _session.page()
    loc = make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )
    return loc.first().text_content()  # tolerate multi-match (agent-friendly read)


@mcp.tool()
def browser_get_attribute(
    attr_name: str,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str | None:
    """Return the value of an HTML attribute on an element."""
    page = _session.page()
    loc = make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )
    return loc.first().get_attribute(attr_name)  # tolerate multi-match


@mcp.tool()
def browser_count(
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> int:
    """Return the count of elements matching the given target."""
    page = _session.page()
    loc = make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )
    return loc.count()


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_click(
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Click an element targeted by role+name, text, or css/xpath selector."""
    page = _session.page()
    make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    ).click()
    return _acted("clicked")


@mcp.tool()
def browser_dblclick(
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Double-click an element."""
    page = _session.page()
    make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    ).dblclick()
    return _acted("double-clicked")


@mcp.tool()
def browser_fill(
    text_value: str,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Fill an input/textarea with the given text_value."""
    page = _session.page()
    make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    ).fill(text_value)
    return _acted(f"filled with {text_value!r}")


@mcp.tool()
def browser_press(
    key: str,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Press a key (e.g. 'Enter', 'Tab', 'Control+a') on the focused element."""
    page = _session.page()
    make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    ).press(key)
    return _acted(f"pressed {key!r}")


@mcp.tool()
def browser_hover(
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Hover over an element."""
    page = _session.page()
    make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    ).hover()
    return _acted("hovered")


@mcp.tool()
def browser_check(
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Check a checkbox or radio button."""
    page = _session.page()
    make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    ).check()
    return _acted("checked")


@mcp.tool()
def browser_uncheck(
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Uncheck a checkbox."""
    page = _session.page()
    make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    ).uncheck()
    return _acted("unchecked")


@mcp.tool()
def browser_select_option(
    value: str,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Select an option from a <select> element by value."""
    page = _session.page()
    make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    ).select_option(value=value)
    return _acted(f"selected option {value!r}")


@mcp.tool()
def browser_drag(
    target_selector: str,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Drag the source element to target_selector (a CSS/XPath selector)."""
    page = _session.page()
    src_loc = make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )
    tgt_loc = page.locator(target_selector)
    src_loc.drag_to(tgt_loc)
    return _acted(f"dragged to {target_selector!r}")


@mcp.tool()
def browser_focus(
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Focus an element."""
    page = _session.page()
    make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    ).focus()
    return _acted("focused")


@mcp.tool()
def browser_clear(
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Clear the value of an input field."""
    page = _session.page()
    make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    ).clear()
    return _acted("cleared")


@mcp.tool()
def browser_set_input_files(
    paths: list[str],
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Set file(s) on a file input element. Provide absolute paths."""
    page = _session.page()
    make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    ).set_input_files(paths)
    return _acted(f"set {len(paths)} file(s)")


# ---------------------------------------------------------------------------
# Wait / Expect
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_wait_for(
    state: str = "visible",
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    timeout: int | None = None,
) -> str:
    """Wait for an element to reach a state: 'visible' or 'hidden'."""
    page = _session.page()
    loc = make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )
    ms = 5000 if timeout is None else timeout
    want_visible = state != "hidden"
    deadline = time.monotonic() + ms / 1000.0
    while True:
        if _any_match_visible(loc) == want_visible:
            return f"element is {state}"
        if time.monotonic() >= deadline:
            raise AssertionError(f"wait_for: no element became {state} within {ms}ms")
        time.sleep(0.1)


@mcp.tool()
def browser_expect_text(
    expected_text: str,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
    timeout: int | None = None,
) -> str:
    """Assert that an element contains the expected text. Returns 'PASSED' or 'FAILED: ...'."""
    page = _session.page()
    loc = make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )
    try:
        expect(loc.first()).to_have_text(expected_text, timeout=timeout)
        return "PASSED"
    except AssertionError as exc:
        return f"FAILED: {exc}"


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_tab_list() -> list[dict]:  # type: ignore[type-arg]
    """List all open tabs as [{index, handle, title, url}].

    Reflects every open tab — including ones opened by a link or window.open —
    by reconciling against the live window handles. ``handle`` is a stable id you
    can pass to browser_tab_activate.
    """
    pages = _session.pages()
    result = []
    for i, p in enumerate(pages):
        try:
            title = p.title()
            url = p.url
        except Exception:
            title = ""
            url = ""
        result.append({"index": i, "handle": p.handle, "title": title, "url": url})
    return result


@mcp.tool()
def browser_tab_new(url: str | None = None) -> str:
    """Open a new browser tab, optionally navigating to url. Returns new tab index."""
    p = _session.new_page(url)
    idx = len(_session.pages()) - 1
    return f"opened tab {idx}" + (f" at {p.url!r}" if url else "")


@mcp.tool()
def browser_tab_select(index: int) -> str:
    """Switch to a tab by its 0-based index."""
    p = _session.select(index)
    return f"switched to tab {index} ({p.url!r})"


@mcp.tool()
def browser_tab_activate(handle: str) -> str:
    """Focus a tab by its stable handle (from browser_tab_list). Survives reordering."""
    p = _session.activate(handle)
    return f"activated tab {handle} ({p.url!r})"


@mcp.tool()
def browser_tab_close(index: int | None = None) -> str:
    """Close a tab by index (default: current tab)."""
    idx = index if index is not None else None
    _session.close_tab(idx)
    return f"closed tab {idx if idx is not None else 'current'}"


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
    on = _session.set_follow(enabled)
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
    page = _session.page()
    msg, typ = page._delegate.handle_next_dialog(
        accept=accept,
        prompt_text=prompt_text,
        timeout_ms=5000,
    )
    action = "accepted" if accept else "dismissed"
    return f"{action} {typ!r} dialog: {msg!r}"


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
    page = _session.page()
    out = [
        {"url": r.url, "method": r.method, "status": r.status, "resource_type": r.resource_type}
        for r in page.network_requests()
    ]
    if url_filter:
        out = [r for r in out if url_filter in str(r["url"])]
    return out


@mcp.tool()
def browser_console_messages(level: str = "") -> list[dict]:  # type: ignore[type-arg]
    """List browser console messages captured so far (console.*, uncaught errors).

    Each entry has level (SEVERE/WARNING/INFO) and text. Pass *level* to filter
    (e.g. "SEVERE" for errors only). Chromium engines only. Check this first
    when a page misbehaves with no visible cause.
    """
    page = _session.page()
    out = [{"level": m.level, "text": m.text} for m in page.console_messages()]
    if level:
        out = [m for m in out if m["level"] == level.upper()]
    return out


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_get_cookies() -> list[dict]:  # type: ignore[type-arg]
    """Return all cookies for the current context."""
    return _session.context().cookies()


@mcp.tool()
def browser_add_cookies(cookies: list[dict]) -> str:  # type: ignore[type-arg]
    """Add cookies to the current context. Each cookie must have at least 'name', 'value', 'url'."""
    _session.context().add_cookies(cookies)
    return f"added {len(cookies)} cookie(s)"


@mcp.tool()
def browser_clear_cookies() -> str:
    """Clear all cookies in the current context."""
    _session.context().clear_cookies()
    return "cookies cleared"


# ---------------------------------------------------------------------------
# Media / JavaScript
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_screenshot(
    full_page: bool = False,
    selector: str | None = None,
) -> Image:
    """Take a screenshot of the page or a specific element. Returns a PNG image."""
    page = _session.page()
    if selector is not None:
        data = page.locator(selector).screenshot()
    else:
        data = page.screenshot(full_page=full_page)
    return Image(data=data, format="png")


@mcp.tool()
def browser_evaluate(
    expression: str,
    arg: object = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> object:
    """Evaluate a JavaScript function in the browser and return the result.

    With no target the function runs on the page and is called as
    '(expression)(arg)', e.g. '() => document.title'.

    With a target (selector / role+name / text) it runs on that ELEMENT and is
    called as '(expression)(element, arg)', e.g. '(el) => el.value' — this is
    how you read id/class/dataset or any property list_fields does not return.
    """
    page = _session.page()
    if selector is None and role is None and text is None:
        return page.evaluate(expression, arg)
    loc = make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )
    return loc.first().evaluate(expression, arg)


# ---------------------------------------------------------------------------
# Vision (OCR / image matching)
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_read_text(
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """OCR the screenshot of an element and return the recognized text.

    Requires the [vision] extra (rapidocr-onnxruntime + opencv).
    """
    page = _session.page()
    loc = make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )
    return loc.ocr_text()


@mcp.tool()
def browser_solve_captcha(
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """OCR-solve a text CAPTCHA shown in the targeted element and return the solution."""
    page = _session.page()
    loc = make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )
    return page.solve_captcha(loc)


@mcp.tool()
def browser_find_image(
    template_path: str,
    confidence: float = 0.8,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> dict:  # type: ignore[type-arg]
    """Find a template image inside the screenshot of the targeted element (or full page).

    Returns a dict with {found, x, y, confidence} or {found: False}.
    Requires the [vision] extra.
    """
    import numpy as np
    from PIL import Image as PILImage

    from visus.web.vision import find_image

    page = _session.page()
    if selector is not None or role is not None or text is not None:
        loc = make_locator(
            page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
        )
        screenshot_bytes = loc.screenshot()
    else:
        screenshot_bytes = page.screenshot()

    import io

    source_img = np.array(PILImage.open(io.BytesIO(screenshot_bytes)).convert("RGB"))
    template_img = np.array(PILImage.open(template_path).convert("RGB"))

    match = find_image(source_img, template_img, confidence=confidence)
    if match is None:
        return {"found": False}
    return {"found": True, "x": match.x, "y": match.y, "confidence": match.confidence}


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_close() -> str:
    """Close the browser and reset the session."""
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
