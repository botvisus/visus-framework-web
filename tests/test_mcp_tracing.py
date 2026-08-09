"""Tracing on the MCP surface: the single-file HTML report as a returned artifact."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any

import pytest

os.environ["VISUS_WEB_HEADLESS"] = "1"


def _fake_zip(path: Path) -> Path:
    """A minimal, valid trace zip — enough for report rendering, no browser."""
    events: list[dict[str, Any]] = [
        {
            "run_id": "abc12345",
            "step_id": 1,
            "action": "click",
            "selector": "#go",
            "role": "button",
            "name": "Go",
            "url": "http://x.test/one",
            "title": "One",
            "duration_ms": 120,
            "backtrack_steps": 0,
            "success": True,
            "error": None,
            "screenshot": None,
            "failure_screenshot": None,
            "timestamp": "2026-08-06T10:00:00+00:00",
            "start_ts": 1.0,
            "end_ts": 1.12,
            "logs": [],
        }
    ]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps({"schema_version": 1}))
        z.writestr("events.jsonl", "\n".join(json.dumps(e) for e in events))
    return path


def test_tracing_report_renders_a_self_contained_html(tmp_path: Path) -> None:
    from visus.web.mcp import server

    zip_path = _fake_zip(tmp_path / "run.zip")
    out = server.browser_tracing_report(str(zip_path), str(tmp_path / "report.html"))
    html = Path(out).read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>")
    assert "visus.web run report" in html
    assert "http://x.test/one" in html
    # Self-contained: no external stylesheet, no external script.
    assert "<link" not in html and 'src="http' not in html


def test_tracing_start_refuses_while_attached(monkeypatch: pytest.MonkeyPatch) -> None:
    """The browser is in the daemon, so recording here would capture nothing."""
    from visus.web.mcp import server

    monkeypatch.setattr(server, "_remote", object())
    with pytest.raises(RuntimeError, match="visus tracing-start"):
        server.browser_tracing_start()
    with pytest.raises(RuntimeError, match="visus tracing-stop"):
        server.browser_tracing_stop()


@pytest.mark.browser
def test_tracing_round_trip_produces_an_attachable_report(tmp_path: Path, base_url: str) -> None:
    from visus.web.mcp import server

    server._session.close()
    try:
        assert "tracing started" in server.browser_tracing_start()
        server.browser_navigate(f"{base_url}/forms.html")
        server.browser_fill("ada", role="textbox", name="Username")
        paths = server.browser_tracing_stop(
            str(tmp_path / "run.zip"), str(tmp_path / "report.html")
        )
        html = Path(paths["report"]).read_text(encoding="utf-8")
        assert "visus.web run report" in html
        # The screenshots are embedded, not linked — that is the whole point.
        assert "data:image/png;base64," in html
        assert "fill" in html
    finally:
        server._session.close()
