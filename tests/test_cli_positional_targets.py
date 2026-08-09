"""A bare positional target is a SELECTOR unless it is all digits.

`visus click "#submit"` is how every other browser CLI spells a click, and it is
what a model writes on the first try. Before this rule the positional slot was
typed `int`, so the natural form died in the PARSER — "'#submit' is not a valid
int" — before any code could offer a better message. Only `visus click 4`
(a `list-fields` index) worked.

The rule is one line and unambiguous, because a CSS selector cannot be all
digits: DIGITS -> field index, ANYTHING ELSE -> selector. Options
(--selector/--role/--text) keep working and still win over a positional.

The totality test at the bottom is the tripwire: a NEW command that takes a
target must be added to the table, or it silently ships without the rule.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from typer.main import get_command_name
from typer.testing import CliRunner

from visus.web.cli import main as cli_main
from visus.web.cli.main import app

runner = CliRunner()

# command -> (argv after the command name, the selector it must resolve to).
# Commands with their own required arguments carry them in the argv.
SELECTOR_FORMS: dict[str, tuple[list[str], str]] = {
    "click": (["#submit"], "#submit"),
    "check": (["#agree"], "#agree"),
    "uncheck": (["#agree"], "#agree"),
    "hover": (["#menu"], "#menu"),
    "dblclick": (["#row"], "#row"),
    "focus": (["#q"], "#q"),
    "clear-input": (["#q"], "#q"),
    "get-text": (["#flash"], "#flash"),
    "count": (["li.item"], "li.item"),
    "highlight": (["#flash"], "#flash"),
    "generate-locator": (["#submit"], "#submit"),
    "wait": (["#flash"], "#flash"),
    "read-text": (["#canvas"], "#canvas"),
    "solve-captcha": (["#captcha"], "#captcha"),
    "drop": (["#zone", "--data", "payload"], "#zone"),
    "session-screenshot": (["#card"], "#card"),
    "get-attribute": (["href", "#link"], "#link"),
    "find-image": (["needle.png", "#scope"], "#scope"),
    "fill": (["#username", "student"], "#username"),
    "select": (["#country", "US"], "#country"),
    "press": (["#q", "Enter"], "#q"),
    "expect-text": (["#flash", "Congratulations"], "#flash"),
    "type": (["#q", "hello"], "#q"),
}

# The same commands addressed by a plain index must keep meaning "field N".
INDEX_FORMS: dict[str, list[str]] = {
    name: ["3" if part == selector else part for part in argv]
    for name, (argv, selector) in SELECTOR_FORMS.items()
}


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Capture what the CLI would send, without a daemon or a browser."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        return {"x": 1.0, "y": 2.0, "confidence": 0.9, "text": "t", "value": "v", "count": 1}

    def fake_send_env(op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        calls.append((op, args or {}))
        return {"ok": True, "result": {"x": 1.0, "y": 2.0, "confidence": 0.9, "text": "t"}}

    monkeypatch.setattr(cli_main, "_send", fake_send)
    monkeypatch.setattr(cli_main, "_send_env", fake_send_env)
    return calls


@pytest.mark.parametrize("command", sorted(SELECTOR_FORMS))
def test_a_bare_css_selector_targets_the_element(
    command: str, sent: list[tuple[str, dict[str, Any]]]
) -> None:
    argv, selector = SELECTOR_FORMS[command]
    result = runner.invoke(app, [command, *argv])
    assert result.exit_code == 0, f"visus {command} <selector> failed:\n{result.output}"
    assert sent, f"visus {command} sent nothing"
    args = sent[0][1]
    assert args.get("selector") == selector, (
        f"visus {command} did not read its positional as a selector: {args}"
    )
    assert "index" not in args, f"visus {command} invented an index from a selector: {args}"


@pytest.mark.parametrize("command", sorted(INDEX_FORMS))
def test_a_bare_number_still_means_a_field_index(
    command: str, sent: list[tuple[str, dict[str, Any]]]
) -> None:
    result = runner.invoke(app, [command, *INDEX_FORMS[command]])
    assert result.exit_code == 0, f"visus {command} 3 failed:\n{result.output}"
    args = sent[0][1]
    assert args.get("index") == 3, f"visus {command} 3 lost the index: {args}"
    assert "selector" not in args, f"visus {command} 3 invented a selector: {args}"


def test_the_value_survives_next_to_a_positional_selector(
    sent: list[tuple[str, dict[str, Any]]]
) -> None:
    """The second positional is the VALUE, not another target."""
    assert runner.invoke(app, ["fill", "#username", "student"]).exit_code == 0
    assert sent[0][1]["text"] == "student"
    sent.clear()
    assert runner.invoke(app, ["select", "#country", "US"]).exit_code == 0
    assert sent[0][1]["value"] == "US"
    sent.clear()
    assert runner.invoke(app, ["press", "#q", "Enter"]).exit_code == 0
    assert sent[0][1]["key"] == "Enter"


def test_an_option_target_still_wins_over_a_positional_value(
    sent: list[tuple[str, dict[str, Any]]]
) -> None:
    """`visus fill -s "#u" hello` — the lone positional is the value, as before."""
    assert runner.invoke(app, ["fill", "-s", "#u", "hello"]).exit_code == 0
    assert sent[0][1]["selector"] == "#u"
    assert sent[0][1]["text"] == "hello"


def test_two_conflicting_targets_are_refused_not_silently_dropped(
    sent: list[tuple[str, dict[str, Any]]]
) -> None:
    """`visus fill -s "#u" "#v" hello` names two elements. Guessing one is worse
    than saying so: an agent that is silently ignored chases the wrong element."""
    result = runner.invoke(app, ["fill", "-s", "#u", "#v", "hello"])
    assert result.exit_code == 1, result.output
    assert "two targets" in result.output, result.output
    assert not sent, "a conflicting invocation must not reach the daemon"


def test_a_lone_number_reports_the_missing_value_not_a_missing_target() -> None:
    """`visus fill 2` is field 2 with no text — the error must say which half is missing."""
    result = runner.invoke(app, ["fill", "2"])
    assert result.exit_code == 1
    assert "no text" in result.output, result.output


def test_type_with_one_positional_types_it(sent: list[tuple[str, dict[str, Any]]]) -> None:
    """`visus type 42` types "42" — it does not focus field 42.

    `type`'s lone positional was ALWAYS the text, and typing a number is common
    (a ZIP, an amount). Only a SECOND positional makes the first one a target.
    """
    assert runner.invoke(app, ["type", "42"]).exit_code == 0
    assert sent[0][1] == {"text": "42"}
    sent.clear()
    assert runner.invoke(app, ["type", "hello"]).exit_code == 0
    assert sent[0][1] == {"text": "hello"}


def test_type_with_two_positionals_targets_then_types(
    sent: list[tuple[str, dict[str, Any]]]
) -> None:
    assert runner.invoke(app, ["type", "7", "hello"]).exit_code == 0
    assert sent[0][1] == {"index": 7, "text": "hello"}


def test_drag_takes_two_positional_targets(sent: list[tuple[str, dict[str, Any]]]) -> None:
    assert runner.invoke(app, ["drag", "#src", "#dst"]).exit_code == 0
    args = sent[0][1]
    assert args.get("selector") == "#src" and args.get("target_selector") == "#dst", args


def test_snapshot_accepts_the_selector_option_like_every_other_command(
    sent: list[tuple[str, dict[str, Any]]]
) -> None:
    """`snapshot` scopes by positional; --selector is what a model reaches for."""
    assert runner.invoke(app, ["snapshot", "--selector", "#main"]).exit_code == 0
    assert sent[0][1].get("selector") == "#main"


def test_xpath_and_text_engine_selectors_are_not_mistaken_for_values(
    sent: list[tuple[str, dict[str, Any]]]
) -> None:
    for target in ("//button[@id='go']", "text=Sign in", "[data-test=login]"):
        sent.clear()
        assert runner.invoke(app, ["click", target]).exit_code == 0, target
        assert sent[0][1].get("selector") == target


def test_every_targeting_command_is_covered_by_this_file() -> None:
    """Totality tripwire: a new target-taking command must land in the table."""
    # These take a target but spend their positionals on something else, so the
    # bare-selector rule does not apply: drag has TWO targets (tested above),
    # eval/find/upload/screenshot lead with an expression, query, paths or URL.
    exempt = {"drag", "eval", "find", "upload", "screenshot"}
    missing = []
    for info in app.registered_commands:
        name = info.name or get_command_name(info.callback.__name__)
        params = inspect.signature(info.callback).parameters
        if "selector" not in params or "role" not in params:
            continue  # not a target-taking command (snapshot/find are covered above)
        positional = [k for k, v in params.items() if type(v.default).__name__ == "ArgumentInfo"]
        if not positional:
            continue
        if name not in SELECTOR_FORMS and name not in exempt:
            missing.append(name)
    assert not missing, f"commands take a target but are untested here: {missing}"
