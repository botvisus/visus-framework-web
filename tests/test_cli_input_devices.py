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
