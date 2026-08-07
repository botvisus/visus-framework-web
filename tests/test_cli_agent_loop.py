"""Tests for the agent-driving loop: global flags, the daemon envelope, the
generated-code echo, snapshot refs, and `visus find`.

The stdout/stderr split is proved in a REAL subprocess: typer's CliRunner merges
or separates the two streams depending on the installed click version, so an
in-process assertion would not prove the property this plan exists to fix.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import session_client
from visus.web.cli.main import app

runner = CliRunner()

_ERROR_SCRIPT = (
    "import sys; from visus.web.cli.main import app; "
    "sys.argv = ['visus', 'title']; app()"
)


def test_daemon_error_never_touches_stdout(tmp_path: Path) -> None:
    """`TOKEN=$(visus ...)` must never capture an error message."""
    proc = subprocess.run(
        [sys.executable, "-c", _ERROR_SCRIPT],
        cwd=str(tmp_path),  # isolated cwd: no .visus/session.json anywhere above
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 1
    assert proc.stdout.strip() == ""
    assert "no live session" in proc.stderr


def test_root_callback_exposes_the_global_flags() -> None:
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    for flag in ("--json", "--raw", "--snapshot", "--output-dir"):
        assert flag in r.output, f"global flag {flag} missing from `visus --help`"


def test_global_json_works_on_commands_that_never_had_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None: "Dashboard")
    r = runner.invoke(app, ["--json", "title"])
    assert r.exit_code == 0
    assert json.loads(r.output) == "Dashboard"


def test_global_raw_prints_a_bare_attribute_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None: "tok-abc")
    r = runner.invoke(app, ["--raw", "get-attribute", "value", "5"])
    assert r.exit_code == 0
    assert r.output == "tok-abc\n"


def test_global_json_wraps_count_as_a_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None: 7)
    r = runner.invoke(app, ["--json", "count", "--selector", ".item"])
    assert r.exit_code == 0
    assert json.loads(r.output) == 7


def test_local_json_flag_still_wins_for_list_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    fields = [{"index": 0, "kind": "input", "name": "n", "locator": "#n"}]
    monkeypatch.setattr(session_client, "send", lambda op, args=None: {"fields": fields})
    r = runner.invoke(app, ["list-fields", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output) == fields


def test_missing_target_error_exits_1_without_writing_stdout_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None: "never-called")
    r = runner.invoke(app, ["get-text"])
    assert r.exit_code == 1
    assert "never-called" not in r.output


def _envelope(monkeypatch: pytest.MonkeyPatch, env: dict[str, Any]) -> list[tuple[str, Any]]:
    """Point session_client.send_envelope at a canned envelope; record the calls."""
    calls: list[tuple[str, Any]] = []

    def fake(op: str, args: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
        calls.append((op, args))
        return env

    monkeypatch.setattr(session_client, "send_envelope", fake)
    return calls


def test_click_prints_the_page_footer(monkeypatch: pytest.MonkeyPatch) -> None:
    _envelope(
        monkeypatch,
        {
            "ok": True,
            "result": "clicked",
            "page": {"url": "http://x/dash", "title": "Dash", "fields_stale": False},
        },
    )
    r = runner.invoke(app, ["click", "3"])
    assert r.exit_code == 0
    assert "clicked" in r.output
    assert "### Page" in r.output
    assert "- URL: http://x/dash" in r.output
    assert "- Title: Dash" in r.output


def test_raw_click_prints_only_the_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _envelope(
        monkeypatch,
        {"ok": True, "result": "clicked", "page": {"url": "u", "title": "t"}},
    )
    r = runner.invoke(app, ["--raw", "click", "3"])
    assert r.exit_code == 0
    assert r.output == "clicked\n"


def test_json_click_emits_the_whole_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {"ok": True, "result": "clicked", "page": {"url": "u", "title": "t"}}
    _envelope(monkeypatch, env)
    r = runner.invoke(app, ["--json", "click", "3"])
    assert r.exit_code == 0
    assert json.loads(r.output) == env


def test_goto_keeps_its_human_line_and_gains_the_footer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _envelope(
        monkeypatch,
        {
            "ok": True,
            "result": "http://x/dash",
            "page": {"url": "http://x/dash", "title": "Dash", "fields_stale": False},
        },
    )
    r = runner.invoke(app, ["goto", "http://x/dash"])
    assert r.exit_code == 0
    assert "navigated to http://x/dash" in r.output
    assert "### Page" in r.output


def test_snapshot_flag_is_forwarded_to_the_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _envelope(
        monkeypatch, {"ok": True, "result": "clicked", "page": {"url": "u", "title": "t"}}
    )
    assert runner.invoke(app, ["--snapshot", "click", "3"]).exit_code == 0
    assert calls[-1][1]["snapshot"] is True
    assert runner.invoke(app, ["click", "3"]).exit_code == 0
    assert "snapshot" not in calls[-1][1]


def test_click_prints_the_generated_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _envelope(
        monkeypatch,
        {
            "ok": True,
            "result": "clicked",
            "code": "page.get_by_role('button', name='Sign in').click()",
            "page": {"url": "u", "title": "t"},
        },
    )
    r = runner.invoke(app, ["click", "--role", "button", "--name", "Sign in"])
    assert r.exit_code == 0
    assert "### Code" in r.output
    assert "page.get_by_role('button', name='Sign in').click()" in r.output


def test_raw_click_suppresses_the_generated_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _envelope(
        monkeypatch,
        {"ok": True, "result": "clicked", "code": "page.locator('#go').click()", "page": {}},
    )
    r = runner.invoke(app, ["--raw", "click", "--selector", "#go"])
    assert r.output == "clicked\n"


@pytest.mark.browser
def test_real_daemon_click_echoes_the_new_page(base_url: str, tmp_path: Path) -> None:
    """The loop closes: a click that navigates reports the URL it produced."""
    info = session_client.start_daemon(
        "chrome", headless=True, url=f"{base_url}/links.html", cwd=tmp_path
    )
    assert info["pid"]
    try:
        env = session_client.send_envelope(
            "click", {"target_text": "Go to page two"}, start_dir=tmp_path
        )
        assert env["ok"] is True
        assert env["result"] == "clicked"
        assert env["page"]["url"].endswith("/page2.html")
        assert env["page"]["title"] == "page two"
    finally:
        session_client.stop(start_dir=tmp_path)
