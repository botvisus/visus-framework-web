"""`visus drop` and the target-free `visus upload`.

Both close a gap that only shows up against a real DOM, so each has a browser
test; the argument plumbing is asserted separately with a recording fake.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


@pytest.mark.browser
def test_drop_delivers_a_file_to_a_zone_with_no_file_input(
    base_url: str, tmp_path: Path
) -> None:
    # write_bytes, not write_text: on Windows text mode turns each "\n" into
    # "\r\n", which would make the File 10 bytes and break the size assertion.
    payload = tmp_path / "report.csv"
    payload.write_bytes(b"a,b\n1,2\n")

    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/dropzone.html"
    )
    try:
        import base64 as _base64

        resp = h.handle(
            "drop",
            {
                "selector": "#zone",
                "file": {
                    "name": "report.csv",
                    "type": "text/csv",
                    "b64": _base64.b64encode(payload.read_bytes()).decode("ascii"),
                },
            },
        )
        assert resp["ok"] is True, resp
        assert resp["result"]["dropped"]["files"] == 1

        out = json.loads(h.handle("get_text", {"selector": "#out"})["result"]["value"])
        assert out["files"] == ["report.csv:8:text/csv"], out
    finally:
        h.close()


@pytest.mark.browser
def test_drop_delivers_plain_text(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/dropzone.html"
    )
    try:
        resp = h.handle("drop", {"selector": "#zone", "data": "hello dropzone"})
        assert resp["ok"] is True, resp
        out = json.loads(h.handle("get_text", {"selector": "#out"})["result"]["value"])
        assert out["text"] == "hello dropzone"
        assert out["files"] == []
    finally:
        h.close()


def test_op_drop_requires_a_payload() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    resp = h.handle("drop", {"selector": "#zone"})
    assert resp["ok"] is False
    assert "--path" in resp["error"] and "--data" in resp["error"]


def test_cli_drop_reads_the_file_client_side(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64 as _base64

    payload = tmp_path / "logo.png"
    payload.write_bytes(b"\x89PNG\r\n\x1a\n")
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(op=op, args=args)
        or {"dropped": {"files": 1, "types": ["Files"]}},
    )
    r = runner.invoke(app, ["drop", "--selector", "#zone", "--path", str(payload)])
    assert r.exit_code == 0, r.output
    assert captured["op"] == "drop"
    assert captured["args"]["file"]["name"] == "logo.png"
    assert captured["args"]["file"]["type"] == "image/png"
    assert _base64.b64decode(captured["args"]["file"]["b64"]) == b"\x89PNG\r\n\x1a\n"


def test_cli_drop_sends_data_and_type(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(args=args) or {"dropped": {"files": 0}},
    )
    r = runner.invoke(
        app,
        ["drop", "3", "--data", '{"id":1}', "--data-type", "application/json"],
    )
    assert r.exit_code == 0, r.output
    assert captured["args"]["index"] == 3
    assert captured["args"]["data"] == '{"id":1}'
    assert captured["args"]["data_type"] == "application/json"


def test_cli_drop_needs_a_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: {"dropped": {}})
    r = runner.invoke(app, ["drop", "--selector", "#zone"])
    assert r.exit_code == 1


def test_cli_drop_rejects_both_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: {"dropped": {}})
    r = runner.invoke(app, ["drop", "--selector", "#z", "--path", "a", "--data", "b"])
    assert r.exit_code == 1


def test_repl_drop_twin() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return {"dropped": {"files": 0, "types": ["text/plain"]}}

    out = console.dispatch("drop 2 hello there", send)
    assert calls == [("drop", {"index": 2, "data": "hello there"})]
    assert "dropped" in out


def test_repl_help_lists_drop() -> None:
    assert "drop" in console.dispatch("help", lambda op, args: None)
