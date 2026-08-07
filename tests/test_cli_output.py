"""Unit tests for the CLI output funnel.

capsys (not CliRunner) is used on purpose: it keeps stdout and stderr apart on
every click version, which is the exact property `emit_error` must guarantee.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import typer

from visus.web.cli import output


@pytest.fixture(autouse=True)
def _reset_output_state() -> Iterator[None]:
    output.set_mode()
    output.set_output_dir(None)
    output.set_snapshot_sink(False)
    yield
    output.set_mode()
    output.set_output_dir(None)
    output.set_snapshot_sink(False)


def test_default_mode_is_text() -> None:
    assert output.mode() is output.Mode.TEXT


def test_set_mode_json_wins_over_raw() -> None:
    output.set_mode(as_json=True, raw=True)
    assert output.mode() is output.Mode.JSON


def test_emit_text_prefers_the_table(capsys: pytest.CaptureFixture[str]) -> None:
    output.emit([1, 2], table="+---+\n| 1 |\n+---+")
    assert capsys.readouterr().out == "+---+\n| 1 |\n+---+\n"


def test_emit_raw_keeps_the_table_for_a_structure(capsys: pytest.CaptureFixture[str]) -> None:
    # --raw strips ### sections, not a structure's own rendering: str([1, 2]) is a repr.
    output.set_mode(raw=True)
    output.emit([1, 2], table="TABLE")
    assert capsys.readouterr().out == "TABLE\n"


def test_emit_raw_drops_the_table_for_a_scalar(capsys: pytest.CaptureFixture[str]) -> None:
    """`SHOT=$(visus --raw session-screenshot -o s.png)` must capture the path alone."""
    output.set_mode(raw=True)
    output.emit("C:/tmp/s.png", table="saved C:/tmp/s.png")
    assert capsys.readouterr().out == "C:/tmp/s.png\n"


def test_emit_text_keeps_the_table_for_a_scalar(capsys: pytest.CaptureFixture[str]) -> None:
    output.emit("C:/tmp/s.png", table="saved C:/tmp/s.png")
    assert capsys.readouterr().out == "saved C:/tmp/s.png\n"


def test_emit_raw_scalar_has_no_decoration(capsys: pytest.CaptureFixture[str]) -> None:
    output.set_mode(raw=True)
    output.emit("abc123")
    assert capsys.readouterr().out == "abc123\n"


def test_emit_json_dumps_the_value_not_the_table(capsys: pytest.CaptureFixture[str]) -> None:
    output.set_mode(as_json=True)
    output.emit({"a": 1}, table="IGNORED")
    assert json.loads(capsys.readouterr().out) == {"a": 1}


def test_emit_error_goes_to_stderr_and_exits(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(typer.Exit) as exc:
        output.emit_error("error: no live session")
    assert exc.value.exit_code == 1
    captured = capsys.readouterr()
    assert captured.out == ""  # stdout stays clean for $(...) capture
    assert "no live session" in captured.err


def test_emit_error_json_mode_emits_json_on_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    output.set_mode(as_json=True)
    with pytest.raises(typer.Exit):
        output.emit_error("boom")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"ok": False, "error": "boom"}


def test_emit_envelope_text_renders_code_then_page(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output.emit_envelope(
        {
            "ok": True,
            "result": "clicked",
            "code": 'page.get_by_role("button", name="Submit").click()',
            "page": {"url": "http://x/dash", "title": "Dash", "fields_stale": False},
            "snapshot": ".visus/snapshots/page-2026-08-06T14-22-42-679.yml",
        }
    )
    out = capsys.readouterr().out
    assert out.splitlines() == [
        "clicked",
        "",
        "### Code",
        'page.get_by_role("button", name="Submit").click()',
        "",
        "### Page",
        "- URL: http://x/dash",
        "- Title: Dash",
        "- Snapshot: .visus/snapshots/page-2026-08-06T14-22-42-679.yml",
    ]


def test_emit_envelope_reports_stale_field_cache(capsys: pytest.CaptureFixture[str]) -> None:
    output.emit_envelope(
        {"ok": True, "result": "ok", "page": {"url": "u", "title": "t", "fields_stale": True}}
    )
    assert "- Fields: stale" in capsys.readouterr().out


def test_emit_envelope_raw_prints_only_the_result(capsys: pytest.CaptureFixture[str]) -> None:
    output.set_mode(raw=True)
    output.emit_envelope(
        {
            "ok": True,
            "result": "http://x/dash",
            "code": "page.goto('http://x/dash')",
            "page": {"url": "http://x/dash", "title": "Dash", "fields_stale": False},
        },
        table="navigated to http://x/dash",
    )
    assert capsys.readouterr().out == "http://x/dash\n"


def test_emit_envelope_json_dumps_the_whole_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    output.set_mode(as_json=True)
    env = {"ok": True, "result": "clicked", "code": "c", "page": {"url": "u", "title": "t"}}
    output.emit_envelope(env)
    assert json.loads(capsys.readouterr().out) == env


def test_resolve_out_is_absolute_and_honours_the_output_dir(tmp_path: Path) -> None:
    output.set_output_dir(str(tmp_path))
    assert output.resolve_out("shot.png") == str((tmp_path / "shot.png").resolve())
    absolute = str((tmp_path / "other.png").resolve())
    assert output.resolve_out(absolute) == absolute


def test_snapshot_sink_flag_round_trips() -> None:
    assert output.snapshot_sink() is False
    output.set_snapshot_sink(True)
    assert output.snapshot_sink() is True
