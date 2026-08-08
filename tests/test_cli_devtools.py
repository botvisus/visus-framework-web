"""CLI devtools surface: console logs, network requests, NetworkCapture export."""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


class _FakeConsoleMessage:
    def __init__(self, level: str, text: str) -> None:
        self.level = level
        self.text = text


class _LogPage:
    """Minimal page exposing console_messages (the only surface `logs` needs)."""

    url = "http://x/"

    def console_messages(self) -> list[_FakeConsoleMessage]:
        return [
            _FakeConsoleMessage("INFO", "hello"),
            _FakeConsoleMessage("SEVERE", "boom"),
        ]


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


def test_op_console_messages_returns_all() -> None:
    h = _handler(_LogPage())
    resp = h.handle("console_messages", {})
    assert resp["ok"] is True
    assert resp["result"]["messages"] == [
        {"level": "INFO", "text": "hello"},
        {"level": "SEVERE", "text": "boom"},
    ]


def test_op_console_messages_filters_by_level_case_insensitively() -> None:
    h = _handler(_LogPage())
    resp = h.handle("console_messages", {"level": "severe"})
    assert resp["result"]["messages"] == [{"level": "SEVERE", "text": "boom"}]


def test_cli_logs_sends_level_and_prints_a_table(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["op"], captured["args"] = op, args
        return {"messages": [{"level": "SEVERE", "text": "boom"}]}

    monkeypatch.setattr(session_client, "send", fake_send)
    r = runner.invoke(app, ["logs", "SEVERE"])
    assert r.exit_code == 0, r.output
    assert captured["op"] == "console_messages"
    assert captured["args"] == {"level": "SEVERE"}
    assert "SEVERE" in r.output and "boom" in r.output


def test_cli_logs_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: {"messages": [{"level": "INFO", "text": "x"}]}
    )
    r = runner.invoke(app, ["logs", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output) == [{"level": "INFO", "text": "x"}]


def test_cli_logs_empty_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None: {"messages": []})
    r = runner.invoke(app, ["logs"])
    assert r.exit_code == 0 and "no console messages" in r.output


def test_repl_logs_branch() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return {"messages": [{"level": "SEVERE", "text": "boom"}]}

    out = console.dispatch("logs severe", send)
    assert calls == [("console_messages", {"level": "severe"})]
    assert "boom" in out
    assert "logs" in console.dispatch("help", send)


@pytest.mark.browser
def test_logs_op_against_a_real_page(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/forms.html"
    )
    try:
        h.handle("eval", {"expression": "() => console.error('boom-from-cli-test')"})
        resp = h.handle("console_messages", {"level": "SEVERE"})
        assert resp["ok"] is True, resp
        texts = [m["text"] for m in resp["result"]["messages"]]
        assert any("boom-from-cli-test" in t for t in texts), texts
    finally:
        h.close()
