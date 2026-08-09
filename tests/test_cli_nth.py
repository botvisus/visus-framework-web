"""`--nth` is the way out of a strict-mode violation from the CLI.

A loose target ("text=Submit") legitimately matches several elements, and the
engine refuses to guess — correctly. But the refusal used to advise
`first()/last()/nth()`, which are PYTHON methods: an agent driving the CLI could
read the advice and still have no way to follow it. Every escape hatch the error
names must exist on the surface the caller is using.
"""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import main as cli_main
from visus.web.cli.main import app

runner = CliRunner()


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        return {"ok": True, "result": "done", "text": "t"}

    monkeypatch.setattr(cli_main, "_send", fake)
    monkeypatch.setattr(
        cli_main, "_send_env", lambda op, args=None: (fake(op, args), {"ok": True, "result": ""})[1]
    )
    return calls


def test_nth_reaches_the_payload(sent: list[tuple[str, dict[str, Any]]]) -> None:
    assert runner.invoke(app, ["click", "text=Submit", "--nth", "0"]).exit_code == 0
    assert sent[0][1]["nth"] == 0


def test_a_negative_nth_counts_from_the_end(sent: list[tuple[str, dict[str, Any]]]) -> None:
    assert runner.invoke(app, ["click", "li", "--nth", "-1"]).exit_code == 0
    assert sent[0][1]["nth"] == -1


def test_nth_is_absent_when_not_asked_for(sent: list[tuple[str, dict[str, Any]]]) -> None:
    """The payload stays minimal — the daemon reads `nth` only when present."""
    assert runner.invoke(app, ["click", "#x"]).exit_code == 0
    assert "nth" not in sent[0][1]


def test_nth_works_with_every_target_spelling(sent: list[tuple[str, dict[str, Any]]]) -> None:
    for argv in (
        ["click", "3", "--nth", "1"],
        ["click", "--selector", "li", "--nth", "1"],
        ["click", "--role", "button", "--nth", "1"],
        ["fill", "input", "hi", "--nth", "1"],
    ):
        sent.clear()
        result = runner.invoke(app, argv)
        assert result.exit_code == 0, f"{argv}: {result.output}"
        assert sent[0][1]["nth"] == 1, argv


def test_the_strict_mode_error_names_a_flag_the_cli_actually_has() -> None:
    """The message must not send a CLI user off to a Python method it cannot call."""
    from visus.web.cli.session_server import cli_hint

    message = "locator resolved to 5 elements; use first()/last()/nth()"
    hinted = cli_hint(message)
    assert "--nth" in hinted, hinted
    assert "first()" not in hinted, "the Python-only advice must be replaced, not appended"


def test_cli_hint_leaves_unrelated_errors_alone() -> None:
    from visus.web.cli.session_server import cli_hint

    for message in ("no such element", "timeout waiting for #x", ""):
        assert cli_hint(message) == message


def test_make_locator_applies_nth() -> None:
    """The shared layer carries it, so the MCP server gets the same escape hatch."""
    from visus.web.ops.targeting import make_locator

    class _Loc:
        def __init__(self) -> None:
            self.nth_called: int | None = None

        def nth(self, index: int) -> Any:
            self.nth_called = index
            return self

    class _Page:
        def __init__(self) -> None:
            self.loc = _Loc()

        def locator(self, selector: str) -> Any:
            return self.loc

    page = _Page()
    make_locator(page, selector="li", nth=2)  # type: ignore[arg-type]
    assert page.loc.nth_called == 2

    page2 = _Page()
    make_locator(page2, selector="li")  # type: ignore[arg-type]
    assert page2.loc.nth_called is None, "nth must not be applied when not asked for"
