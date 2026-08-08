"""Persistent CLI session server (daemon).

A :class:`SessionHandler` holds a live ``Browser``/``Context``/``Page`` and maps
JSON ops to page operations. The handler is **fully unit-testable without
sockets** -- :meth:`SessionHandler.handle` takes ``(op, args)`` and returns a
plain dict.

A thin JSON-lines TCP server (bound to ``127.0.0.1`` on an ephemeral port) wraps
the handler: one JSON request per line in, one JSON response line out. Every
request must carry the session ``token``. :func:`main` is the detached-process
entrypoint: it reads engine/headless/url from argv/env, writes
``.visus/session.json`` and serves until a ``shutdown`` op arrives.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import secrets
import socket
import sys
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, cast

from visus.web import Engine, errors, launch
from visus.web.api.assertions import expect
from visus.web.api.browser import Browser
from visus.web.api.context import Context
from visus.web.api.fields import Field
from visus.web.api.locator import Locator
from visus.web.api.page import Page
from visus.web.backends.selenium.driver_delegate import SeleniumPageDelegate
from visus.web.cli import session_client
from visus.web.cli.codegen import generate_line


def _any_match_visible(loc: Locator) -> bool:
    """True if at least one element the locator matches is visible.

    Local copy of the MCP helper: tolerant of mid-navigation errors (treated as
    "not yet visible") and of locators that match several elements.
    """
    try:
        return any(loc.nth(i).is_visible() for i in range(loc.count()))
    except errors.VisusWebError:
        return False


def make_locator(
    page: Page,
    *,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> Locator:
    """Resolve a locator from the given target params.

    Local copy of the MCP helper (the cli must not import the ``mcp`` package, as
    the ``mcp`` extra may be absent).
    """
    root: Any = page if frame is None else page.frame_locator(frame)
    if role is not None:
        return cast(Locator, root.get_by_role(role, name=name, exact=exact))
    if text is not None:
        return cast(Locator, root.get_by_text(text, exact=exact))
    if selector is not None:
        return cast(Locator, root.locator(selector))
    raise ValueError("provide one of: index, role, text, selector")


class StaleFieldIndexError(RuntimeError):
    """Raised when a cached field index no longer belongs to the current page.

    Index targeting re-resolves a stored selector against whatever page is loaded
    now. Generated selectors intentionally fall back to generic forms
    (``button.btn.primary``, ``input[type="email"]``, a bare tag), each of which
    matches *something* on a different page — so without this guard a stale index
    clicks the wrong element and reports success.
    """


# Ops that change what the agent is looking at. Only these get a `page` footer;
# reads stay bare so piping (`visus --raw get-text 3`) is never polluted.
#
# This set is a cross-plan tripwire: PLANS 5, 6 and 7 each add new mutating ops
# and are REQUIRED to add their names here too. test_mutating_ops_cover_every_state_changing_op
# in tests/test_cli_session.py asserts this set by exact equality, so forgetting
# to update it turns that test red at the offending plan's own commit gate —
# that failure is the whole point of the test, not a bug in it.
_MUTATING_OPS: frozenset[str] = frozenset(
    {
        "click", "dblclick", "fill", "check", "uncheck", "select", "press",
        "hover", "focus", "clear_input", "drag", "upload", "goto", "back",
        "forward", "reload", "tab", "tab_new", "tab_close", "dialog",
        "add_cookies", "clear_cookies", "eval",
    }
)

# op -> (codegen action, the args key holding its value)
_CODE_ACTIONS: dict[str, tuple[str, str | None]] = {
    "click": ("click", None),
    "dblclick": ("dblclick", None),
    "check": ("check", None),
    "uncheck": ("uncheck", None),
    "hover": ("hover", None),
    "focus": ("focus", None),
    "clear_input": ("clear", None),
    "fill": ("fill", "text"),
    "press": ("press", "key"),
    "select": ("select_option", "value"),
    "upload": ("set_input_files", "paths"),
}


def generate_script_goto(url: str) -> str:
    """The generated line for a navigation."""
    return f"page.goto({url!r})"


class SessionHandler:
    """Holds a live browser/context/page and dispatches ops to page operations.

    Modeled on ``mcp/session.py``'s :class:`Session`: lazy ``_ensure`` reads the
    engine/headless from ctor args (falling back to env
    ``VISUS_WEB_ENGINE`` / ``VISUS_WEB_HEADLESS``). The last ``list_fields``
    result is cached so index-based ops re-resolve the stored field via the
    foundation contract (frame chain + ``deep``).
    """

    def __init__(
        self,
        *,
        engine: str | None = None,
        headless: bool | None = None,
        url: str | None = None,
    ) -> None:
        self._engine = engine or os.environ.get("VISUS_WEB_ENGINE", "chrome")
        if headless is None:
            headless = os.environ.get("VISUS_WEB_HEADLESS", "0") != "0"
        self._headless = headless
        self._url = url
        self._browser: Browser | None = None
        self._context: Context | None = None
        self._page: Page | None = None
        self._fields: list[Field] = []
        self._fields_url: str | None = None
        self._script: list[str] = []
        self._known_handles: list[str] = []
        self._active_handle: str | None = None
        self._stop: threading.Event | None = None
        # One WebDriver, one thread per connection in serve(): every op body runs
        # under this mutex. RLock (not Lock) so an op may re-enter handle().
        self._lock = threading.RLock()
        self._last_op_at = time.monotonic()

    def bind_stop(self, stop: threading.Event) -> None:
        """Give the handler the server's stop event so an op can end the daemon.

        Closing the LAST tab has to actually stop the daemon: ``close()`` alone
        leaves the socket bound and ``session.json`` on disk, and the next op
        would silently launch a brand-new browser at the original URL — losing
        whatever session state (logins, cookies in memory) the user built up.
        """
        self._stop = stop

    def last_op_at(self) -> float:
        """``time.monotonic()`` of the most recently dispatched op (idle reaper).

        Read WITHOUT taking ``self._lock``: the reaper runs on the accept thread
        and must not queue behind an in-flight ``wait``. A float assignment is
        atomic, and a one-tick-stale read only postpones reaping by 0.5 s.
        """
        return self._last_op_at

    # --- lifecycle -------------------------------------------------------
    def _ensure(self) -> None:
        if self._browser is None:
            self._browser = launch(Engine.from_str(self._engine), headless=self._headless)
            # Failure-atomic: if any step after launch raises (bad URL, etc.),
            # tear the partial browser down so the next op retries from scratch
            # instead of wedging on a non-None browser with a None page.
            try:
                # new_page() reuses the browser's DEFAULT context. Calling
                # new_context() here would spawn a SECOND WebDriver/browser window
                # (the daemon is headed) — that was the "2 browsers" bug.
                self._page = self._browser.new_page()
                if self._url:
                    self._page.goto(self._url)
                    # Record it by hand: this navigation does NOT go through
                    # handle(), so the codegen recorder never sees it. Without
                    # this line `session export-script` emits a script that
                    # starts on a blank page, and every locator in it misses.
                    self._script.append(generate_script_goto(self._url))
            except Exception:
                self.close()
                raise

    def page(self) -> Page:
        """The page to operate on — the active window/tab.

        Auto-follows a newly-opened tab/popup window, otherwise stays on the
        last-active one (switch explicitly with the ``tab`` op). A modal/dialog is
        part of the same document, so it is already covered by the active page.
        """
        return self._active_page()

    def _driver(self) -> Any:
        return getattr(getattr(self._page, "_delegate", None), "_driver", None)

    def _active_page(self) -> Page:
        self._ensure()
        if self._page is None:
            raise RuntimeError("session page is not available")
        driver = self._driver()
        if driver is None:
            return self._page  # non-selenium page (tests) — no tab tracking
        try:
            handles = list(driver.window_handles)
        except Exception:  # noqa: BLE001
            return self._page
        if not handles:
            return self._page
        handle = self._resolve_active(handles)
        if getattr(self._page._delegate, "_handle", None) == handle:
            return self._page
        return Page(SeleniumPageDelegate(driver, handle), self._page._defaults)

    def _resolve_active(self, handles: list[str]) -> str:
        """Pick the active handle: auto-follow a newly-opened tab/window, else stay
        on the last-active one (sticky), else the newest. The ``tab`` op overrides."""
        new = [h for h in handles if h not in self._known_handles]
        self._known_handles = list(handles)
        if new:
            self._active_handle = new[-1]  # follow the newest new tab/popup
        if self._active_handle not in handles:
            self._active_handle = handles[-1]
        return self._active_handle

    def _peek_active(self, handles: list[str]) -> str:
        """The active handle WITHOUT adopting new windows or mutating state.

        ``status``/``tabs`` are observations: polling them must never change where
        the next click lands. ``_resolve_active`` auto-follows a new window on
        purpose — that belongs to the ACTION path only.
        """
        active = self._active_handle
        if active is not None and active in handles:
            return active
        return handles[-1]

    def _peek_page(self) -> Page:
        """The active page WITHOUT auto-following newly-opened windows."""
        self._ensure()
        if self._page is None:
            raise RuntimeError("session page is not available")
        driver = self._driver()
        if driver is None:
            return self._page  # non-selenium page (tests) — no tab tracking
        try:
            handles = list(driver.window_handles)
        except Exception:  # noqa: BLE001
            return self._page
        if not handles:
            return self._page
        handle = self._peek_active(handles)
        if getattr(self._page._delegate, "_handle", None) == handle:
            return self._page
        return Page(SeleniumPageDelegate(driver, handle), self._page._defaults)

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        self._browser = None
        self._context = None
        self._page = None
        self._invalidate_fields()

    def _invalidate_fields(self) -> None:
        """Drop the cached field list and its page stamp — index targeting is void."""
        self._fields = []
        self._fields_url = None

    def fields_stale(self) -> bool:
        """True when cached field indexes no longer address the current page.

        The single source of truth for staleness: never raises, so a status/footer
        caller can read it unconditionally.
        """
        if self._browser is None or not self._fields or self._fields_url is None:
            return True
        try:
            return self.page().url != self._fields_url
        except Exception:  # noqa: BLE001 — an unreadable page is a stale page
            return True

    def context(self) -> Context:
        """The browser context (shared with the active page) — cookies live here.

        Cookies are a CONTEXT concern, not a page one (mirrors the MCP server).
        The daemon's pages all share the launch driver's default context, so the
        first context is the right one for cookie reads/writes.
        """
        self._ensure()
        assert self._browser is not None
        contexts = self._browser.contexts
        if not contexts:
            raise RuntimeError("no browser context available")
        return contexts[0]

    # --- targeting -------------------------------------------------------
    def _resolve_field(self, index: int) -> Locator:
        """Re-resolve a cached field for an action via the foundation contract."""
        if index < 0 or index >= len(self._fields):
            raise IndexError(
                f"field index {index} out of range "
                f"(have {len(self._fields)}; run list_fields first)"
            )
        if self._fields_url is not None:
            current = self.page().url
            if current != self._fields_url:
                raise StaleFieldIndexError(
                    f"field indexes were captured on {self._fields_url}, "
                    f"page is now {current} — run list-fields again"
                )
        field = self._fields[index]
        root: Any = self.page()
        for sel in field.frame:
            root = root.frame_locator(sel)
        return cast(Locator, root.locator(field.locator, deep=field.deep))

    @staticmethod
    def _has_target(args: dict[str, Any]) -> bool:
        """True if args carry an explicit target (index/selector/role/target_text)."""
        if args.get("index") is not None:
            return True
        return any(args.get(k) is not None for k in ("selector", "role", "target_text"))

    def _target(self, args: dict[str, Any]) -> Locator:
        """Resolve the action target: cached index OR a make_locator target.

        Note the locator-text target is read from ``target_text`` (not ``text``)
        so it never collides with ``fill``'s ``text`` *value* payload.
        """
        if "index" in args and args["index"] is not None:
            return self._resolve_field(int(args["index"]))
        return make_locator(
            self.page(),
            selector=args.get("selector"),
            role=args.get("role"),
            name=args.get("name"),
            text=args.get("target_text"),
            exact=bool(args.get("exact", False)),
            frame=args.get("frame"),
        )

    def _field_code(self, index: int) -> str | None:
        """The cached field's ready-to-paste, frame-aware visus.web expression.

        ``_resolve_field`` returns a Locator (its signature is fixed); this is the
        sibling accessor for the same field's ``code``.
        """
        if index < 0 or index >= len(self._fields):
            return None
        return self._fields[index].code or None

    def _target_event(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """The codegen ``target`` for an action's args, or None when unknowable."""
        if args.get("index") is not None:
            code = self._field_code(int(args["index"]))
            return None if code is None else {"kind": "code", "expr": code}
        if args.get("role"):
            return {"kind": "role", "role": args["role"], "name": args.get("name") or ""}
        if args.get("target_text"):
            return {"kind": "text", "value": args["target_text"]}
        if args.get("selector"):
            return {"kind": "css", "value": args["selector"]}
        return None

    def _generated_code(self, op: str, args: dict[str, Any]) -> str | None:
        """The visus.web line equivalent to this op, or None when it has none.

        Computed BEFORE the op runs, so an index target resolves against the cache
        the caller actually addressed. Never raises: a codegen failure must not
        turn a successful action into an error.
        """
        try:
            if op == "goto":
                return generate_script_goto(str(args.get("url", "")))
            entry = _CODE_ACTIONS.get(op)
            if entry is None:
                return None
            action, value_key = entry
            target = self._target_event(args)
            if target is None:
                return None
            event: dict[str, Any] = {"action": action, "target": target}
            if value_key is not None:
                event["value"] = args.get(value_key, "")
            return generate_line(event)
        except Exception:  # noqa: BLE001 — codegen is a convenience, never a failure
            return None

    # --- ops -------------------------------------------------------------
    def _post_state(self) -> dict[str, Any]:
        """Page state AFTER a mutating op: ``{url, title, fields_stale}``.

        Best-effort telemetry — it must never turn a successful action into a
        failed response, so every failure collapses to ``{}``.

        Staleness is NOT re-derived here: ``fields_stale()`` (PLAN 3) is the single
        definition, and it also treats an unreadable page as stale. It reports True
        when there is no cache at all, so the guard is ``bool(self._fields) and …``
        — an agent that never ran ``list-fields`` must not be warned that its
        non-existent indexes went stale.
        """
        try:
            page = self.page()
            stale = bool(self._fields) and self.fields_stale()
            return {"url": page.url, "title": page.title(), "fields_stale": stale}
        except Exception:  # noqa: BLE001 — page state is telemetry, not the result
            return {}

    def _snapshot_refs(self, rows: list[dict[str, Any]]) -> list[int | None]:
        """Map each snapshot row to a ``list_fields`` index — ONE numbering.

        Both enumerations come from the same bundle helpers (``computeRole`` and
        ``accessibleName``), so ``(role, name)`` identifies a row that is also an
        actionable field. Rows with no actionable twin (headings, options) get None.
        """
        by_key: dict[tuple[str, str], int] = {}
        for f in self._fields:
            by_key.setdefault(((f.role or ""), (f.name or "")), f.index)
        return [by_key.get(((r.get("role") or ""), (r.get("name") or ""))) for r in rows]

    def _write_snapshot(self) -> str | None:
        """Write the current snapshot under ``.visus/snapshots/`` and return its path.

        The daemon owns ``.visus/`` (see :func:`session_file`), and its cwd is the
        directory ``visus session start`` ran in, so the returned path is relative
        to the project root. Never raises.
        """
        try:
            page = self.page()
            rows = page.snapshot()
            refs = self._snapshot_refs(rows)
            elements = [{**row, "ref": refs[i]} for i, row in enumerate(rows)]
            text = render_snapshot_yaml(elements, url=page.url, title=page.title())
            base = Path.cwd() / ".visus" / "snapshots"
            base.mkdir(parents=True, exist_ok=True)
            stamp = _dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3]
            path = base / f"page-{stamp}.yml"
            path.write_text(text, encoding="utf-8")
            try:
                return str(path.relative_to(Path.cwd()))
            except ValueError:
                return str(path)
        except Exception:  # noqa: BLE001 — the sink is a convenience, never a failure
            return None

    def handle(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Dispatch one op.

        Returns ``{ok:True, result:...}`` plus, for a mutating op, the ``page``
        state the agent needs to choose its next command — the perception half of
        the perception-action loop. Failures return ``{ok:False, error:str}``.

        The whole body runs under ``self._lock``: ``serve()`` runs one thread per
        connection over a SHARED handler, and a WebDriver plus the tab bookkeeping
        in ``_known_handles``/``_active_handle`` are not safe to interleave.
        """
        args = args or {}
        with self._lock:
            self._last_op_at = time.monotonic()
            try:
                method = getattr(self, f"_op_{op}", None)
                if method is None:
                    raise ValueError(f"unknown op {op!r}")
                # Computed BEFORE method(args) runs: an index target must resolve
                # against the cache the caller actually addressed, not the one the
                # op is about to replace (list_fields, snapshot) or invalidate (goto).
                code = self._generated_code(op, args)
                resp: dict[str, Any] = {"ok": True, "result": method(args)}
            except Exception as exc:  # noqa: BLE001 — daemon must never crash a client
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            if op in _MUTATING_OPS:
                resp["page"] = self._post_state()
                if args.get("snapshot"):
                    resp["snapshot"] = self._write_snapshot()
            if code:
                resp["code"] = code
                self._script.append(code)
            return resp

    def _op_list_fields(self, args: dict[str, Any]) -> dict[str, Any]:
        kinds = args.get("kinds")
        include_hidden = bool(args.get("include_hidden", False))
        highlight = bool(args.get("highlight", True))
        page = self.page()
        fields = page.list_fields(
            kinds=kinds, include_hidden=include_hidden, highlight=highlight
        )
        self._fields = list(fields)
        # Stamp the page identity so a later index op can tell the page moved.
        self._fields_url = page.url
        return {"fields": [f.to_dict() for f in fields]}

    def _op_click(self, args: dict[str, Any]) -> str:
        self._target(args).click()
        return "clicked"

    def _op_fill(self, args: dict[str, Any]) -> str:
        text = args.get("text", "")
        self._target(args).fill(text)
        return f"filled with {text!r}"

    def _op_check(self, args: dict[str, Any]) -> str:
        self._target(args).check()
        return "checked"

    def _op_uncheck(self, args: dict[str, Any]) -> str:
        self._target(args).uncheck()
        return "unchecked"

    def _op_select(self, args: dict[str, Any]) -> str:
        value = args.get("value")
        self._target(args).select_option(value=value)
        return f"selected {value!r}"

    def _op_press(self, args: dict[str, Any]) -> str:
        key = args.get("key", "")
        self._target(args).press(key)
        return f"pressed {key!r}"

    def _op_get_text(self, args: dict[str, Any]) -> dict[str, Any]:
        """Text content of the target, keeping "absent" distinct from "empty".

        ``typer.echo(None)`` and ``typer.echo("")`` print an identical blank line,
        so the two cases have to be separated here, in the payload.
        """
        value = self._target(args).first().text_content()
        return {"value": value, "present": value is not None}

    def _op_goto(self, args: dict[str, Any]) -> str:
        url = args["url"]
        page = self.page()
        page.goto(url)
        self._invalidate_fields()  # cached indexes belonged to the previous page
        return page.url

    def _op_screenshot(self, args: dict[str, Any]) -> str:
        """Screenshot the page (optionally full-page) or a single element.

        Mirrors ``browser_screenshot`` in the MCP server: when a target
        (index/selector/role/target_text) is given, screenshot that element via
        ``Locator.screenshot``; otherwise screenshot the page, honouring
        ``full_page``.
        """
        path = args.get("path") or "screenshot.png"
        if self._has_target(args):
            self._target(args).screenshot(path=path)
        else:
            self.page().screenshot(path=path, full_page=bool(args.get("full_page")))
        return str(Path(path).resolve())

    def _op_clear_highlights(self, args: dict[str, Any]) -> str:
        self.page().clear_highlights()
        return "cleared"

    # --- navigation ------------------------------------------------------
    def _op_back(self, args: dict[str, Any]) -> str:
        page = self.page()
        page.go_back()
        self._invalidate_fields()  # cached indexes belonged to the previous page
        return page.url

    def _op_forward(self, args: dict[str, Any]) -> str:
        page = self.page()
        page.go_forward()
        self._invalidate_fields()  # cached indexes belonged to the previous page
        return page.url

    def _op_reload(self, args: dict[str, Any]) -> str:
        page = self.page()
        page.reload()
        self._invalidate_fields()  # a reload rebuilds the DOM from scratch
        return page.url

    # --- inspect ---------------------------------------------------------
    def _op_title(self, args: dict[str, Any]) -> str:
        return self.page().title()

    def _op_url(self, args: dict[str, Any]) -> str:
        return self.page().url

    def _op_snapshot(self, args: dict[str, Any]) -> dict[str, Any]:
        """The page's interactive elements, numbered with list_fields indexes.

        ``refs`` (default on) re-enumerates the page so every row's ``ref`` is a
        live index an action can use immediately — this is what makes ``snapshot``
        addressable instead of a second, incompatible numbering. Pass
        ``refs=False`` for a pure read that leaves the field cache untouched.
        """
        page = self.page()
        depth = args.get("depth")
        rows = page.snapshot(args.get("selector"), depth=None if depth is None else int(depth))
        if args.get("refs", True):
            fields = page.list_fields(kinds=None, include_hidden=False, highlight=False)
            self._fields = list(fields)
            self._fields_url = page.url
        refs = self._snapshot_refs(rows)
        elements = [{**row, "ref": refs[i]} for i, row in enumerate(rows)]
        return {"elements": elements, "url": page.url, "title": page.title()}

    def _op_find(self, args: dict[str, Any]) -> dict[str, Any]:
        """Grep the page snapshot instead of printing all of it.

        Each row is matched as ``"<role> <name>"``. Substring matching is
        case-insensitive; ``regex`` switches to a Python regular expression.
        ``context`` rows around each hit are returned too, like ``grep -C``.
        """
        query = str(args.get("query") or "")
        use_regex = bool(args.get("regex", False))
        context = max(0, int(args.get("context") or 0))
        page = self.page()
        depth = args.get("depth")
        rows = page.snapshot(args.get("selector"), depth=None if depth is None else int(depth))

        def _line(row: dict[str, Any]) -> str:
            return f"{row.get('role') or ''} {row.get('name') or ''}"

        if use_regex:
            pattern = re.compile(query)
            hits = [i for i, row in enumerate(rows) if pattern.search(_line(row))]
        else:
            needle = query.casefold()
            hits = [i for i, row in enumerate(rows) if needle in _line(row).casefold()]

        hit_set = set(hits)
        keep: set[int] = set()
        for i in hits:
            keep.update(range(max(0, i - context), min(len(rows), i + context + 1)))
        refs = self._snapshot_refs(rows)
        out: list[dict[str, Any]] = []
        for i in sorted(keep):
            out.append({**rows[i], "line": i, "ref": refs[i], "match": i in hit_set})
        return {
            "query": query,
            "regex": use_regex,
            "total": len(rows),
            "matched": len(hits),
            "rows": out,
        }

    def _op_get_attribute(self, args: dict[str, Any]) -> dict[str, Any]:
        """Attribute value of the target, keeping "absent" distinct from ``""``."""
        name = args.get("attr_name", "")
        value = self._target(args).first().get_attribute(name)
        return {"value": value, "present": value is not None}

    def _op_count(self, args: dict[str, Any]) -> int:
        return self._target(args).count()

    # --- actions ---------------------------------------------------------
    def _op_hover(self, args: dict[str, Any]) -> str:
        self._target(args).hover()
        return "hovered"

    def _op_dblclick(self, args: dict[str, Any]) -> str:
        self._target(args).dblclick()
        return "double-clicked"

    def _op_focus(self, args: dict[str, Any]) -> str:
        self._target(args).focus()
        return "focused"

    def _op_clear_input(self, args: dict[str, Any]) -> str:
        """Clear an input's value (mirrors browser_clear; distinct from clear_highlights)."""
        self._target(args).clear()
        return "cleared"

    def _op_drag(self, args: dict[str, Any]) -> str:
        src = self._target(args)
        target_selector = args.get("target_selector")
        if target_selector is not None:
            tgt = self.page().locator(target_selector)
        elif args.get("target_index") is not None:
            tgt = self._resolve_field(int(args["target_index"]))
        else:
            raise ValueError("provide a drag target: target_selector or target_index")
        src.drag_to(tgt)
        if target_selector is not None:
            return f"dragged to {target_selector!r}"
        return f"dragged to field {args['target_index']}"

    def _op_upload(self, args: dict[str, Any]) -> str:
        paths = args.get("paths") or []
        self._target(args).set_input_files(paths)
        return f"set {len(paths)} file(s)"

    # --- wait / expect ---------------------------------------------------
    def _op_wait(self, args: dict[str, Any]) -> str:
        state = args.get("state") or "visible"
        loc = self._target(args)
        timeout = args.get("timeout")
        ms = 5000 if timeout is None else int(timeout)
        want_visible = state != "hidden"
        deadline = time.monotonic() + ms / 1000.0
        while True:
            if _any_match_visible(loc) == want_visible:
                return f"element is {state}"
            if time.monotonic() >= deadline:
                raise AssertionError(f"wait: no element became {state} within {ms}ms")
            time.sleep(0.1)

    def _op_expect_text(self, args: dict[str, Any]) -> str:
        expected = args.get("expected_text", "")
        loc = self._target(args)
        timeout = args.get("timeout")
        try:
            expect(loc.first()).to_have_text(
                expected, timeout=int(timeout) if timeout is not None else None
            )
            return "PASSED"
        except AssertionError as exc:
            return f"FAILED: {exc}"

    # --- new tab / close tab --------------------------------------------
    def _op_tab_new(self, args: dict[str, Any]) -> dict[str, Any]:
        """Open a new tab/window, register it, and make it the active handle."""
        self._ensure()
        driver = self._driver()
        if driver is None:
            raise RuntimeError("no live browser")
        before = list(driver.window_handles)
        driver.switch_to.new_window("tab")
        handles = list(driver.window_handles)
        new = [h for h in handles if h not in before]
        self._known_handles = handles
        self._active_handle = new[-1] if new else handles[-1]
        self._invalidate_fields()
        url = args.get("url")
        if url:
            driver.switch_to.window(self._active_handle)
            self.page().goto(url)
        idx = handles.index(self._active_handle)
        try:
            driver.switch_to.window(self._active_handle)
            title = driver.title
        except Exception:  # noqa: BLE001
            title = ""
        return {"index": idx, "title": title}

    def _op_tab_close(self, args: dict[str, Any]) -> dict[str, Any]:
        """Close a tab by index (default: the active one), resetting the active handle.

        Closing the last tab ends the whole session: the browser is gone, so the
        daemon stops rather than pretending it can still serve.
        """
        self._ensure()
        driver = self._driver()
        if driver is None:
            raise RuntimeError("no live browser")
        handles = list(driver.window_handles)
        idx = args.get("index")
        if idx is None:
            target = self._active_handle if self._active_handle in handles else handles[-1]
            i = handles.index(target)
        else:
            i = int(idx)
            if i < 0 or i >= len(handles):
                raise IndexError(f"tab index {i} out of range (have {len(handles)} tabs)")
            target = handles[i]
        driver.switch_to.window(target)
        driver.close()
        try:
            remaining = list(driver.window_handles)
        except Exception:  # noqa: BLE001 — the driver is gone once the last window closes
            remaining = []
        self._known_handles = remaining
        self._invalidate_fields()
        if not remaining:
            self.close()
            stopped = self._stop is not None
            if self._stop is not None:
                self._stop.set()
            return {"closed": i, "remaining": 0, "session_stopped": stopped}
        self._active_handle = remaining[min(i, len(remaining) - 1)]
        try:
            driver.switch_to.window(self._active_handle)
        except Exception:  # noqa: BLE001
            pass
        return {
            "closed": i,
            "remaining": len(remaining),
            "active": remaining.index(self._active_handle),
        }

    # --- dialogs ---------------------------------------------------------
    def _op_dialog(self, args: dict[str, Any]) -> str:
        """Handle the next pending dialog (mirrors browser_handle_dialog exactly)."""
        accept = bool(args.get("accept", True))
        prompt_text = args.get("prompt_text")
        page = self.page()
        msg, typ = page._delegate.handle_next_dialog(
            accept=accept,
            prompt_text=prompt_text,
            timeout_ms=5000,
        )
        action = "accepted" if accept else "dismissed"
        return f"{action} {typ!r} dialog: {msg!r}"

    # --- cookies (context-level) -----------------------------------------
    def _op_cookies(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"cookies": self.context().cookies()}

    def _op_add_cookies(self, args: dict[str, Any]) -> str:
        cookies = args.get("cookies") or []
        self.context().add_cookies(cookies)
        return f"added {len(cookies)} cookie(s)"

    def _op_clear_cookies(self, args: dict[str, Any]) -> str:
        self.context().clear_cookies()
        return "cookies cleared"

    # --- javascript ------------------------------------------------------
    def _op_eval(self, args: dict[str, Any]) -> dict[str, Any]:
        expression = args.get("expression", "")
        arg = args.get("arg")
        return {"result": self.page().evaluate(expression, arg)}

    # --- devtools: console / network -------------------------------------
    def _op_console_messages(self, args: dict[str, Any]) -> dict[str, Any]:
        """Browser console messages captured so far (mirrors browser_console_messages).

        ``level`` filters case-insensitively on the WebDriver level
        (SEVERE / WARNING / INFO). Chromium engines only.
        """
        level = str(args.get("level") or "")
        out = [{"level": m.level, "text": m.text} for m in self.page().console_messages()]
        if level:
            out = [m for m in out if m["level"] == level.upper()]
        return {"messages": out}

    # --- vision (requires the [vision] extra) ----------------------------
    def _op_read_text(self, args: dict[str, Any]) -> str:
        return self._target(args).ocr_text()

    def _op_solve_captcha(self, args: dict[str, Any]) -> str:
        loc = self._target(args)
        return self.page().solve_captcha(loc)

    def _op_find_image(self, args: dict[str, Any]) -> dict[str, Any]:
        import io

        import numpy as np
        from PIL import Image as PILImage

        from visus.web.vision import find_image

        template_path = args.get("template_path", "")
        confidence = float(args.get("confidence", 0.8))
        page = self.page()
        if args.get("selector") or args.get("role") or args.get("target_text") or (
            args.get("index") is not None
        ):
            screenshot_bytes = self._target(args).screenshot()
        else:
            screenshot_bytes = page.screenshot()
        source_img = np.array(PILImage.open(io.BytesIO(screenshot_bytes)).convert("RGB"))
        template_img = np.array(PILImage.open(template_path).convert("RGB"))
        match = find_image(source_img, template_img, confidence=confidence)
        if match is None:
            return {"found": False}
        return {"found": True, "x": match.x, "y": match.y, "confidence": match.confidence}

    def _op_tabs(self, args: dict[str, Any]) -> dict[str, Any]:
        """List every open tab/window with its title/url and the active marker.

        READ-ONLY: uses ``_peek_active``, never ``_resolve_active`` — listing tabs
        must not silently adopt a background popup as the active one.
        """
        self._ensure()
        driver = self._driver()
        if driver is None:
            return {"tabs": [], "active": None}
        handles = list(driver.window_handles)
        active = self._peek_active(handles)
        tabs: list[dict[str, Any]] = []
        for i, h in enumerate(handles):
            try:
                driver.switch_to.window(h)
                title, url = driver.title, driver.current_url
            except Exception:  # noqa: BLE001
                title, url = "", ""
            tabs.append(
                {"index": i, "handle": h, "title": title, "url": url, "active": h == active}
            )
        try:
            driver.switch_to.window(active)  # restore the active tab
        except Exception:  # noqa: BLE001
            pass
        return {"tabs": tabs, "active": handles.index(active) if active in handles else None}

    def _op_tab(self, args: dict[str, Any]) -> dict[str, Any]:
        """Switch the active tab/window by index (omit/None → jump to the newest)."""
        self._ensure()
        driver = self._driver()
        if driver is None:
            raise RuntimeError("no live browser")
        handles = list(driver.window_handles)
        self._known_handles = list(handles)
        idx = args.get("index")
        if idx is None:
            self._active_handle = handles[-1]
        else:
            i = int(idx)
            if i < 0 or i >= len(handles):
                raise IndexError(f"tab index {i} out of range (have {len(handles)} tabs)")
            self._active_handle = handles[i]
        self._invalidate_fields()  # cached indexes belonged to the previous tab
        try:
            driver.switch_to.window(self._active_handle)
            title = driver.title
        except Exception:  # noqa: BLE001
            title = ""
        return {"active": handles.index(self._active_handle), "title": title}

    def _op_status(self, args: dict[str, Any]) -> dict[str, Any]:
        """Report session state. READ-ONLY: never adopts a background window."""
        running = self._browser is not None
        info: dict[str, Any] = {
            "running": running,
            "engine": self._engine,
            "headless": self._headless,
            "fields_cached": len(self._fields),
        }
        if running:
            try:
                p = self._peek_page()
                info["url"] = p.url
                info["title"] = p.title()
                driver = self._driver()
                handles = (
                    list(driver.window_handles)
                    if driver is not None
                    else list(self._known_handles)
                )
                info["windows"] = len(handles)
                active = self._peek_active(handles) if handles else None
                if active is not None and active in handles:
                    info["active_tab"] = handles.index(active)
            except Exception:  # noqa: BLE001
                pass
        return info

    def _op_export_script(self, args: dict[str, Any]) -> dict[str, Any]:
        """Everything this session did, as a runnable visus.web script.

        The daemon has been the recorder since the first action: each op's
        generated line was appended to ``_script`` by :meth:`handle`.
        """
        body = list(self._script)
        lines = [
            "from visus.web import launch",
            "",
            "with launch(headless=False) as browser:",
            "    page = browser.new_page()",
        ]
        lines.extend("    " + line for line in body)
        if not body:
            lines.append("    pass  # no recorded actions yet")
        return {"script": "\n".join(lines) + "\n", "lines": len(body)}

    def _op_shutdown(self, args: dict[str, Any]) -> str:
        self.close()
        return "shutdown"


# ---------------------------------------------------------------------------
# Session file helpers
# ---------------------------------------------------------------------------


def _yaml_scalar(value: object) -> str:
    """Render one scalar as YAML. Strings are always quoted — names contain colons."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def render_snapshot_yaml(elements: list[dict[str, Any]], *, url: str, title: str) -> str:
    """Render a page snapshot as the YAML written to ``.visus/snapshots/``."""
    out = [
        "# visus page snapshot",
        f"url: {_yaml_scalar(url)}",
        f"title: {_yaml_scalar(title)}",
        f"count: {len(elements)}",
        "elements:",
    ]
    for e in elements:
        out.append(f"  - ref: {_yaml_scalar(e.get('ref'))}")
        out.append(f"    role: {_yaml_scalar(e.get('role') or '')}")
        out.append(f"    name: {_yaml_scalar(e.get('name') or '')}")
        if e.get("depth") is not None:
            out.append(f"    depth: {_yaml_scalar(e.get('depth'))}")
    return "\n".join(out) + "\n"


def session_file(cwd: str | Path | None = None) -> Path:
    """Path to ``.visus/session.json`` under *cwd* (default: process cwd)."""
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".visus" / "session.json"


# ---------------------------------------------------------------------------
# JSON-lines TCP server
# ---------------------------------------------------------------------------


def _handle_conn(
    conn: socket.socket, handler: SessionHandler, token: str, stop: threading.Event
) -> None:
    with conn:
        f = conn.makefile("rwb")

        def _reply(resp: dict[str, Any]) -> None:
            f.write((json.dumps(resp) + "\n").encode("utf-8"))
            f.flush()

        for raw in f:
            line = raw.decode("utf-8").strip()
            if not line:
                continue
            # Wrap the whole per-line body so a malformed/odd request can never
            # silently kill this handler thread without writing a response.
            try:
                try:
                    req = json.loads(line)
                except json.JSONDecodeError as exc:
                    _reply({"ok": False, "error": f"bad json: {exc}"})
                    continue
                if not isinstance(req, dict):
                    _reply({"ok": False, "error": "bad request: expected a JSON object"})
                    continue
                tok = req.get("token")
                # Constant-time and type-safe: compare_digest raises TypeError on
                # a non-str/bytes argument, and a malicious client controls this
                # value entirely.
                if not isinstance(tok, str) or not secrets.compare_digest(
                    tok.encode("utf-8"), token.encode("utf-8")
                ):
                    _reply({"ok": False, "error": "unauthorized: bad token"})
                    continue
                op = req.get("op", "")
                resp = handler.handle(op, req.get("args") or {})
                _reply(resp)
                if op == "shutdown" and resp.get("ok"):
                    stop.set()
                    return
            except Exception as exc:  # noqa: BLE001 — never crash the handler thread
                _reply({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


class SessionLockedError(RuntimeError):
    """Raised when another daemon already holds the session lock."""


def _write_private(path: Path, text: str) -> None:
    """Create *path* exclusively with owner-only permissions and write *text*.

    The session file carries the daemon's shared secret, and that token authorises
    ``eval``, screenshot writes to an arbitrary path and file upload — so it must
    not be world-readable. ``O_EXCL`` additionally refuses to write THROUGH a file
    somebody else planted. POSIX enforces the mode bits; on Windows the exclusive
    create still holds but ACLs are inherited from ``.visus/``.
    """
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)


def _read_lock_pid(lock: Path) -> int:
    """The pid recorded in *lock*, or ``-1`` when it is missing/empty/garbage."""
    try:
        return int(lock.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return -1


def _claim_lock(sf: Path) -> Path:
    """Atomically claim ownership for this daemon (O_CREAT|O_EXCL lock file).

    Closes the TOCTOU between ``find_session() is None`` and ``Popen`` in the
    client: two concurrent daemons cannot both claim the lock, so the loser
    exits immediately (before serving / launching a browser) instead of running
    forever untracked with a live driver.

    A lock left behind by a daemon that was killed (``kill -9``, reboot, power
    cut) would otherwise wedge every future ``visus session start`` forever, so
    the pid written into the lock is read back: when its owner is gone the lock
    is removed and claimed on ONE retry. A live rival that grabs it in between
    wins that retry, which keeps the mutual-exclusion guarantee intact.
    """
    lock = sf.with_name(sf.name + ".lock")
    for attempt in (0, 1):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            owner = _read_lock_pid(lock)
            if attempt == 0 and not session_client._probe_pid(owner):
                try:
                    lock.unlink()
                except OSError:
                    pass
                continue
            raise SessionLockedError(
                f"another daemon already holds {lock} (owner pid {owner})"
            ) from exc
        try:
            os.write(fd, str(os.getpid()).encode("utf-8"))
        finally:
            os.close(fd)
        return lock
    raise SessionLockedError(f"another daemon already holds {lock}")


# How long serve() waits for in-flight ops before tearing the driver down. Kept
# under session_client.stop()'s 10 s wait so a normal stop still observes the
# session file disappear.
SHUTDOWN_GRACE_SECONDS = 8.0


def _prune(threads: list[threading.Thread]) -> list[threading.Thread]:
    """Drop finished workers so the list cannot grow without bound.

    Every command costs about two connections (``find_session`` probes liveness
    with its own connect), so an unpruned list leaks a Thread object per probe
    for the whole life of the daemon.
    """
    return [t for t in threads if t.is_alive()]


def serve(
    handler: SessionHandler,
    *,
    token: str,
    cwd: str | Path | None = None,
    host: str = "127.0.0.1",
    idle_timeout: float | None = None,
) -> None:
    """Bind a JSON-lines TCP server, write the session file, serve until shutdown.

    *idle_timeout* (seconds, ``None`` = never) reaps a session nobody is using:
    an abandoned headed browser otherwise sits on the desktop forever.
    """
    sf = session_file(cwd)
    sf.parent.mkdir(parents=True, exist_ok=True)
    # Claim ownership atomically BEFORE binding / writing session.json so a
    # concurrently-spawned duplicate daemon aborts here and never serves.
    lock = _claim_lock(sf)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, 0))
    srv.listen(8)
    srv.settimeout(0.5)
    port = srv.getsockname()[1]

    # Write atomically (tmp file in the same dir + os.replace) so a concurrent
    # find_session() can never read a half-written file and delete it as "stale".
    payload = json.dumps(
        {
            "pid": os.getpid(),
            "port": port,
            "token": token,
            "engine": handler._engine,
            "headless": handler._headless,
            "url": handler._url,
            "started_at": time.time(),
        }
    )
    tmp = sf.with_name(f"{sf.name}.{os.getpid()}.tmp")
    try:
        tmp.unlink()  # a crashed predecessor may have left this behind
    except OSError:
        pass
    _write_private(tmp, payload)
    os.replace(tmp, sf)

    stop = threading.Event()
    handler.bind_stop(stop)
    threads: list[threading.Thread] = []
    try:
        while not stop.is_set():
            threads = _prune(threads)
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                if idle_timeout is not None and (
                    time.monotonic() - handler.last_op_at() > idle_timeout
                ):
                    break
                continue
            t = threading.Thread(
                target=_handle_conn,
                args=(conn, handler, token, stop),
                name="visus-session-conn",
                daemon=True,
            )
            t.start()
            threads.append(t)
    finally:
        srv.close()
        # Let in-flight ops finish BEFORE the driver is torn down: a concurrent
        # `wait`/`expect_text` can block for tens of seconds and would otherwise
        # run against a driver closing underneath it.
        deadline = time.monotonic() + SHUTDOWN_GRACE_SECONDS
        for worker in _prune(threads):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.join(timeout=remaining)
        handler.close()
        try:
            sf.unlink()
        except OSError:
            pass
        try:
            lock.unlink()
        except OSError:
            pass


def _idle_timeout_from_env() -> float | None:
    """``VISUS_WEB_IDLE_TIMEOUT`` in seconds; ``0``/unset/garbage means never."""
    try:
        seconds = float(os.environ.get("VISUS_WEB_IDLE_TIMEOUT", "") or 0)
    except ValueError:
        return None
    return seconds if seconds > 0 else None


LOG_MAX_BYTES = 1_048_576
LOG_BACKUP_COUNT = 3


def _make_logger(
    log_path: Path,
    *,
    max_bytes: int = LOG_MAX_BYTES,
    backup_count: int = LOG_BACKUP_COUNT,
) -> logging.Logger:
    """The daemon's logger, writing to a size-capped rotating file.

    ``.visus/daemon.log`` used to be an unbounded append; a long-lived headed
    session logs on every start/abort/crash and nothing ever truncated it.
    Idempotent: re-creating the logger replaces its handler instead of stacking
    a second one (which would double every line).
    """
    logger = logging.getLogger("visus.web.cli.session_server")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        existing.close()
    handler = RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    return logger


def main(argv: list[str] | None = None) -> None:
    """Daemon entrypoint: ``python -m visus.web.cli.session_server [engine] [headless] [url]``.

    Engine/headless/url come from argv first, then env. Logs to ``.visus/daemon.log``.
    """
    argv = sys.argv[1:] if argv is None else argv
    engine = argv[0] if len(argv) > 0 and argv[0] else os.environ.get("VISUS_WEB_ENGINE", "chrome")
    if len(argv) > 1 and argv[1]:
        headless = argv[1] not in ("0", "false", "False", "no")
    else:
        headless = os.environ.get("VISUS_WEB_HEADLESS", "0") != "0"
    url = argv[2] if len(argv) > 2 and argv[2] else os.environ.get("VISUS_WEB_URL") or None
    token = os.environ.get("VISUS_WEB_TOKEN") or secrets.token_hex(16)

    log_dir = Path.cwd() / ".visus"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = _make_logger(log_dir / "daemon.log")

    def _log(msg: str) -> None:
        logger.info(msg)

    _log(f"daemon starting engine={engine} headless={headless} url={url!r} pid={os.getpid()}")
    handler = SessionHandler(engine=engine, headless=headless, url=url)
    try:
        serve(handler, token=token, idle_timeout=_idle_timeout_from_env())
    except SessionLockedError as exc:
        # A duplicate daemon lost the ownership race: exit cleanly (no browser
        # was launched, the winner owns session.json) instead of crashing.
        _log(f"daemon aborting: {exc}")
        return
    except Exception as exc:  # noqa: BLE001
        _log(f"daemon crashed: {type(exc).__name__}: {exc}")
        raise
    finally:
        _log("daemon stopped")


if __name__ == "__main__":
    main()
