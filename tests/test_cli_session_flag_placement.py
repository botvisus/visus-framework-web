"""`--session NAME` is accepted after the subcommand, not only before it.

`visus --session work session start` is the correct spelling and the only one
that used to parse. But the flag reads as an option *of starting a session*, so
`visus session start --session work` is what anyone — and every model — writes
first, and it died with "No such option: --session".

Both spellings now select the same session. The global flag still exists and
still applies to every other command.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from visus.web.cli import session_client
from visus.web.cli.main import app

runner = CliRunner()

SUBCOMMANDS = ["start", "stop", "status"]


@pytest.fixture
def names(monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    """Record the session name each invocation resolves to, without a daemon."""
    seen: list[str | None] = []

    def record(name: str | None = None) -> str:
        seen.append(name)
        return name or "default"

    monkeypatch.setattr(session_client, "start_daemon", lambda *a, **k: {"pid": 1, "port": 2})
    monkeypatch.setattr(session_client, "stop", lambda **k: "stopped")
    monkeypatch.setattr(session_client, "status", lambda **k: {"pid": 1, "port": 2})
    monkeypatch.setattr(session_client, "set_session_name", record)
    return seen


@pytest.mark.parametrize("sub", SUBCOMMANDS)
def test_the_flag_is_accepted_after_the_subcommand(sub: str, names: list[str | None]) -> None:
    result = runner.invoke(app, ["session", sub, "--session", "work"])
    assert result.exit_code == 0, result.output
    assert "work" in names, f"`visus session {sub} --session work` did not select 'work': {names}"


@pytest.mark.parametrize("sub", SUBCOMMANDS)
def test_the_global_placement_still_works(sub: str, names: list[str | None]) -> None:
    result = runner.invoke(app, ["--session", "work", "session", sub])
    assert result.exit_code == 0, result.output
    assert "work" in names, names


def test_the_short_form_works_after_the_subcommand(names: list[str | None]) -> None:
    """-S, not -s: `-s` is --selector everywhere else and must not be overloaded."""
    result = runner.invoke(app, ["session", "start", "-S", "work"])
    assert result.exit_code == 0, result.output
    assert "work" in names, names


def test_no_flag_leaves_the_name_alone(names: list[str | None]) -> None:
    """Without the flag the subcommand must not override the global/config name."""
    assert runner.invoke(app, ["session", "status"]).exit_code == 0
    assert "work" not in names, names


def test_session_start_help_advertises_the_flag() -> None:
    result = runner.invoke(app, ["session", "start", "--help"])
    assert "--session" in result.output, result.output


def test_the_short_form_is_not_taken_by_selector() -> None:
    """A regression guard: -s must stay --selector on element commands."""
    result = runner.invoke(app, ["click", "--help"])
    assert "-s" in result.output, result.output
    assert "--selector" in result.output, result.output
