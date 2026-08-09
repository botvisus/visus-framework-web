"""Tracing from the CLI: a Recorder that `_steps.run_step` can actually see.

`tracing._STATE` is process-global, so the autouse fixture below force-stops any
session a test leaves behind — a leaked Recorder keeps a handler on the ROOT
logger and would corrupt every later test in this worker.
"""

from __future__ import annotations

import json
import logging
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web import tracing
from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


def _force_stop() -> None:
    try:
        tracing.stop_recording(None, None)
    except RuntimeError:
        pass
    tracing.disable()


@pytest.fixture(autouse=True)
def _no_leaked_recording() -> Iterator[None]:
    _force_stop()  # before, in case an earlier module in this worker leaked
    yield
    _force_stop()  # and after, so this module never leaks either


class _FakeBrowser:
    def close(self) -> None:
        pass

    @property
    def contexts(self) -> list[Any]:
        return []


class _TracePage:
    url = "http://x/"
    title_text = "T"

    def title(self) -> str:
        return self.title_text


def _handler(page: Any) -> session_server.SessionHandler:
    h = session_server.SessionHandler(engine="chrome", headless=True)
    h._browser = _FakeBrowser()  # type: ignore[assignment]
    h._page = page
    return h


def test_start_recording_satisfies_both_conditions_run_step_checks() -> None:
    """_steps.run_step needs is_enabled() AND current_recorder() — today only the first."""
    assert tracing.current_recorder() is None
    rec = tracing.start_recording()
    assert tracing.is_enabled() is True
    assert tracing.current_recorder() is rec
    assert len(rec.run_id) == 8


def test_start_recording_refuses_a_second_session() -> None:
    rec = tracing.start_recording()
    with pytest.raises(RuntimeError, match=rec.run_id):
        tracing.start_recording()


def test_stop_recording_without_a_session_raises() -> None:
    with pytest.raises(RuntimeError, match="no tracing session"):
        tracing.stop_recording(None, None)


def test_stop_recording_restores_state_and_writes_a_zip(tmp_path: Path) -> None:
    zip_path = tmp_path / "run.zip"
    rec = tracing.start_recording()
    out = tracing.stop_recording(str(zip_path), None)
    assert out["run_id"] == rec.run_id
    assert Path(out["zip"]) == zip_path.resolve()
    assert zipfile.ZipFile(zip_path).namelist() == ["manifest.json", "events.jsonl"]
    # State restored: tracing is off again and no recorder is installed.
    assert tracing.current_recorder() is None
    assert tracing.is_enabled() is False


def test_stop_recording_without_a_path_just_releases_the_handler() -> None:
    before = len(logging.getLogger().handlers)
    tracing.start_recording()
    assert len(logging.getLogger().handlers) == before + 1
    out = tracing.stop_recording(None, None)
    assert "zip" not in out
    assert len(logging.getLogger().handlers) == before


def test_op_tracing_start_and_stop(tmp_path: Path) -> None:
    zip_path = tmp_path / "run.zip"
    h = _handler(_TracePage())
    started = h.handle("tracing_start", {"zip_path": str(zip_path)})
    assert started["ok"] is True, started
    assert started["result"]["zip_path"] == str(zip_path.resolve())
    assert tracing.current_recorder() is not None

    again = h.handle("tracing_start", {})
    assert again["ok"] is False and "already recording" in again["error"]

    stopped = h.handle("tracing_stop", {})["result"]
    assert stopped["actions"] == 0 and stopped["failures"] == 0
    assert Path(stopped["zip"]) == zip_path.resolve()
    assert tracing.current_recorder() is None

    idle = h.handle("tracing_stop", {})
    assert idle["ok"] is False and "not recording" in idle["error"]


def test_close_flushes_a_live_recording(tmp_path: Path) -> None:
    """A daemon killed mid-trace must not leave the log handler attached."""
    zip_path = tmp_path / "run.zip"
    h = _handler(_TracePage())
    h.handle("tracing_start", {"zip_path": str(zip_path)})
    h.close()
    assert tracing.current_recorder() is None
    assert zip_path.exists()


def test_cli_tracing_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        if op == "tracing_start":
            return {"run_id": "abcd1234", "zip_path": str(tmp_path / "run.zip")}
        return {
            "run_id": "abcd1234",
            "zip": str(tmp_path / "run.zip"),
            "report": str(tmp_path / "report.html"),
            "actions": 4,
            "failures": 1,
        }

    monkeypatch.setattr(session_client, "send", fake_send)
    r1 = runner.invoke(app, ["tracing-start", "-o", str(tmp_path / "run.zip")])
    assert r1.exit_code == 0, r1.output
    assert "abcd1234" in r1.output
    r2 = runner.invoke(app, ["tracing-stop", "--report", str(tmp_path / "report.html")])
    assert r2.exit_code == 0
    assert "4" in r2.output and "report.html" in r2.output
    assert calls[0][0] == "tracing_start"
    assert calls[0][1]["zip_path"] == str((tmp_path / "run.zip").resolve())
    assert calls[0][1]["screenshots"] is True
    assert calls[1][0] == "tracing_stop"
    assert calls[1][1]["report"] == str((tmp_path / "report.html").resolve())


def test_cli_tracing_start_no_screenshots(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {})) or {"run_id": "x", "zip_path": None},
    )
    assert runner.invoke(app, ["tracing-start", "--no-screenshots"]).exit_code == 0
    assert calls[0][1]["screenshots"] is False


def test_cli_report_renders_from_a_zip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`visus report` is one-shot: no daemon, straight to tracing.render_report."""
    seen: dict[str, str] = {}

    def fake_render(zip_path: str, output: str = "report.html") -> str:
        seen["zip"], seen["out"] = zip_path, output
        return output

    monkeypatch.setattr(tracing, "render_report", fake_render)
    src = tmp_path / "run.zip"
    src.write_bytes(b"")
    dst = tmp_path / "out.html"
    r = runner.invoke(app, ["report", str(src), "-o", str(dst)])
    assert r.exit_code == 0, r.output
    assert seen["zip"] == str(src.resolve())
    assert seen["out"] == str(dst.resolve())


def test_repl_tracing_branches() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "tracing_start":
            return {"run_id": "abcd1234", "zip_path": "run.zip"}
        return {"run_id": "abcd1234", "zip": "run.zip", "actions": 2, "failures": 0}

    assert "abcd1234" in console.dispatch("tracing-start run.zip", send)
    assert "2" in console.dispatch("tracing-stop", send)
    assert calls[0][0] == "tracing_start"
    assert calls[0][1]["zip_path"] == str(Path("run.zip").resolve())
    assert calls[1] == ("tracing_stop", {"report": None})
    assert "tracing-start" in console.dispatch("help", send)


@pytest.mark.browser
def test_tracing_records_real_daemon_actions_and_renders_a_report(
    base_url: str, tmp_path: Path
) -> None:
    """The regression test for D11: without a Recorder these actions record nothing."""
    zip_path = tmp_path / "run.zip"
    report_path = tmp_path / "report.html"
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/forms.html"
    )
    try:
        # Force the lazy launch BEFORE recording: _ensure() navigates to the
        # session's start URL on the first op that needs the page, and that goto
        # would otherwise land inside the trace as the first action.
        assert h.handle("url", {})["ok"] is True

        started = h.handle("tracing_start", {"zip_path": str(zip_path)})
        assert started["ok"] is True, started
        run_id = started["result"]["run_id"]

        assert h.handle("fill", {"selector": "#user", "text": "student"})["ok"] is True
        assert h.handle("click", {"selector": "#closebtn"})["ok"] is True

        stopped = h.handle("tracing_stop", {"report": str(report_path)})
        assert stopped["ok"] is True, stopped
        assert stopped["result"]["actions"] >= 2
    finally:
        h.close()

    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        events = [
            json.loads(line)
            for line in z.read("events.jsonl").decode("utf-8").splitlines()
            if line.strip()
        ]
    assert [e["action"] for e in events[:2]] == ["fill", "click"]
    assert all(e["run_id"] == run_id for e in events)
    assert any(n.startswith("screenshots/") for n in names), names

    html = report_path.read_text(encoding="utf-8")
    assert run_id in html
