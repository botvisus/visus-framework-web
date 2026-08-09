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


@pytest.mark.browser
def test_upload_without_a_target_finds_the_only_file_input(
    base_url: str, tmp_path: Path
) -> None:
    """`visus upload <file>` must work on a page whose input is hidden behind a button."""
    payload = tmp_path / "avatar.png"
    payload.write_bytes(b"\x89PNG\r\n\x1a\n")

    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/upload_single.html"
    )
    try:
        resp = h.handle("upload", {"paths": [str(payload)]})
        assert resp["ok"] is True, resp
        assert h.handle("get_text", {"selector": "#out"})["result"]["value"] == "avatar.png"
    finally:
        h.close()


@pytest.mark.browser
def test_upload_without_a_target_says_what_to_do_when_there_is_none(
    base_url: str, tmp_path: Path
) -> None:
    payload = tmp_path / "x.txt"
    payload.write_text("x", encoding="utf-8")
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/dropzone.html"
    )
    try:
        resp = h.handle("upload", {"paths": [str(payload)]})
        assert resp["ok"] is False
        assert "no <input type=file>" in resp["error"]
        assert "visus drop" in resp["error"]
    finally:
        h.close()


@pytest.mark.browser
def test_upload_without_a_target_refuses_an_ambiguous_page(
    base_url: str, tmp_path: Path
) -> None:
    payload = tmp_path / "x.txt"
    payload.write_text("x", encoding="utf-8")
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/upload_single.html"
    )
    try:
        h.handle(
            "eval",
            {
                "expression": (
                    "() => { const i = document.createElement('input');"
                    " i.type = 'file'; i.id = 'second'; document.body.appendChild(i);"
                    " return true; }"
                )
            },
        )
        resp = h.handle("upload", {"paths": [str(payload)]})
        assert resp["ok"] is False
        assert "2 file inputs" in resp["error"]
        assert "list-fields" in resp["error"]
    finally:
        h.close()


def test_op_upload_still_honours_an_explicit_target() -> None:
    """The targeted path is unchanged — the fake records the set_input_files call."""
    from test_cli_session import _FakePage, _handler_with_fake_page

    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("list_fields", {})
    resp = h.handle("upload", {"index": 0, "paths": ["/tmp/a.png"]})
    assert resp["ok"] is True and resp["result"] == "set 1 file(s)"
    # _FakeLocator.set_input_files records "upload:<label>:<paths>".
    assert any(entry.startswith("upload:") for entry in page.log), page.log


def test_op_upload_requires_paths() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    resp = h.handle("upload", {})
    assert resp["ok"] is False and "at least one file path" in resp["error"]


def test_cli_upload_without_a_target_sends_only_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # `upload` is a MUTATING op, so it goes through send_envelope for the `### Page`
    # footer. _patch_client stubs both entry points — stubbing only `send` would let
    # the command reach a real socket.
    from test_cli_session import _patch_client

    payload = tmp_path / "a.png"
    payload.write_bytes(b"x")
    captured: dict[str, Any] = {}
    _patch_client(
        monkeypatch,
        lambda op, args=None: captured.update(op=op, args=args) or "set 1 file(s)",
    )
    r = runner.invoke(app, ["upload", str(payload)])
    assert r.exit_code == 0, r.output
    assert captured["op"] == "upload"
    assert list(captured["args"]) == ["paths"]
    assert captured["args"]["paths"] == [str(payload.resolve())]


def test_cli_upload_with_an_index_still_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_cli_session import _patch_client

    payload = tmp_path / "a.png"
    payload.write_bytes(b"x")
    captured: dict[str, Any] = {}
    _patch_client(
        monkeypatch,
        lambda op, args=None: captured.update(args=args) or "set 1 file(s)",
    )
    r = runner.invoke(app, ["upload", "4", str(payload)])
    assert r.exit_code == 0, r.output
    assert captured["args"]["index"] == 4
    assert captured["args"]["paths"] == [str(payload.resolve())]


def test_cli_upload_still_needs_a_path(monkeypatch: pytest.MonkeyPatch) -> None:
    from test_cli_session import _patch_client

    _patch_client(monkeypatch, lambda op, args=None: "")
    assert runner.invoke(app, ["upload"]).exit_code == 1


def test_repl_upload_twin() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return "set 1 file(s)"

    assert "set 1 file(s)" in console.dispatch("upload ./a.png", send)
    assert calls[0][0] == "upload"
    assert calls[0][1]["paths"][0].endswith("a.png")
    assert "index" not in calls[0][1]

    console.dispatch("upload 3 ./a.png", send)
    assert calls[1][1]["index"] == 3
