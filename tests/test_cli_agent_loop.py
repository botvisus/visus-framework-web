"""Tests for the agent-driving loop: global flags, the daemon envelope, the
generated-code echo, snapshot refs, and `visus find`.

The stdout/stderr split is proved in a REAL subprocess: typer's CliRunner merges
or separates the two streams depending on the installed click version, so an
in-process assertion would not prove the property this plan exists to fix.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

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
