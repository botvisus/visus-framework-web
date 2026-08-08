"""`visus run-code`: the opt-in gate first, then the execution path.

The gate is the reason this file exists — arbitrary Python against a live browser
session is only safe because the DEFAULT refuses it, so that is what is asserted
before anything can run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


def test_run_code_is_disabled_by_default() -> None:
    """A session started the ordinary way must refuse to execute Python."""
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    assert h._allow_run_code is False
    resp = h.handle("run_code", {"code": "page.title()"})
    assert resp["ok"] is False
    assert "disabled" in resp["error"]
    assert "--allow-run-code" in resp["error"]


def test_run_code_gate_is_not_bypassable_by_an_empty_payload() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    for args in ({}, {"code": ""}, {"code": "   "}):
        resp = h.handle("run_code", args)
        assert resp["ok"] is False and "disabled" in resp["error"], args


def test_status_reports_the_gate() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    off = _handler_with_fake_page(_FakePage())
    assert off.handle("status", {})["result"]["allow_run_code"] is False

    on = _handler_with_fake_page(_FakePage())
    on._allow_run_code = True
    assert on.handle("status", {})["result"]["allow_run_code"] is True


def test_handler_accepts_the_flag() -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True, allow_run_code=True)
    assert h._allow_run_code is True


def test_daemon_main_reads_the_gate_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: dict[str, Any] = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VISUS_WEB_ALLOW_RUN_CODE", "1")
    monkeypatch.setattr(session_server, "SessionHandler", lambda **kw: built.update(kw))
    monkeypatch.setattr(session_server, "serve", lambda handler, **kw: None)
    session_server.main(["chrome", "1", ""])
    assert built["allow_run_code"] is True


def test_daemon_main_gate_defaults_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: dict[str, Any] = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VISUS_WEB_ALLOW_RUN_CODE", raising=False)
    monkeypatch.setattr(session_server, "SessionHandler", lambda **kw: built.update(kw))
    monkeypatch.setattr(session_server, "serve", lambda handler, **kw: None)
    session_server.main(["chrome", "1", ""])
    assert built["allow_run_code"] is False


def test_start_daemon_exports_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, *a: Any, **kw: Any) -> None:
            captured["env"] = kw["env"]

    monkeypatch.setattr(session_client, "find_session", lambda base, name=None: None)
    monkeypatch.setattr(session_client.subprocess, "Popen", _FakePopen)
    with pytest.raises(session_client.SessionError):
        session_client.start_daemon(
            "chrome", True, None, cwd=tmp_path, timeout=0.2, allow_run_code=True
        )
    assert captured["env"]["VISUS_WEB_ALLOW_RUN_CODE"] == "1"


def test_start_daemon_omits_the_gate_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, *a: Any, **kw: Any) -> None:
            captured["env"] = kw["env"]

    monkeypatch.setattr(session_client, "find_session", lambda base, name=None: None)
    monkeypatch.setattr(session_client.subprocess, "Popen", _FakePopen)
    monkeypatch.delenv("VISUS_WEB_ALLOW_RUN_CODE", raising=False)
    with pytest.raises(session_client.SessionError):
        session_client.start_daemon("chrome", True, None, cwd=tmp_path, timeout=0.2)
    assert "VISUS_WEB_ALLOW_RUN_CODE" not in captured["env"]


def test_cli_session_start_passes_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_start(engine: str, headless: bool, url: str | None, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"pid": 1, "port": 2}

    monkeypatch.setattr(session_client, "start_daemon", fake_start)
    assert runner.invoke(app, ["session", "start"]).exit_code == 0
    assert captured["allow_run_code"] is False
    assert runner.invoke(app, ["session", "start", "--allow-run-code"]).exit_code == 0
    assert captured["allow_run_code"] is True
