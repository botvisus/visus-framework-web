"""Session singleton + locator helper for the visus-web MCP server."""

from __future__ import annotations

import os
from typing import Any

from visus.web import Engine, launch
from visus.web.api.browser import Browser
from visus.web.api.context import Context
from visus.web.api.fields import Field
from visus.web.api.locator import Locator
from visus.web.api.page import Page
from visus.web.backends.selenium.driver_delegate import SeleniumPageDelegate
from visus.web.ops.targeting import make_locator, resolve_field

__all__ = ["Session", "make_locator"]


class Session:
    """Manages a single browser + multi-tab page list for the MCP server."""

    def __init__(self) -> None:
        self._browser: Browser | None = None
        self._context: Context | None = None
        self._pages: list[Page] = []
        self._current_idx: int = 0
        # Tab-follow mode (opt-in). Manual by default: a click that opens a new
        # tab/popup does NOT silently change the active context — the agent steers
        # with tab_list/tab_select (predictable). When enabled, page() auto-follows
        # the most recently opened window/tab (like the CLI daemon).
        self._follow: bool = False
        self._known_handles: list[str] = []
        self._active_handle: str | None = None
        # The last browser_list_fields result, so an action tool can act by INDEX
        # and get the daemon's frame/shadow re-resolution for free. Stamped with
        # the page it was captured on: a stale index must refuse, never re-resolve
        # a generic fallback selector against a page it never described.
        self._fields: list[Field] = []
        self._fields_url: str | None = None

    def _ensure(self) -> None:
        if self._browser is None:
            engine_str = os.environ.get("VISUS_WEB_ENGINE", "chrome")
            headless = os.environ.get("VISUS_WEB_HEADLESS", "1") != "0"
            self._browser = launch(Engine.from_str(engine_str), headless=headless)
            self._context = self._browser.new_context()
            first = self._context.new_page()
            self._pages = [first]
            self._current_idx = 0

    def page(self) -> Page:
        self._ensure()
        base = self._pages[self._current_idx]
        if not self._follow:
            return base  # manual (default): explicit tab control via tab_select
        driver = getattr(getattr(base, "_delegate", None), "_driver", None)
        if driver is None:
            return base
        try:
            handles = list(driver.window_handles)
        except Exception:  # noqa: BLE001
            return base
        if not handles:
            return base
        new = [h for h in handles if h not in self._known_handles]
        self._known_handles = list(handles)
        active = new[-1] if new else self._active_handle  # follow the newest new tab/popup
        if active is None or active not in handles:
            active = handles[-1]
        self._active_handle = active
        if getattr(base._delegate, "_handle", None) == active:
            return base
        return Page(SeleniumPageDelegate(driver, active), base._defaults)

    def set_follow(self, enabled: bool) -> bool:
        """Toggle auto-follow of newly-opened tabs/popups (default off = manual)."""
        self._follow = bool(enabled)
        if not self._follow:
            self._active_handle = None
        return self._follow

    def invalidate_fields(self) -> None:
        """Drop the cached field list and its page stamp — index targeting is void."""
        self._fields = []
        self._fields_url = None

    def cache_fields(self, fields: list[Field]) -> None:
        """Remember an enumeration so index targeting can re-resolve from it."""
        self._fields = list(fields)
        self._fields_url = self.page().url

    def field_locator(self, index: int) -> Locator:
        """Re-resolve cached field *index* — iframe chain and shadow ``deep`` included.

        Bounds-checked BEFORE ``page()`` is touched: ``page()`` lazily launches a
        browser, and an out-of-range index is an argument error that must not
        cost one.
        """
        if index < 0 or index >= len(self._fields):
            raise IndexError(
                f"field index {index} out of range "
                f"(have {len(self._fields)}; run list_fields first)"
            )
        return resolve_field(self.page(), self._fields, index, fields_url=self._fields_url)

    def target(self, args: dict[str, Any]) -> Locator:
        """Resolve an action target from the DAEMON's payload keys.

        Deliberately the daemon's spelling — ``index`` first, then
        ``selector``/``role``/``name``/``target_text``/``exact``/``frame`` — so a
        single payload dict serves both this in-process resolver and
        ``RemoteDispatcher``. ``target_text`` (not ``text``) is the locator-text
        key, because ``text`` is already fill's VALUE payload.
        """
        nth = args.get("nth")
        if args.get("index") is not None:
            field = self.field_locator(int(args["index"]))
            return field.nth(int(nth)) if nth is not None else field
        if all(args.get(key) is None for key in ("selector", "role", "target_text")):
            # Validate before page(): a missing target is an argument error, and
            # page() would lazily LAUNCH A BROWSER just to report it.
            raise ValueError("provide one of: index, role, text, selector")
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

    def context(self) -> Context:
        self._ensure()
        assert self._context is not None
        return self._context

    def new_page(self, url: str | None = None) -> Page:
        self._ensure()
        assert self._context is not None
        p = self._context.new_page()
        self._pages.append(p)
        self._current_idx = len(self._pages) - 1
        self.invalidate_fields()  # cached indexes belonged to the previous tab
        if url is not None:
            p.goto(url)
        return p

    def pages(self) -> list[Page]:
        self._ensure()
        assert self._context is not None
        # Surface tabs opened outside our tracking (a link / window.open) by
        # reconciling against the live window handles — additive, dedup by handle.
        seen = {p.handle for p in self._pages}
        for p in self._context.adopt_open_windows():
            if p.handle not in seen:
                self._pages.append(p)
                seen.add(p.handle)
        return list(self._pages)

    def select(self, index: int) -> Page:
        self._ensure()
        if index < 0 or index >= len(self._pages):
            raise IndexError(f"tab index {index} out of range (have {len(self._pages)} tabs)")
        self._current_idx = index
        self.invalidate_fields()  # cached indexes belonged to the previous tab
        return self._pages[index]

    def activate(self, handle: str) -> Page:
        """Focus a tab by its stable window handle (reconciles external tabs first)."""
        self.pages()  # reconcile so externally-opened tabs are selectable
        for i, p in enumerate(self._pages):
            if p.handle == handle:
                p.bring_to_front()
                self._current_idx = i
                self.invalidate_fields()  # cached indexes belonged to the previous tab
                return p
        raise ValueError(f"no open tab with handle {handle!r}")

    def close_tab(self, index: int | None = None) -> None:
        self._ensure()
        idx = self._current_idx if index is None else index
        if idx < 0 or idx >= len(self._pages):
            raise IndexError(f"tab index {idx} out of range")
        self._pages[idx].close()
        self._pages.pop(idx)
        if not self._pages:
            # all tabs closed — reset
            self.close()
        else:
            self._current_idx = min(idx, len(self._pages) - 1)
            self.invalidate_fields()  # cached indexes belonged to the closed tab

    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        self._browser = None
        self._context = None
        self._pages = []
        self._current_idx = 0
        self._follow = False
        self._known_handles = []
        self._active_handle = None
        self.invalidate_fields()


