"""Every `visus ...` line the skill teaches must actually parse.

The bug that motivated this file was found by hand, not by the suite: the docs
told a model to write `visus fill --selector "#u" hello`, and the CLI answered
"'hello' is not a valid int" — a PARSE error, before any code ran. Unit tests
passed the whole time, because they called the commands the way the *code*
expected rather than the way the *documentation* promised.

So the documentation is the fixture here. Each command line is split, invoked
with the transport stubbed out, and only exit code 2 (Click's usage error) is a
failure: exit 1 is a runtime answer like "no live session", which means the line
parsed and reached the body.

Illustrative lines with `<PLACEHOLDER>` or `[optional]` syntax are skipped —
they are notation, not commands.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import main as cli_main
from visus.web.cli.main import app

runner = CliRunner()

SKILL_DIR = Path(cli_main.__file__).parent.parent / "skills" / "visus-web"
DOCS = [SKILL_DIR / "SKILL.md", *sorted((SKILL_DIR / "references").glob("*.md"))]

# Notation, not invocations: `<name>` and `[optional]` placeholders, shell
# plumbing, and continuation lines.
_NOTATION = re.compile(r"[<\[\]|>]|\.\.\.|\$\(|`")


def _command_lines() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for doc in DOCS:
        if not doc.is_file():
            continue
        for lineno, raw in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line.startswith("visus "):
                continue
            if _NOTATION.search(line):
                continue
            found.append((doc.name, lineno, line))
    return found


COMMAND_LINES = _command_lines()


def _entry_argv(line: str) -> list[str]:
    """Split a documented line into argv EXACTLY as the console script would.

    `visus` is not `app` directly: ``_entry.cli_main`` passes argv through
    ``skills.normalize_skills_argv`` first, which is what makes the bare
    ``--skills`` legal (Typer has no optional-value option). Invoking ``app``
    without it would test a surface no user ever reaches — and would report a
    documented, working command as broken.
    """
    from visus.web.cli.skills import normalize_skills_argv

    # comments=True so a trailing `# explanation` is dropped WITHOUT cutting a
    # quoted "#id" selector in half — a naive line.split("#") does exactly that.
    return normalize_skills_argv(shlex.split(line, comments=True)[1:])


@pytest.fixture(autouse=True)
def _stub_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """No daemon, no browser, no filesystem side effects — only the parser runs."""
    from visus.web.cli import session_client

    result: dict[str, Any] = {
        "ok": True,
        "result": {"x": 1.0, "y": 2.0, "confidence": 0.9, "text": "t", "elements": []},
    }
    monkeypatch.setattr(cli_main, "_send", lambda op, args=None: result["result"])
    monkeypatch.setattr(cli_main, "_send_env", lambda op, args=None: result)
    monkeypatch.setattr(session_client, "start_daemon", lambda *a, **k: {"pid": 1, "port": 2})
    monkeypatch.setattr(session_client, "stop", lambda **k: "stopped")
    monkeypatch.setattr(session_client, "status", lambda **k: {"pid": 1, "port": 2})
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **k: result["result"])
    # `visus translate` reads the clipboard; without a stub the documented line
    # would pass or fail depending on what the developer last copied.
    monkeypatch.setattr(cli_main, "_read_clipboard", lambda: '<input id="u" name="user">')
    monkeypatch.setattr(cli_main, "_install_skills", lambda target, force=False: None)


def test_the_docs_actually_contain_commands() -> None:
    """A regex that silently matches nothing would make every case below vacuous."""
    assert len(COMMAND_LINES) > 40, f"only found {len(COMMAND_LINES)} command lines"


def test_the_remediation_commands_the_cli_prints_are_runnable() -> None:
    """The advice a tool gives about ITSELF must run.

    `installed_skill_targets` supplies the "run this to fix it" line printed on
    every command when the installed skill has drifted. One of them was
    `visus install --skills`, which Click rejected for want of an argument — the
    tool told the user to run something that could not run.
    """
    from pathlib import Path as _Path

    from visus.web.cli import skills

    for target in skills.installed_skill_targets(_Path(".")):
        argv = _entry_argv(target.command)
        result = runner.invoke(app, argv)
        assert result.exit_code != 2, (
            f"the CLI tells users to run {target.command!r}, which does not parse:\n"
            f"{result.output}"
        )


@pytest.mark.parametrize(
    ("doc", "lineno", "line"),
    COMMAND_LINES,
    ids=[f"{d}:{n}" for d, n, _ in COMMAND_LINES],
)
def test_every_documented_command_parses(doc: str, lineno: int, line: str) -> None:
    result = runner.invoke(app, _entry_argv(line))
    assert result.exit_code != 2, (
        f"{doc}:{lineno} documents a command the CLI cannot parse:\n"
        f"  {line}\n{result.output}"
    )
