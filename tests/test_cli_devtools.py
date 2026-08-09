"""CLI devtools surface: console logs, network requests, NetworkCapture export."""

from __future__ import annotations

import json
from pathlib import Path
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


# ---------------------------------------------------------------------------
# requests / request N
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, url: str, status: int, body: str | None) -> None:
        self.url = url
        self.method = "GET"
        self.status = status
        self.resource_type = "Document"
        self._body = body

    def body(self) -> str:
        if self._body is None:
            raise RuntimeError("body evicted")
        return self._body


class _NetPage:
    url = "http://x/"

    def network_requests(self) -> list[_FakeResponse]:
        return [
            _FakeResponse("http://x/index.html", 200, "<html>"),
            _FakeResponse("http://x/api/orders", 500, None),
        ]


def test_op_network_requests_lists_and_filters() -> None:
    h = _handler(_NetPage())
    all_rows = h.handle("network_requests", {})["result"]["requests"]
    assert [r["url"] for r in all_rows] == [
        "http://x/index.html",
        "http://x/api/orders",
    ]
    assert all_rows[1]["status"] == 500
    filtered = h.handle("network_requests", {"url_filter": "/api/"})["result"]["requests"]
    assert len(filtered) == 1 and filtered[0]["url"].endswith("/api/orders")


def test_op_network_request_returns_body_and_survives_eviction() -> None:
    h = _handler(_NetPage())
    first = h.handle("network_request", {"index": 0})["result"]
    assert first["body"] == "<html>" and first["status"] == 200
    evicted = h.handle("network_request", {"index": 1})["result"]
    assert evicted["body"] is None  # eviction is reported, not raised
    bad = h.handle("network_request", {"index": 9})
    assert bad["ok"] is False and "out of range" in bad["error"]


def test_cli_requests_filter_and_table(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["op"], captured["args"] = op, args
        return {
            "requests": [
                {
                    "url": "http://x/api/orders",
                    "method": "GET",
                    "status": 200,
                    "resource_type": "XHR",
                }
            ]
        }

    monkeypatch.setattr(session_client, "send", fake_send)
    r = runner.invoke(app, ["requests", "--filter", "/api/"])
    assert r.exit_code == 0, r.output
    assert captured["op"] == "network_requests"
    assert captured["args"] == {"url_filter": "/api/"}
    assert "200" in r.output and "/api/orders" in r.output


def test_cli_request_by_index_prints_body(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["op"], captured["args"] = op, args
        return {
            "index": 2,
            "url": "http://x/api",
            "method": "POST",
            "status": 201,
            "resource_type": "Fetch",
            "body": '{"id": 7}',
        }

    monkeypatch.setattr(session_client, "send", fake_send)
    r = runner.invoke(app, ["request", "2"])
    assert r.exit_code == 0
    assert captured["op"] == "network_request" and captured["args"] == {"index": 2}
    assert '{"id": 7}' in r.output and "201" in r.output


def test_repl_requests_and_request() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "network_requests":
            return {"requests": [{"url": "http://x/a", "method": "GET", "status": 200}]}
        return {"index": 0, "url": "http://x/a", "method": "GET", "status": 200, "body": "hi"}

    assert "http://x/a" in console.dispatch("requests /a", send)
    assert "hi" in console.dispatch("request 0", send)
    assert calls[0] == ("network_requests", {"url_filter": "/a"})
    assert calls[1] == ("network_request", {"index": 0})


@pytest.mark.browser
def test_requests_op_against_a_real_page(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/network.html"
    )
    try:
        h.handle(
            "eval",
            {
                "expression": "() => new Promise(r => {"
                " const t = setInterval(() => {"
                " if (document.getElementById('r').textContent !== 'pending')"
                " { clearInterval(t); r(true); } }, 50); })"
            },
        )
        rows = h.handle("network_requests", {})["result"]["requests"]
        urls = [r["url"] for r in rows]
        assert any(u.endswith("/network.html") for u in urls), urls
        assert any(u.endswith("/forms.html") for u in urls), urls
        idx = next(i for i, r in enumerate(rows) if r["url"].endswith("/forms.html"))
        one = h.handle("network_request", {"index": idx})["result"]
        assert one["status"] == 200
        assert "Username" in (one["body"] or "")
    finally:
        h.close()


# ---------------------------------------------------------------------------
# NetworkCapture: start / stop / export
# ---------------------------------------------------------------------------


class _CapturePage:
    """Page stub that records every evaluate -- the hook install is an evaluate."""

    def __init__(self, url: str = "http://x/") -> None:
        self.url = url
        self.evaluated: list[str] = []

    def evaluate(self, expression: str, arg: object = None) -> object:
        self.evaluated.append(expression)
        if expression.startswith("() => JSON"):  # the _READ_JS drain
            return json.dumps(
                [
                    {
                        "url": "http://x/api",
                        "method": "POST",
                        "status": 200,
                        "reqBody": '{"q": 1}',
                        "respBody": '{"ok": true}',
                        "headers": {"authorization": "Bearer s3cret"},
                        "resourceType": "fetch",
                    }
                ]
            )
        return True  # the _HOOK_JS install


def test_rebind_repoints_and_rearms_the_hook() -> None:
    from visus.web.network import NetworkCapture

    first, second = _CapturePage("http://a/"), _CapturePage("http://b/")
    cap = NetworkCapture(first, use_cdp=False)
    cap.start()
    assert len(first.evaluated) == 1  # the hook install

    cap.rebind(second)
    assert cap.page is second
    assert len(second.evaluated) == 1  # re-armed on the new page

    # Before start(), rebind must not install anything.
    third = _CapturePage("http://c/")
    idle = NetworkCapture(third, use_cdp=False)
    idle.rebind(_CapturePage("http://d/"))
    assert third.evaluated == []


def test_op_network_capture_lifecycle_and_export(tmp_path: Path) -> None:
    page = _CapturePage()
    h = _handler(page)

    started = h.handle("network_capture_start", {})
    assert started["ok"] is True, started
    assert started["result"] == {"started": True}

    out_file = tmp_path / "capture.json"
    exported = h.handle("network_capture_export", {"path": str(out_file)})["result"]
    assert exported["path"] == str(out_file.resolve())
    assert exported["entries"] == 1

    doc = json.loads(out_file.read_text(encoding="utf-8"))
    assert doc["target_url"] == "http://x/"
    entry = doc["entries"][0]
    assert entry["reqBody"] == '{"q": 1}'
    assert entry["headers"]["authorization"] == "REDACTED"  # scrubbed on the way out

    stopped = h.handle("network_capture_stop", {})["result"]
    assert stopped == {"stopped": True, "captured": 1}


def test_op_network_export_without_a_capture_is_a_clean_error(tmp_path: Path) -> None:
    h = _handler(_CapturePage())
    bad = h.handle("network_capture_export", {"path": str(tmp_path / "c.json")})
    assert bad["ok"] is False
    assert "visus network start" in bad["error"]


def test_close_drops_the_capture() -> None:
    h = _handler(_CapturePage())
    h.handle("network_capture_start", {})
    assert h._capture is not None
    h.close()
    assert h._capture is None


def test_cli_network_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        if op == "network_capture_export":
            return {"path": str(tmp_path / "capture.json"), "entries": 12}
        if op == "network_capture_stop":
            return {"stopped": True, "captured": 12}
        return {"started": True}

    monkeypatch.setattr(session_client, "send", fake_send)
    assert runner.invoke(app, ["network", "start"]).exit_code == 0
    r = runner.invoke(app, ["network", "export", "-o", str(tmp_path / "capture.json")])
    assert r.exit_code == 0, r.output
    assert "12" in r.output
    assert runner.invoke(app, ["network", "stop"]).exit_code == 0
    assert calls[0] == ("network_capture_start", {})
    assert calls[1] == (
        "network_capture_export",
        {"path": str((tmp_path / "capture.json").resolve())},
    )
    assert calls[2] == ("network_capture_stop", {})


def test_repl_network_branches() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "network_capture_export":
            return {"path": "capture.json", "entries": 3}
        if op == "network_capture_stop":
            return {"stopped": True, "captured": 3}
        return {"started": True}

    console.dispatch("network start", send)
    console.dispatch("network export capture.json", send)
    console.dispatch("network stop", send)
    assert calls[0] == ("network_capture_start", {})
    assert calls[1][0] == "network_capture_export"
    assert calls[1][1]["path"] == str(Path("capture.json").resolve())
    assert calls[2] == ("network_capture_stop", {})
    assert "network" in console.dispatch("help", send)


@pytest.mark.browser
def test_network_capture_export_against_a_real_page(base_url: str, tmp_path: Path) -> None:
    """The JS hook records the REQUEST body -- the thing `visus requests` cannot show."""
    import time

    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/network.html"
    )
    try:
        assert h.handle("network_capture_start", {})["ok"] is True
        # Two fetches: the POST proves the hook records the REQUEST body (which the
        # CDP response log, and therefore `visus requests`, can never show); the GET
        # proves it records the RESPONSE body. The fixture server only implements
        # do_GET, so the POST answers 501 -- irrelevant, the request side is the test.
        h.handle(
            "eval",
            {
                "expression": "() => { window.__t = 0;"
                " fetch('/forms.html', {method: 'POST', body: 'q=visus'})"
                " .then(r => r.text()).then(() => { window.__t += 1; });"
                " fetch('/forms.html').then(r => r.text())"
                " .then(() => { window.__t += 1; }); return true; }"
            },
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if h.handle("eval", {"expression": "() => window.__t === 2"})["result"]["result"]:
                break
            time.sleep(0.1)

        out_file = tmp_path / "capture.json"
        exported = h.handle("network_capture_export", {"path": str(out_file)})
        assert exported["ok"] is True, exported
        assert exported["result"]["entries"] >= 2
    finally:
        h.close()

    doc = json.loads(out_file.read_text(encoding="utf-8"))
    assert doc["target_url"].endswith("/network.html")
    posted = [e for e in doc["entries"] if e["method"] == "POST"]
    assert posted, doc["entries"]
    assert posted[0]["reqBody"] == "q=visus"
    got = [
        e
        for e in doc["entries"]
        if e["method"] == "GET" and e["url"].endswith("/forms.html")
    ]
    assert got, doc["entries"]
    # forms.html's <label for="user">Username</label> -- the response body really
    # came back through the hook, not just the request line.
    assert "Username" in (got[0]["respBody"] or "")
