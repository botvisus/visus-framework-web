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
