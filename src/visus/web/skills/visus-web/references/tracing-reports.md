# Tracing and HTML reports

The strongest thing `visus.web` has that a CLI wrapper cannot give you: a
**single-file HTML report** with every screenshot embedded as base64, a KPI band
(total steps, success rate, duration, failures, distinct pages, backtrack
steps), per-step correlated logs, and an ARIA snapshot captured automatically at
the point of failure. It opens in any browser — mail it, attach it to a ticket,
publish it as a CI artifact.

```python
from visus.web import rpa, expect

with rpa("login", engine="chrome") as page:
    page.goto("https://example.com/login")
    page.get_by_label("Email").fill("ada@example.com")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_text("Welcome")).to_be_visible()
# -> ./visus-runs/login-<timestamp>/report.html  (+ run.zip, + a printed summary)
```

**Caveat:** tracing is a *library* feature. No `visus` command starts or stops a
trace, and setting `VISUS_WEB_TRACING=1` on its own does nothing — a recorder
only exists inside `rpa()` or `tracing.record()`.

## `rpa()` — the batteries-included path

```python
with rpa(
    "checkout",                # run label (used in the output folder name)
    engine="chrome",           # "chrome" | "edge" | "firefox" | "edge_ie"
    headless=False,            # watch it drive; True for CI
    outdir=None,               # default: ./visus-runs/<name>-<timestamp>/
    report=True,               # render report.html on exit (even if a step fails)
    summary=True,              # print a one-block run summary on exit
    open_report=False,         # open report.html in the default browser
    reraise=False,             # True: re-raise VisusWebError for programmatic handling
) as page:
    ...
```

Without `reraise=True`, `rpa()` catches a failed step, still writes the report
and prints a friendly summary, and exits non-zero — a failure is always
debuggable from `report.html`, not just from a stack trace scrolled off a
terminal.

## `tracing.record()` — around any `launch()` block

```python
from visus.web import tracing, launch

with tracing.record("run.zip", report="report.html"):   # report written even on exception
    with launch(headless=True) as browser:
        page = browser.new_page()
        page.goto("https://example.com")
        page.get_by_label("Search").fill("visus")

# Or render a report from a saved zip later:
tracing.render_report("run.zip", "report.html")
# Global toggles: tracing.enable() / tracing.disable() / tracing.is_enabled()
```

The report is still written **even when the body raises** — `record()`'s
`finally` block writes the zip and, on a clean exit, renders the report and
lets a render error propagate; while unwinding an exception it renders
best-effort so a report bug can never mask the real failure.

## What's in the report

- A KPI band: total actions, success rate, total duration, failures, distinct
  pages visited, and summed backtrack steps.
- One card per recorded action: target, duration, success/failure, and its
  screenshot (embedded inline as base64 — the file is fully self-contained,
  nothing to host separately).
- A `↻ backtrack ×N` badge on any action that replayed previous steps —
  `page.click(..., backtrack=True)` (or an integer count) retries by re-running
  the previous N step(s) before retrying the failed one; failed exceptions
  carry the attempted count as `exc.backtrack_steps` so it still shows up even
  when the recovery itself failed.
- An ARIA snapshot captured automatically at the point of failure
  (best-effort — a dead page yields no snapshot rather than a second error).

## Output layout

```
./visus-runs/<name>-<timestamp>/
├── report.html
└── run.zip
```

`rpa()`'s printed summary (when `summary=True`) looks like:

```
actions   : 6
failures  : 0
backtrack : 0 step(s) replayed
```
