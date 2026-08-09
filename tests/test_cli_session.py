"""Fast unit tests for the persistent-session CLI.

Covers:
  * SessionHandler.handle pure paths with a fake page (+ a real headless page for
    actions, marked browser),
  * console.dispatch with a fake send,
  * session-file discovery + stale cleanup (isolated via tmp_path),
  * Typer CliRunner arg parsing with session_client monkeypatched.

NEVER writes .visus into the repo root — all session files live under tmp_path.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


def _patch_client(monkeypatch: pytest.MonkeyPatch, fake: Any) -> None:
    """Point BOTH client entry points at one fake.

    `session_client.send` returns only `result`; `send_envelope` returns the whole
    reply. Mutating commands go through `send_envelope`, plain reads through
    `send`, so a test that stubs only one of them silently reaches a real socket.
    """
    monkeypatch.setattr(session_client, "send", fake)
    monkeypatch.setattr(
        session_client,
        "send_envelope",
        lambda op, args=None, **_: {"ok": True, "result": fake(op, args)},
    )


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeLocator:
    def __init__(self, log: list[str], label: str = "loc") -> None:
        self._log = log
        self._label = label

    def first(self) -> _FakeLocator:
        return self

    def frame_locator(self, sel: str) -> _FakeLocator:
        return _FakeLocator(self._log, f"{self._label}>frame({sel})")

    def locator(self, selector: str, *, deep: bool = False) -> _FakeLocator:
        return _FakeLocator(self._log, f"{self._label}>loc({selector},deep={deep})")

    def get_by_role(
        self, role: str, *, name: str | None = None, exact: bool = False
    ) -> _FakeLocator:
        return _FakeLocator(self._log, f"role({role},{name})")

    def get_by_text(self, text: str, *, exact: bool = False) -> _FakeLocator:
        return _FakeLocator(self._log, f"text({text})")

    def click(self) -> None:
        self._log.append(f"click:{self._label}")

    def fill(self, text: str) -> None:
        self._log.append(f"fill:{self._label}:{text}")

    def check(self) -> None:
        self._log.append(f"check:{self._label}")

    def uncheck(self) -> None:
        self._log.append(f"uncheck:{self._label}")

    def select_option(self, *, value: str | None = None) -> None:
        self._log.append(f"select:{self._label}:{value}")

    def press(self, key: str) -> None:
        self._log.append(f"press:{self._label}:{key}")

    def hover(self) -> None:
        self._log.append(f"hover:{self._label}")

    def dblclick(self) -> None:
        self._log.append(f"dblclick:{self._label}")

    def focus(self) -> None:
        self._log.append(f"focus:{self._label}")

    def clear(self) -> None:
        self._log.append(f"clear:{self._label}")

    def drag_to(self, target: _FakeLocator) -> None:
        self._log.append(f"drag:{self._label}->{target._label}")

    def set_input_files(self, paths: list[str]) -> None:
        self._log.append(f"upload:{self._label}:{','.join(paths)}")

    def count(self) -> int:
        self._log.append(f"count:{self._label}")
        return 3

    def nth(self, i: int) -> _FakeLocator:
        return _FakeLocator(self._log, f"{self._label}[{i}]")

    def is_visible(self) -> bool:
        return True

    def get_attribute(self, name: str) -> str:
        return f"attr:{self._label}:{name}"

    def ocr_text(self) -> str:
        return f"ocr:{self._label}"

    def text_content(self) -> str:
        return f"text-of:{self._label}"

    def screenshot(self, *, path: str | None = None) -> bytes:
        self._log.append(f"screenshot:{self._label}")
        if path:
            Path(path).write_bytes(b"PNG")
        return b"PNG"


class _FakeField:
    def __init__(self, index: int, locator: str, frame: list[str], deep: bool) -> None:
        self.index = index
        self.locator = locator
        self.frame = frame
        self.deep = deep
        self.kind = "input"
        self.name = f"f{index}"
        self.role = None
        chain = "".join(f'.frame_locator("{sel}")' for sel in frame)
        self.code = f'page{chain}.locator("{locator}")'

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "kind": self.kind,
            "name": self.name,
            "role": self.role,
            "locator": self.locator,
            "frame": self.frame,
            "deep": self.deep,
            "code": self.code,
        }


class _FakePage:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.url = "about:blank"
        self._fields = [
            _FakeField(0, "#a", [], False),
            _FakeField(1, "#b", ["#f1"], True),
        ]

    def list_fields(
        self, *, kinds: Any = None, include_hidden: bool = False, highlight: bool = True
    ):
        self.log.append(f"list_fields:kinds={kinds}:hidden={include_hidden}:hl={highlight}")
        return self._fields

    def frame_locator(self, sel: str) -> _FakeLocator:
        return _FakeLocator(self.log, f"frame({sel})")

    def locator(self, selector: str, *, deep: bool = False) -> _FakeLocator:
        return _FakeLocator(self.log, f"loc({selector},deep={deep})")

    def get_by_role(
        self, role: str, *, name: str | None = None, exact: bool = False
    ) -> _FakeLocator:
        return _FakeLocator(self.log, f"role({role},{name})")

    def get_by_text(self, text: str, *, exact: bool = False) -> _FakeLocator:
        return _FakeLocator(self.log, f"text({text})")

    def goto(self, url: str) -> None:
        self.log.append(f"goto:{url}")
        self.url = url

    def title(self) -> str:
        return "FakeTitle"

    def go_back(self) -> None:
        self.log.append("go_back")
        self.url = "about:back"

    def go_forward(self) -> None:
        self.log.append("go_forward")
        self.url = "about:forward"

    def reload(self) -> None:
        self.log.append("reload")

    def snapshot(
        self, selector: str | None = None, *, depth: int | None = None
    ) -> list[dict[str, Any]]:
        self.log.append(f"snapshot:selector={selector}:depth={depth}")
        return [
            {"role": "button", "name": "Go", "depth": 0},
            {"role": "textbox", "name": "Email", "depth": 1},
        ]

    def evaluate(self, expression: str, arg: object = None) -> object:
        self.log.append(f"eval:{expression}:{arg}")
        return {"expr": expression, "arg": arg}

    def solve_captcha(self, loc: _FakeLocator) -> str:
        return f"captcha:{loc._label}"

    def clear_highlights(self) -> None:
        self.log.append("clear_highlights")

    def screenshot(self, *, path: str | None = None, full_page: bool = False) -> bytes:
        self.log.append(f"screenshot:full_page={full_page}")
        if path:
            Path(path).write_bytes(b"PNG")
        return b"PNG"


class _FakeContext:
    def __init__(self) -> None:
        self._cookies: list[dict[str, Any]] = [
            {"name": "sid", "value": "abc", "domain": "x.test"}
        ]

    def cookies(self) -> list[dict[str, Any]]:
        return list(self._cookies)

    def add_cookies(self, cookies: list[dict[str, Any]]) -> None:
        self._cookies.extend(cookies)

    def clear_cookies(self) -> None:
        self._cookies = []


class _FakeBrowser:
    def __init__(self) -> None:
        self.closed = False
        self._context = _FakeContext()

    @property
    def contexts(self) -> list[_FakeContext]:
        return [self._context]

    def close(self) -> None:
        self.closed = True


def _handler_with_fake_page(page: _FakePage) -> session_server.SessionHandler:
    h = session_server.SessionHandler(engine="chrome", headless=True)
    h._browser = _FakeBrowser()  # mark as "running" so _ensure() is a no-op
    h._page = page  # type: ignore[assignment]
    return h


# ---------------------------------------------------------------------------
# SessionHandler.handle — pure paths (fake page, no sockets, no browser)
# ---------------------------------------------------------------------------


def test_handle_unknown_op_returns_error() -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True)
    resp = h.handle("nope", {})
    assert resp["ok"] is False
    assert "unknown op" in resp["error"]


def test_handle_list_fields_caches_and_returns_dicts() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("list_fields", {"kinds": ["input"], "include_hidden": True, "highlight": False})
    assert resp["ok"] is True
    fields = resp["result"]["fields"]
    assert [f["index"] for f in fields] == [0, 1]
    assert h._fields  # cached for index targeting
    assert "list_fields:kinds=['input']:hidden=True:hl=False" in page.log


def test_handle_click_by_index_reresolves_via_frame_and_deep() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("list_fields", {})
    resp = h.handle("click", {"index": 1})  # field 1 has frame=['#f1'], deep=True
    assert resp["ok"] is True and resp["result"] == "clicked"
    # The cached field was re-resolved through frame_locator(#f1).locator(#b, deep=True).
    assert any("click:frame(#f1)>loc(#b,deep=True)" == e for e in page.log)


def test_handle_click_index_out_of_range_is_clean_error() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("list_fields", {})
    resp = h.handle("click", {"index": 99})
    assert resp["ok"] is False
    assert "out of range" in resp["error"]


def test_handle_actions_by_selector_use_make_locator() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    assert h.handle("fill", {"selector": "#x", "text": "hi"})["result"] == "filled with 'hi'"
    assert h.handle("check", {"selector": "#c"})["result"] == "checked"
    assert h.handle("uncheck", {"selector": "#c"})["result"] == "unchecked"
    assert h.handle("select", {"selector": "#s", "value": "v"})["result"] == "selected 'v'"
    assert h.handle("press", {"selector": "#i", "key": "Enter"})["result"] == "pressed 'Enter'"
    assert "fill:loc(#x,deep=False):hi" in page.log


def test_handle_get_text_by_role() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("get_text", {"role": "button", "name": "OK"})
    assert resp["ok"] is True
    assert resp["result"] == {"value": "text-of:role(button,OK)", "present": True}


def test_handle_get_text_by_index_reresolves_via_frame_and_deep() -> None:
    """Index read re-resolves the cached field (frame chain + deep) before .text_content()."""
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("list_fields", {})
    resp = h.handle("get_text", {"index": 1})  # field 1: frame=['#f1'], deep=True
    assert resp["ok"] is True
    assert resp["result"] == {"value": "text-of:frame(#f1)>loc(#b,deep=True)", "present": True}


def test_handle_target_text_resolves_via_get_by_text_not_fill_value() -> None:
    """target_text maps to get_by_text; the load-bearing text/target_text split."""
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("click", {"target_text": "Save", "exact": True})
    assert resp["ok"] is True and resp["result"] == "clicked"
    # Re-resolved via get_by_text('Save', ...) -> _FakeLocator label "text(Save)".
    assert any(e == "click:text(Save)" for e in page.log)


def test_handle_target_without_target_errors() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("click", {})  # no index, no selector/role/text
    assert resp["ok"] is False
    assert "provide one of" in resp["error"]


def test_handle_mutating_op_carries_page_state() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("click", {"selector": "#go"})
    assert resp["ok"] is True and resp["result"] == "clicked"
    assert resp["page"] == {
        "url": "about:blank",
        "title": "FakeTitle",
        "fields_stale": False,
    }


def test_handle_read_op_carries_no_page_state() -> None:
    """Reads stay bare so `visus --raw get-text 3 | wc -c` is not polluted."""
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("get_text", {"selector": "#x"})
    assert resp["ok"] is True
    assert "page" not in resp


def test_handle_failed_op_carries_no_page_state() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("click", {})  # no target at all
    assert resp["ok"] is False
    assert "page" not in resp


def test_post_state_flags_a_stale_field_cache() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("list_fields", {})          # stamps _fields_url = "about:blank"
    resp = h.handle("goto", {"url": "http://elsewhere"})
    assert resp["ok"] is True
    # PLAN 3's navigation ops clear the cache, so a fresh index is impossible to
    # misuse; when JS moved the page instead, the URL stamp still catches it.
    h._fields = list(page._fields)       # simulate a JS-driven navigation
    h._fields_url = "about:blank"
    state = h._post_state()
    assert state["fields_stale"] is True


def test_post_state_never_raises() -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True)  # no browser
    h._browser = _FakeBrowser()
    h._page = None  # type: ignore[assignment]
    assert h._post_state() == {}


def test_mutating_ops_cover_every_state_changing_op() -> None:
    """Exact-equality inventory — a cross-plan tripwire.

    A later plan that adds a new state-changing `_op_*` without adding its name
    here fails LOUDLY, right here, rather than silently shipping a mutating op
    with no `page` footer. The assert message names exactly which op(s) are
    missing/extra so the fix is a one-line diff, not an investigation.
    """
    expected = frozenset(
        {
            "click", "dblclick", "fill", "check", "uncheck", "select", "press",
            "hover", "focus", "clear_input", "drag", "drop", "upload", "goto", "back",
            "forward", "reload", "tab", "tab_new", "tab_close", "dialog",
            "add_cookies", "clear_cookies", "eval", "route", "unroute", "run_code",
            "state_load",
            "type", "key_down", "key_up",
            "mouse_move", "mouse_down", "mouse_up", "mouse_wheel", "resize",
            "click_image", "click_ocr_text",
            "storage_set", "storage_delete", "storage_clear",
            "cookie_set", "cookie_delete",
        }
    )
    actual = session_server._MUTATING_OPS
    missing = expected - actual
    extra = actual - expected
    assert actual == expected, (
        f"_MUTATING_OPS drifted from the expected inventory — "
        f"missing (add these to _MUTATING_OPS): {sorted(missing) or 'none'}; "
        f"extra (remove or update this test): {sorted(extra) or 'none'}. "
        f"A new state-changing op MUST be added to _MUTATING_OPS in the same "
        f"commit that adds its _op_<name> method, or it silently ships with no "
        f"`page` footer."
    )


# ---------------------------------------------------------------------------
# New ops — parity with the MCP browser_* tools (fake page/locator/context)
# ---------------------------------------------------------------------------


def test_handle_navigation_back_forward_reload() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    assert h.handle("back", {})["result"] == "about:back"
    assert h.handle("forward", {})["result"] == "about:forward"
    assert h.handle("reload", {})["result"] == page.url  # reload doesn't change url
    assert "go_back" in page.log and "go_forward" in page.log and "reload" in page.log


def test_handle_title_url_snapshot() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    assert h.handle("title", {})["result"] == "FakeTitle"
    assert h.handle("url", {})["result"] == page.url
    snap = h.handle("snapshot", {})["result"]
    assert snap["elements"][0]["role"] == "button"
    assert snap["elements"][0]["name"] == "Go"
    assert "ref" in snap["elements"][0]


def test_handle_get_attribute_and_count() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("get_attribute", {"selector": "#a", "attr_name": "href"})
    assert resp["result"] == {"value": "attr:loc(#a,deep=False):href", "present": True}
    assert h.handle("count", {"selector": "#a"})["result"] == 3


def test_handle_hover_dblclick_focus_clear_input_by_selector() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    assert h.handle("hover", {"selector": "#h"})["result"] == "hovered"
    assert h.handle("dblclick", {"selector": "#d"})["result"] == "double-clicked"
    assert h.handle("focus", {"selector": "#f"})["result"] == "focused"
    assert h.handle("clear_input", {"selector": "#ci"})["result"] == "cleared"
    assert "hover:loc(#h,deep=False)" in page.log
    assert "dblclick:loc(#d,deep=False)" in page.log
    assert "focus:loc(#f,deep=False)" in page.log
    assert "clear:loc(#ci,deep=False)" in page.log


def test_handle_drag_by_selector_target() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("drag", {"selector": "#src", "target_selector": "#dst"})
    assert resp["ok"] is True and resp["result"] == "dragged to '#dst'"
    assert "drag:loc(#src,deep=False)->loc(#dst,deep=False)" in page.log


def test_handle_drag_by_index_targets() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("list_fields", {})
    resp = h.handle("drag", {"index": 0, "target_index": 1})
    assert resp["ok"] is True and "dragged to field 1" == resp["result"]


def test_handle_drag_without_target_errors() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("drag", {"selector": "#src"})
    assert resp["ok"] is False and "drag target" in resp["error"]


def test_handle_upload_sets_files() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("upload", {"selector": "#file", "paths": ["/a.png", "/b.png"]})
    assert resp["result"] == "set 2 file(s)"
    assert "upload:loc(#file,deep=False):/a.png,/b.png" in page.log


def test_handle_wait_visible_passes_immediately() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("wait", {"selector": "#x", "state": "visible", "timeout": 1000})
    assert resp["ok"] is True and resp["result"] == "element is visible"


def test_handle_wait_hidden_times_out_cleanly() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    # The fake locator is always visible, so waiting for 'hidden' must time out.
    resp = h.handle("wait", {"selector": "#x", "state": "hidden", "timeout": 50})
    assert resp["ok"] is False and "hidden" in resp["error"]


def test_handle_expect_text_passes() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)

    class _Expectable(_FakeLocator):
        def to_have_text(self, expected: str, *, timeout: int | None = None) -> None:
            if expected not in self.text_content():
                raise AssertionError("mismatch")

    # Monkeypatch expect() to wrap our fake first() locator.
    import visus.web.cli.session_server as ss

    page._fields = []
    h._fields = []
    loc = _Expectable([])
    orig_target = h._target
    h._target = lambda args: loc  # type: ignore[assignment, method-assign]
    real_expect = ss.expect
    ss.expect = lambda location: location  # type: ignore[assignment]
    try:
        resp = h.handle("expect_text", {"selector": "#x", "expected_text": "text-of:loc"})
        assert resp["result"] == "PASSED"
        resp2 = h.handle("expect_text", {"selector": "#x", "expected_text": "nope"})
        assert resp2["result"].startswith("FAILED")
    finally:
        ss.expect = real_expect  # type: ignore[assignment]
        h._target = orig_target  # type: ignore[method-assign]


def test_handle_cookies_roundtrip() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    got = h.handle("cookies", {})["result"]
    assert got["cookies"][0]["name"] == "sid"
    assert h.handle("add_cookies", {"cookies": [{"name": "x", "value": "1"}]})["result"] == (
        "added 1 cookie(s)"
    )
    assert any(c["name"] == "x" for c in h.handle("cookies", {})["result"]["cookies"])
    assert h.handle("clear_cookies", {})["result"] == "cookies cleared"
    assert h.handle("cookies", {})["result"]["cookies"] == []


def test_handle_eval_returns_result() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("eval", {"expression": "() => 1", "arg": 7})
    assert resp["ok"] is True
    assert resp["result"]["result"] == {"expr": "() => 1", "arg": 7}


def test_handle_read_text_and_solve_captcha() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    assert h.handle("read_text", {"selector": "#c"})["result"] == "ocr:loc(#c,deep=False)"
    assert h.handle("solve_captcha", {"selector": "#c"})["result"] == "captcha:loc(#c,deep=False)"


def test_handle_goto_screenshot_clear_status(tmp_path: Path) -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    assert h.handle("goto", {"url": "http://x"})["result"] == "http://x"
    out = tmp_path / "shot.png"
    assert h.handle("screenshot", {"path": str(out)})["ok"] is True
    assert out.read_bytes() == b"PNG"
    assert h.handle("clear_highlights", {})["result"] == "cleared"
    status = h.handle("status", {})["result"]
    assert status["running"] is True and status["url"] == "http://x"


def test_handle_click_by_index_echoes_the_field_code() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("list_fields", {})
    resp = h.handle("click", {"index": 1})
    assert resp["ok"] is True
    assert resp["code"] == 'page.frame_locator("#f1").locator("#b").click()'


def test_handle_fill_by_role_echoes_a_role_call() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("fill", {"role": "textbox", "name": "Email", "text": "a@b.c"})
    assert resp["code"] == "page.get_by_role('textbox', name='Email').fill('a@b.c')"


def test_handle_goto_echoes_a_goto_call() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("goto", {"url": "http://x"})
    assert resp["code"] == "page.goto('http://x')"


def test_handle_read_op_has_no_code() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    assert "code" not in h.handle("get_text", {"selector": "#x"})


def test_handle_records_a_replayable_script() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("goto", {"url": "http://x"})
    h.handle("fill", {"selector": "#u", "text": "ada"})
    h.handle("click", {"role": "button", "name": "Sign in"})
    assert h._script == [
        "page.goto('http://x')",
        "page.locator('#u').fill('ada')",
        "page.get_by_role('button', name='Sign in').click()",
    ]


def test_handle_snapshot_forwards_scope_and_depth() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("snapshot", {"selector": "#main", "depth": 2, "refs": False})
    assert "snapshot:selector=#main:depth=2" in page.log


def test_handle_snapshot_shares_the_list_fields_numbering() -> None:
    """One numbering: a snapshot REF is a list-fields index you can act on."""
    page = _FakePage()
    page._fields[0].role = "button"
    page._fields[0].name = "Go"
    h = _handler_with_fake_page(page)
    result = h.handle("snapshot", {})["result"]
    # Row 0 is ("button", "Go") and field 0 was just given that exact (role, name),
    # so it gets that field's index. Row 1 is ("textbox", "Email"); field 1's role
    # is None, so no cached field carries that key and the ref is None.
    assert result["elements"][0]["ref"] == 0
    assert result["elements"][1]["ref"] is None
    assert len(h._fields) == 2                   # snapshot populated the cache


def test_handle_snapshot_no_refs_leaves_the_cache_alone() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    result = h.handle("snapshot", {"refs": False})["result"]
    assert h._fields == []
    assert all(e["ref"] is None for e in result["elements"])


def test_render_snapshot_yaml_is_parseable_and_quoted() -> None:
    text = session_server.render_snapshot_yaml(
        [{"ref": 0, "role": "button", "name": 'Say "hi"', "depth": 1}],
        url="http://x/a",
        title="A",
    )
    assert 'url: "http://x/a"' in text
    assert "count: 1" in text
    assert "  - ref: 0" in text
    assert '    name: "Say \\"hi\\""' in text
    assert text.endswith("\n")


def test_write_snapshot_lands_under_dot_visus(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    h = _handler_with_fake_page(_FakePage())
    rel = h._write_snapshot()
    assert rel is not None
    written = tmp_path / rel
    assert written.is_file()
    assert written.parent == tmp_path / ".visus" / "snapshots"
    assert written.name.startswith("page-") and written.suffix == ".yml"
    assert "role:" in written.read_text(encoding="utf-8")


def test_handle_writes_the_sink_only_when_asked(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    h = _handler_with_fake_page(_FakePage())
    assert "snapshot" not in h.handle("click", {"selector": "#go"})
    resp = h.handle("click", {"selector": "#go", "snapshot": True})
    assert resp["snapshot"] is not None
    assert (tmp_path / resp["snapshot"]).is_file()


class _FindPage(_FakePage):
    """A page with enough rows to make grep-style context observable."""

    def snapshot(
        self, selector: str | None = None, *, depth: int | None = None
    ) -> list[dict[str, Any]]:
        self.log.append(f"snapshot:selector={selector}:depth={depth}")
        names = ["Home", "Products", "Blue widget", "Add to cart", "Red widget", "About", "Legal"]
        return [{"role": "link", "name": n, "depth": 1} for n in names]


def test_handle_find_returns_matches_with_context() -> None:
    h = _handler_with_fake_page(_FindPage())
    result = h.handle("find", {"query": "Add to cart", "context": 1})["result"]
    assert result["total"] == 7
    assert result["matched"] == 1
    assert [r["name"] for r in result["rows"]] == ["Blue widget", "Add to cart", "Red widget"]
    assert [r["match"] for r in result["rows"]] == [False, True, False]


def test_handle_find_is_case_insensitive_by_default() -> None:
    h = _handler_with_fake_page(_FindPage())
    result = h.handle("find", {"query": "WIDGET", "context": 0})["result"]
    assert result["matched"] == 2


def test_handle_find_regex_mode() -> None:
    h = _handler_with_fake_page(_FindPage())
    result = h.handle("find", {"query": r"^link (Blue|Red)", "regex": True, "context": 0})
    assert result["result"]["matched"] == 2


def test_handle_find_no_match_returns_no_rows() -> None:
    h = _handler_with_fake_page(_FindPage())
    result = h.handle("find", {"query": "nothing here"})["result"]
    assert result["matched"] == 0 and result["rows"] == []


def test_handle_find_forwards_scope_and_depth() -> None:
    page = _FindPage()
    h = _handler_with_fake_page(page)
    h.handle("find", {"query": "Home", "selector": "#main", "depth": 2})
    assert "snapshot:selector=#main:depth=2" in page.log


def test_handle_export_script_wraps_the_recorded_lines() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("goto", {"url": "http://x"})
    h.handle("fill", {"selector": "#u", "text": "ada"})
    result = h.handle("export_script", {})["result"]
    assert result["lines"] == 2
    assert result["script"] == (
        "from visus.web import launch\n"
        "\n"
        "with launch(headless=False) as browser:\n"
        "    page = browser.new_page()\n"
        "    page.goto('http://x')\n"
        "    page.locator('#u').fill('ada')\n"
    )


def test_handle_export_script_with_nothing_recorded_is_still_runnable() -> None:
    h = _handler_with_fake_page(_FakePage())
    result = h.handle("export_script", {})["result"]
    assert result["lines"] == 0
    assert result["script"].endswith("    pass  # no recorded actions yet\n")


def test_handle_status_not_running() -> None:
    h = session_server.SessionHandler(engine="firefox", headless=True)
    status = h.handle("status", {})["result"]
    assert status["running"] is False and status["engine"] == "firefox"


def test_handle_shutdown_closes_browser() -> None:
    closed = {"v": False}

    class _B:
        def close(self) -> None:
            closed["v"] = True

    h = session_server.SessionHandler(engine="chrome", headless=True)
    h._browser = _B()  # type: ignore[assignment]
    h._page = _FakePage()  # type: ignore[assignment]
    assert h.handle("shutdown", {})["result"] == "shutdown"
    assert closed["v"] is True and h._browser is None


def test_handler_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISUS_WEB_ENGINE", "edge")
    monkeypatch.setenv("VISUS_WEB_HEADLESS", "1")
    h = session_server.SessionHandler()
    assert h._engine == "edge" and h._headless is True


def test_make_locator_requires_a_target() -> None:
    page = _FakePage()
    with pytest.raises(ValueError, match="provide one of"):
        session_server.make_locator(page)  # type: ignore[arg-type]


def test_ensure_partial_launch_failure_is_atomic_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If context/page/goto setup raises, the partial browser is torn down so the
    next op retries cleanly (no wedge, no leaked driver)."""
    launched: list[_FakeBrowser] = []

    class _PageBoomBrowser(_FakeBrowser):
        def new_page(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("page boom")

    class _GoodBrowser(_FakeBrowser):
        def new_page(self):  # type: ignore[no-untyped-def]
            return _FakePage()

    browsers = [_PageBoomBrowser(), _GoodBrowser()]

    # Mirrors the real launch() call in _ensure(): a fake that drops a keyword
    # would fail with a TypeError and hide the teardown behaviour under test.
    def fake_launch(  # type: ignore[no-untyped-def]
        engine,
        *,
        headless,
        slow_mo=0,
        user_data_dir=None,
        remote_url=None,
        debugger_address=None,
    ):
        b = browsers.pop(0)
        launched.append(b)
        return b

    monkeypatch.setattr(session_server, "launch", fake_launch)
    h = session_server.SessionHandler(engine="chrome", headless=True)

    # First op: setup raises -> clean error AND the partial browser is closed.
    resp = h.handle("status", {})  # status triggers page() via no-op? -> use list_fields
    # status() does NOT call page() when not running, so drive an op that needs the page.
    resp = h.handle("list_fields", {})
    assert resp["ok"] is False
    assert "page boom" in resp["error"]
    assert "AssertionError" not in resp["error"]  # not the empty-assert wedge
    assert launched[0].closed is True  # partial browser was torn down
    assert h._browser is None  # reset so the next op retries

    # Second op: a fresh launch succeeds (proves it retried, did not wedge).
    resp2 = h.handle("list_fields", {})
    assert resp2["ok"] is True
    assert len(launched) == 2  # launched again on retry


# ---------------------------------------------------------------------------
# console.dispatch — pure (fake send)
# ---------------------------------------------------------------------------


def _recording_send() -> tuple[list[tuple[str, dict[str, Any]]], Any]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "list_fields":
            return {
                "fields": [
                    {
                        "index": 0,
                        "kind": "button",
                        "name": "Go",
                        "locator": "#go",
                        "code": 'page.locator("#go")',
                        "css": "#go",
                        "xpath": '//*[@id="go"]',
                        "frame": [],
                    }
                ]
            }
        if op == "goto":
            return "http://dest"
        if op == "get_text":
            return "hello"
        if op == "screenshot":
            return "/tmp/shot.png"
        return "ok"

    return calls, send


def test_dispatch_blank_and_help_and_quit() -> None:
    _, send = _recording_send()
    assert console.dispatch("", send) == ""
    assert "commands:" in console.dispatch("help", send)
    assert console.dispatch("quit", send) == "__QUIT__"


def test_dispatch_list_renders_table() -> None:
    calls, send = _recording_send()
    out = console.dispatch("list", send)
    assert calls[0][0] == "list_fields"
    # short, wrap-safe tokens (the table may wrap long cells at default width)
    assert "button" in out and "#go" in out


def test_dispatch_actions_map_to_ops() -> None:
    calls, send = _recording_send()
    console.dispatch("click 3", send)
    console.dispatch("fill 2 hello world", send)
    console.dispatch("check 1", send)
    console.dispatch("uncheck 1", send)
    console.dispatch("select 4 us", send)
    console.dispatch("press 5 Enter", send)
    console.dispatch("clear", send)
    ops = [c[0] for c in calls]
    assert ops == ["click", "fill", "check", "uncheck", "select", "press", "clear_highlights"]
    assert calls[0][1] == {"index": 3}
    assert calls[1][1] == {"index": 2, "text": "hello world"}
    assert calls[4][1] == {"index": 4, "value": "us"}
    assert calls[5][1] == {"index": 5, "key": "Enter"}


def test_dispatch_goto_text_screenshot() -> None:
    _, send = _recording_send()
    assert "navigated to http://dest" in console.dispatch("goto http://dest", send)
    assert console.dispatch("text 0", send) == "hello"
    assert "saved /tmp/shot.png" in console.dispatch("screenshot", send)


def test_dispatch_screenshot_resolves_the_path_against_the_client_cwd() -> None:
    """The daemon's cwd is not the user's; a relative path must be resolved here."""
    calls, send = _recording_send()
    out = console.dispatch("screenshot shots/out.png", send)
    assert "saved" in out
    op, args = calls[-1]
    assert op == "screenshot"
    assert args == {"path": str(Path("shots/out.png").resolve())}
    assert Path(args["path"]).is_absolute()

    # With NO argument the default name is resolved client-side too: letting the
    # daemon pick it would write screenshot.png into the DAEMON's cwd, which is
    # the same B9 bug in its default case.
    console.dispatch("screenshot", send)
    assert calls[-1][1] == {"path": str(Path("screenshot.png").resolve())}


def test_render_value_keeps_null_and_empty_apart() -> None:
    assert console.render_value({"value": "hi", "present": True}) == "hi"
    assert console.render_value({"value": "", "present": True}) == "(empty)"
    assert console.render_value({"value": None, "present": False}) == "(null)"
    # Anything that is not a {value, present} payload passes straight through.
    assert console.render_value("plain") == "plain"
    assert console.render_value(7) == "7"


def test_dispatch_text_and_attr_render_the_distinction() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        return {"value": None, "present": False}

    assert console.dispatch("text 0", send) == "(null)"
    assert console.dispatch("attr href 0", send) == "(null)"


def test_dispatch_unknown_and_missing_arg() -> None:
    _, send = _recording_send()
    assert "unknown command" in console.dispatch("frobnicate", send)
    # A targeted verb with no target names the forms it accepts (the `_target`
    # guard), while a verb whose missing argument is not a target still reports
    # the generic miss — both paths must stay clean, neither may traceback.
    out = console.dispatch("click", send)
    assert "bad argument" in out and "--selector" in out
    assert "missing argument" in console.dispatch("goto", send)


def test_dispatch_surfaces_session_error() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        raise session_client.SessionError("daemon gone")

    out = console.dispatch("click 1", send)
    assert "error: daemon gone" in out


def test_format_fields_empty() -> None:
    assert console.format_fields([]) == "(no fields found)"


def test_format_fields_table_shows_visus_css_xpath() -> None:
    # width=200 so long cells do not wrap and full strings are assertable.
    out = console.format_fields(
        [
            {
                "index": 0,
                "kind": "button",
                "name": "Submit",
                "frame": ["#f1"],
                "code": 'page.frame_locator("#f1").locator("#submit")',
                "css": "#submit",
                "xpath": '//*[@id="submit"]',
            }
        ],
        width=200,
        full=True,
    )
    assert "VISUS" in out and "CSS" in out and "XPATH" in out  # column headers
    assert "button" in out and "Submit" in out
    # frame-aware visus call + the css value are present (rich folds/crops long
    # cells at narrow widths, so assert short, wrap-safe tokens; the exact code /
    # xpath values are asserted at the source in test_e2e_fields.py).
    assert "frame" in out and "#f1" in out  # the frame_locator(...) wrapping
    assert "#submit" in out  # css value

def test_repl_click_shows_page_and_code_when_an_envelope_sender_is_given() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        raise AssertionError("mutating REPL commands must use the envelope sender")

    def send_env(op: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "result": "clicked",
            "code": 'page.locator("#go").click()',
            "page": {"url": "http://x/next", "title": "Next", "fields_stale": False},
        }

    out = console.dispatch("click 3", send, send_env)
    assert out.splitlines() == [
        "clicked",
        "",
        "### Code",
        'page.locator("#go").click()',
        "",
        "### Page",
        "- URL: http://x/next",
        "- Title: Next",
    ]


def test_repl_without_an_envelope_sender_prints_the_bare_result() -> None:
    out = console.dispatch("click 3", lambda op, args: "clicked")
    assert out == "clicked"


def test_repl_read_command_is_unchanged_by_the_envelope_sender() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        assert op == "get_text"
        return "hello"

    def send_env(op: str, args: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("reads must not go through the envelope sender")

    assert console.dispatch("text 3", send, send_env) == "hello"


def test_repl_snapshot_shows_refs() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        return {
            "elements": [
                {"ref": 4, "role": "button", "name": "Go", "depth": 0},
                {"ref": None, "role": "heading", "name": "Title", "depth": 0},
            ],
            "url": "u",
            "title": "t",
        }

    out = console.dispatch("snapshot", send)
    assert out.splitlines() == ["   4  button           Go", "   -  heading          Title"]


def test_repl_find_renders_matches() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        assert args == {"query": "cart", "regex": False, "context": 3,
                        "selector": None, "depth": None}
        return {
            "query": "cart",
            "regex": False,
            "total": 9,
            "matched": 1,
            "rows": [{"line": 2, "role": "button", "name": "Add to cart", "ref": 1,
                      "match": True}],
        }

    out = console.dispatch("find cart", send)
    assert "1 of 9 rows match 'cart'" in out
    assert "Add to cart" in out


def test_repl_screenshot_path_resolves_against_the_client_cwd(tmp_path: Path) -> None:
    """Regression lock on PLAN 3 Task 13 (B9): the dispatch rewrite must keep the
    client-cwd resolution — a raw string lands the PNG in the DAEMON's cwd."""
    captured: dict[str, Any] = {}

    def send(op: str, args: dict[str, Any]) -> Any:
        captured["args"] = args
        return args["path"]

    console.dispatch("screenshot shot.png", send)
    assert Path(captured["args"]["path"]).is_absolute()
    assert Path(captured["args"]["path"]).name == "shot.png"


def test_repl_help_lists_the_new_commands() -> None:
    out = console.dispatch("help", lambda op, args: None)
    assert "find " in out
    assert "export-script" in out


def test_repl_goto_keeps_its_sentence_and_gains_the_footer() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        raise AssertionError("goto is mutating: it must use the envelope sender")

    def send_env(op: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "result": "http://dest",
            "page": {"url": "http://dest", "title": "Dest", "fields_stale": False},
        }

    out = console.dispatch("goto http://dest", send, send_env)
    assert out.startswith("navigated to http://dest")
    assert "### Page" in out and "- Title: Dest" in out


def test_repl_tab_commands_keep_their_sentences() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        if op == "tab":
            return {"active": 0, "title": "A"}
        if op == "tab_new":
            return {"index": 1, "title": "B"}
        return {"closed": 1, "remaining": 1, "active": 0}

    assert "switched to tab 0" in console.dispatch("tab 0", send)
    assert "opened tab 1" in console.dispatch("tab-new http://x", send)
    assert "closed tab 1" in console.dispatch("tab-close 1", send)


def test_repl_export_script_prints_and_saves(tmp_path: Path) -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        assert op == "export_script"
        return {"script": "from visus.web import launch\n", "lines": 1}

    assert console.dispatch("export-script", send) == "from visus.web import launch\n"
    dest = tmp_path / "flow.py"
    out = console.dispatch(f"export-script {dest}", send)
    assert dest.read_text(encoding="utf-8") == "from visus.web import launch\n"
    assert "saved" in out and "1 action(s)" in out


def test_repl_highlight_all_opts_into_the_overlay() -> None:
    captured: dict[str, Any] = {}

    def send(op: str, args: dict[str, Any]) -> Any:
        captured[op] = args
        return {"fields": []}

    assert console.dispatch("highlight-all", send) == "overlay drawn"
    assert captured["list_fields"]["highlight"] is True


def test_repl_list_does_not_draw_the_overlay() -> None:
    """`list` is a read — same rule Task 12 applied to `visus list-fields`."""
    captured: dict[str, Any] = {}

    def send(op: str, args: dict[str, Any]) -> Any:
        captured[op] = args
        return {"fields": []}

    console.dispatch("list", send)
    assert captured["list_fields"]["highlight"] is False


_ONE_FIELD = [
    {
        "index": 0,
        "kind": "button",
        "name": "Submit",
        "frame": [],
        "code": 'page.locator("#submit")',
        "css": "#submit",
        "xpath": '//*[@id="submit"]',
    }
]


def test_format_fields_default_drops_css_and_xpath() -> None:
    out = console.format_fields(_ONE_FIELD, width=200)
    assert "VISUS" in out and "KIND" in out
    assert "CSS" not in out and "XPATH" not in out


def test_format_fields_default_has_no_row_rules() -> None:
    """show_lines=True doubled the line count of every list-fields call."""
    two = [_ONE_FIELD[0], {**_ONE_FIELD[0], "index": 1}]
    out = console.format_fields(two, width=200)
    # header rule, header, header rule, 2 rows, closing rule -> 6 lines.
    assert len(out.splitlines()) == 6


def test_format_fields_full_restores_the_forensic_columns() -> None:
    out = console.format_fields(_ONE_FIELD, width=200, full=True)
    assert "CSS" in out and "XPATH" in out


def test_cli_list_fields_full_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, lambda op, args=None: {"fields": _ONE_FIELD})
    assert "XPATH" not in runner.invoke(app, ["list-fields"]).output
    assert "XPATH" in runner.invoke(app, ["list-fields", "--full"]).output


def test_cli_target_flags_reach_the_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args or {}
        return "clicked"

    _patch_client(monkeypatch, fake)
    r = runner.invoke(
        app, ["click", "--role", "button", "--name", "Pay", "--exact", "--frame", "#checkout"]
    )
    assert r.exit_code == 0
    assert captured["args"]["exact"] is True
    assert captured["args"]["frame"] == "#checkout"


def test_cli_target_flags_are_absent_when_unused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults stay off the wire so the daemon payload does not grow."""
    captured: dict[str, Any] = {}

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args or {}
        return "3"

    _patch_client(monkeypatch, fake)
    assert runner.invoke(app, ["count", "--selector", ".item"]).exit_code == 0
    assert "exact" not in captured["args"] and "frame" not in captured["args"]


def test_cli_frame_flag_works_with_an_index_target(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args or {}
        return "ok"

    _patch_client(monkeypatch, fake)
    assert runner.invoke(app, ["get-text", "2", "--frame", "#f"]).exit_code == 0
    assert captured["args"] == {"index": 2, "frame": "#f"}


def test_cli_list_fields_does_not_draw_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A read must not mutate the DOM: the overlay pollutes screenshots/OCR."""
    captured: dict[str, Any] = {}

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args or {}
        return {"fields": []}

    _patch_client(monkeypatch, fake)
    assert runner.invoke(app, ["list-fields"]).exit_code == 0
    assert captured["args"]["highlight"] is False


def test_cli_list_fields_highlight_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args or {}
        return {"fields": []}

    _patch_client(monkeypatch, fake)
    assert runner.invoke(app, ["list-fields", "--highlight"]).exit_code == 0
    assert captured["args"]["highlight"] is True


def test_cli_list_fields_no_highlight_still_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args or {}
        return {"fields": []}

    _patch_client(monkeypatch, fake)
    assert runner.invoke(app, ["list-fields", "--no-highlight"]).exit_code == 0
    assert captured["args"]["highlight"] is False


# ---------------------------------------------------------------------------
# console.run_console — session attach + input loop (injected fns)
# ---------------------------------------------------------------------------


def test_run_console_starts_session_when_none(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, Any] = {}
    monkeypatch.setattr(console.session_client, "find_session", lambda d=None, name=None: None)
    monkeypatch.setattr(
        console.session_client,
        "start_daemon",
        lambda engine, headless, url, **kw: calls.update(
            engine=engine, headless=headless, url=url
        ),
    )
    outputs: list[str] = []
    console.run_console(
        "http://x",
        engine="firefox",
        headless=True,
        input_fn=lambda _p: "quit",
        output_fn=outputs.append,
    )
    assert calls == {"engine": "firefox", "headless": True, "url": "http://x"}


def test_run_console_gotos_when_session_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        console.session_client, "find_session", lambda d=None, name=None: {"pid": 1, "port": 2}
    )
    _patch_client(monkeypatch, lambda op, args=None, **kw: sent.append((op, args)) or None)
    console.run_console(
        "http://dest",
        input_fn=lambda _p: "quit",
        output_fn=lambda _s: None,
    )
    assert ("goto", {"url": "http://dest"}) in sent


def test_run_console_loop_dispatches_then_quits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        console.session_client, "find_session", lambda d=None, name=None: {"pid": 1, "port": 2}
    )
    _patch_client(monkeypatch, lambda op, args=None, **kw: "ok")
    lines = iter(["help", "quit"])
    outputs: list[str] = []
    console.run_console(
        None,
        input_fn=lambda _p: next(lines),
        output_fn=outputs.append,
    )
    assert any("commands:" in o for o in outputs)  # help ran before quit broke the loop


@pytest.mark.parametrize("exc", [EOFError, KeyboardInterrupt])
def test_run_console_clean_break_on_eof_or_interrupt(
    monkeypatch: pytest.MonkeyPatch, exc: type[BaseException]
) -> None:
    monkeypatch.setattr(
        console.session_client, "find_session", lambda d=None, name=None: {"pid": 1, "port": 2}
    )

    def _raise(_prompt: str) -> str:
        raise exc

    # Must return cleanly (no exception propagates).
    console.run_console(None, input_fn=_raise, output_fn=lambda _s: None)


def test_cli_console_command_invokes_run_console(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run_console(url=None, *, engine="chrome", headless=False, **kw):  # type: ignore[no-untyped-def]
        captured.update(url=url, engine=engine, headless=headless)

    monkeypatch.setattr("visus.web.cli.console.run_console", fake_run_console)
    r = runner.invoke(app, ["console", "http://x", "--engine", "edge", "--headless"])
    assert r.exit_code == 0
    assert captured == {"url": "http://x", "engine": "edge", "headless": True}


# ---------------------------------------------------------------------------
# session-file discovery + stale cleanup (isolated under tmp_path)
# ---------------------------------------------------------------------------


def _write_session(dir_: Path, info: dict[str, Any], name: str = "default") -> Path:
    sessions = dir_ / ".visus" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    sf = sessions / f"{name}.json"
    sf.write_text(json.dumps(info), encoding="utf-8")
    return sf


def test_find_session_none_when_absent(tmp_path: Path) -> None:
    assert session_client.find_session(tmp_path) is None


def test_find_session_searches_upward(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Live socket so the liveness check passes.
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        _write_session(tmp_path, {"pid": 1, "port": port, "token": "t"})
        monkeypatch.setattr(session_client, "_pid_alive", lambda pid: True)
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        info = session_client.find_session(deep)
        assert info is not None and info["port"] == port and info["token"] == "t"
    finally:
        srv.close()


def test_find_session_cleans_stale_dead_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sf = _write_session(tmp_path, {"pid": 999999, "port": 1, "token": "t"})
    monkeypatch.setattr(session_client, "_pid_alive", lambda pid: False)
    assert session_client.find_session(tmp_path) is None
    assert not sf.exists()  # stale file removed


def test_find_session_cleans_stale_socket_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pid "alive" but nothing listening on the recorded port → stale.
    sf = _write_session(tmp_path, {"pid": 1, "port": 1, "token": "t"})
    monkeypatch.setattr(session_client, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(session_client, "_socket_open", lambda port, **kw: False)
    assert session_client.find_session(tmp_path) is None
    assert not sf.exists()


def test_find_session_cleans_corrupt_file(tmp_path: Path) -> None:
    visus = tmp_path / ".visus" / "sessions"
    visus.mkdir(parents=True)
    sf = visus / "default.json"
    sf.write_text("{not json", encoding="utf-8")
    assert session_client.find_session(tmp_path) is None
    assert not sf.exists()


def test_cleanup_removes_the_lock_beside_the_session_file(tmp_path: Path) -> None:
    sf = _write_session(tmp_path, {"pid": 1, "port": 2, "token": "t"})
    lock = sf.with_name(sf.name + ".lock")
    lock.write_text("999999", encoding="utf-8")
    session_client._cleanup(sf)
    assert not sf.exists()
    assert not lock.exists(), "the orphaned lock survived cleanup"


def test_find_session_stale_cleanup_removes_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sf = _write_session(tmp_path, {"pid": 999999, "port": 1, "token": "t"})
    lock = sf.with_name(sf.name + ".lock")
    lock.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(session_client, "_pid_alive", lambda pid: False)
    assert session_client.find_session(tmp_path) is None
    assert not sf.exists() and not lock.exists()


def test_stop_on_a_wedged_daemon_removes_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`visus session stop` must not print success while leaving the lock."""
    sf = _write_session(tmp_path, {"pid": 1, "port": 9, "token": "t"})
    lock = sf.with_name(sf.name + ".lock")
    lock.write_text("1", encoding="utf-8")
    info = {"pid": 1, "port": 9, "token": "t", "_file": str(sf)}
    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None, name=None: info)
    monkeypatch.setattr(
        session_client,
        "_send_raw",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("connection refused")),
    )
    assert session_client.stop(start_dir=tmp_path) == "session stopped"
    assert not sf.exists() and not lock.exists()


def test_send_without_session_raises(tmp_path: Path) -> None:
    with pytest.raises(session_client.SessionError, match="no live session"):
        session_client.send("status", start_dir=tmp_path)


def test_status_none_without_session(tmp_path: Path) -> None:
    assert session_client.status(start_dir=tmp_path) is None


def test_stop_without_session(tmp_path: Path) -> None:
    assert session_client.stop(start_dir=tmp_path) == "no session 'default' running"


def test_send_real_raises_on_daemon_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive the REAL send(): a daemon {ok:False,error} must surface as SessionError."""
    handler = _handler_with_fake_page(_FakePage())
    token = "tok"
    t, port = _serve_in_thread(handler, token, tmp_path)
    monkeypatch.setattr(session_client, "_pid_alive", lambda pid: True)
    try:
        with pytest.raises(session_client.SessionError, match="out of range"):
            # No list_fields run -> index 999 is out of range -> ok:False from daemon.
            session_client.send("click", {"index": 999}, start_dir=tmp_path)
    finally:
        _shutdown_thread(t, port, token)


def test_send_raw_raises_on_empty_response(tmp_path: Path) -> None:
    """_send_raw: an empty/closed response line -> 'daemon closed the connection'."""
    import threading

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def _accept_and_eof() -> None:
        conn, _ = srv.accept()
        try:
            # Read the client's request line, then send a clean EOF (no response
            # line) so the client's readline() returns b"" -> the empty-line path.
            conn.recv(4096)
            conn.shutdown(socket.SHUT_WR)
            conn.recv(4096)  # wait for the client to finish before closing
        finally:
            conn.close()

    th = threading.Thread(target=_accept_and_eof, daemon=True)
    th.start()
    try:
        with pytest.raises(session_client.SessionError, match="closed the connection"):
            session_client._send_raw(port, {"token": "t", "op": "status"}, timeout=5)
    finally:
        th.join(timeout=5)
        srv.close()


def test_socket_timeout_for_derives_from_the_op_timeout() -> None:
    assert session_client.socket_timeout_for(None) == 60.0
    assert session_client.socket_timeout_for({}) == 60.0
    assert session_client.socket_timeout_for({"timeout": 500}) == 60.0  # floored
    assert session_client.socket_timeout_for({"timeout": 120000}) == 130.0
    assert session_client.socket_timeout_for({"timeout": "nope"}) == 60.0
    assert session_client.socket_timeout_for({"timeout": None}) == 60.0


def test_send_honours_an_explicit_socket_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The timeout genuinely reaches the socket: a silent daemon must time out."""
    import threading as _threading

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    gate = _threading.Event()

    def _accept_and_stay_silent() -> None:
        conn, _ = srv.accept()
        try:
            gate.wait(timeout=10)
        finally:
            conn.close()

    th = _threading.Thread(target=_accept_and_stay_silent, daemon=True)
    th.start()
    _write_session(tmp_path, {"pid": 1, "port": port, "token": "t"})
    monkeypatch.setattr(session_client, "_pid_alive", lambda pid: True)
    try:
        with pytest.raises(TimeoutError):
            session_client.send(
                "wait", {"timeout": 5}, start_dir=tmp_path, timeout=0.3
            )
    finally:
        gate.set()
        th.join(timeout=10)
        srv.close()


def test_cli_send_maps_a_socket_timeout_to_a_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """socket.timeout is an OSError, not a SessionError — it used to traceback."""

    def boom(op: str, args: dict[str, Any] | None = None, **_: Any) -> Any:
        raise TimeoutError("timed out")

    monkeypatch.setattr(session_client, "send", boom)
    monkeypatch.setattr(session_client, "send_envelope", boom)
    r = runner.invoke(app, ["click", "0"])
    assert r.exit_code == 1
    assert not isinstance(r.exception, TimeoutError), "the raw exception escaped"
    assert "error:" in r.output and "timed out" in r.output


def test_cli_send_maps_a_corrupt_response_to_a_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(op: str, args: dict[str, Any] | None = None, **_: Any) -> Any:
        raise json.JSONDecodeError("Expecting value", "{oops", 0)

    monkeypatch.setattr(session_client, "send", boom)
    monkeypatch.setattr(session_client, "send_envelope", boom)
    r = runner.invoke(app, ["click", "0"])
    assert r.exit_code == 1
    assert not isinstance(r.exception, json.JSONDecodeError)
    assert "error:" in r.output


def test_start_daemon_refuses_when_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client,
        "find_session",
        lambda d=None, name=None: {"pid": 7, "port": 8, "token": "t"},
    )
    with pytest.raises(session_client.SessionError, match="already running"):
        session_client.start_daemon("chrome", True, None, cwd=tmp_path)


def test_start_daemon_forwards_the_idle_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, *a: Any, **kw: Any) -> None:
            captured["env"] = kw["env"]

    monkeypatch.setattr(session_client, "find_session", lambda d=None, name=None: None)
    monkeypatch.setattr(session_client.subprocess, "Popen", _FakePopen)
    with pytest.raises(session_client.SessionError):
        session_client.start_daemon(
            "chrome", True, None, cwd=tmp_path, timeout=0.3, idle_timeout=900.0
        )
    assert captured["env"]["VISUS_WEB_IDLE_TIMEOUT"] == "900.0"


def test_start_daemon_timeout_reports_the_real_daemon_log(tmp_path: Path) -> None:
    """A wedged start must show WHY, not just "did not come up within Ns".

    Fully real: the lock is held by THIS (live) process, so a genuinely spawned
    daemon aborts on the lock and writes its reason to .visus/daemon.log before
    exiting — no browser is ever launched on that path.
    """
    import os as _os

    visus = tmp_path / ".visus" / "sessions"
    visus.mkdir(parents=True)
    (visus / "default.json.lock").write_text(str(_os.getpid()), encoding="utf-8")

    with pytest.raises(session_client.SessionError) as excinfo:
        session_client.start_daemon("chrome", True, None, cwd=tmp_path, timeout=8.0)

    message = str(excinfo.value)
    assert "did not come up within 8s" in message
    assert "daemon aborting" in message, message
    assert "already holds" in message, message


def test_log_tail_of_a_missing_log_is_empty(tmp_path: Path) -> None:
    assert session_client._log_tail(tmp_path) == ""


def test_log_tail_returns_only_the_last_lines(tmp_path: Path) -> None:
    # daemon.log stays at .visus/daemon.log — only session STATE is namespaced.
    visus = tmp_path / ".visus"
    visus.mkdir(parents=True)
    (visus / "daemon.log").write_text(
        "\n".join(f"line {i}" for i in range(50)), encoding="utf-8"
    )
    tail = session_client._log_tail(tmp_path, lines=3)
    assert tail == "line 47\nline 48\nline 49"


def test_start_daemon_retries_through_partial_session_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Popen no-op; session.json first corrupt then valid with a live socket.

    Exercises start_daemon's not-yet-ready polling: JSONDecodeError retry, then a
    valid file whose socket accepts -> returns the info dict.
    """
    monkeypatch.setattr(session_client, "find_session", lambda d=None, name=None: None)

    # A real listening socket so _socket_open() succeeds once the file is valid.
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    visus = tmp_path / ".visus" / "sessions"
    visus.mkdir(parents=True, exist_ok=True)
    sf = visus / "default.json"

    state = {"calls": 0}

    class _FakePopen:
        def __init__(self, *a: Any, **kw: Any) -> None:
            # First write a corrupt/partial file (simulates a mid-write read).
            sf.write_text("{partial", encoding="utf-8")

    monkeypatch.setattr(session_client.subprocess, "Popen", _FakePopen)

    # On the second poll, replace the corrupt file with a valid one.
    real_is_file = Path.is_file

    def patched_is_file(self: Path) -> bool:
        if self == sf:
            state["calls"] += 1
            if state["calls"] >= 2 and sf.read_text(encoding="utf-8").startswith("{partial"):
                sf.write_text(
                    json.dumps({"pid": 1, "port": port, "token": "t"}), encoding="utf-8"
                )
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", patched_is_file)
    try:
        info = session_client.start_daemon("chrome", True, None, cwd=tmp_path, timeout=5.0)
        assert info["port"] == port and info["token"] == "t"
    finally:
        srv.close()


def test_stop_swallows_send_failure_on_dead_socket(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stop() against a session whose port refuses must swallow the error and clean up."""
    sf = _write_session(tmp_path, {"pid": 1, "port": 9, "token": "t"})
    info = {"pid": 1, "port": 9, "token": "t", "_file": str(sf)}
    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None, name=None: info)
    # _send_raw blows up (nothing listening); stop() must still finish cleanly.
    monkeypatch.setattr(
        session_client,
        "_send_raw",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("connection refused")),
    )
    assert session_client.stop(start_dir=tmp_path) == "session stopped"
    assert not sf.exists()  # cleaned up


def test_pid_alive_negative() -> None:
    assert session_client._pid_alive(-1) is False


def test_pid_alive_windows_tasklist_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the win32 tasklist parse (uncached probe): present -> True,
    absent/raising -> False."""
    monkeypatch.setattr(session_client.sys, "platform", "win32")

    class _Completed:
        def __init__(self, stdout: str) -> None:
            self.stdout = stdout

    # pid present in tasklist output -> alive.
    monkeypatch.setattr(
        session_client.subprocess,
        "run",
        lambda *a, **kw: _Completed("python.exe   12345 Console   1   50,000 K"),
    )
    assert session_client._probe_pid(12345) is True

    # pid absent -> not alive.
    monkeypatch.setattr(
        session_client.subprocess,
        "run",
        lambda *a, **kw: _Completed("INFO: No tasks are running which match the criteria."),
    )
    assert session_client._probe_pid(12345) is False

    # subprocess raises -> treated as not alive (exception fallback).
    def _boom(*a: Any, **kw: Any) -> Any:
        raise OSError("tasklist missing")

    monkeypatch.setattr(session_client.subprocess, "run", _boom)
    assert session_client._probe_pid(12345) is False


def test_status_costs_exactly_one_liveness_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`visus session status` used to probe twice; on Windows that is 2x tasklist."""
    probes: list[int] = []
    real_probe = session_client._probe_pid

    def spy(pid: int) -> bool:
        probes.append(pid)
        return real_probe(pid)

    handler = _handler_with_fake_page(_FakePage())
    t, port = _serve_in_thread(handler, "tok", tmp_path)
    try:
        # Rewrite the session file with THIS process's pid so the probe is real.
        import os as _os

        sf = session_server.session_file(tmp_path)
        info = json.loads(sf.read_text(encoding="utf-8"))
        info["pid"] = _os.getpid()
        sf.write_text(json.dumps(info), encoding="utf-8")

        session_client._pid_alive_cache.clear()
        monkeypatch.setattr(session_client, "_probe_pid", spy)
        result = session_client.status(start_dir=tmp_path)
        assert result is not None and result["running"] is True
        assert len(probes) == 1, f"{len(probes)} liveness probes for one status"
    finally:
        monkeypatch.undo()
        _shutdown_thread(t, port, "tok")


def test_pid_alive_is_memoised_within_its_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        session_client, "_probe_pid", lambda pid: calls.append(pid) or True
    )
    session_client._pid_alive_cache.clear()
    assert session_client._pid_alive(4242) is True
    assert session_client._pid_alive(4242) is True
    assert session_client._pid_alive(4242) is True
    assert calls == [4242], "the probe was not memoised"


def test_pid_alive_memo_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        session_client, "_probe_pid", lambda pid: calls.append(pid) or True
    )
    monkeypatch.setattr(session_client, "PID_ALIVE_TTL", 0.0)
    session_client._pid_alive_cache.clear()
    session_client._pid_alive(4242)
    session_client._pid_alive(4242)
    assert calls == [4242, 4242], "a zero TTL must not memoise"


def test_socket_open_false_on_closed_port() -> None:
    # Bind then immediately close → that port should refuse.
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    assert session_client._socket_open(port, timeout=0.5) is False


# ---------------------------------------------------------------------------
# JSON-lines protocol — drive serve() in a thread (no real browser)
# ---------------------------------------------------------------------------


def test_serve_protocol_with_fake_handler(tmp_path: Path) -> None:
    """Exercise the socket server end-to-end against a fake page handler."""
    import threading

    page = _FakePage()
    handler = _handler_with_fake_page(page)
    token = "secret-token"

    t = threading.Thread(
        target=session_server.serve, kwargs={"handler": handler, "token": token, "cwd": tmp_path}
    )
    t.start()
    try:
        sf = session_server.session_file(tmp_path)
        # Wait for the session file to appear.
        for _ in range(100):
            if sf.is_file():
                break
            import time

            time.sleep(0.05)
        info = json.loads(sf.read_text(encoding="utf-8"))
        port = info["port"]
        assert info["token"] == token

        def rpc(payload: dict[str, Any]) -> dict[str, Any]:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
                f = sock.makefile("rwb")
                f.write((json.dumps(payload) + "\n").encode("utf-8"))
                f.flush()
                return json.loads(f.readline().decode("utf-8"))

        # bad token rejected
        assert rpc({"token": "wrong", "op": "status"})["error"].startswith("unauthorized")
        # list_fields works
        r = rpc({"token": token, "op": "list_fields", "args": {}})
        assert r["ok"] and len(r["result"]["fields"]) == 2
        # index click re-resolves through the cache
        assert rpc({"token": token, "op": "click", "args": {"index": 0}})["result"] == "clicked"
        # bad json line gets an error response
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            fb = sock.makefile("rwb")
            fb.write(b"{garbage\n")
            fb.flush()
            assert json.loads(fb.readline().decode("utf-8"))["ok"] is False
        # shutdown stops the server
        assert rpc({"token": token, "op": "shutdown"})["result"] == "shutdown"
    finally:
        t.join(timeout=10)
    assert not t.is_alive()
    assert not session_server.session_file(tmp_path).is_file()  # cleaned on shutdown


def _serve_in_thread(handler: session_server.SessionHandler, token: str, tmp_path: Path):
    """Start serve() in a thread; return (thread, port). Wait for the session file."""
    import threading
    import time as _time

    t = threading.Thread(
        target=session_server.serve,
        kwargs={"handler": handler, "token": token, "cwd": tmp_path},
        daemon=True,
    )
    t.start()
    sf = session_server.session_file(tmp_path)
    for _ in range(200):
        if sf.is_file():
            break
        _time.sleep(0.02)
    info = json.loads(sf.read_text(encoding="utf-8"))
    return t, int(info["port"])


def _shutdown_thread(t, port: int, token: str) -> None:
    with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
        f = sock.makefile("rwb")
        f.write((json.dumps({"token": token, "op": "shutdown"}) + "\n").encode("utf-8"))
        f.flush()
        f.readline()
    t.join(timeout=10)


@pytest.mark.parametrize("bad", ["123", '"hi"', "[1, 2, 3]", "null"])
def test_serve_non_dict_request_returns_error_not_crash(bad: str, tmp_path: Path) -> None:
    """A valid-JSON-but-non-dict line must get {ok:False,error} and keep the thread alive."""
    handler = _handler_with_fake_page(_FakePage())
    token = "tok"
    t, port = _serve_in_thread(handler, token, tmp_path)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            f = sock.makefile("rwb")
            f.write((bad + "\n").encode("utf-8"))
            f.flush()
            resp = json.loads(f.readline().decode("utf-8"))
            assert resp["ok"] is False
            assert "expected a JSON object" in resp["error"]
            # The same connection's handler thread is still alive: a follow-up
            # well-formed request on it gets a normal response.
            f.write(
                (json.dumps({"token": token, "op": "status"}) + "\n").encode("utf-8")
            )
            f.flush()
            ok = json.loads(f.readline().decode("utf-8"))
            assert ok["ok"] is True
    finally:
        _shutdown_thread(t, port, token)
    assert not t.is_alive()


def test_serve_writes_session_file_atomically(tmp_path: Path) -> None:
    """No leftover *.tmp file remains after the atomic os.replace startup write."""
    handler = _handler_with_fake_page(_FakePage())
    token = "tok"
    t, port = _serve_in_thread(handler, token, tmp_path)
    try:
        visus = tmp_path / ".visus" / "sessions"
        leftovers = list(visus.glob("default.json.*.tmp"))
        assert leftovers == []
        assert (visus / "default.json").is_file()
    finally:
        _shutdown_thread(t, port, token)


def test_write_private_creates_exclusively_and_owner_only(tmp_path: Path) -> None:
    import os as _os
    import stat as _stat

    target = tmp_path / "secret.json"
    session_server._write_private(target, '{"token": "abc"}')
    assert target.read_text(encoding="utf-8") == '{"token": "abc"}'

    # O_EXCL: never write THROUGH a file somebody else planted.
    with pytest.raises(FileExistsError):
        session_server._write_private(target, "second")
    assert target.read_text(encoding="utf-8") == '{"token": "abc"}'

    if hasattr(_os, "getuid"):  # POSIX enforces the mode bits
        assert _stat.S_IMODE(target.stat().st_mode) == 0o600


def test_token_check_is_type_safe_and_rejects_same_length_tokens(
    tmp_path: Path,
) -> None:
    """compare_digest raises TypeError on non-str input — that must never leak."""
    handler = _handler_with_fake_page(_FakePage())
    token = "0123456789abcdef"
    t, port = _serve_in_thread(handler, token, tmp_path)

    def rpc(payload: dict[str, Any]) -> dict[str, Any]:
        with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
            f = sock.makefile("rwb")
            f.write((json.dumps(payload) + "\n").encode("utf-8"))
            f.flush()
            return json.loads(f.readline().decode("utf-8"))

    try:
        assert rpc({"token": token, "op": "status"})["ok"] is True
        for bad in ("fedcba9876543210", "", "café", None):
            resp = rpc({"token": bad, "op": "status"})
            assert resp["ok"] is False, bad
            assert resp["error"] == "unauthorized: bad token", (bad, resp)
        for bad_typed in (123, ["x"], {"a": 1}):
            resp = rpc({"token": bad_typed, "op": "status"})
            assert resp["ok"] is False, bad_typed
            assert resp["error"] == "unauthorized: bad token", (bad_typed, resp)
        assert rpc({"op": "status"})["error"] == "unauthorized: bad token"
    finally:
        _shutdown_thread(t, port, token)

    # The behaviour above is IDENTICAL before and after the fix — `!=` also
    # rejects every bad token. What changes is HOW: a plain `!=` on str leaks the
    # length of the shared prefix through timing. That is unobservable from a
    # socket, so pin it at the source, the same way Task 2 pins the single
    # `self._fields = []` literal.
    src = Path(session_server.__file__).read_text(encoding="utf-8")
    assert "secrets.compare_digest(" in src, (
        "compare the session token with secrets.compare_digest, not `!=`"
    )
    assert 'req.get("token") != token' not in src, (
        "the timing-variable `!=` token comparison is still in the source"
    )


def test_session_file_is_written_privately(tmp_path: Path) -> None:
    import os as _os
    import stat as _stat

    handler = _handler_with_fake_page(_FakePage())
    t, port = _serve_in_thread(handler, "tok", tmp_path)
    try:
        sf = session_server.session_file(tmp_path)
        assert json.loads(sf.read_text(encoding="utf-8"))["token"] == "tok"
        assert list((tmp_path / ".visus" / "sessions").glob("default.json.*.tmp")) == []
        if hasattr(_os, "getuid"):
            assert _stat.S_IMODE(sf.stat().st_mode) == 0o600
    finally:
        _shutdown_thread(t, port, "tok")


def test_serve_second_daemon_aborts_via_lock(tmp_path: Path) -> None:
    """A duplicate serve() on the same dir must hit the O_EXCL lock and abort."""
    handler = _handler_with_fake_page(_FakePage())
    token = "tok"
    t, port = _serve_in_thread(handler, token, tmp_path)
    try:
        with pytest.raises(session_server.SessionLockedError):
            session_server.serve(
                handler=_handler_with_fake_page(_FakePage()), token="other", cwd=tmp_path
            )
    finally:
        _shutdown_thread(t, port, token)
    # Lock is released on shutdown so a fresh daemon can claim it again.
    assert not (tmp_path / ".visus" / "sessions" / "default.json.lock").exists()


def test_serve_reaps_itself_after_the_idle_timeout(tmp_path: Path) -> None:
    import threading as _threading
    import time as _time

    handler = _handler_with_fake_page(_FakePage())
    t = _threading.Thread(
        target=session_server.serve,
        kwargs={
            "handler": handler,
            "token": "tok",
            "cwd": tmp_path,
            "idle_timeout": 0.5,
        },
        daemon=True,
    )
    t.start()
    sf = session_server.session_file(tmp_path)
    for _ in range(200):
        if sf.is_file():
            break
        _time.sleep(0.02)
    assert sf.is_file()

    t.join(timeout=20)
    assert not t.is_alive(), "the idle daemon never reaped itself"
    assert not sf.is_file()
    assert not sf.with_name(sf.name + ".lock").exists()


def test_activity_postpones_the_idle_timeout(tmp_path: Path) -> None:
    import threading as _threading
    import time as _time

    handler = _handler_with_fake_page(_FakePage())
    t = _threading.Thread(
        target=session_server.serve,
        kwargs={
            "handler": handler,
            "token": "tok",
            "cwd": tmp_path,
            "idle_timeout": 1.5,
        },
        daemon=True,
    )
    t.start()
    sf = session_server.session_file(tmp_path)
    for _ in range(200):
        if sf.is_file():
            break
        _time.sleep(0.02)
    port = int(json.loads(sf.read_text(encoding="utf-8"))["port"])

    deadline = _time.monotonic() + 3.0
    while _time.monotonic() < deadline:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            f = sock.makefile("rwb")
            f.write((json.dumps({"token": "tok", "op": "status"}) + "\n").encode("utf-8"))
            f.flush()
            assert json.loads(f.readline().decode("utf-8"))["ok"] is True
        _time.sleep(0.4)
    assert t.is_alive(), "an actively-used daemon reaped itself"
    _shutdown_thread(t, port, "tok")


def test_prune_drops_finished_threads() -> None:
    import threading as _threading

    done = _threading.Thread(target=lambda: None)
    done.start()
    done.join(timeout=10)
    running_gate = _threading.Event()
    running = _threading.Thread(target=running_gate.wait, daemon=True)
    running.start()
    try:
        assert session_server._prune([done, running]) == [running]
    finally:
        running_gate.set()
        running.join(timeout=10)


def test_serve_joins_worker_threads_before_tearing_down(tmp_path: Path) -> None:
    """No worker may outlive serve(): a live op must not meet a closing driver."""
    import threading as _threading

    baseline = {
        t.ident for t in _threading.enumerate() if t.name == "visus-session-conn"
    }
    handler = _handler_with_fake_page(_FakePage())
    token = "tok"
    t, port = _serve_in_thread(handler, token, tmp_path)
    for _ in range(12):
        # `with sock.makefile(...) as f:` (nested, not a bare local `f`) matters:
        # socket.makefile() bumps the socket's internal `_io_refs`, so `sock`'s own
        # `close()` (from the outer `with`) leaves the OS fd open — deferred to
        # whenever `f` is GC'd — unless `f` is *itself* closed first. An unclosed
        # `f` here would starve the corresponding server thread of EOF for the
        # rest of this function's lifetime, wedging it well past the shutdown
        # grace period and producing a false-positive "leftover worker thread".
        with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
            with sock.makefile("rwb") as f:
                f.write((json.dumps({"token": token, "op": "status"}) + "\n").encode("utf-8"))
                f.flush()
                assert json.loads(f.readline().decode("utf-8"))["ok"] is True
    _shutdown_thread(t, port, token)
    assert not t.is_alive()
    leftovers = [
        x
        for x in _threading.enumerate()
        if x.name == "visus-session-conn" and x.ident not in baseline
    ]
    assert leftovers == [], f"worker threads outlived serve(): {leftovers}"


@pytest.mark.browser
def test_closing_the_last_tab_really_stops_the_daemon(tmp_path: Path) -> None:
    """The socket must close and session.json must go — otherwise the next op
    launches a BRAND-NEW browser and the login is silently gone."""
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url="data:text/html,<title>only</title>"
    )
    token = "tok"
    t, port = _serve_in_thread(h, token, tmp_path)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=30) as sock:
            f = sock.makefile("rwb")
            payload = {"token": token, "op": "tab_close", "args": {}}
            f.write((json.dumps(payload) + "\n").encode("utf-8"))
            f.flush()
            resp = json.loads(f.readline().decode("utf-8"))
        assert resp["ok"] is True
        assert resp["result"] == {"closed": 0, "remaining": 0, "session_stopped": True}
        t.join(timeout=20)
        assert not t.is_alive(), "the daemon kept serving after the last tab closed"
        assert not session_server.session_file(tmp_path).is_file()
        assert not (tmp_path / ".visus" / "sessions" / "default.json.lock").exists()
    finally:
        if t.is_alive():
            _shutdown_thread(t, port, token)
        h.close()


def test_bind_stop_is_optional_and_binds() -> None:
    """A handler starts unbound (unit tests, embedders) and bind_stop attaches
    the server's event — an unbound handler must never raise, it just reports
    session_stopped=False when the last tab closes."""
    import threading as _threading

    h = session_server.SessionHandler(engine="chrome", headless=True)
    assert h._stop is None
    ev = _threading.Event()
    h.bind_stop(ev)
    assert h._stop is ev
    assert not ev.is_set(), "bind_stop must only wire the event, never set it"


def test_handle_serialises_concurrent_ops() -> None:
    """One handler, many connection threads: op bodies must never overlap.

    `serve()` runs one thread per connection over a SHARED handler, and the ops
    mutate `_known_handles`/`_active_handle` and switch the driver's window.
    """
    import threading as _threading
    import time as _time

    counter_lock = _threading.Lock()
    inside = {"now": 0, "max": 0}

    class _SlowPage(_FakePage):
        def title(self) -> str:
            with counter_lock:
                inside["now"] += 1
                inside["max"] = max(inside["max"], inside["now"])
            _time.sleep(0.05)
            with counter_lock:
                inside["now"] -= 1
            return "FakeTitle"

    h = _handler_with_fake_page(_SlowPage())
    results: list[dict[str, Any]] = []
    results_lock = _threading.Lock()

    def drive() -> None:
        resp = h.handle("title", {})
        with results_lock:
            results.append(resp)

    threads = [_threading.Thread(target=drive) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert len(results) == 8
    assert all(r["ok"] is True and r["result"] == "FakeTitle" for r in results)
    assert inside["max"] == 1, f"{inside['max']} ops ran concurrently on one driver"


def test_handle_lock_is_reentrant() -> None:
    """RLock, not Lock: an op that dispatches another op must not deadlock."""
    page = _FakePage()
    h = _handler_with_fake_page(page)
    with h._lock:
        assert h.handle("title", {})["result"] == "FakeTitle"


def test_peek_active_never_adopts_a_new_handle() -> None:
    """`_peek_active` observes; `_resolve_active` deliberately auto-follows."""
    h = session_server.SessionHandler(engine="chrome", headless=True)
    h._known_handles = ["A"]
    h._active_handle = "A"

    assert h._peek_active(["A", "B"]) == "A"
    assert h._known_handles == ["A"], "an observation mutated _known_handles"
    assert h._active_handle == "A", "an observation mutated _active_handle"

    # A closed active handle still falls back to the newest window.
    assert h._peek_active(["B", "C"]) == "C"
    assert h._active_handle == "A"

    # Contrast: the ACTION path adopts the new window on purpose.
    assert h._resolve_active(["A", "B"]) == "B"
    assert h._active_handle == "B"


@pytest.mark.browser
def test_status_and_tabs_do_not_adopt_a_background_window() -> None:
    """Polling status/tabs must not silently move the session to a popup."""
    h = session_server.SessionHandler(
        engine="chrome",
        headless=True,
        url="data:text/html,<title>first</title><button id=firstbtn>First</button>",
    )
    try:
        h.handle("list_fields", {"highlight": False})  # tab 0 becomes active
        driver = h._page._delegate._driver  # type: ignore[attr-defined]
        driver.switch_to.new_window("window")
        driver.get("data:text/html,<title>second</title><button id=b2>Second</button>")
        driver.switch_to.window(driver.window_handles[0])

        st = h.handle("status", {})["result"]
        assert st["title"] == "first", "status adopted the background window"
        assert st["windows"] == 2
        assert st["active_tab"] == 0

        tabs = h.handle("tabs", {})["result"]
        assert len(tabs["tabs"]) == 2
        assert tabs["active"] == 0, "tabs adopted the background window"
        assert tabs["tabs"][0]["active"] is True

        # Repeat polling is still stable.
        assert h.handle("status", {})["result"]["title"] == "first"
        assert h.handle("tabs", {})["result"]["active"] == 0
    finally:
        h.close()


def _exited_pid() -> int:
    """A pid that genuinely belonged to a process which has now exited."""
    import subprocess
    import sys as _sys

    proc = subprocess.Popen([_sys.executable, "-c", ""])
    proc.wait(timeout=30)
    return proc.pid


def test_kill_removes_json_and_lock_and_reports(tmp_path: Path) -> None:
    sf = _write_session(tmp_path, {"pid": _exited_pid(), "port": 2, "token": "t"})
    lock = sf.with_name(sf.name + ".lock")
    lock.write_text("999999", encoding="utf-8")
    msg = session_client.kill(start_dir=tmp_path)
    assert not sf.exists() and not lock.exists()
    assert "default.json" in msg and "default.json.lock" in msg


def test_kill_removes_an_orphaned_lock_with_no_session_file(tmp_path: Path) -> None:
    """The wedge case: the json was cleaned, the lock was not."""
    visus = tmp_path / ".visus" / "sessions"
    visus.mkdir(parents=True)
    lock = visus / "default.json.lock"
    lock.write_text(str(_exited_pid()), encoding="utf-8")
    msg = session_client.kill(start_dir=tmp_path)
    assert not lock.exists()
    assert "default.json.lock" in msg


def test_kill_with_nothing_to_remove(tmp_path: Path) -> None:
    assert session_client.kill(start_dir=tmp_path) == "no session state to remove"


def test_kill_terminates_a_live_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[int] = []
    sf = _write_session(tmp_path, {"pid": 4242, "port": 2, "token": "t"})
    sf.with_name(sf.name + ".lock").write_text("4242", encoding="utf-8")
    monkeypatch.setattr(session_client, "_probe_pid", lambda pid: True)
    monkeypatch.setattr(session_client, "_terminate", killed.append)
    msg = session_client.kill(start_dir=tmp_path)
    assert killed == [4242]
    assert "killed daemon pid 4242" in msg


def test_cli_session_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "kill", lambda: "removed session.json")
    r = runner.invoke(app, ["session", "kill"])
    assert r.exit_code == 0 and "removed session.json" in r.output


def test_claim_lock_reclaims_a_lock_whose_owner_is_dead(tmp_path: Path) -> None:
    """A `kill -9`'d daemon leaves its lock behind; the next daemon must reclaim it."""
    import os as _os

    sf = session_server.session_file(tmp_path)
    sf.parent.mkdir(parents=True, exist_ok=True)
    lock = sf.with_name(sf.name + ".lock")
    lock.write_text(str(_exited_pid()), encoding="utf-8")

    claimed = session_server._claim_lock(sf)
    assert claimed == lock
    assert lock.read_text(encoding="utf-8") == str(_os.getpid())


def test_claim_lock_refuses_while_the_owner_is_alive(tmp_path: Path) -> None:
    """A live owner still wins: the TOCTOU guard must not become a no-op."""
    import os as _os

    sf = session_server.session_file(tmp_path)
    sf.parent.mkdir(parents=True, exist_ok=True)
    lock = sf.with_name(sf.name + ".lock")
    lock.write_text(str(_os.getpid()), encoding="utf-8")  # THIS process is alive

    with pytest.raises(session_server.SessionLockedError, match="already holds"):
        session_server._claim_lock(sf)
    assert lock.read_text(encoding="utf-8") == str(_os.getpid())  # untouched


def test_claim_lock_reclaims_an_unreadable_lock(tmp_path: Path) -> None:
    """An empty/garbage lock carries no owner, so it is orphaned by definition."""
    import os as _os

    sf = session_server.session_file(tmp_path)
    sf.parent.mkdir(parents=True, exist_ok=True)
    lock = sf.with_name(sf.name + ".lock")
    lock.write_text("", encoding="utf-8")

    session_server._claim_lock(sf)
    assert lock.read_text(encoding="utf-8") == str(_os.getpid())


# ---------------------------------------------------------------------------
# Typer CliRunner arg parsing (session_client monkeypatched — no real daemon)
# ---------------------------------------------------------------------------


def test_cli_list_fields_json(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_send(op: str, args: dict[str, Any]) -> Any:
        captured["op"] = op
        captured["args"] = args
        return {"fields": [{"index": 0, "kind": "input", "name": "n", "locator": "#n"}]}

    _patch_client(monkeypatch, lambda op, args=None: fake_send(op, args or {}))
    r = runner.invoke(app, ["list-fields", "--kind", "input,button", "--all", "--json"])
    assert r.exit_code == 0
    assert captured["op"] == "list_fields"
    assert captured["args"]["kinds"] == ["input", "button"]
    assert captured["args"]["include_hidden"] is True
    data = json.loads(r.output)
    assert data[0]["locator"] == "#n"


def test_cli_list_fields_blocks_and_no_highlight(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args
        return {
            "fields": [
                {
                    "index": 0,
                    "kind": "input",
                    "name": "n",
                    "locator": "#n",
                    "code": 'page.locator("#n")',
                    "css": "#n",
                    "xpath": '//*[@id="n"]',
                    "frame": [],
                }
            ]
        }

    _patch_client(monkeypatch, fake_send)
    r = runner.invoke(app, ["list-fields", "--no-highlight"])
    assert r.exit_code == 0
    assert captured["args"]["highlight"] is False
    assert "input" in r.output and "#n" in r.output


def test_cli_click_by_index(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["op"], captured["args"] = op, args
        return "clicked"

    _patch_client(monkeypatch, fake_send)
    r = runner.invoke(app, ["click", "2"])
    assert r.exit_code == 0 and "clicked" in r.output
    assert captured["op"] == "click" and captured["args"] == {"index": 2}


def test_cli_click_by_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    _patch_client(
        monkeypatch, lambda op, args=None: captured.update(op=op, args=args) or "clicked"
    )
    r = runner.invoke(app, ["click", "--selector", "#go"])
    assert r.exit_code == 0
    assert captured["args"]["selector"] == "#go"


def test_cli_click_requires_target(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, lambda op, args=None: "x")
    r = runner.invoke(app, ["click"])
    assert r.exit_code == 1
    assert "no target" in r.output
    assert "--selector" in r.output


def test_cli_click_by_role_and_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """--role/--name wire through to the target dict (role re-resolution path)."""
    captured: dict[str, Any] = {}
    _patch_client(
        monkeypatch, lambda op, args=None: captured.update(op=op, args=args) or "ok"
    )
    r = runner.invoke(app, ["get-text", "--role", "button", "--name", "OK"])
    assert r.exit_code == 0
    assert captured["args"] == {
        "selector": None,
        "role": "button",
        "name": "OK",
        "target_text": None,
    }


def test_cli_click_by_text_maps_to_target_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """--text becomes a target_text TARGET (never a colliding 'text' key)."""
    captured: dict[str, Any] = {}
    _patch_client(
        monkeypatch, lambda op, args=None: captured.update(op=op, args=args) or "ok"
    )
    r = runner.invoke(app, ["click", "--text", "Save"])
    assert r.exit_code == 0
    assert captured["args"]["target_text"] == "Save"
    assert "text" not in captured["args"]  # no collision with fill's text VALUE


def test_cli_fill_keeps_text_value_and_target_text_distinct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """fill's positional VALUE lands in 'text'; a --selector target stays separate."""
    captured: dict[str, Any] = {}
    _patch_client(
        monkeypatch, lambda op, args=None: captured.update(op=op, args=args) or "ok"
    )
    r = runner.invoke(app, ["fill", "--selector", "#email", "--value", "hi"])
    assert r.exit_code == 0
    assert captured["args"]["text"] == "hi"  # the fill VALUE
    assert captured["args"]["selector"] == "#email"  # the TARGET
    assert "target_text" in captured["args"] and captured["args"]["target_text"] is None


def test_cli_fill_select_press(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    _patch_client(
        monkeypatch, lambda op, args=None: calls.append((op, args)) or "ok"
    )
    # index-first, value-second (intuitive: `visus fill 7 hello`, like `click N`)
    assert runner.invoke(app, ["fill", "1", "hello"]).exit_code == 0
    assert runner.invoke(app, ["select", "2", "us"]).exit_code == 0
    assert runner.invoke(app, ["press", "3", "Enter"]).exit_code == 0
    assert calls[0] == ("fill", {"index": 1, "text": "hello"})
    assert calls[1] == ("select", {"index": 2, "value": "us"})
    assert calls[2] == ("press", {"index": 3, "key": "Enter"})


def test_cli_goto_and_get_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        return "http://x" if op == "goto" else "the text"

    _patch_client(monkeypatch, fake_send)
    assert "navigated to http://x" in runner.invoke(app, ["goto", "http://x"]).output
    assert "the text" in runner.invoke(app, ["get-text", "0"]).output


def test_cli_check_uncheck_clear_screenshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_client(monkeypatch, lambda op, args=None: f"did-{op}")
    assert "did-check" in runner.invoke(app, ["check", "0"]).output
    assert "did-uncheck" in runner.invoke(app, ["uncheck", "0"]).output
    assert "did-clear_highlights" in runner.invoke(app, ["clear"]).output
    out = tmp_path / "x.png"
    assert "did-screenshot" in runner.invoke(app, ["session-screenshot", "-o", str(out)]).output


def test_cli_session_screenshot_full_page_and_element(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--full-page and element targeting reach the daemon (MCP browser_screenshot parity)."""
    calls: list[tuple[str, dict[str, Any]]] = []
    _patch_client(
        monkeypatch, lambda op, args=None: calls.append((op, args or {})) or "/p.png"
    )
    out = tmp_path / "x.png"

    # No target → page screenshot; full_page defaults to False and is forwarded.
    assert runner.invoke(app, ["session-screenshot", "-o", str(out)]).exit_code == 0
    assert calls[-1][0] == "screenshot"
    assert calls[-1][1]["full_page"] is False
    assert "index" not in calls[-1][1] and "selector" not in calls[-1][1]

    # --full-page forwards full_page=True.
    assert runner.invoke(app, ["session-screenshot", "-o", str(out), "--full-page"]).exit_code == 0
    assert calls[-1][1]["full_page"] is True

    # Element by index.
    assert runner.invoke(app, ["session-screenshot", "-o", str(out), "2"]).exit_code == 0
    assert calls[-1][1]["index"] == 2

    # Element by selector.
    assert (
        runner.invoke(app, ["session-screenshot", "-o", str(out), "-s", "#hero"]).exit_code == 0
    )
    assert calls[-1][1]["selector"] == "#hero"


def test_handle_screenshot_full_page_and_element(tmp_path: Path) -> None:
    """The daemon op honours full_page and element targets (mirrors browser_screenshot)."""
    page = _FakePage()
    h = _handler_with_fake_page(page)

    out = tmp_path / "full.png"
    assert h.handle("screenshot", {"path": str(out), "full_page": True})["ok"] is True
    assert out.read_bytes() == b"PNG"
    assert "screenshot:full_page=True" in page.log

    elem = tmp_path / "elem.png"
    res = h.handle("screenshot", {"path": str(elem), "selector": "#hero"})
    assert res["ok"] is True
    assert elem.read_bytes() == b"PNG"
    # The element path screenshots the locator, not the page.
    assert any(entry.startswith("screenshot:loc(#hero") for entry in page.log)


def test_cli_send_error_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """A daemon failure exits 1. The stdout/stderr split is asserted in a real
    subprocess by tests/test_cli_agent_loop.py — CliRunner's stream merging is
    click-version dependent, so only the exit code is asserted here."""

    def boom(op: str, args: dict[str, Any] | None = None, **_: Any) -> Any:
        raise session_client.SessionError("no live session")

    monkeypatch.setattr(session_client, "send", boom)
    monkeypatch.setattr(session_client, "send_envelope", boom)
    r = runner.invoke(app, ["click", "0"])
    assert r.exit_code == 1


# ---------------------------------------------------------------------------
# New CLI commands — arg parsing (session_client.send monkeypatched)
# ---------------------------------------------------------------------------


def _record(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Monkeypatch session_client.send to record (op, args) and return a generic result."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        if op in ("back", "forward", "reload", "url", "title"):
            return "http://dest"
        if op == "snapshot":
            return {"elements": [{"role": "button", "name": "Go"}]}
        if op == "count":
            return 3
        if op == "cookies":
            return {"cookies": [{"name": "sid", "value": "v", "domain": "d"}]}
        if op == "eval":
            return {"result": "evald"}
        if op == "tab_new":
            return {"index": 1, "title": "T"}
        if op == "tab_close":
            return {"closed": 1, "remaining": 1, "active": 0}
        if op == "find_image":
            return {"found": True, "x": 10, "y": 20, "confidence": 0.95}
        return f"did-{op}"

    _patch_client(monkeypatch, fake_send)
    return calls


def test_cli_back_forward_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    assert "went back to http://dest" in runner.invoke(app, ["back"]).output
    assert "went forward to http://dest" in runner.invoke(app, ["forward"]).output
    assert "reloaded http://dest" in runner.invoke(app, ["reload"]).output
    assert [c[0] for c in calls] == ["back", "forward", "reload"]


def test_cli_title_url_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    _record(monkeypatch)
    assert "http://dest" in runner.invoke(app, ["title"]).output
    assert "http://dest" in runner.invoke(app, ["url"]).output
    out = runner.invoke(app, ["snapshot"])
    assert out.exit_code == 0 and "button" in out.output and "Go" in out.output
    outj = runner.invoke(app, ["snapshot", "--json"])
    assert json.loads(outj.output)[0]["role"] == "button"


def test_cli_get_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    r = runner.invoke(app, ["get-attribute", "href", "2"])
    assert r.exit_code == 0
    assert calls[-1] == ("get_attribute", {"index": 2, "attr_name": "href"})
    r2 = runner.invoke(app, ["get-attribute", "href", "--selector", "#a"])
    assert r2.exit_code == 0
    assert calls[-1][1]["selector"] == "#a" and calls[-1][1]["attr_name"] == "href"


def test_cli_get_text_and_get_attribute_render_the_distinction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = iter(
        [
            {"value": "", "present": True},
            {"value": None, "present": False},
        ]
    )
    _patch_client(monkeypatch, lambda op, args=None: next(payloads))
    assert "(empty)" in runner.invoke(app, ["get-text", "0"]).output
    assert "(null)" in runner.invoke(app, ["get-attribute", "href", "0"]).output


def test_cli_count(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    r = runner.invoke(app, ["count", "--selector", ".item"])
    assert r.exit_code == 0 and "3" in r.output
    assert calls[-1] == ("count", {"selector": ".item", "role": None, "name": None,
                                    "target_text": None})


def test_cli_hover_dblclick_focus_clear_input(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    assert runner.invoke(app, ["hover", "1"]).exit_code == 0
    assert runner.invoke(app, ["dblclick", "2"]).exit_code == 0
    assert runner.invoke(app, ["focus", "3"]).exit_code == 0
    assert runner.invoke(app, ["clear-input", "4"]).exit_code == 0
    assert [c[0] for c in calls] == ["hover", "dblclick", "focus", "clear_input"]
    assert calls[0][1] == {"index": 1}
    assert calls[3][1] == {"index": 4}


def test_cli_drag_by_index_and_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    assert runner.invoke(app, ["drag", "0", "1"]).exit_code == 0
    assert calls[-1] == ("drag", {"index": 0, "target_index": 1})
    assert runner.invoke(app, ["drag", "--selector", "#s", "--to-selector", "#t"]).exit_code == 0
    assert calls[-1][1]["selector"] == "#s" and calls[-1][1]["target_selector"] == "#t"
    assert runner.invoke(app, ["drag", "--selector", "#s", "--to-index", "4"]).exit_code == 0
    assert calls[-1][1]["target_index"] == 4


def test_cli_drag_requires_target(monkeypatch: pytest.MonkeyPatch) -> None:
    _record(monkeypatch)
    r = runner.invoke(app, ["drag", "--selector", "#s"])
    assert r.exit_code == 1 and "drag target" in r.output


def test_cli_upload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _record(monkeypatch)
    f1 = tmp_path / "a.txt"
    f1.write_text("x")
    r = runner.invoke(app, ["upload", "2", str(f1)])
    assert r.exit_code == 0
    assert calls[-1][0] == "upload" and calls[-1][1]["index"] == 2
    assert calls[-1][1]["paths"] == [str(f1.resolve())]


def test_cli_upload_requires_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    _record(monkeypatch)
    r = runner.invoke(app, ["upload", "2"])
    assert r.exit_code == 1 and "file path" in r.output


def test_cli_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    r = runner.invoke(app, ["wait", "0", "--state", "hidden", "--timeout", "1234"])
    assert r.exit_code == 0
    assert calls[-1][0] == "wait"
    assert calls[-1][1]["state"] == "hidden" and calls[-1][1]["timeout"] == 1234


def test_cli_expect_text(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    r = runner.invoke(app, ["expect-text", "0", "Welcome"])
    assert r.exit_code == 0
    assert calls[-1] == ("expect_text", {"index": 0, "expected_text": "Welcome"})
    r2 = runner.invoke(app, ["expect-text", "--selector", "#h", "--expected", "Hi", "--timeout",
                             "500"])
    assert r2.exit_code == 0
    assert calls[-1][1]["expected_text"] == "Hi" and calls[-1][1]["timeout"] == 500


def test_cli_expect_text_requires_value(monkeypatch: pytest.MonkeyPatch) -> None:
    _record(monkeypatch)
    r = runner.invoke(app, ["expect-text", "--selector", "#h"])
    assert r.exit_code == 1 and "expected text" in r.output


def test_cli_tab_new_and_close(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    r = runner.invoke(app, ["tab-new", "http://x"])
    assert r.exit_code == 0 and "opened tab 1" in r.output
    assert calls[-1] == ("tab_new", {"url": "http://x"})
    r2 = runner.invoke(app, ["tab-close", "1"])
    assert r2.exit_code == 0 and "closed tab 1" in r2.output
    assert calls[-1] == ("tab_close", {"index": 1})


def test_cli_tab_close_last_tab_message(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        lambda op, args=None: {"closed": 0, "remaining": 0, "session_stopped": True},
    )
    r = runner.invoke(app, ["tab-close"])
    assert r.exit_code == 0 and "session stopped" in r.output


def test_cli_tab_close_last_tab_message_when_session_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never claim the session stopped when it did not."""
    _patch_client(
        monkeypatch,
        lambda op, args=None: {"closed": 0, "remaining": 0, "session_stopped": False},
    )
    r = runner.invoke(app, ["tab-close"])
    assert r.exit_code == 0
    assert "browser is closed" in r.output and "session stopped" not in r.output


def test_cli_dialog(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    assert runner.invoke(app, ["dialog"]).exit_code == 0
    assert calls[-1] == ("dialog", {"accept": True, "prompt_text": None})
    assert runner.invoke(app, ["dialog", "--dismiss"]).exit_code == 0
    assert calls[-1][1]["accept"] is False
    assert runner.invoke(app, ["dialog", "--prompt-text", "hi"]).exit_code == 0
    assert calls[-1][1]["prompt_text"] == "hi"


def test_cli_cookies_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _record(monkeypatch)
    r = runner.invoke(app, ["cookies"])
    assert r.exit_code == 0 and "sid=v" in r.output
    rj = runner.invoke(app, ["cookies", "--json"])
    assert json.loads(rj.output)[0]["name"] == "sid"


def test_cli_add_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    r = runner.invoke(app, ["add-cookies", '[{"name":"a","value":"b","url":"http://x"}]'])
    assert r.exit_code == 0
    assert calls[-1][0] == "add_cookies"
    assert calls[-1][1]["cookies"] == [{"name": "a", "value": "b", "url": "http://x"}]


def test_cli_add_cookies_bad_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _record(monkeypatch)
    assert runner.invoke(app, ["add-cookies", "{not json"]).exit_code == 1
    r2 = runner.invoke(app, ["add-cookies", '{"name":"a"}'])  # not a list
    assert r2.exit_code == 1 and "JSON list" in r2.output


def test_cli_clear_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    assert runner.invoke(app, ["clear-cookies"]).exit_code == 0
    assert calls[-1][0] == "clear_cookies"


def test_cli_eval(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    r = runner.invoke(app, ["eval", "() => 1+1", "42"])
    assert r.exit_code == 0 and "evald" in r.output
    assert calls[-1][0] == "eval"
    assert calls[-1][1]["expression"] == "() => 1+1" and calls[-1][1]["arg"] == 42
    # non-JSON arg falls back to a plain string
    runner.invoke(app, ["eval", "() => x", "plainstr"])
    assert calls[-1][1]["arg"] == "plainstr"


def test_cli_read_text_and_solve_captcha(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _record(monkeypatch)
    assert runner.invoke(app, ["read-text", "0"]).exit_code == 0
    assert calls[-1] == ("read_text", {"index": 0})
    assert runner.invoke(app, ["solve-captcha", "--selector", "#c"]).exit_code == 0
    assert calls[-1][0] == "solve_captcha" and calls[-1][1]["selector"] == "#c"


def test_cli_find_image(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls = _record(monkeypatch)
    tpl = tmp_path / "tpl.png"
    tpl.write_bytes(b"x")
    r = runner.invoke(app, ["find-image", str(tpl), "--confidence", "0.9"])
    assert r.exit_code == 0 and "found at (10, 20)" in r.output
    assert calls[-1][0] == "find_image"
    assert calls[-1][1]["template_path"] == str(tpl.resolve())
    assert calls[-1][1]["confidence"] == 0.9
    rj = runner.invoke(app, ["find-image", str(tpl), "--json"])
    assert json.loads(rj.output)["found"] is True


def test_cli_find_image_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _patch_client(monkeypatch, lambda op, args=None: {"found": False})
    tpl = tmp_path / "tpl.png"
    tpl.write_bytes(b"x")
    r = runner.invoke(app, ["find-image", str(tpl)])
    assert r.exit_code == 0 and "not found" in r.output


def test_cli_session_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda engine, headless, url, **kw: {"pid": 42, "port": 5555},
    )
    r = runner.invoke(app, ["session", "start", "http://x", "--engine", "chrome"])
    assert r.exit_code == 0 and "pid 42" in r.output and "port 5555" in r.output


def test_cli_session_start_forwards_the_idle_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_start(engine: str, headless: bool, url: str | None, **kw: Any) -> Any:
        captured.update(kw)
        return {"pid": 1, "port": 2}

    monkeypatch.setattr(session_client, "start_daemon", fake_start)
    r = runner.invoke(app, ["session", "start", "--idle-timeout", "600"])
    assert r.exit_code == 0
    assert captured["idle_timeout"] == 600.0
    r2 = runner.invoke(app, ["session", "start"])
    assert r2.exit_code == 0 and captured["idle_timeout"] is None


def test_cli_session_start_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a: Any, **kw: Any) -> Any:
        raise session_client.SessionError("already running")

    monkeypatch.setattr(session_client, "start_daemon", boom)
    r = runner.invoke(app, ["session", "start"])
    assert r.exit_code == 1 and "already running" in r.output


def test_cli_session_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "stop", lambda: "session stopped")
    r = runner.invoke(app, ["session", "stop"])
    assert r.exit_code == 0 and "session stopped" in r.output


def test_cli_session_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client,
        "status",
        lambda: {"pid": 1, "port": 2, "engine": "chrome", "headless": False, "url": "http://x"},
    )
    r = runner.invoke(app, ["session", "status"])
    assert r.exit_code == 0 and "chrome" in r.output and "http://x" in r.output
    rj = runner.invoke(app, ["session", "status", "--json"])
    assert json.loads(rj.output)["pid"] == 1


def test_cli_session_status_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "status", lambda: None)
    r = runner.invoke(app, ["session", "status"])
    assert r.exit_code == 1 and "no session running" in r.output


# ---------------------------------------------------------------------------
# SessionHandler action paths against a REAL headless page (browser-marked)
# ---------------------------------------------------------------------------


@pytest.mark.browser
def test_handle_real_page_list_and_index_actions(base_url: str) -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True, url=f"{base_url}/fields.html")
    try:
        resp = h.handle("list_fields", {"highlight": False})
        assert resp["ok"] is True
        fields = resp["result"]["fields"]
        assert fields and any(f["locator"] == "#topinput" for f in fields)
        top_idx = next(f["index"] for f in fields if f["locator"] == "#topinput")
        # fill the top input by index, then read it back via get_text on a shadow field
        assert h.handle("fill", {"index": top_idx, "text": "hi there"})["ok"] is True
        # an iframe field re-resolves via the frame chain
        iframe_idx = next(
            (f["index"] for f in fields if f["locator"] == "#iframeinput"), None
        )
        assert iframe_idx is not None
        assert h.handle("fill", {"index": iframe_idx, "text": "in frame"})["ok"] is True
    finally:
        h.close()


@pytest.mark.browser
def test_handle_real_page_deep_shadow_field_action(base_url: str) -> None:
    """End-to-end: the daemon's _resolve_field reaches an OPEN shadow root (deep=True)."""
    h = session_server.SessionHandler(engine="chrome", headless=True, url=f"{base_url}/fields.html")
    try:
        resp = h.handle("list_fields", {"highlight": False, "include_hidden": True})
        assert resp["ok"] is True
        fields = resp["result"]["fields"]
        # The shadow input/button live inside an open shadow root -> deep=True locators.
        shadow_in = next(
            (f for f in fields if f["locator"] == "#shadowinput"), None
        )
        assert shadow_in is not None, "expected a #shadowinput shadow-DOM field"
        assert shadow_in["deep"] is True  # re-resolution must use a deep (piercing) query
        # Filling it proves the daemon's frame-chain + deep re-resolution actually
        # reached an OPEN shadow root: a non-deep query could never match the
        # element, so an ok:True fill is end-to-end evidence the shadow root was
        # pierced via the cached field's deep flag (not just an iframe).
        r = h.handle("fill", {"index": shadow_in["index"], "text": "deep-x"})
        assert r["ok"] is True, r
        # The shadow button is also a deep field (deep re-resolution found it).
        shadow_btn = next((f for f in fields if f["locator"] == "#shadowbtn"), None)
        assert shadow_btn is not None and shadow_btn["deep"] is True
    finally:
        h.close()


@pytest.mark.browser
def test_handler_follows_focus_to_a_new_window() -> None:
    # Opening a new tab/window must make list_fields operate on THAT window (the
    # focused one), not the original — the "detect where I'm focused" behaviour.
    from visus.web.cli.session_server import SessionHandler

    h = SessionHandler(
        engine="chrome",
        headless=True,
        url="data:text/html,<button id=firstbtn>First</button>",
    )
    try:
        r1 = h.handle("list_fields", {"highlight": False})
        assert r1["ok"] is True
        assert "#firstbtn" in {f["locator"] for f in r1["result"]["fields"]}
        # A fresh session has exactly ONE browser window (regression: new_context()
        # used to spawn a second, headed browser — the "2 browsers" bug).
        assert h.handle("status", {})["result"]["windows"] == 1

        # Open a second window with a distinct element and switch focus to it.
        driver = h._page._delegate._driver  # type: ignore[attr-defined]
        driver.switch_to.new_window("window")
        driver.get("data:text/html,<button id=secondbtn>Second</button>")

        # The handler now enumerates the NEW (focused) window, not the first.
        r2 = h.handle("list_fields", {"highlight": False})
        assert r2["ok"] is True
        locs = {f["locator"] for f in r2["result"]["fields"]}
        assert "#secondbtn" in locs, locs
        assert h.handle("status", {})["result"]["windows"] == 2
    finally:
        h.close()


@pytest.mark.browser
def test_handler_manual_tab_switch_lists_and_acts_on_chosen_tab() -> None:
    # `tabs` lists every window/tab; `tab N` switches manually so list_fields runs
    # on the chosen tab (both directions), not just the auto-followed newest.
    from visus.web.cli.session_server import SessionHandler

    h = SessionHandler(
        engine="chrome",
        headless=True,
        url="data:text/html,<button id=firstbtn>First</button>",
    )
    try:
        h.handle("list_fields", {"highlight": False})  # establishes tab 0
        driver = h._page._delegate._driver  # type: ignore[attr-defined]
        driver.switch_to.new_window("tab")
        driver.get("data:text/html,<button id=secondbtn>Second</button>")
        h.handle("list_fields", {"highlight": False})  # auto-follows the new tab

        tabs = h.handle("tabs", {})["result"]
        assert len(tabs["tabs"]) == 2

        # manual switch BACK to tab 0
        assert h.handle("tab", {"index": 0})["result"]["active"] == 0
        back = h.handle("list_fields", {"highlight": False})
        assert "#firstbtn" in {f["locator"] for f in back["result"]["fields"]}

        # manual switch to tab 1
        h.handle("tab", {"index": 1})
        fwd = h.handle("list_fields", {"highlight": False})
        assert "#secondbtn" in {f["locator"] for f in fwd["result"]["fields"]}

        # out-of-range index is a clean error, not a crash
        assert h.handle("tab", {"index": 9})["ok"] is False
    finally:
        h.close()


# ---------------------------------------------------------------------------
# New ops — REAL headless page e2e (browser-marked)
# ---------------------------------------------------------------------------


@pytest.mark.browser
def test_handle_real_back_forward_reload(base_url: str) -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True, url=f"{base_url}/fields.html")
    try:
        h.handle("goto", {"url": f"{base_url}/index.html"})
        back = h.handle("back", {})
        assert back["ok"] is True and back["result"].endswith("fields.html")
        fwd = h.handle("forward", {})
        assert fwd["ok"] is True and fwd["result"].endswith("index.html")
        rel = h.handle("reload", {})
        assert rel["ok"] is True and rel["result"].endswith("index.html")
    finally:
        h.close()


@pytest.mark.browser
def test_handle_real_same_url_reload_and_goto_still_drop_the_field_cache(
    base_url: str,
) -> None:
    """A reload — or a goto to the CURRENT url — rebuilds the DOM without changing
    the url, so Task 1's url stamp alone would never notice. The explicit
    `_invalidate_fields()` clear is what catches this case."""
    url = f"{base_url}/fields.html"
    h = session_server.SessionHandler(engine="chrome", headless=True, url=url)
    try:
        fields = h.handle("list_fields", {"highlight": False})["result"]["fields"]
        assert fields
        assert h._fields_url == url  # same url before and after -> stamp is unchanged

        rel = h.handle("reload", {})
        assert rel["ok"] is True and rel["result"] == url
        assert h._fields == [] and h._fields_url is None
        stale = h.handle("click", {"index": 0})
        assert stale["ok"] is False and "run list_fields first" in stale["error"]

        h.handle("list_fields", {"highlight": False})
        assert h._fields

        same_goto = h.handle("goto", {"url": url})
        assert same_goto["ok"] is True and same_goto["result"] == url
        assert h._fields == [] and h._fields_url is None
        stale2 = h.handle("click", {"index": 0})
        assert stale2["ok"] is False and "run list_fields first" in stale2["error"]
    finally:
        h.close()


@pytest.mark.browser
def test_handle_real_title_url_snapshot(base_url: str) -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True, url=f"{base_url}/fields.html")
    try:
        assert h.handle("title", {})["result"] == "fields fixture"
        assert h.handle("url", {})["result"].endswith("fields.html")
        snap = h.handle("snapshot", {})
        assert snap["ok"] is True and isinstance(snap["result"]["elements"], list)
    finally:
        h.close()


@pytest.mark.browser
def test_handle_real_get_attribute_and_count(base_url: str) -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True, url=f"{base_url}/fields.html")
    try:
        href = h.handle("get_attribute", {"selector": "#lnk", "attr_name": "href"})
        assert href["ok"] is True and href["result"] == {
            "value": "https://example.com/",
            "present": True,
        }
        cnt = h.handle("count", {"selector": "input"})
        assert cnt["ok"] is True and cnt["result"] >= 5
    finally:
        h.close()


@pytest.mark.browser
def test_get_text_and_get_attribute_distinguish_null_from_empty(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/nullvsempty.html"
    )
    try:
        assert h.handle("get_text", {"selector": "#sometext"})["result"] == {
            "value": "hello",
            "present": True,
        }
        assert h.handle("get_text", {"selector": "#emptytext"})["result"] == {
            "value": "",
            "present": True,
        }
        flag = h.handle("get_attribute", {"selector": "#btn", "attr_name": "data-flag"})
        assert flag["result"] == {"value": "", "present": True}
        missing = h.handle(
            "get_attribute", {"selector": "#btn", "attr_name": "data-missing"}
        )
        assert missing["result"] == {"value": None, "present": False}
    finally:
        h.close()


@pytest.mark.browser
def test_handle_real_hover_dblclick_focus(base_url: str) -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True, url=f"{base_url}/fields.html")
    try:
        assert h.handle("hover", {"selector": "#btn"})["result"] == "hovered"
        assert h.handle("dblclick", {"selector": "#btn"})["result"] == "double-clicked"
        assert h.handle("focus", {"selector": "#topinput"})["result"] == "focused"
    finally:
        h.close()


@pytest.mark.browser
def test_export_script_replays_the_session_start_url(base_url: str) -> None:
    """A session started at a URL must export a script that can actually replay.

    The first navigation happens inside `_ensure()`, not through `handle()`, so
    the normal codegen path never sees it — without an explicit record the
    exported script starts on a blank page and every locator in it misses.
    """
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/links.html"
    )
    try:
        h.handle("click", {"target_text": "Go to page two"})
        script = h.handle("export_script", {})["result"]["script"]
        assert f"page.goto('{base_url}/links.html')" in script
        assert script.index("page.goto(") < script.index(".click()")
    finally:
        h.close()


@pytest.mark.browser
def test_handle_real_eval(base_url: str) -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True, url=f"{base_url}/fields.html")
    try:
        title = h.handle("eval", {"expression": "() => document.title"})
        assert title["ok"] is True and title["result"]["result"] == "fields fixture"
        doubled = h.handle("eval", {"expression": "(x) => x * 2", "arg": 21})
        assert doubled["result"]["result"] == 42
    finally:
        h.close()


@pytest.mark.browser
def test_handle_real_wait_visible(base_url: str) -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True, url=f"{base_url}/fields.html")
    try:
        ok = h.handle("wait", {"selector": "#topinput", "state": "visible", "timeout": 3000})
        assert ok["ok"] is True and ok["result"] == "element is visible"
        # A non-existent element must never become visible -> clean timeout error.
        bad = h.handle("wait", {"selector": "#nope", "state": "visible", "timeout": 200})
        assert bad["ok"] is False and "visible" in bad["error"]
    finally:
        h.close()


@pytest.mark.browser
def test_handle_real_expect_text(base_url: str) -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True, url=f"{base_url}/fields.html")
    try:
        ok = h.handle("expect_text", {"selector": "h1", "expected_text": "Fields"})
        assert ok["ok"] is True and ok["result"] == "PASSED"
        bad = h.handle(
            "expect_text", {"selector": "h1", "expected_text": "Nope", "timeout": 300}
        )
        assert bad["ok"] is True and bad["result"].startswith("FAILED")
    finally:
        h.close()


@pytest.mark.browser
def test_handle_real_cookies_roundtrip(base_url: str) -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True, url=f"{base_url}/fields.html")
    try:
        h.handle("clear_cookies", {})
        add = h.handle(
            "add_cookies", {"cookies": [{"name": "vt", "value": "yes", "url": base_url}]}
        )
        assert add["ok"] is True and add["result"] == "added 1 cookie(s)"
        got = h.handle("cookies", {})
        assert got["ok"] is True and any(c["name"] == "vt" for c in got["result"]["cookies"])
        cleared = h.handle("clear_cookies", {})
        assert cleared["result"] == "cookies cleared"
        assert h.handle("cookies", {})["result"]["cookies"] == []
    finally:
        h.close()


@pytest.mark.browser
def test_handle_real_tab_new_and_close(base_url: str) -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True, url=f"{base_url}/fields.html")
    try:
        new = h.handle("tab_new", {"url": f"{base_url}/index.html"})
        assert new["ok"] is True
        # The new tab is active and enumerable.
        assert h.handle("url", {})["result"].endswith("index.html")
        assert h.handle("tabs", {})["result"]["tabs"].__len__() == 2
        closed = h.handle("tab_close", {})  # close the active (new) tab
        assert closed["ok"] is True and closed["result"]["remaining"] == 1
        # Back on the original tab.
        assert h.handle("url", {})["result"].endswith("fields.html")
    finally:
        h.close()


@pytest.mark.browser
def test_handle_real_drag(base_url: str) -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True, url=f"{base_url}/fields.html")
    try:
        # Drag is a best-effort gesture; success here means no crash + ok:True.
        resp = h.handle("drag", {"selector": "#btn", "target_selector": "#topinput"})
        assert resp["ok"] is True and "dragged to" in resp["result"]
    finally:
        h.close()


# ---------------------------------------------------------------------------
# Field-cache staleness contract
# ---------------------------------------------------------------------------


@pytest.mark.browser
def test_index_targeting_refuses_after_a_js_driven_navigation(base_url: str) -> None:
    """A cached index must never re-resolve against a page it was not captured on.

    The two fixtures share the generic fallback selector `button.btn.primary`, so
    before this fix `click <index>` returned "clicked" having hit page B's button.
    """
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/stale_a.html"
    )
    try:
        fields = h.handle("list_fields", {"highlight": False})["result"]["fields"]
        by_locator = {f["locator"]: f["index"] for f in fields}
        assert "button.btn.primary" in by_locator, by_locator
        btn_idx = by_locator["button.btn.primary"]
        link_idx = by_locator["#tob"]

        # Navigate by CLICKING the link: a JS/DOM navigation that never reaches
        # the `goto` op, so only the URL stamp can catch it.
        assert h.handle("click", {"index": link_idx})["ok"] is True
        assert h.handle(
            "wait", {"selector": "#bmarker", "state": "visible", "timeout": 5000}
        )["result"] == "element is visible"

        resp = h.handle("click", {"index": btn_idx})
        assert resp["ok"] is False
        assert "StaleFieldIndexError" in resp["error"]
        assert "run list-fields again" in resp["error"]

        # Proof the risk was real: the stale selector DOES match an element here,
        # and it was not clicked.
        assert h.handle("count", {"selector": "button.btn.primary"})["result"] == 1
        clicked = h.handle(
            "eval", {"expression": "() => document.body.dataset.clicked || ''"}
        )["result"]["result"]
        assert clicked == "", f"a stale index clicked the wrong element: {clicked!r}"

        # A fresh list_fields re-stamps and the SAME selector is a different index.
        fresh = h.handle("list_fields", {"highlight": False})["result"]["fields"]
        fresh_by_locator = {f["locator"]: f["index"] for f in fresh}
        assert fresh_by_locator["button.btn.primary"] != btn_idx
        assert h.handle(
            "click", {"index": fresh_by_locator["button.btn.primary"]}
        )["ok"] is True
        assert h.handle(
            "eval", {"expression": "() => document.body.dataset.clicked || ''"}
        )["result"]["result"] == "B"
    finally:
        h.close()


def test_fields_stale_predicate() -> None:
    """fields_stale() is the single source of truth PLAN 4's page footer reads."""
    h = session_server.SessionHandler(engine="chrome", headless=True)
    assert h.fields_stale() is True  # no browser, no cache

    page = _FakePage()
    h = _handler_with_fake_page(page)
    assert h.fields_stale() is True  # browser up, but nothing cached yet
    h.handle("list_fields", {})
    assert h.fields_stale() is False
    assert h._fields_url == page.url
    page.url = "http://elsewhere.test/"
    assert h.fields_stale() is True


def test_invalidate_fields_drops_cache_and_stamp() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("list_fields", {})
    assert h._fields and h._fields_url is not None
    h._invalidate_fields()
    assert h._fields == [] and h._fields_url is None


def test_navigation_ops_invalidate_the_field_cache() -> None:
    """goto/back/forward/reload drop cached indexes — like tab/tab_new/tab_close."""
    for op, args in (
        ("goto", {"url": "http://elsewhere.test/"}),
        ("back", {}),
        ("forward", {}),
        ("reload", {}),
    ):
        page = _FakePage()
        h = _handler_with_fake_page(page)
        h.handle("list_fields", {})
        assert h._fields, op
        assert h.handle(op, args)["ok"] is True, op
        assert h._fields == [], f"{op} left the field cache in place"
        assert h._fields_url is None, f"{op} left the page stamp in place"
        resp = h.handle("click", {"index": 0})
        assert resp["ok"] is False, op
        assert "run list_fields first" in resp["error"], op


def test_tab_ops_also_drop_the_page_stamp() -> None:
    """The pre-existing `self._fields = []` sites must clear the stamp too."""
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("list_fields", {})
    h._invalidate_fields()
    assert h._fields_url is None
    # tab ops need a real driver, so assert the source contract instead: every
    # site that empties the cache goes through _invalidate_fields(), so the only
    # remaining literal is the one inside _invalidate_fields itself.
    src = Path(session_server.__file__).read_text(encoding="utf-8")
    assert src.count("self._fields = []") == 1, (
        "clear the cache via self._invalidate_fields(); the only literal "
        "`self._fields = []` belongs inside _invalidate_fields itself"
    )


def test_cli_tabs_and_tab(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["call"] = (op, args)
        if op == "tabs":
            return {
                "tabs": [
                    {"index": 0, "title": "A", "url": "u0", "active": True},
                    {"index": 1, "title": "B", "url": "u1", "active": False},
                ],
                "active": 0,
            }
        return {"active": 1, "title": "B"}

    _patch_client(monkeypatch, lambda op, args=None: fake_send(op, args))
    r = runner.invoke(app, ["tabs"])
    assert r.exit_code == 0 and "[0]" in r.output and "[1]" in r.output and "*" in r.output
    r2 = runner.invoke(app, ["tab", "1"])
    assert r2.exit_code == 0 and "switched to tab 1" in r2.output
    assert captured["call"] == ("tab", {"index": 1})


def test_dispatch_tabs_and_tab() -> None:
    calls: list[tuple[str, Any]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "tabs":
            return {"tabs": [{"index": 0, "title": "A", "url": "u", "active": True}], "active": 0}
        return {"active": 0, "title": "A"}

    assert "[0]" in console.dispatch("tabs", send)
    assert "switched to tab 0" in console.dispatch("tab 0", send)
    assert calls[-1] == ("tab", {"index": 0})


# ---------------------------------------------------------------------------
# console.dispatch — new verbs (fake send)
# ---------------------------------------------------------------------------


def _dispatch_send() -> tuple[list[tuple[str, dict[str, Any]]], Any]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op in ("back", "forward", "reload", "url", "title"):
            return "http://dest"
        if op == "snapshot":
            return {"elements": [{"role": "button", "name": "Go"}]}
        if op == "count":
            return 2
        if op == "cookies":
            return {"cookies": [{"name": "sid", "value": "v", "domain": "d"}]}
        if op == "eval":
            return {"result": "RES"}
        if op == "tab_new":
            return {"index": 1, "title": "T"}
        if op == "tab_close":
            return {"closed": 1, "remaining": 1, "active": 0}
        return "ok"

    return calls, send


def test_dispatch_navigation_and_inspect_verbs() -> None:
    calls, send = _dispatch_send()
    assert "went back to http://dest" in console.dispatch("back", send)
    assert "went forward to http://dest" in console.dispatch("forward", send)
    assert "reloaded http://dest" in console.dispatch("reload", send)
    assert console.dispatch("title", send) == "http://dest"
    assert console.dispatch("url", send) == "http://dest"
    assert "button" in console.dispatch("snapshot", send)
    assert [c[0] for c in calls] == ["back", "forward", "reload", "title", "url", "snapshot"]


def test_dispatch_hover_dblclick_focus_clear_attr_count() -> None:
    calls, send = _dispatch_send()
    console.dispatch("hover 1", send)
    console.dispatch("dblclick 2", send)
    console.dispatch("focus 3", send)
    console.dispatch("clear-input 6", send)
    console.dispatch("attr href 4", send)
    assert console.dispatch("count 5", send) == "2"
    ops = [c[0] for c in calls]
    assert ops == ["hover", "dblclick", "focus", "clear_input", "get_attribute", "count"]
    assert calls[0][1] == {"index": 1}
    assert calls[3][1] == {"index": 6}
    assert calls[4][1] == {"index": 4, "attr_name": "href"}


def test_dispatch_wait_and_expect() -> None:
    calls, send = _dispatch_send()
    console.dispatch("wait 0 hidden", send)
    console.dispatch("expect 1 Welcome back", send)
    assert calls[0] == ("wait", {"index": 0, "state": "hidden"})
    assert calls[1] == ("expect_text", {"index": 1, "expected_text": "Welcome back"})


def test_dispatch_cookies_eval_dialog() -> None:
    calls, send = _dispatch_send()
    assert "sid=v" in console.dispatch("cookies", send)
    assert console.dispatch("eval () => 1", send) == "RES"
    console.dispatch("dialog", send)
    console.dispatch("dialog dismiss", send)
    assert calls[1] == ("eval", {"expression": "() => 1"})
    assert calls[2][1]["accept"] is True
    assert calls[3][1]["accept"] is False


def test_dispatch_tab_new_and_close() -> None:
    calls, send = _dispatch_send()
    assert "opened tab 1" in console.dispatch("tab-new http://x", send)
    assert "closed tab 1" in console.dispatch("tab-close 1", send)
    assert calls[0] == ("tab_new", {"url": "http://x"})
    assert calls[1] == ("tab_close", {"index": 1})


def test_dispatch_tab_close_last_tab_messages() -> None:
    def send_stopped(op: str, args: dict[str, Any]) -> Any:
        return {"closed": 0, "remaining": 0, "session_stopped": True}

    def send_alive(op: str, args: dict[str, Any]) -> Any:
        return {"closed": 0, "remaining": 0, "session_stopped": False}

    assert "session stopped" in console.dispatch("tab-close", send_stopped)
    out = console.dispatch("tab-close", send_alive)
    assert "browser is closed" in out and "session stopped" not in out


def test_daemon_log_rotates_instead_of_growing_forever(tmp_path: Path) -> None:
    log = tmp_path / "daemon.log"
    logger = session_server._make_logger(log, max_bytes=2048, backup_count=2)
    try:
        for i in range(400):
            logger.info("%s %d", "x" * 80, i)
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    assert log.is_file()
    assert log.stat().st_size <= 4096, "the active log grew past its cap"
    assert (tmp_path / "daemon.log.1").is_file(), "nothing rotated"
    assert (tmp_path / "daemon.log.2").is_file()
    assert not (tmp_path / "daemon.log.3").exists(), "backupCount was not honoured"


def test_make_logger_is_idempotent(tmp_path: Path) -> None:
    """Re-creating the logger must not stack handlers (double-written lines)."""
    log = tmp_path / "daemon.log"
    first = session_server._make_logger(log)
    second = session_server._make_logger(log)
    try:
        assert first is second
        assert len(second.handlers) == 1
        second.info("hello")
    finally:
        for handler in list(second.handlers):
            second.removeHandler(handler)
            handler.close()
    assert log.read_text(encoding="utf-8").count("hello") == 1
