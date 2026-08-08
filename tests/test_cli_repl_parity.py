"""REPL parity: target parsing and the previously-missing console commands.

The REPL's dispatch is a pure function over an injected `send`, so these are
unit tests; the same ops are exercised against a real browser by the daemon
tests in tests/test_cli_session.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import console
from visus.web.cli.main import app


def _recorder() -> tuple[list[tuple[str, dict[str, Any]]], console.SendFn]:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "list_fields":
            return {"fields": []}
        if op == "find_image":
            return {"found": True, "x": 3, "y": 4, "confidence": 0.91}
        return f"did-{op}"

    return calls, send


def test_target_parses_index_selector_and_flags() -> None:
    assert console._target(["3"]) == ({"index": 3}, [])
    assert console._target(["#submit"]) == ({"selector": "#submit"}, [])
    assert console._target(["//button[1]", "rest"]) == ({"selector": "//button[1]"}, ["rest"])
    args, rest = console._target(["--role", "button", "--name", "Save", "tail"])
    assert args == {"role": "button", "name": "Save"}
    assert rest == ["tail"]
    args, rest = console._target(["--text", "Sign in", "--exact"])
    assert args == {"target_text": "Sign in", "exact": True}
    assert rest == []


def test_target_rejects_empty_and_name_only() -> None:
    for tokens in ([], ["--name", "Save"]):
        try:
            console._target(tokens)
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {tokens!r}")


def test_click_by_selector_no_longer_raises() -> None:
    calls, send = _recorder()
    out = console.dispatch("click #submit", send)
    assert out == "did-click"
    assert calls == [("click", {"selector": "#submit"})]


def test_click_by_role_and_name() -> None:
    calls, send = _recorder()
    console.dispatch("click --role button --name Submit", send)
    assert calls == [("click", {"role": "button", "name": "Submit"})]


def test_fill_keeps_value_after_flag_target() -> None:
    calls, send = _recorder()
    console.dispatch("fill --selector #email hello world", send)
    assert calls == [("fill", {"selector": "#email", "text": "hello world"})]


def test_bad_target_flag_is_a_clean_message_not_a_traceback() -> None:
    _, send = _recorder()
    assert "unknown target flag" in console.dispatch("click --nope x", send)


def test_upload_resolves_paths_against_the_client_cwd(tmp_path: Path) -> None:
    calls, send = _recorder()
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    console.dispatch(f"upload 4 {f}", send)
    op, args = calls[0]
    assert op == "upload"
    assert args["index"] == 4
    assert args["paths"] == [str(f.resolve())]


def test_drag_accepts_index_and_selector_targets() -> None:
    calls, send = _recorder()
    console.dispatch("drag 3 7", send)
    console.dispatch("drag #src #dst", send)
    assert calls[0] == ("drag", {"index": 3, "target_index": 7})
    assert calls[1] == ("drag", {"selector": "#src", "target_selector": "#dst"})


def test_add_and_clear_cookies() -> None:
    calls, send = _recorder()
    console.dispatch('add-cookies [{"name":"a","value":"b","url":"http://x"}]', send)
    console.dispatch("clear-cookies", send)
    assert calls[0] == (
        "add_cookies",
        {"cookies": [{"name": "a", "value": "b", "url": "http://x"}]},
    )
    assert calls[1] == ("clear_cookies", {})


def test_add_cookies_invalid_json_is_a_clean_message() -> None:
    _, send = _recorder()
    assert "invalid JSON" in console.dispatch("add-cookies {nope", send)


def test_vision_commands_reach_the_daemon() -> None:
    calls, send = _recorder()
    console.dispatch("read-text 2", send)
    console.dispatch("solve-captcha #cap", send)
    out = console.dispatch("find-image tmpl.png 5 0.7", send)
    assert calls[0] == ("read_text", {"index": 2})
    assert calls[1] == ("solve_captcha", {"selector": "#cap"})
    op, args = calls[2]
    assert op == "find_image"
    assert args["template_path"] == str(Path("tmpl.png").resolve())
    assert args["index"] == 5 and args["confidence"] == 0.7
    assert "found at (3, 4)" in out


def test_help_lists_the_new_commands() -> None:
    _, send = _recorder()
    out = console.dispatch("help", send)
    for cmd in ("upload", "drag", "add-cookies", "clear-cookies",
                "read-text", "solve-captcha", "find-image"):
        assert cmd in out, f"{cmd} missing from REPL help"


# ---------------------------------------------------------------------------
# `visus repl` (canonical) and `visus console` (deprecated alias)
# ---------------------------------------------------------------------------

runner = CliRunner()


def _all_output(result: Any) -> str:
    """stdout + stderr, across Click versions.

    Click < 8.2 mixes stderr into ``output`` and raises on ``.stderr``;
    Click >= 8.2 captures them separately.
    """
    try:
        return result.output + result.stderr
    except ValueError:
        return result.output


def test_repl_command_starts_the_console(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run_console(url: str | None = None, **kwargs: Any) -> None:
        seen["url"] = url
        seen["kwargs"] = kwargs

    monkeypatch.setattr(console, "run_console", fake_run_console)
    r = runner.invoke(app, ["repl", "http://x", "--engine", "edge", "--headless"])
    assert r.exit_code == 0, _all_output(r)
    assert seen["url"] == "http://x"
    assert seen["kwargs"]["engine"] == "edge"
    assert seen["kwargs"]["headless"] is True


def test_console_alias_still_works_and_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        console, "run_console", lambda url=None, **kw: seen.update(url=url, kwargs=kw)
    )
    r = runner.invoke(app, ["console"])
    assert r.exit_code == 0
    assert "url" in seen, "the deprecated alias must still open the REPL"
    text = _all_output(r)
    assert "deprecated" in text and "visus repl" in text


def test_console_deprecation_does_not_pollute_stdout() -> None:
    """The notice is a warning, so it must not corrupt a piped `visus console` run."""
    import inspect

    from visus.web.cli import main as cli_main

    src = inspect.getsource(cli_main.console)
    assert "err=True" in src, "the deprecation notice must go to stderr"
