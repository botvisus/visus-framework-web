"""The report's own copy — fast, no browser, no recorder."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from visus.web import tracing


def _event(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
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
    base.update(over)
    return base


def _render(tmp_path: Path, events: list[dict[str, Any]]) -> str:
    zip_path = tmp_path / "run.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("manifest.json", json.dumps({"schema_version": 1}))
        z.writestr("events.jsonl", "\n".join(json.dumps(e) for e in events))
    out = tracing.render_report(str(zip_path), str(tmp_path / "report.html"))
    return Path(out).read_text(encoding="utf-8")


def test_the_kpi_band_names_self_healing_retries(tmp_path: Path) -> None:
    html = _render(tmp_path, [_event(backtrack_steps=3)])
    assert "Self-healing retries" in html
    assert "Backtrack steps" not in html, "the old label meant nothing to a report reader"
    assert "backtrack cycles" not in html.lower()  # stale prose, removed long ago


def test_a_recovered_step_says_it_healed(tmp_path: Path) -> None:
    html = _render(tmp_path, [_event(backtrack_steps=2, success=True)])
    # `class="…"` and not the bare word: `.badge-backtrack` is also a RULE in the
    # embedded stylesheet, so a bare substring test would pass on an empty report
    # and prove nothing.
    assert 'class="badge-backtrack"' in html
    assert "self-healed" in html
    assert "replayed 2 previous step(s)" in html


def test_a_failed_step_says_it_tried(tmp_path: Path) -> None:
    html = _render(
        tmp_path,
        [_event(backtrack_steps=2, success=False, error="VisusWebError: no such element")],
    )
    assert "self-healing failed" in html
    assert "replayed 2 previous step(s)" in html
    assert 'class="badge-failure"' in html


def test_a_clean_step_shows_no_healing_copy(tmp_path: Path) -> None:
    html = _render(tmp_path, [_event(backtrack_steps=0)])
    assert 'class="badge-backtrack"' not in html
    assert "self-healed" not in html
    # The KPI card is always present; it just reads zero.
    assert "Self-healing retries" in html


def test_the_hero_lede_explains_the_number(tmp_path: Path) -> None:
    html = _render(tmp_path, [_event()])
    assert "self-healing retries" in html
