"""`visus run-code`: the opt-in gate first, then the execution path.

The gate is the reason this file exists — arbitrary Python against a live browser
session is only safe because the DEFAULT refuses it, so that is what is asserted
before anything can run.
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
        def poll(self) -> None:  # o daemon de mentira não sai
            return None

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
        def poll(self) -> None:  # o daemon de mentira não sai
            return None

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


def _enabled_handler() -> session_server.SessionHandler:
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    h._allow_run_code = True
    return h


def test_run_code_evaluates_a_single_expression() -> None:
    h = _enabled_handler()
    assert h.handle("run_code", {"code": "page.title()"})["result"] == {
        "result": "FakeTitle"
    }


def test_run_code_runs_a_script_and_returns_result() -> None:
    h = _enabled_handler()
    code = "\n".join(
        [
            "titles = [page.title() for _ in range(2)]",
            "result = {'titles': titles, 'url': page.url}",
        ]
    )
    resp = h.handle("run_code", {"code": code})
    assert resp["ok"] is True
    assert resp["result"]["result"] == {"titles": ["FakeTitle", "FakeTitle"], "url": "about:blank"}


def test_run_code_binds_every_documented_name() -> None:
    h = _enabled_handler()
    resp = h.handle(
        "run_code",
        {"code": "result = sorted(n for n in ('page','context','browser','expect'))"},
    )
    assert resp["ok"] is True
    code = "result = [type(page).__name__, browser is not None, callable(expect)]"
    got = h.handle("run_code", {"code": code})["result"]["result"]
    assert got[1] is True and got[2] is True


def test_run_code_reports_an_exception_without_killing_the_daemon() -> None:
    h = _enabled_handler()
    resp = h.handle("run_code", {"code": "raise ValueError('boom')"})
    assert resp["ok"] is False
    assert "ValueError: boom" in resp["error"]
    # The handler is still usable.
    assert h.handle("title", {})["result"] == "FakeTitle"


def test_run_code_reports_a_syntax_error_clearly() -> None:
    h = _enabled_handler()
    resp = h.handle("run_code", {"code": "def ("})
    assert resp["ok"] is False and "SyntaxError" in resp["error"]


def test_run_code_rejects_empty_code_once_enabled() -> None:
    h = _enabled_handler()
    resp = h.handle("run_code", {"code": "   "})
    assert resp["ok"] is False and "no code" in resp["error"]


def test_run_code_invalidates_cached_field_indexes() -> None:
    """Arbitrary code may navigate — a cached index must not survive it."""
    h = _enabled_handler()
    h.handle("list_fields", {})
    assert h._fields
    h.handle("run_code", {"code": "result = 1"})
    assert h._fields == [] and h._fields_url is None


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("None", None),
        ("42", 42),
        ("3.5", 3.5),
        ("True", True),
        ("'hi'", "hi"),
        ("[1, 'a', None]", [1, "a", None]),
        ("(1, 2)", [1, 2]),
        ("{'k': [1, {'n': 2}]}", {"k": [1, {"n": 2}]}),
        ("{1: 'a'}", {"1": "a"}),
    ],
)
def test_run_code_return_values_are_json_safe(expression: str, expected: Any) -> None:
    h = _enabled_handler()
    value = h.handle("run_code", {"code": f"result = {expression}"})["result"]["result"]
    assert value == expected
    json.dumps(value)  # the reply must survive the socket


def test_run_code_falls_back_to_repr_for_a_live_object() -> None:
    h = _enabled_handler()
    value = h.handle("run_code", {"code": "result = page"})["result"]["result"]
    assert isinstance(value, str) and "FakePage" in value
    json.dumps(value)


def test_cli_run_code_sends_the_code(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(op=op, args=args) or {"result": "ok"},
    )
    r = runner.invoke(app, ["run-code", "page.title()"])
    assert r.exit_code == 0, r.output
    assert captured == {"op": "run_code", "args": {"code": "page.title()"}}
    assert "ok" in r.output


def test_cli_run_code_reads_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "snippet.py"
    script.write_text("result = page.url\n", encoding="utf-8")
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(args=args) or {"result": "http://x"},
    )
    r = runner.invoke(app, ["run-code", "--file", str(script)])
    assert r.exit_code == 0, r.output
    assert captured["args"]["code"] == "result = page.url\n"


def test_cli_run_code_needs_code_or_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: {"result": None})
    r = runner.invoke(app, ["run-code"])
    assert r.exit_code == 1


def test_cli_run_code_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None, **kw: {"result": {"a": 1}}
    )
    r = runner.invoke(app, ["--json", "run-code", "result = {'a': 1}"])
    assert r.exit_code == 0
    assert json.loads(r.output) == {"a": 1}


def test_repl_run_code_twin() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return {"result": "Dashboard"}

    assert console.dispatch("run-code page.title()", send) == "Dashboard"
    assert calls == [("run_code", {"code": "page.title()"})]


def test_repl_help_lists_run_code() -> None:
    assert "run-code" in console.dispatch("help", lambda op, args: None)
