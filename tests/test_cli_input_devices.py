"""Standalone keyboard and mouse: daemon ops, CLI wiring, REPL, real browser."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


def _record_envelope(
    monkeypatch: pytest.MonkeyPatch, calls: list[tuple[str, dict[str, Any]]]
) -> None:
    """Record `send_envelope` calls — `fill` and `press` go through the envelope."""
    monkeypatch.setattr(
        session_client,
        "send_envelope",
        lambda op, args=None, **_: calls.append((op, args or {}))
        or {"ok": True, "result": "ok", "page": {"url": "http://x/", "title": "T"}},
    )


class _RecordingKeyboard:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def down(self, key: str) -> None:
        self._log.append(f"kb.down:{key}")

    def up(self, key: str) -> None:
        self._log.append(f"kb.up:{key}")

    def press(self, key: str) -> None:
        self._log.append(f"kb.press:{key}")

    def type(self, text: str) -> None:
        self._log.append(f"kb.type:{text}")


class _RecordingLocator:
    def __init__(self, log: list[str], label: str) -> None:
        self._log = log
        self._label = label

    def first(self) -> _RecordingLocator:
        return self

    def focus(self) -> None:
        self._log.append(f"focus:{self._label}")

    def press(self, key: str) -> None:
        self._log.append(f"press:{self._label}:{key}")

    def fill(self, text: str) -> None:
        self._log.append(f"fill:{self._label}:{text}")


class _KeyPage:
    url = "http://x/"

    def __init__(self) -> None:
        self.log: list[str] = []

    @property
    def keyboard(self) -> _RecordingKeyboard:
        return _RecordingKeyboard(self.log)

    def locator(self, selector: str, *, deep: bool = False) -> _RecordingLocator:
        return _RecordingLocator(self.log, f"loc({selector})")


class _FakeBrowser:
    def close(self) -> None:
        pass

    @property
    def contexts(self) -> list[Any]:
        return []


def _handler(page: Any) -> session_server.SessionHandler:
    h = session_server.SessionHandler(engine="chrome", headless=True)
    h._browser = _FakeBrowser()  # type: ignore[assignment]
    h._page = page
    return h


def test_op_press_without_a_target_uses_the_page_keyboard() -> None:
    page = _KeyPage()
    h = _handler(page)
    assert h.handle("press", {"key": "Enter"})["result"] == "pressed 'Enter'"
    assert page.log == ["kb.press:Enter"]


def test_op_press_with_a_target_still_targets_the_element() -> None:
    page = _KeyPage()
    h = _handler(page)
    assert h.handle("press", {"selector": "#i", "key": "Tab"})["result"] == "pressed 'Tab'"
    assert page.log == ["press:loc(#i):Tab"]


def test_op_type_focuses_the_target_then_types() -> None:
    page = _KeyPage()
    h = _handler(page)
    assert h.handle("type", {"selector": "#i", "text": "abc"})["result"] == "typed 'abc'"
    assert page.log == ["focus:loc(#i)", "kb.type:abc"]
    page.log.clear()
    assert h.handle("type", {"text": "xyz"})["result"] == "typed 'xyz'"
    assert page.log == ["kb.type:xyz"]


def test_op_key_down_and_up() -> None:
    page = _KeyPage()
    h = _handler(page)
    assert h.handle("key_down", {"key": "Shift"})["result"] == "key down 'Shift'"
    assert h.handle("key_up", {"key": "Shift"})["result"] == "key up 'Shift'"
    assert page.log == ["kb.down:Shift", "kb.up:Shift"]


def test_op_fill_submit_presses_enter_and_keeps_the_old_message() -> None:
    page = _KeyPage()
    h = _handler(page)
    assert h.handle("fill", {"selector": "#q", "text": "hi"})["result"] == "filled with 'hi'"
    assert page.log == ["fill:loc(#q):hi"]
    page.log.clear()
    out = h.handle("fill", {"selector": "#q", "text": "hi", "submit": True})["result"]
    assert out == "filled with 'hi' and pressed Enter"
    assert page.log == ["fill:loc(#q):hi", "press:loc(#q):Enter"]


def test_cli_press_standalone_and_by_index(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    _record_envelope(monkeypatch, calls)
    assert runner.invoke(app, ["press", "Enter"]).exit_code == 0
    assert runner.invoke(app, ["press", "3", "Tab"]).exit_code == 0
    assert runner.invoke(app, ["press", "--selector", "#i", "--key", "Escape"]).exit_code == 0
    assert calls[0] == ("press", {"key": "Enter"})
    assert calls[1] == ("press", {"index": 3, "key": "Tab"})
    assert calls[2][1]["selector"] == "#i" and calls[2][1]["key"] == "Escape"


def test_cli_type_keydown_keyup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: calls.append((op, args or {})) or "ok"
    )
    assert runner.invoke(app, ["type", "hello world"]).exit_code == 0
    assert runner.invoke(app, ["type", "scoped", "--selector", "#i"]).exit_code == 0
    assert runner.invoke(app, ["keydown", "Shift"]).exit_code == 0
    assert runner.invoke(app, ["keyup", "Shift"]).exit_code == 0
    assert calls[0] == ("type", {"text": "hello world"})
    assert calls[1][1]["text"] == "scoped" and calls[1][1]["selector"] == "#i"
    assert calls[2] == ("key_down", {"key": "Shift"})
    assert calls[3] == ("key_up", {"key": "Shift"})


def test_cli_fill_submit_only_sent_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    _record_envelope(monkeypatch, calls)
    assert runner.invoke(app, ["fill", "1", "hello"]).exit_code == 0
    assert runner.invoke(app, ["fill", "1", "hello", "--submit"]).exit_code == 0
    assert calls[0] == ("fill", {"index": 1, "text": "hello"})
    assert calls[1] == ("fill", {"index": 1, "text": "hello", "submit": True})


def test_repl_keyboard_commands() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return "ok"

    console.dispatch("press Enter", send)
    console.dispatch("press 3 Tab", send)
    console.dispatch("type hello world", send)
    console.dispatch("keydown Shift", send)
    console.dispatch("keyup Shift", send)
    assert calls[0] == ("press", {"key": "Enter"})
    assert calls[1] == ("press", {"index": 3, "key": "Tab"})
    assert calls[2] == ("type", {"text": "hello world"})
    assert calls[3] == ("key_down", {"key": "Shift"})
    assert calls[4] == ("key_up", {"key": "Shift"})
    help_text = console.dispatch("help", send)
    for cmd in ("type", "keydown", "keyup"):
        assert cmd in help_text


@pytest.mark.browser
def test_keyboard_ops_against_a_real_page(base_url: str) -> None:
    """input.html reports Enter on #k and a held Shift on #shift."""
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/input.html"
    )
    try:
        assert h.handle("focus", {"selector": "#k"})["ok"] is True
        assert h.handle("type", {"text": "abc"})["ok"] is True
        value = h.handle("eval", {"expression": "() => document.getElementById('k').value"})
        assert value["result"]["result"] == "abc"

        assert h.handle("press", {"key": "Enter"})["ok"] is True
        marker = h.handle(
            "eval", {"expression": "() => document.getElementById('k2').textContent"}
        )
        assert marker["result"]["result"] == "enter"

        assert h.handle("focus", {"selector": "#shift"})["ok"] is True
        assert h.handle("key_down", {"key": "Shift"})["ok"] is True
        assert h.handle("press", {"key": "a"})["ok"] is True
        assert h.handle("key_up", {"key": "Shift"})["ok"] is True
        held = h.handle(
            "eval", {"expression": "() => document.getElementById('k3').textContent"}
        )
        assert held["result"]["result"] == "shift-held"
    finally:
        h.close()


@pytest.mark.browser
def test_fill_submit_against_a_real_page(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/interactions.html"
    )
    try:
        out = h.handle("fill", {"selector": "#txt", "text": "typed", "submit": True})
        assert out["ok"] is True and "pressed Enter" in out["result"]
        marker = h.handle(
            "eval", {"expression": "() => document.getElementById('pressres').textContent"}
        )
        assert marker["result"]["result"] == "enter"
    finally:
        h.close()


# ---------------------------------------------------------------------------
# Mouse device: mousemove / mousedown / mouseup / mousewheel, and --button
# ---------------------------------------------------------------------------


class _RecordingMouse:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def move(self, x: float, y: float) -> None:
        self._log.append(f"mouse.move:{x},{y}")

    def down(self, *, button: str = "left") -> None:
        self._log.append(f"mouse.down:{button}")

    def up(self, *, button: str = "left") -> None:
        self._log.append(f"mouse.up:{button}")

    def click(self, x: float, y: float, *, button: str = "left") -> None:
        self._log.append(f"mouse.click:{x},{y},{button}")

    def dblclick(self, x: float, y: float, *, button: str = "left") -> None:
        self._log.append(f"mouse.dblclick:{x},{y},{button}")

    def wheel(self, delta_x: float, delta_y: float) -> None:
        self._log.append(f"mouse.wheel:{delta_x},{delta_y}")


class _BoxLocator:
    """Locator stub that reports a bounding box -- what a non-left click needs."""

    def __init__(self, log: list[str], label: str) -> None:
        self._log = log
        self._label = label

    def first(self) -> _BoxLocator:
        return self

    def click(self) -> None:
        self._log.append(f"click:{self._label}")

    def dblclick(self) -> None:
        self._log.append(f"dblclick:{self._label}")

    def scroll_into_view_if_needed(self) -> None:
        self._log.append(f"scroll:{self._label}")

    def bounding_box(self) -> dict[str, float]:
        return {"x": 10.0, "y": 20.0, "width": 40.0, "height": 10.0}


class _MousePage:
    url = "http://x/"

    def __init__(self) -> None:
        self.log: list[str] = []

    @property
    def mouse(self) -> _RecordingMouse:
        return _RecordingMouse(self.log)

    def locator(self, selector: str, *, deep: bool = False) -> _BoxLocator:
        return _BoxLocator(self.log, f"loc({selector})")


def test_mouse_facade_forwards_the_button() -> None:
    """Mouse.down/up/click/dblclick must pass `button` down to the delegate."""
    from visus.web.api.input import Mouse

    calls: list[tuple[str, object]] = []

    class _Delegate:
        def mouse_move(self, x: float, y: float) -> None:
            calls.append(("move", (x, y)))

        def mouse_down(self, *, button: str = "left") -> None:
            calls.append(("down", button))

        def mouse_up(self, *, button: str = "left") -> None:
            calls.append(("up", button))

        def mouse_click(self, x: float, y: float, *, button: str = "left") -> None:
            calls.append(("click", (x, y, button)))

        def mouse_dblclick(self, x: float, y: float, *, button: str = "left") -> None:
            calls.append(("dblclick", (x, y, button)))

        def mouse_wheel(self, delta_x: float, delta_y: float) -> None:
            calls.append(("wheel", (delta_x, delta_y)))

    m = Mouse(_Delegate())  # type: ignore[arg-type]
    m.down(button="right")
    m.up(button="right")
    m.click(1.0, 2.0, button="middle")
    m.dblclick(3.0, 4.0)
    m.wheel(0.0, 120.0)
    assert calls == [
        ("down", "right"),
        ("up", "right"),
        ("click", (1.0, 2.0, "middle")),
        ("dblclick", (3.0, 4.0, "left")),
        ("wheel", (0.0, 120.0)),
    ]


def test_op_mouse_move_down_up_wheel() -> None:
    page = _MousePage()
    h = _handler(page)
    assert h.handle("mouse_move", {"x": 5, "y": 6})["result"] == "moved to (5.0, 6.0)"
    assert h.handle("mouse_down", {"button": "right"})["result"] == "right button down"
    assert h.handle("mouse_up", {"button": "right"})["result"] == "right button up"
    assert h.handle("mouse_wheel", {"delta_x": 0, "delta_y": 120})["result"] == (
        "scrolled by (0.0, 120.0)"
    )
    assert page.log == [
        "mouse.move:5.0,6.0",
        "mouse.down:right",
        "mouse.up:right",
        "mouse.wheel:0.0,120.0",
    ]


def test_op_click_default_button_still_uses_the_locator() -> None:
    """The left path must stay on the actionability click -- no pointer geometry."""
    page = _MousePage()
    h = _handler(page)
    assert h.handle("click", {"selector": "#b"})["result"] == "clicked"
    assert h.handle("dblclick", {"selector": "#b"})["result"] == "double-clicked"
    assert page.log == ["click:loc(#b)", "dblclick:loc(#b)"]


def test_op_click_and_dblclick_with_a_non_left_button() -> None:
    page = _MousePage()
    h = _handler(page)
    out = h.handle("click", {"selector": "#b", "button": "right"})["result"]
    assert out == "clicked with the right button"
    # centre of {x:10, y:20, w:40, h:10}
    assert page.log == ["scroll:loc(#b)", "mouse.click:30.0,25.0,right"]
    page.log.clear()
    out = h.handle("dblclick", {"selector": "#b", "button": "middle"})["result"]
    assert out == "double-clicked with the middle button"
    assert page.log == ["scroll:loc(#b)", "mouse.dblclick:30.0,25.0,middle"]


def test_cli_mouse_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: calls.append((op, args or {})) or "ok"
    )
    assert runner.invoke(app, ["mousemove", "12", "34"]).exit_code == 0
    assert runner.invoke(app, ["mousedown", "--button", "right"]).exit_code == 0
    assert runner.invoke(app, ["mouseup", "--button", "right"]).exit_code == 0
    assert runner.invoke(app, ["mousewheel", "0", "240"]).exit_code == 0
    assert calls[0] == ("mouse_move", {"x": 12.0, "y": 34.0})
    assert calls[1] == ("mouse_down", {"button": "right"})
    assert calls[2] == ("mouse_up", {"button": "right"})
    assert calls[3] == ("mouse_wheel", {"delta_x": 0.0, "delta_y": 240.0})


def test_cli_click_button_flag_only_sent_when_not_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default payload must stay {"index": N} so existing tests still hold."""
    calls: list[tuple[str, dict[str, Any]]] = []
    _record_envelope(monkeypatch, calls)
    assert runner.invoke(app, ["click", "2"]).exit_code == 0
    assert runner.invoke(app, ["click", "2", "--button", "right"]).exit_code == 0
    assert runner.invoke(app, ["dblclick", "2", "-b", "middle"]).exit_code == 0
    assert calls[0] == ("click", {"index": 2})
    assert calls[1] == ("click", {"index": 2, "button": "right"})
    assert calls[2] == ("dblclick", {"index": 2, "button": "middle"})


def test_repl_mouse_and_button_clicks() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return "ok"

    console.dispatch("mousemove 12 34", send)
    console.dispatch("mousedown right", send)
    console.dispatch("mouseup right", send)
    console.dispatch("mousewheel 0 240", send)
    console.dispatch("click 3 right", send)
    console.dispatch("dblclick #b middle", send)
    console.dispatch("click 3", send)
    assert calls[0] == ("mouse_move", {"x": 12.0, "y": 34.0})
    assert calls[1] == ("mouse_down", {"button": "right"})
    assert calls[2] == ("mouse_up", {"button": "right"})
    assert calls[3] == ("mouse_wheel", {"delta_x": 0.0, "delta_y": 240.0})
    assert calls[4] == ("click", {"index": 3, "button": "right"})
    assert calls[5] == ("dblclick", {"selector": "#b", "button": "middle"})
    assert calls[6] == ("click", {"index": 3})
    help_text = console.dispatch("help", send)
    for cmd in ("mousemove", "mousedown", "mouseup", "mousewheel"):
        assert cmd in help_text


@pytest.mark.browser
def test_mouse_buttons_against_a_real_page(base_url: str) -> None:
    """mouse.html records e.button, so this proves the right index reached the DOM."""
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/mouse.html"
    )

    def text(el: str) -> object:
        return h.handle(
            "eval", {"expression": f"() => document.getElementById('{el}').textContent"}
        )["result"]["result"]

    try:
        assert h.handle("mouse_move", {"x": 150, "y": 140})["ok"] is True
        assert h.handle("mouse_down", {"button": "middle"})["ok"] is True
        assert h.handle("mouse_up", {"button": "middle"})["ok"] is True
        assert text("downres") == "down-1"
        assert text("upres") == "up-1"
        assert text("auxres") == "aux-1"
    finally:
        h.close()


@pytest.mark.browser
def test_mouse_wheel_scrolls_at_the_pointer(base_url: str) -> None:
    """Wheel gets its own session: a middle click first would swallow it.

    Chrome enters autoscroll mode on a middle click and consumes the next wheel
    event until the pointer moves again — a browser behaviour, not a bug, but
    one that makes a combined button+wheel test lie about the wheel.

    The assertion auto-retries rather than reading once: the fixture's `wheel`
    listener is registered `{passive: true}`, which Chrome dispatches
    asynchronously, so an immediate read wins the race only sometimes.
    """
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/mouse.html"
    )
    try:
        assert h.handle("mouse_move", {"x": 150, "y": 140})["ok"] is True
        assert h.handle("mouse_wheel", {"delta_x": 0, "delta_y": 200})["ok"] is True
        settled = h.handle(
            "expect_text",
            {"selector": "#wheelres", "expected_text": "wheel-200", "timeout": 5000},
        )
        assert settled["result"] == "PASSED", settled
    finally:
        h.close()


@pytest.mark.browser
def test_right_click_opens_the_context_menu(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/mouse.html"
    )
    try:
        out = h.handle("click", {"selector": "#pad", "button": "right"})
        assert out["ok"] is True, out
        assert out["result"] == "clicked with the right button"
        marker = h.handle(
            "eval", {"expression": "() => document.getElementById('ctxres').textContent"}
        )
        assert marker["result"]["result"] == "context"
        down = h.handle(
            "eval", {"expression": "() => document.getElementById('downres').textContent"}
        )
        assert down["result"]["result"] == "down-2"
    finally:
        h.close()
