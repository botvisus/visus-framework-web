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
import hashlib
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

from visus.web import Engine, _action_timeout_ms, errors, launch
from visus.web.api.assertions import expect
from visus.web.api.browser import Browser
from visus.web.api.context import Context
from visus.web.api.fields import Field
from visus.web.api.locator import Locator
from visus.web.api.page import Page
from visus.web.backends.selenium.driver_delegate import SeleniumPageDelegate
from visus.web.cli import session_client
from visus.web.cli.codegen import generate_line
from visus.web.ops.targeting import StaleFieldIndexError, make_locator, resolve_field
from visus.web.ops.targeting import any_match_visible as _any_match_visible

# `StaleFieldIndexError` and `make_locator` are re-exported, not used here: PLAN 3
# named the exception `session_server.StaleFieldIndexError` and tests/main.py
# import `make_locator` from this module. Listing them in __all__ is what tells
# ruff's F401 they are a deliberate re-export.
__all__ = [
    "SessionHandler",
    "SessionLockedError",
    "StaleFieldIndexError",
    "cli_hint",
    "main",
    "make_locator",
    "serve",
    "session_file",
]

# The library raises strict-mode violations naming its own Python methods. A CLI
# caller cannot call those, so the daemon rewrites the advice into the flag the
# CLI actually has. The wording is matched, not the exception type, because the
# same sentence is raised from the resolver and from the assertion engine.
_PY_ESCAPE = "use first()/last()/nth()"
_CLI_ESCAPE = "pass --nth N to pick one (0 = first, -1 = last), or use a narrower target"


def cli_hint(message: str) -> str:
    """Rewrite library-API advice into CLI advice, leaving other errors untouched."""
    return message.replace(_PY_ESCAPE, _CLI_ESCAPE)


def _norm_rect(rect: Any) -> dict[str, float] | None:
    """Normalise the JS bundle's ``{x,y,w,h}`` to ``bounding_box()``'s key names."""
    if not isinstance(rect, dict):
        return None
    return {
        "x": float(rect.get("x", 0)),
        "y": float(rect.get("y", 0)),
        "width": float(rect.get("w", 0)),
        "height": float(rect.get("h", 0)),
    }


def _cookie_matches(
    cookie: dict[str, Any],
    *,
    name: str | None,
    domain: str | None,
    path: str | None,
) -> bool:
    """True when *cookie* satisfies every filter that was given.

    A stored domain may carry a leading dot (``.example.com``) for a
    subdomain-wide cookie; the comparison strips it so ``--domain example.com``
    matches both spellings.
    """
    if name is not None and cookie.get("name") != name:
        return False
    if domain is not None:
        have = str(cookie.get("domain") or "").lstrip(".")
        if have != domain.lstrip("."):
            return False
    if path is not None and cookie.get("path") != path:
        return False
    return True


# Ops that change what the agent is looking at. Only these get a `page` footer;
# reads stay bare so piping (`visus --raw get-text 3`) is never polluted.
#
# This set is a cross-plan tripwire: PLANS 5, 6 and 7 each add new mutating ops
# and are REQUIRED to add their names here too. test_mutating_ops_cover_every_state_changing_op
# in tests/test_cli_session.py asserts this set by exact equality, so forgetting
# to update it turns that test red at the offending plan's own commit gate —
# that failure is the whole point of the test, not a bug in it.
# Ops que podem rodar com um diálogo aberto sem fechá-lo: o próprio `dialog`, o
# encerramento, e o `status` (que então informa o diálogo em vez de ler a página)
_DIALOG_SAFE_OPS: frozenset[str] = frozenset({"dialog", "shutdown", "status"})

_MUTATING_OPS: frozenset[str] = frozenset(
    {
        "click",
        "dblclick",
        "fill",
        "check",
        "uncheck",
        "select",
        "press",
        "hover",
        "focus",
        "clear_input",
        "drag",
        "drop",
        "upload",
        "goto",
        "back",
        "forward",
        "reload",
        "tab",
        "tab_new",
        "tab_close",
        "dialog",
        "add_cookies",
        "clear_cookies",
        "eval",
        "route",
        "unroute",
        "run_code",
        "state_load",
        "solve_captcha",
        "type",
        "key_down",
        "key_up",
        "mouse_move",
        "mouse_down",
        "mouse_up",
        "mouse_wheel",
        "resize",
        "click_image",
        "click_ocr_text",
        "storage_set",
        "storage_delete",
        "storage_clear",
        "cookie_set",
        "cookie_delete",
        "pick_date",
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


def _jsonable(value: Any, *, depth: int = 0) -> Any:
    """Coerce a ``run_code`` return value into something ``json.dumps`` accepts.

    A snippet can legitimately return a ``Page``, a ``Locator`` or any other live
    object; those have no JSON form, and an unencodable reply would break the
    socket protocol rather than the snippet. Anything unknown becomes its
    ``repr`` — informative, and always encodable.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth >= 6:  # guards a self-referential structure
        return repr(value)
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v, depth=depth + 1) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v, depth=depth + 1) for k, v in value.items()}
    return repr(value)


# Locator.evaluate calls the expression as (element, arg) — see
# SeleniumPageDelegate.locator_evaluate. A DataTransfer is built here rather
# than in Python because a File object cannot cross the WebDriver boundary.
_DROP_JS = r"""(el, a) => {
  const dt = new DataTransfer();
  if (a.file) {
    const bin = atob(a.file.b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    dt.items.add(new File([arr], a.file.name,
                          {type: a.file.type || 'application/octet-stream'}));
  }
  if (a.data !== null && a.data !== undefined) {
    dt.setData(a.dataType || 'text/plain', a.data);
  }
  const init = {bubbles: true, cancelable: true, composed: true, dataTransfer: dt};
  for (const type of ['dragenter', 'dragover', 'drop']) {
    el.dispatchEvent(new DragEvent(type, init));
  }
  return {files: dt.files.length, types: Array.from(dt.types)};
}"""


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
        user_data_dir: str | None = None,
        remote_url: str | None = None,
        slow_mo: int = 0,
        allow_run_code: bool = False,
        debugger_address: str | None = None,
        device: str | None = None,
    ) -> None:
        self._engine = engine or os.environ.get("VISUS_WEB_ENGINE", "chrome")
        if headless is None:
            headless = os.environ.get("VISUS_WEB_HEADLESS", "0") != "0"
        self._headless = headless
        self._url = url
        self._user_data_dir = user_data_dir
        self._remote_url = remote_url
        self._slow_mo = slow_mo
        # Arbitrary Python against the LIVE browser is opt-in per session: the
        # daemon holds cookies, logins and a token that authorises file writes,
        # so `run-code` stays off unless the user asked for it at start time.
        self._allow_run_code = allow_run_code
        self._debugger_address = debugger_address
        # True when the browser belongs to somebody else: closing it would destroy
        # the user's own window, so only `detach` may end such a session.
        self._attached = debugger_address is not None
        self._detached = False
        self._device = device
        self._browser: Browser | None = None
        self._context: Context | None = None
        self._page: Page | None = None
        self._fields: list[Field] = []
        # Downloads já informados ao cliente: `wait-download` devolve só os novos
        self._seen_downloads: set[str] = set()
        self._fields_url: str | None = None
        self._script: list[str] = []
        self._known_handles: list[str] = []
        self._active_handle: str | None = None
        # Auto-follow a newly-opened tab/popup (the daemon's historical default).
        # `tab_follow` flips it to MANUAL, matching the MCP server's default and
        # giving an agent a predictable context that a popup cannot steal.
        self._follow: bool = True
        # A tracing session is process-global (tracing._STATE has no thread
        # locality), so the handler owns at most one and flushes it on close().
        self._recorder: Any = None
        self._trace_zip: str | None = None
        # NetworkCapture is created with use_cdp=False on purpose: the delegate
        # already drains driver.get_log("performance") for page.network_requests(),
        # and that read is DESTRUCTIVE — two drainers would silently split the log.
        self._capture: Any = None
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
            self._browser = launch(
                Engine.from_str(self._engine),
                headless=self._headless,
                slow_mo=self._slow_mo,
                user_data_dir=self._user_data_dir,
                remote_url=self._remote_url,
                debugger_address=self._debugger_address,
            )
            # Failure-atomic: if any step after launch raises (bad URL, etc.),
            # tear the partial browser down so the next op retries from scratch
            # instead of wedging on a non-None browser with a None page.
            try:
                # new_page() reuses the browser's DEFAULT context. Calling
                # new_context() here would spawn a SECOND WebDriver/browser window
                # (the daemon is headed) — that was the "2 browsers" bug.
                self._page = self._browser.new_page()
                # BEFORE the initial goto: a device session whose first load saw a
                # desktop viewport would render (and cache) the wrong layout.
                if self._device:
                    from visus.web.api.devices import get_device

                    preset = get_device(self._device)
                    self._page.set_device_metrics(
                        preset.width,
                        preset.height,
                        device_scale_factor=preset.device_scale_factor,
                        mobile=preset.mobile,
                    )
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
        """Pick the active handle: auto-follow a newly-opened tab/window when follow
        mode is on, else stay on the last-active one (sticky), else the newest.
        The ``tab``/``tab_activate`` ops override."""
        new = [h for h in handles if h not in self._known_handles]
        self._known_handles = list(handles)
        if new and self._follow:
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

    def _stop_tracing_if_running(self) -> None:
        """Flush a live tracing session so shutdown never orphans its log handler."""
        if self._recorder is None:
            return
        from visus.web import tracing

        try:
            tracing.stop_recording(self._trace_zip, None)
        except Exception:  # noqa: BLE001 — shutdown must not fail on a trace flush
            pass
        self._recorder = None
        self._trace_zip = None

    def close(self) -> None:
        self._stop_tracing_if_running()
        if self._browser is not None:
            self._browser.close()
        self._browser = None
        self._context = None
        self._page = None
        self._capture = None  # a capture without a browser is meaningless
        self._invalidate_fields()

    def detach(self) -> None:
        """Mark this session for release — ``serve()`` must not close the browser."""
        self._detached = True

    def detached(self) -> bool:
        """True once :meth:`detach` was called (read by ``serve()``'s teardown)."""
        return self._detached

    def release(self) -> None:
        """Drop the browser WITHOUT closing it (see :meth:`visus.web.Browser.detach`).

        Same teardown as :meth:`close` in every other respect — a live trace is
        still flushed, because detaching must not orphan its log handler either.
        """
        self._stop_tracing_if_running()
        if self._browser is not None:
            self._browser.detach()
        self._browser = None
        self._context = None
        self._page = None
        self._capture = None
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
        return resolve_field(self.page(), self._fields, index, fields_url=self._fields_url)

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
        nth = args.get("nth")
        if "index" in args and args["index"] is not None:
            field = self._resolve_field(int(args["index"]))
            return field.nth(int(nth)) if nth is not None else field
        return make_locator(
            self.page(),
            selector=args.get("selector"),
            role=args.get("role"),
            name=args.get("name"),
            text=args.get("target_text"),
            exact=bool(args.get("exact", False)),
            frame=args.get("frame"),
            nth=None if nth is None else int(nth),
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
            if op == "pick_date":
                target = self._target_event(args)
                if target is None:
                    return None
                dates = [args.get("start"), args.get("end")]
                return generate_line({"action": "pick_date", "target": target, "value": dates})
            if op == "solve_captcha":
                # a chave fica fora: o script lê VISUS_CAPTCHA_KEY quando roda
                return None if self._has_target(args) else "page.solve_captcha()"
            if op == "wait":
                # o script espera o mesmo que o agente esperou (e não um sleep chutado)
                target = self._target_event(args)
                if target is None:
                    return None
                state = args.get("state") or "visible"
                return generate_line({"action": "wait_for", "target": target, "value": state})
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
        # Um diálogo que o próprio clique abriu: ler a página agora o fecharia
        pending = self._open_dialog_text()
        if pending is not None:
            return {"dialog": pending}
        try:
            page = self.page()
            stale = bool(self._fields) and self.fields_stale()
            return {"url": page.url, "title": page.title(), "fields_stale": stale}
        except Exception:  # noqa: BLE001 — page state is telemetry, not the result
            return {}

    def _open_dialog_text(self) -> str | None:
        """O texto do alert/confirm/prompt aberto, ou None. Usa só o endpoint do
        alerta, que NÃO dispara o fechamento automático do ChromeDriver."""
        driver = self._driver()
        if driver is None:
            return None
        try:
            return str(driver.switch_to.alert.text)
        except Exception:  # noqa: BLE001 — NoAlertPresent e afins = nenhum diálogo
            return None

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
            # Com um alert/confirm/prompt aberto, QUALQUER comando que toque a página
            # faz o ChromeDriver fechá-lo em silêncio ("dismiss and notify"): o agente
            # nunca saberia que houve um diálogo. Recusa e diz como tratá-lo.
            if op not in _DIALOG_SAFE_OPS:
                pending = self._open_dialog_text()
                if pending is not None:
                    return {
                        "ok": False,
                        "error": f"a dialog is open: {pending!r} — handle it first with "
                        "`visus dialog` (accept) or `visus dialog --dismiss`",
                    }
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
                return {"ok": False, "error": cli_hint(f"{type(exc).__name__}: {exc}")}
            # the op that ended the session (the last tab closed) leaves no page to
            # describe: reading one would launch a BRAND-NEW browser just to quit it
            if op in _MUTATING_OPS and self._browser is not None:
                resp["page"] = self._post_state()
                if args.get("snapshot"):
                    resp["snapshot"] = self._write_snapshot()
            if code:
                resp["code"] = code
                self._script.append(code)
            return resp

    def _op_list_fields(self, args: dict[str, Any]) -> dict[str, Any]:
        """Enumerate interactive fields. ``boxes`` keeps each field's viewport rect.

        The rect is stripped by default: it roughly doubles the payload an agent
        usually reads for index/kind/name only.
        """
        kinds = args.get("kinds")
        include_hidden = bool(args.get("include_hidden", False))
        highlight = bool(args.get("highlight", True))
        # the CLI is what agents use: list the click-only elements too (menus, calendar
        # days) unless asked not to — without them an agent falls back to text= guesses
        clickables = bool(args.get("clickables", True))
        page = self.page()
        fields = page.list_fields(
            kinds=kinds, include_hidden=include_hidden, highlight=highlight, clickables=clickables
        )
        self._fields = list(fields)
        # Stamp the page identity so a later index op can tell the page moved.
        self._fields_url = page.url
        rows = [f.to_dict() for f in fields]
        if not args.get("boxes"):
            for row in rows:
                row.pop("box", None)
        return {"fields": rows}

    def _op_click(self, args: dict[str, Any]) -> str:
        """Click the target.

        ``button`` is ``left`` (default), ``middle`` or ``right``. A non-left
        click goes through the pointer device at the target's centre, because
        the actionability click path is left-button only.
        """
        button = str(args.get("button") or "left")
        if button == "left":
            self._target(args).click()
            return "clicked"
        x, y = self._pointer_center(args)
        self.page().mouse.click(x, y, button=button)
        return f"clicked with the {button} button"

    def _op_fill(self, args: dict[str, Any]) -> str:
        text = args.get("text", "")
        loc = self._target(args)
        loc.fill(text)
        if args.get("submit"):
            loc.press("Enter")
            return f"filled with {text!r} and pressed Enter"
        return f"filled with {text!r}"

    def _op_pick_date(self, args: dict[str, Any]) -> str:
        """A date, or a range, in any date field — native, typed, or a calendar it
        steps through (see :mod:`visus.web.ops.dates`)."""
        from visus.web.ops import dates

        start = dates.parse_iso(str(args.get("start", "")))
        end = dates.parse_iso(str(args["end"])) if args.get("end") else None
        return dates.pick_date(self.page(), self._target(args), start, end)

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
        """Press a key on a target, or on the page itself when no target is given."""
        key = args.get("key", "")
        if self._has_target(args):
            self._target(args).press(key)
        else:
            self.page().keyboard.press(key)
        return f"pressed {key!r}"

    def _op_type(self, args: dict[str, Any]) -> str:
        """Type text with real key events. With a target, focus it first."""
        text = str(args.get("text", ""))
        page = self.page()
        if self._has_target(args):
            self._target(args).first().focus()
        page.keyboard.type(text)
        return f"typed {text!r}"

    def _op_key_down(self, args: dict[str, Any]) -> str:
        """Hold a key down (e.g. Shift, Control) until ``key_up``."""
        key = str(args.get("key", ""))
        self.page().keyboard.down(key)
        return f"key down {key!r}"

    def _op_key_up(self, args: dict[str, Any]) -> str:
        """Release a key held by ``key_down``."""
        key = str(args.get("key", ""))
        self.page().keyboard.up(key)
        return f"key up {key!r}"

    def _op_get_text(self, args: dict[str, Any]) -> dict[str, Any]:
        """Text content of the target, keeping "absent" distinct from "empty".

        ``typer.echo(None)`` and ``typer.echo("")`` print an identical blank line,
        so the two cases have to be separated here, in the payload.
        """
        target = self._target(args).first()
        # visible: o texto como aparece na tela (inner_text) — sem linhas escondidas de
        # uma tabela filtrada nem o código de um <script>
        value = target.inner_text() if args.get("visible") else target.text_content()
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

        ``hires`` captures at device-pixel-ratio 2 — markedly better for OCR and
        for a vision model reading the numbered overlay. There is no
        "clear override" in the delegate, so the scale is restored by
        re-overriding at the same size with DPR 1, in a ``finally`` so a failed
        capture cannot leave the session stuck at 2x.
        """
        path = args.get("path") or "screenshot.png"
        page = self.page()
        hires = bool(args.get("hires"))
        size: dict[str, Any] | None = None
        if hires:
            size = cast(
                "dict[str, Any]",
                page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})"),
            )
            page.set_device_metrics(int(size["w"]), int(size["h"]), device_scale_factor=2.0)
        try:
            if self._has_target(args):
                self._target(args).screenshot(path=path)
            else:
                page.screenshot(path=path, full_page=bool(args.get("full_page")))
        finally:
            if size is not None:
                page.set_device_metrics(int(size["w"]), int(size["h"]), device_scale_factor=1.0)
        return str(Path(path).resolve())

    def _op_pdf(self, args: dict[str, Any]) -> str:
        """Print the session's current page to a PDF file (Chromium/W3C print).

        Same contract as ``_op_screenshot``: the client resolves the path
        against ITS cwd, the daemon writes the file and returns the absolute
        path it wrote.
        """
        path = args.get("path") or "page.pdf"
        self.page().pdf(path=path)
        return str(Path(path).resolve())

    def _op_clear_highlights(self, args: dict[str, Any]) -> str:
        self.page().clear_highlights()
        return "cleared"

    def _op_highlight(self, args: dict[str, Any]) -> str:
        """Draw (or clear) the single-element debug highlight box.

        Distinct from ``clear_highlights``, which removes the NUMBERED overlay
        drawn by ``list_fields``. ``style`` replaces the default border;
        ``hide=True`` removes the box.
        """
        page = self.page()
        if args.get("hide"):
            # A page that never ran a locator has no window.__visus yet; resolving
            # one forces the bundle in (same trick as cli/codegen.py).
            page.locator("html").count()
            page.evaluate("() => window.__visus.unhighlight()")
            return "highlight cleared"
        style = args.get("style")
        self._target(args).first().highlight(style=str(style) if style else None)
        return "highlighted"

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

    def _op_resize(self, args: dict[str, Any]) -> dict[str, Any]:
        """Resize the window so the viewport is width × height.

        Returns the size actually achieved: a window manager can clamp the
        request (minimum widths, screen size), and reporting the request back
        would hide that.
        """
        width, height = int(args.get("width", 0)), int(args.get("height", 0))
        if width <= 0 or height <= 0:
            raise ValueError("resize needs a positive width and height")
        page = self.page()
        page.set_viewport_size(width, height)
        got = cast(
            "dict[str, Any]",
            page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})"),
        )
        return {"width": int(got["w"]), "height": int(got["h"])}

    def _op_url(self, args: dict[str, Any]) -> str:
        return self.page().url

    def _op_snapshot(self, args: dict[str, Any]) -> dict[str, Any]:
        """The page's interactive elements, numbered with list_fields indexes.

        ``refs`` (default on) re-enumerates the page so every row's ``ref`` is a
        live index an action can use immediately — this is what makes ``snapshot``
        addressable instead of a second, incompatible numbering. Pass
        ``refs=False`` for a pure read that leaves the field cache untouched.

        ``boxes`` adds each element's viewport rect as ``box`` (``{x, y, width,
        height}``); without it the raw bundle ``rect`` is dropped entirely.
        """
        page = self.page()
        depth = args.get("depth")
        rows = page.snapshot(args.get("selector"), depth=None if depth is None else int(depth))
        if args.get("refs", True):
            fields = page.list_fields(kinds=None, include_hidden=False, highlight=False)
            self._fields = list(fields)
            self._fields_url = page.url
        refs = self._snapshot_refs(rows)
        # `boxes` renames the bundle's {x,y,w,h} rect to bounding_box()'s keys;
        # without it the raw `rect` is stripped, as it was before this task.
        want_boxes = bool(args.get("boxes"))
        elements = [
            {
                **{k: v for k, v in row.items() if k != "rect"},
                "ref": refs[i],
                **({"box": _norm_rect(row.get("rect"))} if want_boxes else {}),
            }
            for i, row in enumerate(rows)
        ]
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

    def _op_generate_locator(self, args: dict[str, Any]) -> dict[str, Any]:
        """The copy-paste visus.web expression for a target.

        For a cached index this is ``Field.code`` verbatim — the same
        frame-aware string ``list_fields`` puts in its VISUS column — plus that
        field's css/xpath. For a selector/role/text target the expression is
        built by ``codegen.locator_expr`` and there is no css/xpath to report.
        """
        from visus.web.cli.codegen import locator_expr

        index = args.get("index")
        if index is not None:
            i = int(index)
            if i < 0 or i >= len(self._fields):
                raise IndexError(
                    f"field index {i} out of range "
                    f"(have {len(self._fields)}; run list_fields first)"
                )
            field = self._fields[i]
            return {"code": field.code, "css": field.css, "xpath": field.xpath}
        return {
            "code": locator_expr(
                selector=args.get("selector"),
                role=args.get("role"),
                name=args.get("name"),
                text=args.get("target_text"),
                exact=bool(args.get("exact", False)),
                frame=args.get("frame"),
            ),
            "css": None,
            "xpath": None,
        }

    # --- actions ---------------------------------------------------------
    def _op_hover(self, args: dict[str, Any]) -> str:
        self._target(args).hover()
        return "hovered"

    def _op_dblclick(self, args: dict[str, Any]) -> str:
        """Double-click the target (``button``: left, middle or right)."""
        button = str(args.get("button") or "left")
        if button == "left":
            self._target(args).dblclick()
            return "double-clicked"
        x, y = self._pointer_center(args)
        self.page().mouse.dblclick(x, y, button=button)
        return f"double-clicked with the {button} button"

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

    def _op_drop(self, args: dict[str, Any]) -> dict[str, Any]:
        """Drop a file or a data payload onto the target from OUTSIDE the page.

        The case neither ``drag`` nor ``upload`` covers: a dropzone with no
        ``<input type=file>`` only reacts to a ``DragEvent`` carrying a
        ``DataTransfer``, which nothing on the page can produce.
        """
        file = args.get("file")
        data = args.get("data")
        if file is None and data is None:
            raise ValueError("drop: provide a payload — --path <file> or --data <text>")
        payload = {
            "file": file,
            "data": data,
            "dataType": args.get("data_type") or "text/plain",
        }
        result = self._target(args).evaluate(_DROP_JS, payload)
        return {"dropped": result}

    def _only_file_input(self) -> Locator:
        """The page's single ``<input type=file>`` — the target-free ``visus upload``.

        No OS file-chooser interception is needed: a button that "opens the file
        chooser" is proxying for an input, and setting files on that input is both
        simpler and more reliable than driving a native dialog. Hidden inputs count
        — sites routinely hide them behind a styled button.
        """
        loc = self.page().locator('input[type="file"]', deep=True)
        found = loc.count()
        if found == 0:
            raise errors.ElementNotFoundError(
                "no <input type=file> on this page — open the form that reveals one, "
                "or use `visus drop --path <file>` for a dropzone that has none"
            )
        if found > 1:
            raise errors.StrictModeViolation(
                f"{found} file inputs on this page — name one explicitly: run "
                "`visus list-fields` and pass its index, e.g. `visus upload 4 a.png`"
            )
        return loc.first()

    def _op_upload(self, args: dict[str, Any]) -> str:
        """Set file(s) on a file input — the target is optional."""
        paths = args.get("paths") or []
        if not paths:
            raise ValueError("upload: provide at least one file path")
        target = self._target(args) if self._has_target(args) else self._only_file_input()
        target.set_input_files(paths)
        return f"set {len(paths)} file(s)"

    # --- pointer device --------------------------------------------------
    def _pointer_center(self, args: dict[str, Any]) -> tuple[float, float]:
        """Viewport centre of the action target, scrolled into view first.

        ``Locator.bounding_box`` and ``Page.mouse`` both work in viewport
        coordinates, so no conversion is needed between them.
        """
        loc = self._target(args).first()
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        if box is None:
            raise ValueError("target has no bounding box — it may be hidden or detached")
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    def _op_mouse_move(self, args: dict[str, Any]) -> str:
        """Move the pointer to absolute viewport coordinates."""
        x, y = float(args.get("x", 0)), float(args.get("y", 0))
        self.page().mouse.move(x, y)
        return f"moved to ({x}, {y})"

    def _op_mouse_down(self, args: dict[str, Any]) -> str:
        """Hold a mouse button down at the current pointer position."""
        button = str(args.get("button") or "left")
        self.page().mouse.down(button=button)
        return f"{button} button down"

    def _op_mouse_up(self, args: dict[str, Any]) -> str:
        """Release a mouse button held by ``mouse_down``."""
        button = str(args.get("button") or "left")
        self.page().mouse.up(button=button)
        return f"{button} button up"

    def _op_mouse_wheel(self, args: dict[str, Any]) -> str:
        """Scroll by a wheel delta at the current pointer position."""
        dx, dy = float(args.get("delta_x", 0)), float(args.get("delta_y", 0))
        self.page().mouse.wheel(dx, dy)
        return f"scrolled by ({dx}, {dy})"

    # --- wait / expect ---------------------------------------------------
    def _op_wait(self, args: dict[str, Any]) -> str:
        state = args.get("state") or "visible"
        loc = self._target(args)
        timeout = args.get("timeout")
        # espera o quanto uma ação esperaria pelo seu elemento (VISUS_ACTION_TIMEOUT_MS)
        ms = _action_timeout_ms() if timeout is None else int(timeout)
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
        action = "accepted" if accept else "dismissed"
        driver = self._driver()
        if driver is not None:
            # Direto pelo endpoint do alerta, SEM self.page(): resolver a página lê a
            # janela, e com o diálogo já aberto o ChromeDriver o fecharia antes daqui
            deadline = time.monotonic() + 5.0
            while True:
                try:
                    alert = driver.switch_to.alert
                    msg = str(alert.text)
                    if prompt_text is not None:
                        alert.send_keys(str(prompt_text))
                    if accept:
                        alert.accept()
                    else:
                        alert.dismiss()
                    return f"{action} 'dialog' dialog: {msg!r}"
                except Exception:  # noqa: BLE001 — NoAlertPresent: ainda não abriu
                    if time.monotonic() >= deadline:
                        raise errors.VisusTimeoutError(
                            "no dialog appeared within 5000 ms"
                        ) from None
                    time.sleep(0.05)
        page = self.page()
        msg, typ = page._delegate.handle_next_dialog(
            accept=accept,
            prompt_text=prompt_text,
            timeout_ms=5000,
        )
        action = "accepted" if accept else "dismissed"
        return f"{action} {typ!r} dialog: {msg!r}"

    # --- downloads ---------------------------------------------------------
    # O navegador da sessão baixa numa pasta TEMPORÁRIA, apagada quando a sessão
    # fecha: o agente precisa do caminho (e de uma cópia) antes disso.
    _PARTIAL_DOWNLOAD = (".crdownload", ".tmp", ".part")

    def _completed_downloads(self) -> list[dict[str, Any]]:
        folder = getattr(self.page()._delegate, "_download_dir", None)
        if not folder or not os.path.isdir(folder):
            return []
        files = []
        names = os.listdir(folder)
        for name in names:
            path = os.path.join(folder, name)
            # o Firefox cria o nome final VAZIO ao lado de `<nome>.part`
            partial = any(name + s in names for s in self._PARTIAL_DOWNLOAD)
            if name.endswith(self._PARTIAL_DOWNLOAD) or partial or not os.path.isfile(path):
                continue
            st = os.stat(path)
            files.append(
                {
                    "name": name,
                    "path": os.path.abspath(path),
                    "size": st.st_size,
                    "mtime": st.st_mtime,
                }
            )
        files.sort(key=lambda f: f["mtime"], reverse=True)
        return files

    def _op_downloads(self, args: dict[str, Any]) -> dict[str, Any]:
        """Completed downloads of this session, newest first."""
        files = self._completed_downloads()
        self._seen_downloads.update(f["path"] for f in files)
        return {"files": [{k: f[k] for k in ("name", "path", "size")} for f in files]}

    def _op_wait_download(self, args: dict[str, Any]) -> dict[str, Any]:
        """Wait for a completed download not reported yet (or, with ``last``, take the
        newest); with ``save_to``, copy it there so it outlives the session."""
        timeout_ms = int(args.get("timeout") or 30_000)
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            files = self._completed_downloads()
            pick = (
                files[0]
                if args.get("last") and files
                else next((f for f in files if f["path"] not in self._seen_downloads), None)
            )
            if pick is not None:
                break
            if time.monotonic() >= deadline:
                raise errors.VisusTimeoutError(f"no new download completed within {timeout_ms} ms")
            time.sleep(0.1)
        self._seen_downloads.add(pick["path"])
        result = {"name": pick["name"], "path": pick["path"], "size": pick["size"]}
        save_to = args.get("save_to")
        if save_to:
            import shutil

            dest_dir = os.path.abspath(str(save_to))
            os.makedirs(dest_dir, exist_ok=True)
            result["path"] = shutil.copy2(pick["path"], os.path.join(dest_dir, pick["name"]))
        return result

    # --- cookies (context-level) -----------------------------------------
    def _op_cookies(self, args: dict[str, Any]) -> dict[str, Any]:
        """List cookies, optionally filtered by ``domain`` and/or ``path``."""
        domain = args.get("domain")
        path = args.get("path")
        cookies = self.context().cookies()
        if domain is None and path is None:
            return {"cookies": cookies}
        return {
            "cookies": [
                c for c in cookies if _cookie_matches(c, name=None, domain=domain, path=path)
            ]
        }

    def _op_cookie_get(self, args: dict[str, Any]) -> dict[str, Any]:
        """One cookie by name (optionally scoped by domain/path).

        ``present`` distinguishes a cookie holding ``""`` from no cookie at all.
        """
        name = str(args.get("name", ""))
        matches = [
            c
            for c in self.context().cookies()
            if _cookie_matches(c, name=name, domain=args.get("domain"), path=args.get("path"))
        ]
        if not matches:
            return {"value": None, "present": False, "cookie": None}
        hit = matches[0]
        return {"value": hit.get("value", ""), "present": True, "cookie": hit}

    def _op_cookie_set(self, args: dict[str, Any]) -> str:
        """Set one cookie on the current document's domain."""
        name = str(args.get("name", ""))
        cookie: dict[str, Any] = {"name": name, "value": str(args.get("value", ""))}
        for key in ("domain", "path", "url"):
            if args.get(key):
                cookie[key] = args[key]
        cookie.setdefault("path", "/")
        self.context().add_cookies([cookie])
        return f"set cookie {name!r}"

    def _op_cookie_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        """Delete cookies by name (optionally scoped by domain/path).

        WebDriver has no per-cookie delete, so this reads every cookie, drops
        the matches, clears the jar and re-adds the survivors ONE AT A TIME.
        ``driver.add_cookie`` only accepts a cookie for the currently-loaded
        document's domain, so a survivor from another domain cannot be put back
        — those are counted in ``dropped`` instead of vanishing silently.
        """
        name = str(args.get("name", ""))
        ctx = self.context()
        cookies = ctx.cookies()
        keep = [
            c
            for c in cookies
            if not _cookie_matches(c, name=name, domain=args.get("domain"), path=args.get("path"))
        ]
        deleted = len(cookies) - len(keep)
        if deleted == 0:
            return {"deleted": 0, "restored": len(keep), "dropped": 0}
        ctx.clear_cookies()
        restored = 0
        for c in keep:
            try:
                ctx.add_cookies([c])
                restored += 1
            except Exception:  # noqa: BLE001 — a foreign-domain cookie is data, not a crash
                continue
        return {"deleted": deleted, "restored": restored, "dropped": len(keep) - restored}

    def _op_add_cookies(self, args: dict[str, Any]) -> str:
        cookies = args.get("cookies") or []
        self.context().add_cookies(cookies)
        return f"added {len(cookies)} cookie(s)"

    def _op_clear_cookies(self, args: dict[str, Any]) -> str:
        self.context().clear_cookies()
        return "cookies cleared"

    # --- storage state (context-level) -----------------------------------
    def _op_state_save(self, args: dict[str, Any]) -> dict[str, Any]:
        """Snapshot cookies + web storage to a JSON file (reuse it to skip a login)."""
        path = args.get("path")
        state = self.context().storage_state(path=path)
        return {
            "path": str(Path(path).resolve()) if path else None,
            "cookies": len(state.get("cookies", [])),
            "origins": len(state.get("origins", [])),
        }

    def _op_state_load(self, args: dict[str, Any]) -> str:
        """Apply a snapshot written by ``state_save``.

        Cookies only apply to the currently-loaded domain and web storage is
        per-origin, so navigate to the target origin BEFORE loading.
        """
        path = str(args["path"])
        self.context().restore_storage_state(path)
        return f"restored storage state from {path}"

    # --- javascript ------------------------------------------------------
    def _op_eval(self, args: dict[str, Any]) -> dict[str, Any]:
        """Evaluate a JS function, on the page or on a targeted element.

        With no target the function is called as ``(expression)(arg)``. With a
        target (index / selector / role / target_text) it is called as
        ``(expression)(element, arg)`` — the first parameter is the DOM element.
        """
        expression = args.get("expression", "")
        arg = args.get("arg")
        if self._has_target(args):
            return {"result": self._target(args).first().evaluate(expression, arg)}
        return {"result": self.page().evaluate(expression, arg)}

    # --- request interception (Chromium) ---------------------------------
    def _op_route(self, args: dict[str, Any]) -> dict[str, Any]:
        """Install one interception rule on the session's page."""
        pattern = args.get("pattern")
        if not pattern:
            raise ValueError("route: provide a URL pattern, e.g. '**/api/*'")
        headers = args.get("headers") or {}
        rule = self.page().route(
            str(pattern),
            status=None if args.get("status") is None else int(args["status"]),
            body=None if args.get("body") is None else str(args["body"]),
            content_type=(None if args.get("content_type") is None else str(args["content_type"])),
            headers={str(k): str(v) for k, v in dict(headers).items()},
            abort=bool(args.get("abort", False)),
        )
        return {"route": rule.redacted().to_dict()}

    def _op_unroute(self, args: dict[str, Any]) -> dict[str, Any]:
        """Remove one rule (or every rule when no pattern is given)."""
        pattern = args.get("pattern")
        return {"removed": self.page().unroute(None if pattern is None else str(pattern))}

    def _op_route_list(self, args: dict[str, Any]) -> dict[str, Any]:
        """The installed rules, with secret headers redacted before they leave."""
        return {"routes": [r.redacted().to_dict() for r in self.page().routes()]}

    # --- arbitrary python against the live session (opt-in) ---------------
    def _op_run_code(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute Python with ``page``/``context``/``browser``/``expect`` bound live.

        The escape hatch that turns the command list into a floor instead of a
        ceiling. A single expression is evaluated and returned; a longer snippet is
        executed and whatever it assigned to ``result`` is returned.

        Refused unless the session was started with ``--allow-run-code``: this runs
        anything the caller sends inside a browser holding the user's logins.
        """
        if not self._allow_run_code:
            raise PermissionError(
                "run-code is disabled for this session — it executes arbitrary Python "
                "in your live browser. Restart with "
                "`visus session start --allow-run-code` to enable it."
            )
        code = str(args.get("code") or "")
        if not code.strip():
            raise ValueError("run-code: no code given")
        self._ensure()
        namespace: dict[str, Any] = {
            "page": self.page(),
            "context": self.context(),
            "browser": self._browser,
            "expect": expect,
            "result": None,
        }
        try:
            expression = compile(code, "<visus run-code>", "eval")
        except SyntaxError:
            exec(compile(code, "<visus run-code>", "exec"), namespace, namespace)
            value = namespace.get("result")
        else:
            value = eval(expression, namespace, namespace)
        # The snippet may have navigated, so cached indexes are void either way.
        self._invalidate_fields()
        return {"result": _jsonable(value)}

    # --- tracing ---------------------------------------------------------
    def _op_tracing_start(self, args: dict[str, Any]) -> dict[str, Any]:
        """Start recording every action into an in-memory Recorder.

        This is what makes ``VISUS_WEB_TRACING`` meaningful from the shell:
        ``api/_steps.run_step`` only records when tracing is enabled AND a
        Recorder is installed, and nothing outside ``tracing.record()`` ever
        installed one before this op existed.

        ``screenshots=False`` turns off the per-action PNG — every shot is held
        in memory until the zip is written, so a long run should opt out.
        """
        from visus.web import tracing

        if self._recorder is not None:
            raise RuntimeError(
                f"tracing is already recording (run_id {self._recorder.run_id}) — "
                "run `visus tracing-stop` first"
            )
        zip_path = args.get("zip_path")
        self._trace_zip = str(Path(zip_path).resolve()) if zip_path else None
        self._recorder = tracing.start_recording(
            screenshot_each_action=bool(args.get("screenshots", True))
        )
        return {"run_id": self._recorder.run_id, "zip_path": self._trace_zip}

    def _op_tracing_stop(self, args: dict[str, Any]) -> dict[str, Any]:
        """Write the trace zip (and optionally the HTML report) and stop recording."""
        from visus.web import tracing

        if self._recorder is None:
            raise RuntimeError("tracing is not recording — run `visus tracing-start` first")
        summary = self._recorder.summary()
        zip_path = args.get("zip_path") or self._trace_zip or "run.zip"
        report = args.get("report")
        written = tracing.stop_recording(str(Path(zip_path).resolve()), report)
        self._recorder = None
        self._trace_zip = None
        out: dict[str, Any] = dict(written)
        out["actions"] = summary["total"]
        out["failures"] = summary["failures"]
        return out

    # --- web storage (localStorage / sessionStorage) ----------------------
    # Each helper is a one-arg arrow function: Page.evaluate wraps the
    # expression as ``(<expr>)(arg)``, so the whole payload travels in one dict.
    _STORAGE_LIST_JS = (
        "(a) => { const st = a.session ? sessionStorage : localStorage;"
        " const out = []; for (let i = 0; i < st.length; i++)"
        " { const k = st.key(i); out.push({name: k, value: st.getItem(k)}); }"
        " return out; }"
    )
    _STORAGE_GET_JS = (
        "(a) => { const st = a.session ? sessionStorage : localStorage;"
        " const v = st.getItem(a.key); return {value: v, present: v !== null}; }"
    )
    _STORAGE_SET_JS = (
        "(a) => { const st = a.session ? sessionStorage : localStorage;"
        " st.setItem(a.key, a.value); return true; }"
    )
    _STORAGE_DELETE_JS = (
        "(a) => { const st = a.session ? sessionStorage : localStorage;"
        " const had = st.getItem(a.key) !== null; st.removeItem(a.key); return had; }"
    )
    _STORAGE_CLEAR_JS = (
        "(a) => { const st = a.session ? sessionStorage : localStorage;"
        " const n = st.length; st.clear(); return n; }"
    )

    @staticmethod
    def _storage_kind(args: dict[str, Any]) -> str:
        return "sessionStorage" if args.get("session") else "localStorage"

    def _op_storage_list(self, args: dict[str, Any]) -> dict[str, Any]:
        """Every key/value in the current origin's local or session storage."""
        payload = {"session": bool(args.get("session"))}
        items = self.page().evaluate(self._STORAGE_LIST_JS, payload)
        return {"kind": self._storage_kind(args), "items": items}

    def _op_storage_get(self, args: dict[str, Any]) -> dict[str, Any]:
        """One key. ``present`` distinguishes a stored ``""`` from a missing key."""
        payload = {"session": bool(args.get("session")), "key": str(args.get("key", ""))}
        return cast("dict[str, Any]", self.page().evaluate(self._STORAGE_GET_JS, payload))

    def _op_storage_set(self, args: dict[str, Any]) -> str:
        key, value = str(args.get("key", "")), str(args.get("value", ""))
        payload = {"session": bool(args.get("session")), "key": key, "value": value}
        self.page().evaluate(self._STORAGE_SET_JS, payload)
        return f"{self._storage_kind(args)}[{key!r}] = {value!r}"

    def _op_storage_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = {"session": bool(args.get("session")), "key": str(args.get("key", ""))}
        return {"deleted": bool(self.page().evaluate(self._STORAGE_DELETE_JS, payload))}

    def _op_storage_clear(self, args: dict[str, Any]) -> dict[str, Any]:
        """Clear ONE store — clearing sessionStorage never touches localStorage."""
        payload = {"session": bool(args.get("session"))}
        return {"cleared": int(cast(int, self.page().evaluate(self._STORAGE_CLEAR_JS, payload)))}

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

    def _op_network_requests(self, args: dict[str, Any]) -> dict[str, Any]:
        """Network responses captured so far (mirrors browser_network_requests).

        ``url_filter`` is a plain substring test on the URL. Chromium only.
        """
        url_filter = str(args.get("url_filter") or "")
        out = [
            {
                "index": i,
                "url": r.url,
                "method": r.method,
                "status": r.status,
                "resource_type": r.resource_type,
            }
            for i, r in enumerate(self.page().network_requests())
        ]
        if url_filter:
            out = [r for r in out if url_filter in str(r["url"])]
        return {"requests": out}

    def _op_network_request(self, args: dict[str, Any]) -> dict[str, Any]:
        """One captured response by index, including its body.

        The body is fetched lazily over CDP and can be evicted after a
        navigation; an unavailable body is reported as ``None``, never raised.
        """
        index = int(args.get("index", 0))
        responses = self.page().network_requests()
        if index < 0 or index >= len(responses):
            raise IndexError(
                f"request index {index} out of range "
                f"(have {len(responses)}; run `visus requests` first)"
            )
        r = responses[index]
        try:
            body: str | None = r.body()
        except Exception:  # noqa: BLE001 — an evicted body is data, not a failure
            body = None
        return {
            "index": index,
            "url": r.url,
            "method": r.method,
            "status": r.status,
            "resource_type": r.resource_type,
            "body": body,
        }

    def _op_network_capture_start(self, args: dict[str, Any]) -> dict[str, Any]:
        """Install the JS traffic hook on the current page.

        Complements ``network_requests``: that op reads the delegate's CDP
        buffer (every response, incl. assets and redirect legs); this one records
        what the PAGE initiated — request bodies, JSONP ``<script>``,
        ``sendBeacon`` and ``<img>`` pings — which CDP response logging cannot
        give. ``use_cdp=False`` keeps the two off the same destructive
        ``get_log("performance")`` stream.

        Idempotent: starting twice rebinds and re-arms without losing the buffer.
        """
        from visus.web.network import NetworkCapture

        page = self.page()
        if self._capture is None:
            self._capture = NetworkCapture(page, use_cdp=False)
            self._capture.start()
        else:
            self._capture.rebind(page)
        return {"started": True}

    def _op_network_capture_stop(self, args: dict[str, Any]) -> dict[str, Any]:
        """Uninstall the hook and report how many entries were captured."""
        if self._capture is None:
            raise RuntimeError("no capture is running — run `visus network start` first")
        self._capture.rebind(self.page())
        captured = len(self._capture.get_requests())
        self._capture.stop()
        self._capture = None
        return {"stopped": True, "captured": captured}

    def _op_network_capture_export(self, args: dict[str, Any]) -> dict[str, Any]:
        """Write the captured traffic as ``{target_url, entries}`` JSON (scrubbed)."""
        if self._capture is None:
            raise RuntimeError("no capture is running — run `visus network start` first")
        path = str(args.get("path") or "capture.json")
        self._capture.rebind(self.page())
        entries = len(self._capture.get_requests())
        self._capture.export_enriched(path)
        return {"path": str(Path(path).resolve()), "entries": entries}

    # --- vision (requires the [vision] extra) ----------------------------
    def _op_read_text(self, args: dict[str, Any]) -> str:
        return self._target(args).ocr_text()

    def _op_solve_captcha(self, args: dict[str, Any]) -> str:
        # com alvo: o OCR de um captcha de texto; sem alvo: o reCAPTCHA/Turnstile/hCaptcha
        # da página, pelo serviço da chave que o cliente mandou (nunca vai para log)
        if self._has_target(args):
            return self.page().solve_captcha(self._target(args))
        timeout = args.get("timeout")
        return self.page().solve_captcha(
            provider=args.get("provider"),
            api_key=args.get("api_key"),
            timeout=None if timeout is None else float(timeout),
        )

    def _op_find_image(self, args: dict[str, Any]) -> dict[str, Any]:
        import io

        import numpy as np
        from PIL import Image as PILImage

        from visus.web.vision import find_image

        template_path = args.get("template_path", "")
        confidence = float(args.get("confidence", 0.8))
        page = self.page()
        if (
            args.get("selector")
            or args.get("role")
            or args.get("target_text")
            or (args.get("index") is not None)
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

    def _device_pixel_ratio(self) -> float:
        """CSS pixels per screenshot pixel (1.0 on a standard-DPI display).

        A screenshot is captured in DEVICE pixels while the mouse device speaks
        CSS viewport pixels, so on a HiDPI display a match at screenshot (400,200)
        must be clicked at CSS (200,100). An unreadable ratio degrades to 1:1
        rather than failing the click.
        """
        try:
            value = self.page().evaluate("() => window.devicePixelRatio")
        except Exception:  # noqa: BLE001 — telemetry, never the result
            return 1.0
        try:
            ratio = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1.0
        return ratio if ratio > 0 else 1.0

    def _op_click_image(self, args: dict[str, Any]) -> dict[str, Any]:
        """Click the centre of a template image found on the page (or in an element).

        The last-resort target. A canvas app, an embedded PDF viewer or a
        third-party widget with no accessibility tree exposes no role, no name and
        no stable selector — but it still renders pixels, and those can be matched
        and pressed. Give a target (index / selector / role / text) to scope the
        search to one element; the element's own box is then added back so the
        click lands in page coordinates.
        """
        from visus.web.vision import find_image

        template_path = str(args.get("template_path") or "")
        confidence = float(args.get("confidence", 0.8))
        page = self.page()
        origin_x = origin_y = 0.0
        if self._has_target(args):
            loc = self._target(args)
            shot = loc.screenshot()
            box = loc.bounding_box()
            if box is not None:
                origin_x, origin_y = float(box["x"]), float(box["y"])
        else:
            shot = page.screenshot()
        match = find_image(shot, template_path, confidence=confidence)
        if match is None:
            raise LookupError(
                f"template {template_path!r} not found on the page at confidence >= {confidence}"
            )
        ratio = self._device_pixel_ratio()
        x = origin_x + match.center_x / ratio
        y = origin_y + match.center_y / ratio
        page.mouse.click(x, y)
        return {"x": round(x, 1), "y": round(y, 1), "confidence": round(match.confidence, 4)}

    def _op_click_ocr_text(self, args: dict[str, Any]) -> dict[str, Any]:
        """Click the centre of RENDERED text located by OCR.

        For text that exists as pixels and not as a DOM node — canvas-drawn
        labels, an embedded PDF, a chart legend, an image button. Matching is a
        case-insensitive substring by default because OCR routinely merges or
        splits neighbouring words; pass ``exact_text`` to require the whole run.
        A target scopes the search to one element and its box is added back so the
        click lands in page coordinates.
        """
        from visus.web.vision import find_text

        needle = str(args.get("ocr_text") or "")
        exact = bool(args.get("exact_text", False))
        page = self.page()
        origin_x = origin_y = 0.0
        if self._has_target(args):
            loc = self._target(args)
            shot = loc.screenshot()
            box = loc.bounding_box()
            if box is not None:
                origin_x, origin_y = float(box["x"]), float(box["y"])
        else:
            shot = page.screenshot()
        found = find_text(shot, needle, exact=exact)
        if found is None:
            raise LookupError(f"no rendered text matching {needle!r} was found on the page")
        ratio = self._device_pixel_ratio()
        x = origin_x + found.center_x / ratio
        y = origin_y + found.center_y / ratio
        page.mouse.click(x, y)
        return {
            "x": round(x, 1),
            "y": round(y, 1),
            "text": found.text,
            "confidence": round(found.confidence, 4),
        }

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

    def _op_tab_activate(self, args: dict[str, Any]) -> dict[str, Any]:
        """Focus a tab by its stable window handle (from ``tabs``).

        Handles survive reordering and tab closes; indices do not.
        """
        self._ensure()
        driver = self._driver()
        if driver is None:
            raise RuntimeError("no live browser")
        handle = str(args.get("handle") or "")
        handles = list(driver.window_handles)
        if handle not in handles:
            raise ValueError(f"no open tab with handle {handle!r}")
        self._known_handles = list(handles)
        self._active_handle = handle
        self._invalidate_fields()  # cached indexes belonged to the previous tab
        try:
            driver.switch_to.window(handle)
            title = driver.title
        except Exception:  # noqa: BLE001
            title = ""
        return {"active": handles.index(handle), "handle": handle, "title": title}

    def _op_tab_follow(self, args: dict[str, Any]) -> dict[str, Any]:
        """Choose how new tabs/popups are handled.

        ``enabled=True`` (the daemon default): AUTO-FOLLOW — subsequent ops target
        the most recently opened tab/popup. ``enabled=False``: MANUAL — a click that
        opens a popup does not change the context; steer with ``tabs``/``tab``.
        """
        enabled = bool(args.get("enabled", True))
        self._follow = enabled
        if not enabled:
            # Pin the context where it is now so the next op cannot drift.
            driver = self._driver()
            if driver is not None:
                try:
                    handles = list(driver.window_handles)
                except Exception:  # noqa: BLE001
                    handles = []
                if handles:
                    self._known_handles = list(handles)
                    if self._active_handle not in handles:
                        self._active_handle = handles[-1]
        return {"follow": self._follow}

    def _op_status(self, args: dict[str, Any]) -> dict[str, Any]:
        """Report session state. READ-ONLY: never adopts a background window."""
        running = self._browser is not None
        info: dict[str, Any] = {
            "running": running,
            "engine": self._engine,
            "headless": self._headless,
            "allow_run_code": self._allow_run_code,
            "attached": self._attached,
            "device": self._device,
            "follow": self._follow,
            "user_data_dir": self._user_data_dir,
            "remote_url": self._remote_url,
            "slow_mo": self._slow_mo,
            "fields_cached": len(self._fields),
        }
        pending = self._open_dialog_text() if running else None
        if pending is not None:
            info["dialog"] = pending
            return info
        if running:
            try:
                p = self._peek_page()
                info["url"] = p.url
                info["title"] = p.title()
                driver = self._driver()
                handles = (
                    list(driver.window_handles) if driver is not None else list(self._known_handles)
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

    def _op_detach(self, args: dict[str, Any]) -> str:
        """End the session while leaving an ATTACHED browser exactly as it is."""
        if not self._attached:
            raise RuntimeError(
                "detach only works on a session created by `visus session attach` — "
                "use `visus session stop` to close a browser visus launched"
            )
        self.detach()
        if self._stop is not None:
            self._stop.set()
        return "detached — the browser stays open"

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


def sessions_dir(cwd: str | Path | None = None) -> Path:
    """Directory holding this project's named session files."""
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".visus" / "sessions"


def session_file(cwd: str | Path | None = None, name: str | None = None) -> Path:
    """Path to ``.visus/sessions/<name>.json`` under *cwd* (default: process cwd).

    ``.visus/`` is already the daemon's directory, so the namespace lives inside
    it. The ownership lock is ``<name>.json.lock``, which :func:`_claim_lock`
    derives from this path without any change.
    """
    return sessions_dir(cwd) / f"{name or 'default'}.json"


def visus_home() -> Path:
    """The per-user visus directory — ``VISUS_WEB_HOME`` when set, else ``~/.visus``.

    The override exists so tests and CI never touch a real home directory; the
    registry it holds is the ONLY visus state outside the project tree.
    """
    override = os.environ.get("VISUS_WEB_HOME")
    return Path(override) if override else Path.home() / ".visus"


def registry_dir() -> Path:
    """Directory of the cross-project session registry."""
    return visus_home() / "sessions"


def registry_file(cwd: str | Path, name: str) -> Path:
    """Registry path for session *name* under *cwd*.

    Keyed by a hash of the ABSOLUTE cwd plus the session name: a daemon started in
    another project is otherwise invisible (discovery only walks upward) and so
    can be neither listed nor killed from the CLI.
    """
    resolved = str(Path(cwd).resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
    return registry_dir() / f"{digest}-{name}.json"


def _register(
    sf: Path,
    *,
    name: str,
    cwd: Path,
    pid: int,
    port: int,
    engine: str,
    headless: bool,
    url: str | None,
) -> Path | None:
    """Mirror a live session into the registry. Returns the entry path, or ``None``.

    Deliberately token-free: the shared secret stays in the owner-only session
    file, and the entry records that file's PATH so a caller who can read it can
    still shut the daemon down politely. Never raises — a read-only or missing
    home must not stop a daemon from serving.
    """
    try:
        entry = registry_file(cwd, name)
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text(
            json.dumps(
                {
                    "name": name,
                    "cwd": str(cwd),
                    "file": str(sf),
                    "pid": pid,
                    "port": port,
                    "engine": engine,
                    "headless": headless,
                    "url": url,
                    "started_at": time.time(),
                }
            ),
            encoding="utf-8",
        )
        return entry
    except OSError:
        return None


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
                if stop.is_set():
                    # the op ended the session (the last tab closed): this connection
                    # is done -- reading on held the daemon open until the client hung
                    # up or the whole shutdown grace ran out
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
    name: str | None = None,
) -> None:
    """Bind a JSON-lines TCP server, write the session file, serve until shutdown.

    *idle_timeout* (seconds, ``None`` = never) reaps a session nobody is using:
    an abandoned headed browser otherwise sits on the desktop forever.
    *name* selects the ``.visus/sessions/<name>.json`` state file, so several
    daemons can serve the same project directory at once.
    """
    resolved_name = name or "default"
    sf = session_file(cwd, resolved_name)
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
            "name": resolved_name,
            "cwd": str((Path(cwd) if cwd is not None else Path.cwd()).resolve()),
            "pid": os.getpid(),
            "port": port,
            "token": token,
            "engine": handler._engine,
            "headless": handler._headless,
            "url": handler._url,
            "user_data_dir": handler._user_data_dir,
            "remote_url": handler._remote_url,
            "slow_mo": handler._slow_mo,
            "device": handler._device,
            "allow_run_code": handler._allow_run_code,
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

    # Mirror the session into the cross-project registry: discovery only walks
    # UP, so without this a daemon started in a sibling project can be neither
    # listed nor stopped from here. Best-effort — a registry write must never
    # keep a working daemon from serving.
    base_dir = (Path(cwd) if cwd is not None else Path.cwd()).resolve()
    registry_entry = _register(
        sf,
        name=resolved_name,
        cwd=base_dir,
        pid=os.getpid(),
        port=port,
        engine=handler._engine,
        headless=handler._headless,
        url=handler._url,
    )

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
        if handler.detached():
            # An attached browser belongs to the user: end the WebDriver session,
            # never the window.
            handler.release()
        else:
            handler.close()
        try:
            sf.unlink()
        except OSError:
            pass
        try:
            lock.unlink()
        except OSError:
            pass
        if registry_entry is not None:
            try:
                registry_entry.unlink()
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
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
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
    name = os.environ.get("VISUS_WEB_SESSION") or "default"
    user_data_dir = os.environ.get("VISUS_WEB_USER_DATA_DIR") or None
    remote_url = os.environ.get("VISUS_WEB_REMOTE_URL") or None
    try:
        slow_mo = int(os.environ.get("VISUS_WEB_SLOW_MO") or 0)
    except ValueError:
        slow_mo = 0
    allow_run_code = os.environ.get("VISUS_WEB_ALLOW_RUN_CODE", "0") not in (
        "0",
        "",
        "false",
        "False",
        "no",
    )
    debugger_address = os.environ.get("VISUS_WEB_DEBUGGER_ADDRESS") or None
    device = os.environ.get("VISUS_WEB_DEVICE") or None

    log_dir = Path.cwd() / ".visus"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = _make_logger(log_dir / "daemon.log")

    def _log(msg: str) -> None:
        logger.info(msg)

    _log(
        f"daemon starting session={name!r} engine={engine} headless={headless} "
        f"url={url!r} user_data_dir={user_data_dir!r} remote_url={remote_url!r} "
        f"slow_mo={slow_mo} allow_run_code={allow_run_code} pid={os.getpid()}"
    )
    handler = SessionHandler(
        engine=engine,
        headless=headless,
        url=url,
        user_data_dir=user_data_dir,
        remote_url=remote_url,
        slow_mo=slow_mo,
        allow_run_code=allow_run_code,
        debugger_address=debugger_address,
        device=device,
    )
    try:
        serve(handler, token=token, idle_timeout=_idle_timeout_from_env(), name=name)
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
