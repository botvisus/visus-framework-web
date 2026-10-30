"""Single-file HTML run report for visus.web (Observability Slice 2).

Reads the ``events.jsonl`` from a session zip (see
``visus.web.observability.recorder``) and renders a self-contained HTML file
suitable for emailing, attaching to a CI artefact, or pinning in a bug
ticket. Every PNG referenced by ``screenshot`` or ``failure_screenshot`` is
embedded as a base64 data URI so the report has no external dependencies.

The look is the orchestrator's (RunPilot) own run report, so a run reads the same
on the desktop and in the web console: a white sheet on a light-grey floor, the
GMES crimson ``#E0205C`` for the eyebrow, a KPI band with mono numbers, the step
timeline as bordered cards with green OK / red FAILED badges, errors in red tints
and the logs in a light box. Geist when installed, the system sans otherwise. It
is always a light document: a report is printed and shared as a PDF.
"""

from __future__ import annotations

import base64
import json
import os
import zipfile
from collections.abc import Iterable
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_EVENTS_FILE = "events.jsonl"
_SCREENSHOTS_DIR = "screenshots/"

_CSS = """
:root {
  --floor: #f5f5f5;
  --paper: #ffffff;
  --soft: #fafafa;
  --line: #e5e5e5;
  --line-soft: #f5f5f5;
  --ink: #171717;
  --text: #262626;
  --body: #404040;
  --sub: #525252;
  --muted: #737373;
  --faint: #a3a3a3;
  --crimson: #E0205C;
  --ok: #047857;
  --ok-strong: #059669;
  --ok-bg: #ecfdf5;
  --ok-line: #a7f3d0;
  --err: #b91c1c;
  --err-strong: #dc2626;
  --err-text: #991b1b;
  --err-soft: #ef4444;
  --err-bg: #fef2f2;
  --err-line: #fecaca;
  --warn: #b45309;
  --warn-bg: #fffbeb;
  --warn-line: #fde68a;
  --sans: Geist, "Segoe UI Variable Text", "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, "Helvetica Neue", Arial, sans-serif;
  --mono: "Geist Mono", "Cascadia Mono", Consolas, ui-monospace, SFMono-Regular, Menlo, monospace;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--floor);
  color: var(--ink);
  font-family: var(--sans);
  font-size: 14px;
  line-height: 1.5;
  padding: 24px 16px;
  -webkit-font-smoothing: antialiased;
}
.sheet {
  max-width: 896px;
  margin: 0 auto;
  background: var(--paper);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 32px;
  box-shadow: 0 1px 2px rgb(0 0 0 / .05);
  print-color-adjust: exact;
  -webkit-print-color-adjust: exact;
}
header.report { border-bottom: 1px solid var(--line); padding-bottom: 20px; }
.head { display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: space-between; gap: 12px; }
.head > div { min-width: 0; }
.eyebrow {
  margin: 0;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--crimson);
}
h1 {
  margin: 4px 0 0;
  font-size: 20px;
  font-weight: 600;
  letter-spacing: -.01em;
  color: var(--ink);
  overflow-wrap: anywhere;
}
.run-id { margin: 4px 0 0; font-family: var(--mono); font-size: 11px; color: var(--muted); }
.pill {
  flex-shrink: 0;
  border: 1px solid;
  border-radius: 9999px;
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 600;
}
.tone-ok { border-color: var(--ok-line); background: var(--ok-bg); color: var(--ok); }
.tone-failed { border-color: var(--err-line); background: var(--err-bg); color: var(--err); }
.tone-neutral { border-color: var(--line); background: var(--line-soft); color: var(--sub); }
.meta { margin-top: 20px; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px 24px; }
.meta > div { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--muted);
}
.meta .v {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
section.kpis { margin-top: 24px; display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; }
.kpi-card { border: 1px solid var(--line); background: var(--soft); border-radius: 8px; padding: 12px 16px; }
.kpi-card .value {
  font-family: var(--mono);
  font-size: 22px;
  font-weight: 600;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  color: var(--ink);
}
.kpi-card .label { margin-top: 6px; }
.kpi-card.ok .value { color: var(--ok-strong); }
.kpi-card.failed .value { color: var(--err-strong); }
.kpi-card.quiet .value { color: var(--muted); }
section.block { margin-top: 32px; }
.block-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 12px; }
h2 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--body);
}
h2.errors { color: var(--err); }
.error-card {
  border: 1px solid var(--err-line);
  background: var(--err-bg);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 12px;
}
.error-card p.message {
  margin: 0;
  font-size: 13px;
  font-weight: 500;
  line-height: 1.6;
  color: var(--err-text);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.error-card .when { margin: 8px 0 0; font-family: var(--mono); font-size: 10px; color: var(--err-soft); }
.run-header { display: flex; align-items: baseline; gap: 8px; margin: 20px 0 8px; flex-wrap: wrap; }
.run-header:first-child { margin-top: 0; }
.run-header h3 { margin: 0; font-family: var(--mono); font-size: 12px; font-weight: 600; color: var(--body); }
.run-header .run-sub { font-size: 11px; color: var(--muted); }
.steps { display: flex; flex-direction: column; gap: 12px; }
article.task { border: 1px solid var(--line); background: var(--paper); border-radius: 8px; padding: 16px; }
.task .row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.task .index { font-family: var(--mono); font-size: 11px; font-weight: 500; color: var(--faint); }
.task .name { font-size: 13px; font-weight: 500; color: var(--ink); overflow-wrap: anywhere; }
.badge-success, .badge-failure, .badge-backtrack {
  border: 1px solid;
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
}
.badge-success { border-color: var(--ok-line); background: var(--ok-bg); color: var(--ok); }
.badge-failure { border-color: var(--err-line); background: var(--err-bg); color: var(--err); }
.badge-backtrack { border-color: var(--warn-line); background: var(--warn-bg); color: var(--warn); }
.task .duration { margin-left: auto; font-family: var(--mono); font-size: 11px; color: var(--muted); }
.task .action { margin: 4px 0 0; font-family: var(--mono); font-size: 11px; color: var(--muted); overflow-wrap: anywhere; }
.task .action b { font-weight: 400; color: var(--body); }
.task .step-error {
  display: inline-block;
  margin: 8px 0 0;
  border: 1px solid var(--err-line);
  background: var(--err-bg);
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 11px;
  line-height: 1.6;
  color: var(--err);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
dl.kv { margin: 8px 0 0; display: grid; grid-template-columns: max-content 1fr; gap: 2px 12px; }
dl.kv dt { font-family: var(--mono); font-size: 10.5px; color: var(--muted); }
dl.kv dd { margin: 0; min-width: 0; font-family: var(--mono); font-size: 10.5px; color: var(--body); overflow-wrap: anywhere; }
details.logs { margin-top: 12px; border: 1px solid var(--line); background: var(--soft); border-radius: 8px; overflow: hidden; }
details.logs > summary {
  cursor: pointer;
  padding: 6px 12px;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--sub);
}
details.logs > summary::marker { color: var(--crimson); }
.log-output { border-top: 1px solid var(--line); max-height: 360px; overflow-y: auto; }
.log-line { display: flex; gap: 12px; padding: 4px 12px; border-bottom: 1px solid var(--line-soft); }
.log-line:last-child { border-bottom: 0; }
.log-line .lvl {
  flex-shrink: 0;
  min-width: 56px;
  font-family: var(--mono);
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--sub);
}
.log-line .msg { min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; font-family: var(--mono); font-size: 10.5px; color: var(--body); }
.lvl-DEBUG .lvl { color: var(--faint); }
.lvl-WARNING .lvl { color: var(--warn); }
.lvl-ERROR .lvl, .lvl-CRITICAL .lvl { color: var(--err); }
pre.json {
  margin: 0;
  padding: 8px 12px;
  border-top: 1px solid var(--line);
  max-height: 360px;
  overflow: auto;
  font-family: var(--mono);
  font-size: 10.5px;
  color: var(--body);
  white-space: pre-wrap;
}
figure.shot { margin: 12px 0 0; max-width: 672px; }
figure.shot img { display: block; width: 100%; height: auto; border: 1px solid var(--line); border-radius: 6px; }
figure.shot.failure img { border-color: var(--err-line); }
figure.shot figcaption { margin-top: 4px; font-family: var(--mono); font-size: 10px; color: var(--faint); }
.empty {
  border: 1px dashed var(--line);
  border-radius: 8px;
  padding: 32px 16px;
  text-align: center;
  font-size: 13px;
  color: var(--muted);
}
footer.report { margin-top: 32px; border-top: 1px solid var(--line); padding-top: 16px; font-size: 10px; color: var(--faint); }
@media (max-width: 860px) {
  section.kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 560px) {
  body { padding: 0; }
  .sheet { border-radius: 0; border-left: 0; border-right: 0; padding: 20px 16px; }
  .meta, section.kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media print {
  html, body { background: #fff !important; padding: 0 !important; }
  .sheet { max-width: none; margin: 0; padding: 0; border: 0; box-shadow: none; }
  article.task, .error-card, figure.shot { break-inside: avoid; }
  @page { margin: 12mm; }
}
""".strip()


def render_report(zip_path: str, output: str = "report.html") -> str:
    """Read *zip_path* and write a self-contained HTML report to *output*.

    Returns the absolute path of the written file.
    """
    events, screenshots = _read_session(Path(zip_path))
    html = _render_html(events, screenshots)
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return str(out.resolve())


def _read_session(zip_path: Path) -> tuple[list[dict[str, Any]], dict[str, bytes]]:
    """Return ``(events, {basename: png_bytes})`` from a session zip."""
    if not zip_path.exists():
        raise FileNotFoundError(zip_path)
    events: list[dict[str, Any]] = []
    screenshots: dict[str, bytes] = {}
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if _EVENTS_FILE in names:
            raw = zf.read(_EVENTS_FILE).decode("utf-8")
            for line in raw.splitlines():
                if line.strip():
                    events.append(json.loads(line))
        for name in names:
            if name.startswith(_SCREENSHOTS_DIR) and name.lower().endswith(".png"):
                screenshots[os.path.basename(name)] = zf.read(name)
    return events, screenshots


def _kpis(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Compute the headline KPIs displayed in the report's KPI strip."""
    events_list = list(events)
    total = len(events_list)
    if total == 0:
        return {
            "total": 0,
            "success_rate_pct": 0,
            "total_duration_ms": 0,
            "failed": 0,
            "distinct_pages": 0,
            "backtrack_steps": 0,
        }
    succeeded = sum(1 for e in events_list if e.get("success"))
    total_duration = sum(int(e.get("duration_ms") or 0) for e in events_list)
    distinct_pages = len({e.get("url") for e in events_list if e.get("url")})
    total_backtracks = sum(int(e.get("backtrack_steps") or 0) for e in events_list)
    return {
        "total": total,
        "success_rate_pct": round(succeeded / total * 100),
        "total_duration_ms": total_duration,
        "failed": total - succeeded,
        "distinct_pages": distinct_pages,
        "backtrack_steps": total_backtracks,
    }


def _group_runs(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group events into runs (by ``run_id``), preserving first-seen order."""
    runs: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}
    for e in events:
        rid = str(e.get("run_id") or "n/a")
        run = index.get(rid)
        if run is None:
            run = {"run_id": rid, "events": []}
            index[rid] = run
            runs.append(run)
        run["events"].append(e)
    for run in runs:
        evs = run["events"]
        # Order chronologically by when each step started. Backtrack replays are
        # recorded mid-action (before the action's own event), so without this they
        # would sort *before* the step that triggered them.
        evs.sort(key=lambda e: e.get("start_ts") or 0.0)
        run["ts"] = evs[0].get("timestamp", "")
        run["ok"] = sum(1 for e in evs if e.get("success"))
        run["total"] = len(evs)
    return runs


# --- formatting (the orchestrator's: 391ms, 2.4s, 1m 3s; en-US instants) ----------


def _duration(ms: float | None) -> str:
    if ms is None or ms < 0:
        return "—"
    if ms < 1000:
        return f"{round(ms)}ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}".removesuffix(".0") + "s"
    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{minutes}m {round(seconds % 60)}s"
    return f"{minutes // 60}h {minutes % 60}m"


def _instant(value: Any) -> str:
    """``10/30/2026, 9:06:53 AM`` in the reader's local time (or the raw value)."""
    if not value:
        return "—"
    try:
        moment = datetime.fromisoformat(str(value)).astimezone()
    except ValueError:
        return str(value)
    hour = moment.hour % 12 or 12
    half = "AM" if moment.hour < 12 else "PM"
    return (
        f"{moment.month}/{moment.day}/{moment.year}, "
        f"{hour}:{moment.minute:02d}:{moment.second:02d} {half}"
    )


def _short_time(iso_ts: str) -> str:
    """HH:MM:SS of an ISO timestamp in the reader's local time, like the dates above
    it (fallback: the raw string)."""
    try:
        return datetime.fromisoformat(iso_ts).astimezone().strftime("%H:%M:%S")
    except ValueError:
        return iso_ts


def _wall_ms(events: list[dict[str, Any]]) -> float | None:
    """First start to last end, when the events carry their clock."""
    starts = [float(e["start_ts"]) for e in events if e.get("start_ts")]
    ends = [float(e["end_ts"]) for e in events if e.get("end_ts")]
    if not starts or not ends:
        return None
    return max(0.0, (max(ends) - min(starts)) * 1000)


def _hosts(events: list[dict[str, Any]]) -> str:
    """The sites the run went through, in order — the report's headline."""
    seen: list[str] = []
    for e in events:
        host = urlparse(str(e.get("url") or "")).hostname or ""
        host = host.removeprefix("www.")
        if host and host not in seen:
            seen.append(host)
    if not seen:
        return "Browser automation"
    return " · ".join(seen[:2]) + (f" +{len(seen) - 2}" if len(seen) > 2 else "")


def _selector_text(selector: Any) -> str:
    """The recorder keeps the selector chain as JSON (``[{"kind","value"}]``): show
    its first value, the one the step used."""
    text = str(selector)
    try:
        chain = json.loads(text)
    except ValueError:
        return text
    if isinstance(chain, list) and chain and isinstance(chain[0], dict):
        first = str(chain[0].get("value") or text)
        return first + (f"  (+{len(chain) - 1})" if len(chain) > 1 else "")
    return text


def _meta(label: str, value: str) -> str:
    return f'<div><span class="label">{escape(label)}</span><span class="v">{escape(value)}</span></div>'


def _kpi(label: str, value: Any, tone: str = "") -> str:
    cls = f"kpi-card {tone}".strip()
    return f'<div class="{cls}"><div class="value">{escape(str(value))}</div><div class="label">{escape(label)}</div></div>'


def _render_html(events: list[dict[str, Any]], screenshots: dict[str, bytes]) -> str:
    kpis = _kpis(events)
    runs = _group_runs(events)
    ordered = [e for run in runs for e in run["events"]]
    numbered = list(enumerate(ordered, start=1))

    if not events:
        status, tone = "No actions", "tone-neutral"
    elif kpis["failed"]:
        status, tone = "Failed", "tone-failed"
    else:
        status, tone = "Completed", "tone-ok"
    run_ids = ", ".join(run["run_id"] for run in runs) or "—"
    last_title = next((str(e["title"]) for e in reversed(ordered) if e.get("title")), "—")
    meta = "".join(
        [
            _meta("Run", run_ids),
            _meta("Started", _instant(ordered[0].get("timestamp")) if ordered else "—"),
            _meta("Finished", _instant(ordered[-1].get("timestamp")) if ordered else "—"),
            _meta("Duration", _duration(_wall_ms(ordered))),
            _meta("Pages", str(kpis["distinct_pages"])),
            _meta("Last page", last_title),
        ]
    )
    kpi_band = "".join(
        [
            _kpi("Steps", kpis["total"]),
            _kpi("OK", kpis["total"] - kpis["failed"], "ok"),
            _kpi("Failed", kpis["failed"], "failed"),
            _kpi("Self-healing retries", kpis["backtrack_steps"], "quiet"),
            _kpi("Success", f"{kpis['success_rate_pct']}%"),
            _kpi("Duration", _duration(kpis["total_duration_ms"])),
        ]
    )

    failures = [(n, e) for n, e in numbered if not e.get("success")]
    errors_block = ""
    if failures:
        cards = "".join(_render_error(e, screenshots, n) for n, e in failures)
        errors_block = (
            f'<section class="block"><div class="block-head">'
            f'<h2 class="errors">Errors ({len(failures)})</h2></div>{cards}</section>'
        )

    if runs:
        sections = []
        number = 0
        for run in runs:
            failed = run["total"] - run["ok"]
            summary = f"{run['ok']}/{run['total']} ok" + (f" · {failed} failed" if failed else "")
            header = ""
            if len(runs) > 1:
                header = (
                    f'<div class="run-header"><h3>Run {escape(run["run_id"])}</h3>'
                    f'<span class="run-sub">{escape(_instant(run["ts"]))} · {summary}</span></div>'
                )
            cards = []
            for event in run["events"]:
                number += 1
                cards.append(_render_task(event, screenshots, number))
            sections.append(header + f'<div class="steps">{"".join(cards)}</div>')
        timeline = "\n".join(sections)
    else:
        timeline = '<p class="empty">No actions recorded.</p>'

    generated = _instant(datetime.now().astimezone().isoformat())
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>visus.web run report</title>
  <style>{_CSS}</style>
</head>
<body>
  <div class="sheet">
    <header class="report">
      <div class="head">
        <div>
          <p class="eyebrow">visus.web — Run report</p>
          <h1>{escape(_hosts(ordered))}</h1>
          <p class="run-id">{escape(run_ids)}</p>
        </div>
        <span class="pill {tone}">{status}</span>
      </div>
      <div class="meta">{meta}</div>
    </header>

    <section class="kpis" aria-label="Run summary">{kpi_band}</section>

    {errors_block}

    <section class="block">
      <div class="block-head"><h2>Step timeline</h2></div>
      {timeline}
    </section>

    <footer class="report">
      Generated by visus.web on {escape(generated)} · Run {escape(run_ids)} · every action
      in order, with its duration, self-healing retries and screenshots.
    </footer>
  </div>
</body>
</html>
"""


_ACTION_TITLES = {
    "goto": "Go to",
    "select_option": "Select",
    "set_input_files": "Upload",
    "pick_date": "Pick date",
    "dblclick": "Double-click",
    "wait_for": "Wait for",
}


def _target_display(event: dict[str, Any]) -> str:
    role, name = event.get("role") or "", event.get("name") or ""
    if role:
        return f'role={role} name="{name}"'
    for key in ("selector", "target", "url"):
        if event.get(key):
            return _selector_text(event[key]) if key == "selector" else str(event[key])
    return ""


def _render_error(event: dict[str, Any], screenshots: dict[str, bytes], number: int) -> str:
    message = str(event.get("error") or "failed")
    shot = ""
    if event.get("failure_screenshot"):
        shot = _render_screenshot(event["failure_screenshot"], screenshots, kind="failure")
    when = _short_time(str(event.get("timestamp") or ""))
    return (
        f'<div class="error-card"><p class="message">{escape(message)}</p>{shot}'
        f'<p class="when">{escape(when)} · step #{number} · {escape(str(event.get("action") or ""))}</p></div>'
    )


def _render_task(event: dict[str, Any], screenshots: dict[str, bytes], number: int) -> str:
    success = bool(event.get("success"))
    badge = (
        '<span class="badge-success">OK</span>'
        if success
        else '<span class="badge-failure">FAILED</span>'
    )
    action = str(event.get("action") or "action")
    name = str(event.get("name") or "")
    verb = _ACTION_TITLES.get(action, action.replace("_", " ").capitalize())
    title = verb + (f" · {name}" if name else "")
    target = _target_display(event)
    action_line = f"<b>{escape(action)}</b>" + (f" → {escape(target)}" if target else "")

    error = event.get("error")
    error_block = f'<p class="step-error">{escape(str(error))}</p>' if error else ""

    rows: list[tuple[str, str]] = []
    backtrack_steps = int(event.get("backtrack_steps") or 0)
    backtrack_badge = ""
    if backtrack_steps > 0:
        # Self-healing is visible on purpose: a step that only passed on a replay
        # is not the same as a step that passed first time, and a reader who
        # cannot see the difference will trust a fragile flow.
        verb = "self-healed" if success else "self-healing failed"
        rows.append(("healing", f"{verb} after having replayed {backtrack_steps} previous step(s)"))
        backtrack_badge = (
            f'<span class="badge-backtrack" title="re-ran {backtrack_steps} previous '
            f'step(s) and retried">&#8635; self-healed &times;{backtrack_steps}</span>'
        )
    if event.get("role"):
        rows.append(("role", str(event["role"])))
    if name:
        rows.append(("name", name))
    if event.get("url"):
        rows.append(("url", str(event["url"])))
    if event.get("title"):
        rows.append(("title", str(event["title"])))
    if event.get("bbox"):
        rows.append(("bbox", str(event["bbox"])))
    if event.get("timestamp"):
        rows.append(("time", _short_time(str(event["timestamp"]))))
    kv = "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in rows)

    shot = ""
    if event.get("screenshot"):
        shot = _render_screenshot(event["screenshot"], screenshots, kind="step")

    return f"""<article class="task">
        <div class="row">
          <span class="index">#{number}</span>
          <span class="name">{escape(title)}</span>
          {badge}{backtrack_badge}
          <span class="duration">{_duration(int(event.get("duration_ms") or 0))}</span>
        </div>
        <p class="action">{action_line}</p>
        {error_block}
        <dl class="kv">{kv}</dl>
        {_render_logs(event.get("logs") or [])}
        {_render_aria_snapshot(event.get("aria_snapshot"))}
        {shot}
      </article>"""


def _render_logs(lines: list[str]) -> str:
    """Render the per-action log lines as a collapsible ``<details>`` block.

    Lines come in shaped as ``"[LEVEL] logger.name: message"`` (set by
    the Recorder's log-tail handler): one row each, the level coloured.
    """
    if not lines:
        return ""
    rendered: list[str] = []
    for line in lines:
        level, message = "INFO", line
        if line.startswith("[") and "]" in line:
            level = line[1 : line.index("]")] or "INFO"
            message = line[line.index("]") + 1 :].strip()
        safe_class = "".join(c for c in level if c.isalnum()).upper() or "INFO"
        rendered.append(
            f'<div class="log-line lvl-{safe_class}"><span class="lvl">{escape(safe_class)}</span>'
            f'<span class="msg">{escape(message)}</span></div>'
        )
    return (
        f'<details class="logs">'
        f"<summary>Logs · {len(lines)} line(s)</summary>"
        f'<div class="log-output">{"".join(rendered)}</div>'
        "</details>"
    )


def _render_aria_snapshot(snapshot: list[dict[str, Any]] | None) -> str:
    """Render the ARIA snapshot (``{role, name}`` dicts captured on failure) as a
    collapsible ``<details>`` block, pretty-printed JSON."""
    if not snapshot:
        return ""
    pretty = escape(json.dumps(snapshot, indent=2, ensure_ascii=False))
    return (
        f'<details class="logs">'
        f"<summary>ARIA snapshot · {len(snapshot)} element(s)</summary>"
        f'<pre class="json">{pretty}</pre>'
        "</details>"
    )


def _render_screenshot(shot_path: str, screenshots: dict[str, bytes], kind: str = "failure") -> str:
    basename = os.path.basename(shot_path)
    data = screenshots.get(basename)
    if data is None:
        return ""
    encoded = base64.b64encode(data).decode("ascii")
    label = "Step result" if kind == "step" else "Failure screenshot"
    return (
        f'<figure class="shot {kind}">'
        f'<img src="data:image/png;base64,{encoded}" alt="{kind} screenshot" loading="eager" />'
        f"<figcaption>{label} · {escape(basename)}</figcaption>"
        "</figure>"
    )
