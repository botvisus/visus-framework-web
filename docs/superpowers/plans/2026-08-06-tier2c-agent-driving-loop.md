# Agent-Driving Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the `visus` CLI from a set of commands that print bare strings into a closed perception-action loop — every action echoes the page it produced, the code it ran, and a stable vocabulary of refs for the next command.

**Architecture:** A single client-side output funnel (`cli/output.py`) decides how every command prints (TEXT / `--json` / `--raw`), and errors always leave via stderr. The daemon's `handle()` grows a response envelope carrying `page` state, the equivalent `visus.web` `code` line, and an optional `snapshot` file path; `main.py` renders that envelope as `### Code` / `### Page` sections. Token economy comes from four independent levers — a scoped/depth-limited `snapshot`, a grep-style `find`, a slimmed `list-fields` table, and a `.visus/snapshots/*.yml` file sink — while `snapshot` and `list-fields` are unified onto one numbering so a `REF` is directly actionable.

**Tech Stack:** Python 3.10+, Typer, Rich, Selenium 4.38, pytest + pytest-xdist, hatchling, mypy --strict, ruff

## Global Constraints

- Gates that must pass before any commit: `uv run ruff check src tests`, `uv run mypy` (strict), `uv run pytest -q` (≥90% coverage).
- **THE HIDDEN-ENGINE RULE (inviolable):** no `selenium.*` type may appear in any public signature/return/exception/docstring. Selenium imports are allowed ONLY in `backends/browsers/*.py`, `backends/selenium/*.py`, `backends/selenium_backend.py`.
- Test convention: **real browser, no fakes**, `@pytest.mark.browser`, fixtures in `tests/fixtures/*.html` served by the session-scoped `base_url` fixture.
- Test doubles isolate a unit ONLY when its real behaviour is also covered by an integration test. No `skip` / `xfail` / mock-to-pass.
- Ruff: line-length 100, select `["E","F","I","UP","B"]`. mypy: `strict = true`, python_version 3.10.
- Commits: small, TDD (failing test → minimal impl → green → commit), semantic messages `label(scope): description`. Labels: `fix`, `feat`, `chore`, `docs`, `test`, `devops`.
- **Never** add `Co-Authored-By` lines to commits.
- Single-test runs use `--no-cov` (the 90% gate only makes sense on a full run).

## Prerequisites

Two plan files must land before this one.

**PLAN 1 — `2026-08-06-tier1-skill-distribution.md`.** It creates the project's first `@app.callback()` in `src/visus/web/cli/main.py` (there is none today: `main.py:14-17` builds the `Typer` with only `help` / `no_args_is_help`). Symbols consumed here:

- `visus.web.cli.skill_check.check_installed_skills(cwd: Path | None = None) -> None`
- the `@app.callback()` function named `_root(ctx: typer.Context) -> None` in `main.py`, which Task 2 replaces wholesale with a version that also parses the global flags.

**PLAN 3 — `2026-08-06-tier2a-daemon-correctness.md`.** It owns the field-cache staleness contract. Symbols consumed here:

- `SessionHandler._fields_url: str | None` (set in `__init__`, stamped by `_op_list_fields`, cleared by the navigation ops) — read by `_post_state()` in Task 4.
- `StaleFieldIndexError` — surfaced to the agent by the `- Fields: stale` line in Task 4/5.
- PLAN 3 also wraps the body of `SessionHandler.handle()` in `with self._lock:`. Task 4 rewrites that body; **keep the `with self._lock:` wrapper if it is present and replace only the indented body.**

### Ordering inside this plan (hard constraint)

`cli/output.py` and the extended `@app.callback()` must land before any envelope rendering, and the envelope must land before the generated-code echo. That is why the tasks are ordered:

1. Tasks 1–3: the output funnel exists and every command's stdout goes through it.
2. Tasks 4–5: the daemon produces the envelope and the CLI renders `### Page`.
3. Tasks 6–7: the envelope carries `code`, which makes the script exporter possible.
4. Tasks 8–17: token economy, targeting ergonomics, REPL parity, MCP parity.

---

## File Structure

**Created**

| Path | Single responsibility |
|---|---|
| `src/visus/web/cli/output.py` | The one place that decides HOW a value prints: mode state, `emit`, `emit_error`, `emit_envelope`, artifact-path resolution. |
| `tests/test_cli_output.py` | Unit tests for the output funnel (capsys, no CLI). |
| `tests/test_cli_agent_loop.py` | CliRunner + real-browser tests for the envelope, code echo, snapshot refs, and `find`. |
| `tests/fixtures/snapshot_tree.html` | Nested-DOM fixture proving scoped and depth-limited snapshots. |

**Modified**

| Path | What changes |
|---|---|
| `src/visus/web/cli/main.py` | Global `--json` / `--raw` / `--snapshot` / `--output-dir`; every `typer.echo` routed through `output`; `_send_env`; `### Code` / `### Page`; `snapshot` scope/depth/filename/refs; `find`; `session export-script`; `--exact` / `--frame`; targeting error text. |
| `src/visus/web/cli/session_server.py` | `_MUTATING_OPS`, `_post_state`, `_write_snapshot`, `_snapshot_refs`, `_field_code`, `_target_event`, `_generated_code`, `_op_find`, `_op_export_script`, scoped `_op_snapshot`, `render_snapshot_yaml`. |
| `src/visus/web/cli/session_client.py` | `send_envelope()` becomes the primitive; `send()` becomes a thin wrapper over it. |
| `src/visus/web/cli/codegen.py` | `_target_expr` gains a `text` kind; `generate_line` gains an `expr` passthrough and the remaining actions. |
| `src/visus/web/cli/console.py` | `format_fields` slimmed + `full=` columns; `dispatch` gains an optional envelope sender and prints `### Page`; help text; `find` and `snapshot` REF rendering. |
| `src/visus/web/api/page.py` | `Page.snapshot(selector=None, *, depth=None)`. |
| `src/visus/web/async_api/__init__.py` | `AsyncPage.snapshot(selector=None, *, depth=None)`. |
| `src/visus/web/backends/base.py` | `PageDelegate.snapshot(*, selector, depth)`. |
| `src/visus/web/backends/selenium/driver_delegate.py` | Pass `{selector, depth}` into the bundle. |
| `src/visus/web/backends/selenium/js/bundle.js` | `snapshot(opts)` — scope root, depth filter, `depth` in each row. |
| `src/visus/web/mcp/server.py` | `_acted()` helper; every action tool returns action + `### Page`. |
| `tests/test_cli_session.py` | `_patch_client` helper; fakes updated for the new snapshot signature. |
| `tests/test_backend_protocols.py` | Fake delegate's `snapshot` signature. |

---

### Task 1: The output funnel (`cli/output.py`)

**Files:**
- Create: `src/visus/web/cli/output.py`
- Test: `tests/test_cli_output.py`

**Interfaces:**
- Produces (pinned by CONVENTIONS.md, every later task and PLANS 5/6 depend on these exact names):
  ```python
  class Mode(str, Enum): TEXT = "text"; JSON = "json"; RAW = "raw"
  def set_mode(*, as_json: bool = False, raw: bool = False) -> None: ...
  def mode() -> Mode: ...
  def emit(value: Any, *, table: str | None = None) -> None: ...
  def emit_error(message: str, *, code: int = 1) -> NoReturn: ...
  def emit_envelope(env: dict[str, Any], *, table: str | None = None) -> None: ...
  ```
- Produces (additive, only this plan depends on them):
  ```python
  def set_output_dir(path: str | None) -> None: ...
  def resolve_out(path: str) -> str: ...
  def set_snapshot_sink(enabled: bool) -> None: ...
  def snapshot_sink() -> bool: ...
  ```

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_output.py`:

```python
"""Unit tests for the CLI output funnel.

capsys (not CliRunner) is used on purpose: it keeps stdout and stderr apart on
every click version, which is the exact property `emit_error` must guarantee.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

from visus.web.cli import output


@pytest.fixture(autouse=True)
def _reset_output_state() -> None:
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


def test_emit_raw_also_prints_the_table(capsys: pytest.CaptureFixture[str]) -> None:
    # --raw strips ### sections, not the value's own rendering.
    output.set_mode(raw=True)
    output.emit([1, 2], table="TABLE")
    assert capsys.readouterr().out == "TABLE\n"


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_output.py -v --no-cov`
Expected: FAIL — collection error `ModuleNotFoundError: No module named 'visus.web.cli.output'`

- [ ] **Step 3: Write minimal implementation**

Create `src/visus/web/cli/output.py`:

```python
"""Output funnel for the visus CLI — the one place that decides HOW a value prints.

Three modes, selected once by the root ``@app.callback()``:

* ``TEXT`` (default) — human/agent readable: the primary value (or a pre-rendered
  table), then the ``### Code`` and ``### Page`` sections an agent needs in order
  to choose its next command without spending one.
* ``JSON`` (``--json``) — exactly one JSON document per invocation, undecorated.
* ``RAW`` (``--raw``) — the value only: no ``###`` sections, so
  ``TOKEN=$(visus --raw get-attribute value 5)`` captures a token and nothing else.

Errors ALWAYS go to stderr, never stdout: a shell capturing stdout must never
capture an error message as if it were a value.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn

import typer


class Mode(str, Enum):
    """How the current invocation prints its result."""

    TEXT = "text"
    JSON = "json"
    RAW = "raw"


_MODE: Mode = Mode.TEXT
_OUTPUT_DIR: Path | None = None
_SNAPSHOT_SINK: bool = False


def set_mode(*, as_json: bool = False, raw: bool = False) -> None:
    """Select the output mode. ``--json`` wins when both flags are given."""
    global _MODE
    if as_json:
        _MODE = Mode.JSON
    elif raw:
        _MODE = Mode.RAW
    else:
        _MODE = Mode.TEXT


def mode() -> Mode:
    """The active output mode."""
    return _MODE


def set_output_dir(path: str | None) -> None:
    """Directory that relative artifact paths resolve against (``None`` = the cwd)."""
    global _OUTPUT_DIR
    _OUTPUT_DIR = Path(path) if path else None


def resolve_out(path: str) -> str:
    """Absolute path for an artifact the CLIENT writes (screenshot/snapshot/script)."""
    p = Path(path)
    if not p.is_absolute() and _OUTPUT_DIR is not None:
        p = _OUTPUT_DIR / p
    return str(p.resolve())


def set_snapshot_sink(enabled: bool) -> None:
    """When True, mutating commands ask the daemon to write a snapshot file."""
    global _SNAPSHOT_SINK
    _SNAPSHOT_SINK = enabled


def snapshot_sink() -> bool:
    """True when ``--snapshot`` asked for a snapshot file after every action."""
    return _SNAPSHOT_SINK


def _dumps(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def emit(value: Any, *, table: str | None = None) -> None:
    """Print the primary value.

    ``table`` is the pre-rendered text form (a rich table, a formatted line). It is
    used in BOTH text and raw mode — ``--raw`` strips the ``###`` sections, which
    ``emit`` never writes, not the value's own rendering.
    """
    if _MODE is Mode.JSON:
        typer.echo(_dumps(value))
        return
    if table is not None:
        typer.echo(table)
        return
    typer.echo("" if value is None else str(value))


def emit_error(message: str, *, code: int = 1) -> NoReturn:
    """Write an error to STDERR (never stdout) and exit with ``code``."""
    if _MODE is Mode.JSON:
        typer.echo(_dumps({"ok": False, "error": message}), err=True)
    else:
        typer.echo(message, err=True)
    raise typer.Exit(code)


def emit_envelope(env: dict[str, Any], *, table: str | None = None) -> None:
    """Render a full daemon envelope: the value, then ``### Code``, then ``### Page``."""
    if _MODE is Mode.JSON:
        typer.echo(_dumps(env))
        return
    result = env.get("result")
    if _MODE is Mode.RAW:
        typer.echo("" if result is None else str(result))
        return
    typer.echo(table if table is not None else ("" if result is None else str(result)))
    code = env.get("code")
    if code:
        typer.echo("")
        typer.echo("### Code")
        typer.echo(str(code))
    page = env.get("page") or {}
    if page:
        typer.echo("")
        typer.echo("### Page")
        typer.echo(f"- URL: {page.get('url', '')}")
        typer.echo(f"- Title: {page.get('title', '')}")
        snap = env.get("snapshot")
        if snap:
            typer.echo(f"- Snapshot: {snap}")
        if page.get("fields_stale"):
            typer.echo("- Fields: stale — run `visus list-fields` again before using an index")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_output.py -v --no-cov`
Expected: PASS (14 passed)

- [ ] **Step 5: Commit**

```bash
git add src/visus/web/cli/output.py tests/test_cli_output.py
git commit -m "feat(cli): add the output funnel with text/json/raw modes"
```

---

### Task 2: Global `--json` / `--raw` / `--snapshot` / `--output-dir`, and errors on stderr

**Files:**
- Modify: `src/visus/web/cli/main.py` (the `@app.callback()` PLAN 1 added; `_send` at `main.py:205-213`)
- Test: `tests/test_cli_agent_loop.py`
- Modify: `tests/test_cli_session.py` (`test_cli_send_error_exits_1`, currently at `tests/test_cli_session.py:1357-1364`)

**Interfaces:**
- Consumes: `output.set_mode`, `output.set_output_dir`, `output.set_snapshot_sink`, `output.emit_error` (Task 1); `skill_check.check_installed_skills` (PLAN 1).
- Produces: `main._root(ctx, as_json, raw, snapshot_sink, output_dir)` — the global flag surface every later task relies on.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_agent_loop.py` with this content (later tasks append to this file):

```python
"""Tests for the agent-driving loop: global flags, the daemon envelope, the
generated-code echo, snapshot refs, and `visus find`.

The stdout/stderr split is proved in a REAL subprocess: typer's CliRunner merges
or separates the two streams depending on the installed click version, so an
in-process assertion would not prove the property this plan exists to fix.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from visus.web.cli.main import app

runner = CliRunner()

_ERROR_SCRIPT = (
    "import sys; from visus.web.cli.main import app; "
    "sys.argv = ['visus', 'title']; app()"
)


def test_daemon_error_never_touches_stdout(tmp_path: Path) -> None:
    """`TOKEN=$(visus ...)` must never capture an error message."""
    proc = subprocess.run(
        [sys.executable, "-c", _ERROR_SCRIPT],
        cwd=str(tmp_path),  # isolated cwd: no .visus/session.json anywhere above
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 1
    assert proc.stdout.strip() == ""
    assert "no live session" in proc.stderr


def test_root_callback_exposes_the_global_flags() -> None:
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    for flag in ("--json", "--raw", "--snapshot", "--output-dir"):
        assert flag in r.output, f"global flag {flag} missing from `visus --help`"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_agent_loop.py -v --no-cov`
Expected: FAIL — `test_daemon_error_never_touches_stdout` fails on `assert proc.stdout.strip() == ""` because `main.py:212` writes `error: ...` to stdout via `typer.echo`; `test_root_callback_exposes_the_global_flags` fails with `AssertionError: global flag --json missing from 'visus --help'`.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/main.py`, add the import next to the existing `import typer` (line 10):

```python
from visus.web.cli import output
```

Replace the whole `@app.callback()` function PLAN 1 added with:

```python
@app.callback()
def _root(
    ctx: typer.Context,
    as_json: bool = typer.Option(
        False, "--json", help="Emit exactly one JSON document per command."
    ),
    raw: bool = typer.Option(
        False, "--raw", help="Print only the value — no table, no ### Code, no ### Page."
    ),
    snapshot_sink: bool = typer.Option(
        False,
        "--snapshot",
        help="After every action, write .visus/snapshots/page-<ts>.yml and link it.",
    ),
    output_dir: str = typer.Option(
        None,
        "--output-dir",
        envvar="VISUS_WEB_OUTPUT_DIR",
        help="Directory for screenshots/snapshots/scripts (default: the current directory).",
    ),
) -> None:
    """visus.web — Playwright-style web automation on Selenium."""
    output.set_mode(as_json=as_json, raw=raw)
    output.set_output_dir(output_dir)
    output.set_snapshot_sink(snapshot_sink)
    if ctx.invoked_subcommand not in ("install", "install-skills"):
        check_installed_skills()
```

Replace `_send` (`main.py:205-213`) with:

```python
def _send(op: str, args: dict[str, Any] | None = None) -> Any:
    """Send an op to the running daemon, mapping failures to a clean Exit(1)."""
    from visus.web.cli import session_client

    try:
        return session_client.send(op, args or {})
    except session_client.SessionError as exc:
        output.emit_error(f"error: {exc}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_agent_loop.py -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 5: Repair the one existing test that asserted the error was on stdout**

In `tests/test_cli_session.py`, replace `test_cli_send_error_exits_1` (at `tests/test_cli_session.py:1357-1364`):

```python
def test_cli_send_error_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """A daemon failure exits 1. The stdout/stderr split is asserted in a real
    subprocess by tests/test_cli_agent_loop.py — CliRunner's stream merging is
    click-version dependent, so only the exit code is asserted here."""

    def boom(op: str, args: dict[str, Any] | None = None) -> Any:
        raise session_client.SessionError("no live session")

    monkeypatch.setattr(session_client, "send", boom)
    r = runner.invoke(app, ["click", "0"])
    assert r.exit_code == 1
```

- [ ] **Step 6: Run the full CLI suite to verify nothing else regressed**

Run: `uv run pytest tests/test_cli_session.py tests/test_cli.py tests/test_cli_output.py tests/test_cli_agent_loop.py -q --no-cov`
Expected: PASS (no failures)

- [ ] **Step 7: Commit**

```bash
git add src/visus/web/cli/main.py tests/test_cli_agent_loop.py tests/test_cli_session.py
git commit -m "feat(cli): add global --json/--raw/--snapshot/--output-dir and route errors to stderr"
```

---

### Task 3: Route every read command through `emit`

Closes C2's concrete gap: `get-text`, `get-attribute`, `count`, `title`, `url` had no `--json` at all while `README.md:118` claimed "`--json` everywhere". After this task they inherit both global modes for free, and the eight commands that already had a local `--json` funnel through the same code path.

**Files:**
- Modify: `src/visus/web/cli/main.py` — `translate` (`:43-94`), `session_status` (`:263-281`), `list_fields` (`:284-301`), `click`/`fill`/`check`/`uncheck`/`select`/`press` echoes, `goto` (`:404-407`), `get_text` (`:410-419`), `session_screenshot` (`:422-446`), `clear_highlights` (`:449-452`), `tabs` (`:455-468`), `tab` (`:471-477`), `back`/`forward`/`reload` (`:485-500`), `title`/`url` (`:508-517`), `snapshot` (`:520-543`), `get_attribute` (`:546-558`), `count` (`:561-570`), `hover`/`dblclick`/`focus`/`clear_input`/`drag`/`upload` (`:578-672`), `wait`/`expect_text` (`:680-720`), `tab_new`/`tab_close` (`:728-746`), `dialog` (`:754-762`), `cookies`/`add_cookies`/`clear_cookies` (`:770-804`), `eval_js` (`:812-830`), `read_text`/`solve_captcha`/`find_image` (`:838-894`).
- Test: `tests/test_cli_agent_loop.py`

**Interfaces:**
- Consumes: `output.emit`, `output.emit_error`, `output.set_mode` (Task 1).
- Produces: no new symbols — every command's stdout now leaves via `output.emit` / `output.emit_error`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_agent_loop.py`:

```python
import json
from typing import Any

import pytest

from visus.web.cli import session_client


def test_global_json_works_on_commands_that_never_had_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None: "Dashboard")
    r = runner.invoke(app, ["--json", "title"])
    assert r.exit_code == 0
    assert json.loads(r.output) == "Dashboard"


def test_global_raw_prints_a_bare_attribute_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None: "tok-abc")
    r = runner.invoke(app, ["--raw", "get-attribute", "value", "5"])
    assert r.exit_code == 0
    assert r.output == "tok-abc\n"


def test_global_json_wraps_count_as_a_number(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None: 7)
    r = runner.invoke(app, ["--json", "count", "--selector", ".item"])
    assert r.exit_code == 0
    assert json.loads(r.output) == 7


def test_local_json_flag_still_wins_for_list_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    fields = [{"index": 0, "kind": "input", "name": "n", "locator": "#n"}]
    monkeypatch.setattr(session_client, "send", lambda op, args=None: {"fields": fields})
    r = runner.invoke(app, ["list-fields", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output) == fields


def test_missing_target_error_exits_1_without_writing_stdout_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None: "never-called")
    r = runner.invoke(app, ["get-text"])
    assert r.exit_code == 1
    assert "never-called" not in r.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_agent_loop.py -v --no-cov`
Expected: FAIL — `test_global_json_works_on_commands_that_never_had_it` fails with `json.decoder.JSONDecodeError: Expecting value` because `title` still calls `typer.echo(_send("title", {}))` and prints `Dashboard` unquoted.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/main.py`, apply these edits.

Every remaining `typer.echo(<value>)` in a command body becomes `output.emit(<value>)`. Every `typer.echo("error: ...")` followed by `raise typer.Exit(1)` becomes a single `output.emit_error("error: ...")` call. Every local `as_json` branch becomes a `set_mode` call followed by the shared `emit`. Concretely:

```python
@app.command()
def version() -> None:
    """Print the visus.web version."""
    from visus.web import __version__

    output.emit(__version__)
```

```python
    r = _translate(src)
    if as_json:
        output.set_mode(as_json=True)
    if output.mode() is output.Mode.JSON:
        output.emit(r)
        return
    lines = [f"tag    : {r['tag']}"]
    for key, label in (
        ("id", "id     "),
        ("name", "name   "),
        ("css", "css    "),
        ("xpath", "xpath  "),
        ("class", "class  "),
    ):
        if r[key]:
            lines.append(f"{label}: {r[key]}")
    lines.append("candidates (the smart locator tries these in order):")
    for c in [*r["candidates_css"], *r["candidates_xpath"]]:  # type: ignore[misc]
        lines.append(f"  - {c}")
    output.emit(r, table="\n".join(lines))
```

The `translate` "no element HTML found" branch becomes:

```python
    if not src or "<" not in src:
        output.emit_error(
            "No element HTML found. Pass it as an argument, use --file <path>, pipe it via "
            "stdin, or copy the element to your clipboard first.",
            code=2,
        )
```

`doctor` and `install` (one-shot, no daemon):

```python
@app.command()
def doctor(engine: str = "chrome") -> None:
    """Check that a browser + driver launch correctly."""
    try:
        with launch(Engine.from_str(engine), headless=True) as b:
            p = b.new_page()
            p.goto("data:text/html,<title>ok</title>")
            output.emit(f"OK: {engine} launches and navigates (title: {p.title()!r})")
    except Exception as exc:  # noqa: BLE001
        output.emit_error(f"FAILED: {exc}")
```

```python
@app.command()
def install(engine: str = "chrome") -> None:
    """Resolve/download the driver via Selenium Manager (by launching once)."""
    with launch(Engine.from_str(engine), headless=True):
        output.emit(f"{engine} driver is ready (Selenium Manager).")
```

`screenshot`, `pdf`, `open`, `codegen` (the one-shot group): replace each `typer.echo(...)` with `output.emit(...)`, leaving the `input()` prompts as plain `typer.echo` so they stay visible under `--raw` — specifically, `open` keeps `typer.echo("Browser open. Press Enter to close...")` and `codegen` keeps `typer.echo("Recording... interact with the page, then press Enter to finish.")`, because those are prompts, not results.

`session_start` / `session_stop` / `session_status`:

```python
@session_app.command("start")
def session_start(
    url: str = typer.Argument(None, help="URL to open once the browser starts."),
    engine: str = typer.Option("chrome", "--engine", "-e"),
    headless: bool = typer.Option(False, "--headless", help="Run headless (default: headed)."),
) -> None:
    """Start a persistent browser session (detached daemon)."""
    from visus.web.cli import session_client

    try:
        info = session_client.start_daemon(engine, headless, url)
    except session_client.SessionError as exc:
        output.emit_error(f"error: {exc}")
    output.emit(
        info,
        table=f"session started (pid {info['pid']}, port {info['port']}, engine {engine})",
    )


@session_app.command("stop")
def session_stop() -> None:
    """Stop the running session (closes the browser)."""
    from visus.web.cli import session_client

    output.emit(session_client.stop())


@session_app.command("status")
def session_status(
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show the running session's status."""
    from visus.web.cli import session_client

    if as_json:
        output.set_mode(as_json=True)
    info = session_client.status()
    if info is None:
        output.emit_error("no session running")
    keys = ("pid", "port", "engine", "headless", "url", "title", "windows", "active_tab",
            "fields_cached")
    output.emit(
        info,
        table="\n".join(f"{k:14}: {info[k]}" for k in keys if k in info),
    )
```

`list-fields`:

```python
    result = _send(
        "list_fields",
        {"kinds": kinds, "include_hidden": show_all, "highlight": not no_highlight},
    )
    fields = result.get("fields", [])
    if as_json:
        output.set_mode(as_json=True)
    output.emit(fields, table=_format_fields(fields))
```

`click` / `check` / `uncheck` / `hover` / `dblclick` / `focus` / `clear-input` / `read-text` / `solve-captcha` — replace `typer.echo(_send(...))` with `output.emit(_send(...))` (Task 5 upgrades the action subset again).

`fill` / `select` / `press` / `expect-text` / `drag` / `upload` — the missing-value guards become `emit_error`, e.g. for `fill`:

```python
    fill_value = text if text is not None else value
    if fill_value is None:
        output.emit_error("error: no text to fill — use `visus fill <index> <text>` or `--value`")
    args["text"] = fill_value
    output.emit(_send("fill", args))
```

and the same shape for `select` (`"error: no option value — use \`visus select <index> <value>\` or \`--value\`"`), `press` (`"error: no key — use \`visus press <index> <key>\` or \`--key\`"`), `expect-text` (`"error: no expected text — use \`visus expect-text <index> <text>\` or --expected"`), `drag` (`"error: provide a drag target — \`<target_index>\`, --to-selector, or --to-index"`), and `upload` (`"error: provide at least one file path to upload"`).

`goto` / `back` / `forward` / `reload` / `title` / `url` / `get-text` / `get-attribute` / `count` / `clear` / `tab` — each keeps its human sentence as the `table=` argument, and each calls the daemon exactly once by binding the result to a local first:

```python
@app.command()
def goto(url: str = typer.Argument(..., help="URL to navigate to.")) -> None:
    """Navigate the session's page to a URL."""
    result = _send("goto", {"url": url})
    output.emit(result, table=f"navigated to {result}")


@app.command()
def back() -> None:
    """Navigate back in the session's history."""
    result = _send("back", {})
    output.emit(result, table=f"went back to {result}")


@app.command()
def forward() -> None:
    """Navigate forward in the session's history."""
    result = _send("forward", {})
    output.emit(result, table=f"went forward to {result}")


@app.command()
def reload() -> None:
    """Reload the session's current page."""
    result = _send("reload", {})
    output.emit(result, table=f"reloaded {result}")


@app.command()
def title() -> None:
    """Print the session page's title."""
    output.emit(_send("title", {}))


@app.command()
def url() -> None:
    """Print the session page's current URL."""
    output.emit(_send("url", {}))


@app.command("clear")
def clear_highlights() -> None:
    """Remove the numbered field-highlight overlay."""
    output.emit(_send("clear_highlights", {}))


@app.command()
def tab(
    index: int = typer.Argument(None, help="Tab/window index from `visus tabs` (omit = newest)."),
) -> None:
    """Switch the session to a tab/window by index (or the newest if omitted)."""
    result = _send("tab", {"index": index})
    output.emit(
        result, table=f"switched to tab {result['active']}: {str(result.get('title', ''))!r}"
    )
```

`get-text`, `get-attribute`, `count`: `output.emit(_send(...))`.

`session-screenshot`:

```python
    abs_output = output.resolve_out(input_path)
    args: dict[str, Any] = {"path": abs_output, "full_page": full_page}
    if index is not None or selector or role or text:
        args.update(_target_args(index, selector, role, name, text))
    saved = _send("screenshot", args)
    output.emit(saved, table=f"saved {saved}")
```

where the option is renamed in the signature to `input_path: str = typer.Option("screenshot.png", "-o", "--output")` so the local name does not shadow the `output` module. **Apply the same rename in `screenshot`, `pdf`, and `codegen`** — each currently binds a parameter called `output`.

`tabs`, `cookies`, `eval`, `find-image`, `tab-new`, `tab-close`, `dialog`, `add-cookies`, `clear-cookies`, `wait`, `expect-text`:

```python
@app.command()
def tabs(as_json: bool = typer.Option(False, "--json", help="Emit JSON.")) -> None:
    """List open tabs/windows (the active one is marked with *)."""
    result = _send("tabs", {})
    if as_json:
        output.set_mode(as_json=True)
    items = result.get("tabs", [])
    if not items:
        output.emit(result, table="(no tabs)")
        return
    table = "\n".join(
        f"{'*' if t.get('active') else ' '} [{t['index']}] "
        f"{str(t.get('title', ''))!r}  {t.get('url', '')}"
        for t in items
    )
    output.emit(result, table=table)


@app.command()
def cookies(as_json: bool = typer.Option(False, "--json", help="Emit JSON.")) -> None:
    """List all cookies for the session's context."""
    result = _send("cookies", {})
    items = result.get("cookies", [])
    if as_json:
        output.set_mode(as_json=True)
    if not items:
        output.emit(items, table="(no cookies)")
        return
    table = "\n".join(
        f"{c.get('name', '')}={c.get('value', '')}  ({c.get('domain', '')})" for c in items
    )
    output.emit(items, table=table)


@app.command("add-cookies")
def add_cookies(
    cookies_json: str = typer.Argument(..., help='JSON list, e.g. \'[{"name":"a","value":"b","url":"http://x"}]\'.'),
) -> None:
    """Add cookies from a JSON list to the session's context."""
    try:
        parsed = _json.loads(cookies_json)
    except _json.JSONDecodeError as exc:
        output.emit_error(f"error: invalid JSON — {exc}")
    if not isinstance(parsed, list):
        output.emit_error("error: expected a JSON list of cookie objects")
    output.emit(_send("add_cookies", {"cookies": parsed}))


@app.command("eval")
def eval_js(
    expression: str = typer.Argument(..., help="A JS function, e.g. '() => document.title'."),
    arg: str = typer.Argument(None, help="Optional JSON argument passed to the function."),
    as_json: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
) -> None:
    """Evaluate a JavaScript expression in the page and print the result."""
    parsed_arg: Any = None
    if arg is not None:
        try:
            parsed_arg = _json.loads(arg)
        except _json.JSONDecodeError:
            parsed_arg = arg  # treat as a plain string when not valid JSON
    result = _send("eval", {"expression": expression, "arg": parsed_arg})
    if as_json:
        output.set_mode(as_json=True)
    output.emit(result.get("result"))


@app.command("find-image")
def find_image(...) -> None:
    ...
    result = _send("find_image", args)
    if as_json:
        output.set_mode(as_json=True)
    if result.get("found"):
        table = f"found at ({result['x']}, {result['y']}) confidence={result['confidence']:.3f}"
    else:
        table = "not found"
    output.emit(result, table=table)


@app.command("tab-new")
def tab_new(
    url: str = typer.Argument(None, help="Optional URL to open in the new tab."),
) -> None:
    """Open a new tab/window (optionally at URL) and switch the session to it."""
    result = _send("tab_new", {"url": url})
    output.emit(result, table=f"opened tab {result['index']}: {str(result.get('title', ''))!r}")


@app.command("tab-close")
def tab_close(
    index: int = typer.Argument(None, help="Tab index to close (omit = the active tab)."),
) -> None:
    """Close a tab/window by index (or the active one if omitted)."""
    result = _send("tab_close", {"index": index})
    if result.get("remaining", 0) == 0:
        output.emit(result, table="closed the last tab — session stopped")
        return
    output.emit(
        result, table=f"closed tab {result['closed']} ({result['remaining']} remaining)"
    )
```

`dialog`, `clear-cookies`, `wait`, `expect-text`: `output.emit(_send(...))`.

The `snapshot` command keeps its current body for now — Task 9 rewrites it completely.

Because `emit_error` is `NoReturn`, the `raise typer.Exit(1) from exc` lines that followed the old `typer.echo` error calls are deleted; mypy accepts the fall-through.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_agent_loop.py -v --no-cov`
Expected: PASS (7 passed)

- [ ] **Step 5: Run the whole CLI suite**

Run: `uv run pytest tests/test_cli_session.py tests/test_cli.py -q --no-cov`
Expected: PASS

- [ ] **Step 6: Lint and typecheck**

Run: `uv run ruff check src tests && uv run mypy`
Expected: `All checks passed!` and `Success: no issues found`

- [ ] **Step 7: Commit**

```bash
git add src/visus/web/cli/main.py tests/test_cli_agent_loop.py
git commit -m "feat(cli): route every command's output through the emit funnel"
```

---

### Task 4: The daemon response envelope — `_MUTATING_OPS` and `_post_state()`

**Files:**
- Modify: `src/visus/web/cli/session_server.py` (`handle` at `:224-233`; new module constant and methods)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Consumes: `SessionHandler._fields_url` (PLAN 3).
- Produces:
  ```python
  _MUTATING_OPS: frozenset[str]
  def _post_state(self) -> dict[str, Any]: ...
  ```
  and the envelope `{"ok": True, "result": ..., "page": {...}}` that Task 5, PLANS 3/5/6 all honour.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_session.py` (after the existing `test_handle_target_without_target_errors`):

```python
def test_handle_mutating_op_carries_page_state() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("click", {"selector": "#go"})
    assert resp["ok"] is True and resp["result"] == "clicked"
    assert resp["page"] == {
        "url": "about:blank",
        "title": "FakeTitle",
        "fields_stale": False,
    }


def test_handle_read_op_carries_no_page_state() -> None:
    """Reads stay bare so `visus --raw get-text 3 | wc -c` is not polluted."""
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("get_text", {"selector": "#x"})
    assert resp["ok"] is True
    assert "page" not in resp


def test_handle_failed_op_carries_no_page_state() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("click", {})  # no target at all
    assert resp["ok"] is False
    assert "page" not in resp


def test_post_state_flags_a_stale_field_cache() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("list_fields", {})          # stamps _fields_url = "about:blank"
    resp = h.handle("goto", {"url": "http://elsewhere"})
    assert resp["ok"] is True
    # PLAN 3's navigation ops clear the cache, so a fresh index is impossible to
    # misuse; when JS moved the page instead, the URL stamp still catches it.
    h._fields = list(page._fields)       # simulate a JS-driven navigation
    h._fields_url = "about:blank"
    state = h._post_state()
    assert state["fields_stale"] is True


def test_post_state_never_raises() -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True)  # no browser
    h._browser = _FakeBrowser()
    h._page = None  # type: ignore[assignment]
    assert h._post_state() == {}


def test_mutating_ops_cover_every_state_changing_op() -> None:
    assert session_server._MUTATING_OPS == frozenset(
        {
            "click", "dblclick", "fill", "check", "uncheck", "select", "press",
            "hover", "focus", "clear_input", "drag", "upload", "goto", "back",
            "forward", "reload", "tab", "tab_new", "tab_close", "dialog",
            "add_cookies", "clear_cookies", "eval",
        }
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_session.py -k "mutating or post_state" -v --no-cov`
Expected: FAIL — `test_mutating_ops_cover_every_state_changing_op` fails with `AttributeError: module 'visus.web.cli.session_server' has no attribute '_MUTATING_OPS'`; `test_handle_mutating_op_carries_page_state` fails with `KeyError: 'page'`.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/session_server.py`, add the module constant just above `class SessionHandler` (i.e. before line 74):

```python
# Ops that change what the agent is looking at. Only these get a `page` footer;
# reads stay bare so piping (`visus --raw get-text 3`) is never polluted.
_MUTATING_OPS: frozenset[str] = frozenset(
    {
        "click", "dblclick", "fill", "check", "uncheck", "select", "press",
        "hover", "focus", "clear_input", "drag", "upload", "goto", "back",
        "forward", "reload", "tab", "tab_new", "tab_close", "dialog",
        "add_cookies", "clear_cookies", "eval",
    }
)
```

Add `_post_state` immediately above `handle` (i.e. before line 224):

```python
    def _post_state(self) -> dict[str, Any]:
        """Page state AFTER a mutating op: ``{url, title, fields_stale}``.

        Best-effort telemetry — it must never turn a successful action into a
        failed response, so every failure collapses to ``{}``.
        """
        try:
            page = self.page()
            url = page.url
            stale = bool(self._fields) and self._fields_url is not None and self._fields_url != url
            return {"url": url, "title": page.title(), "fields_stale": stale}
        except Exception:  # noqa: BLE001 — page state is telemetry, not the result
            return {}
```

Replace the body of `handle` (`:224-233`) — **if PLAN 3 has wrapped it in `with self._lock:`, keep that wrapper and replace only the indented body**:

```python
    def handle(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Dispatch one op.

        Returns ``{ok:True, result:...}`` plus, for a mutating op, the ``page``
        state the agent needs to choose its next command — the perception half of
        the perception-action loop. Failures return ``{ok:False, error:str}``.
        """
        args = args or {}
        try:
            method = getattr(self, f"_op_{op}", None)
            if method is None:
                raise ValueError(f"unknown op {op!r}")
            resp: dict[str, Any] = {"ok": True, "result": method(args)}
        except Exception as exc:  # noqa: BLE001 — daemon must never crash a client
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if op in _MUTATING_OPS:
            resp["page"] = self._post_state()
        return resp
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_session.py -k "mutating or post_state" -v --no-cov`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the whole session suite**

Run: `uv run pytest tests/test_cli_session.py -q --no-cov`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/session_server.py tests/test_cli_session.py
git commit -m "feat(cli): attach post-action page state to every mutating daemon op"
```

---

### Task 5: `send_envelope` and the `### Page` footer

This is the task that closes C1 for the shell. It also unifies the navigation verbs — which already echoed state ad hoc at `main.py:407`, `:488`, `:494`, `:500` — onto the same mechanism, so there is exactly one code path that prints page state.

**Files:**
- Modify: `src/visus/web/cli/session_client.py` (`send` at `:113-126`)
- Modify: `src/visus/web/cli/main.py` (new `_send_env`; the action + navigation commands)
- Modify: `tests/test_cli_session.py` (add `_patch_client`, migrate the 18 `monkeypatch.setattr(session_client, "send", …)` call sites)
- Test: `tests/test_cli_agent_loop.py`

**Interfaces:**
- Consumes: the envelope from Task 4; `output.emit_envelope` (Task 1).
- Produces:
  ```python
  # session_client.py
  def send_envelope(op: str, args: dict[str, Any] | None = None, *,
                    start_dir: str | Path | None = None) -> dict[str, Any]: ...
  # main.py
  def _send_env(op: str, args: dict[str, Any] | None = None) -> dict[str, Any]: ...
  ```

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_agent_loop.py`:

```python
def _envelope(monkeypatch: pytest.MonkeyPatch, env: dict[str, Any]) -> list[tuple[str, Any]]:
    """Point session_client.send_envelope at a canned envelope; record the calls."""
    calls: list[tuple[str, Any]] = []

    def fake(op: str, args: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
        calls.append((op, args))
        return env

    monkeypatch.setattr(session_client, "send_envelope", fake)
    return calls


def test_click_prints_the_page_footer(monkeypatch: pytest.MonkeyPatch) -> None:
    _envelope(
        monkeypatch,
        {
            "ok": True,
            "result": "clicked",
            "page": {"url": "http://x/dash", "title": "Dash", "fields_stale": False},
        },
    )
    r = runner.invoke(app, ["click", "3"])
    assert r.exit_code == 0
    assert "clicked" in r.output
    assert "### Page" in r.output
    assert "- URL: http://x/dash" in r.output
    assert "- Title: Dash" in r.output


def test_raw_click_prints_only_the_result(monkeypatch: pytest.MonkeyPatch) -> None:
    _envelope(
        monkeypatch,
        {"ok": True, "result": "clicked", "page": {"url": "u", "title": "t"}},
    )
    r = runner.invoke(app, ["--raw", "click", "3"])
    assert r.exit_code == 0
    assert r.output == "clicked\n"


def test_json_click_emits_the_whole_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    env = {"ok": True, "result": "clicked", "page": {"url": "u", "title": "t"}}
    _envelope(monkeypatch, env)
    r = runner.invoke(app, ["--json", "click", "3"])
    assert r.exit_code == 0
    assert json.loads(r.output) == env


def test_goto_keeps_its_human_line_and_gains_the_footer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _envelope(
        monkeypatch,
        {
            "ok": True,
            "result": "http://x/dash",
            "page": {"url": "http://x/dash", "title": "Dash", "fields_stale": False},
        },
    )
    r = runner.invoke(app, ["goto", "http://x/dash"])
    assert r.exit_code == 0
    assert "navigated to http://x/dash" in r.output
    assert "### Page" in r.output


def test_snapshot_flag_is_forwarded_to_the_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _envelope(
        monkeypatch, {"ok": True, "result": "clicked", "page": {"url": "u", "title": "t"}}
    )
    assert runner.invoke(app, ["--snapshot", "click", "3"]).exit_code == 0
    assert calls[-1][1]["snapshot"] is True
    assert runner.invoke(app, ["click", "3"]).exit_code == 0
    assert "snapshot" not in calls[-1][1]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_agent_loop.py -k "footer or raw_click or json_click or goto_keeps or snapshot_flag" -v --no-cov`
Expected: FAIL — `AttributeError: <module 'visus.web.cli.session_client'> has no attribute 'send_envelope'` raised by `monkeypatch.setattr`.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/session_client.py`, replace `send` (`:113-126`) with:

```python
def send_envelope(
    op: str,
    args: dict[str, Any] | None = None,
    *,
    start_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Send an op and return the daemon's FULL reply envelope.

    The envelope carries ``result`` plus, for a mutating op, ``page`` state, the
    generated ``code`` line, and the ``snapshot`` file path — everything the CLI
    needs to print the perception half of the loop. Raises on ``ok: False``.
    """
    info = find_session(start_dir)
    if info is None:
        raise SessionError("no live session — run `visus session start` first")
    resp = _send_raw(int(info["port"]), {"token": info["token"], "op": op, "args": args or {}})
    if not resp.get("ok"):
        raise SessionError(str(resp.get("error", "unknown error")))
    return resp


def send(
    op: str,
    args: dict[str, Any] | None = None,
    *,
    start_dir: str | Path | None = None,
) -> Any:
    """Send an op to the live daemon and return its ``result`` (raises on failure)."""
    return send_envelope(op, args, start_dir=start_dir).get("result")
```

In `src/visus/web/cli/main.py`, add `_send_env` directly below `_send`:

```python
def _send_env(op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send an op and return the daemon's full envelope, mapping failures to Exit(1).

    Commands that change the page use this so they can print ``### Code`` and
    ``### Page``; plain reads keep using :func:`_send`, whose bare value pipes
    cleanly.
    """
    from visus.web.cli import session_client

    payload = dict(args or {})
    if output.snapshot_sink():
        payload["snapshot"] = True
    try:
        return session_client.send_envelope(op, payload)
    except session_client.SessionError as exc:
        output.emit_error(f"error: {exc}")
```

Switch the mutating commands to it. `click`, `check`, `uncheck`, `hover`, `dblclick`, `focus`, `clear-input`:

```python
@app.command()
def click(
    index: int = typer.Argument(None, help="Field index from the last list-fields."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
) -> None:
    """Click a field by index or by --selector/--role/--text."""
    output.emit_envelope(_send_env("click", _target_args(index, selector, role, name, text)))
```

with `check` → `_send_env("check", _target_args(index, selector, role, name, None))`, `uncheck` → `"uncheck"` likewise, and `hover` / `dblclick` / `focus` / `clear_input` each `output.emit_envelope(_send_env("<op>", _target_args(index, selector, role, name, text)))` where `<op>` is `hover`, `dblclick`, `focus`, `clear_input`.

`fill`, `select`, `press`, `drag`, `upload`, `dialog`, `add-cookies`, `clear-cookies`, `eval`: replace their final `output.emit(_send(op, args))` with `output.emit_envelope(_send_env(op, args))`. For `eval`, the envelope's `result` is the `{"result": ...}` dict, so keep the unwrapping in the table:

```python
    env = _send_env("eval", {"expression": expression, "arg": parsed_arg})
    if as_json:
        output.set_mode(as_json=True)
    value = (env.get("result") or {}).get("result")
    output.emit_envelope(env, table="" if value is None else str(value))
```

`goto`, `back`, `forward`, `reload`, `tab`, `tab-new`, `tab-close`:

```python
@app.command()
def goto(url: str = typer.Argument(..., help="URL to navigate to.")) -> None:
    """Navigate the session's page to a URL."""
    env = _send_env("goto", {"url": url})
    output.emit_envelope(env, table=f"navigated to {env.get('result')}")


@app.command()
def back() -> None:
    """Navigate back in the session's history."""
    env = _send_env("back", {})
    output.emit_envelope(env, table=f"went back to {env.get('result')}")


@app.command()
def forward() -> None:
    """Navigate forward in the session's history."""
    env = _send_env("forward", {})
    output.emit_envelope(env, table=f"went forward to {env.get('result')}")


@app.command()
def reload() -> None:
    """Reload the session's current page."""
    env = _send_env("reload", {})
    output.emit_envelope(env, table=f"reloaded {env.get('result')}")


@app.command()
def tab(
    index: int = typer.Argument(None, help="Tab/window index from `visus tabs` (omit = newest)."),
) -> None:
    """Switch the session to a tab/window by index (or the newest if omitted)."""
    env = _send_env("tab", {"index": index})
    result = env.get("result") or {}
    output.emit_envelope(
        env, table=f"switched to tab {result['active']}: {str(result.get('title', ''))!r}"
    )


@app.command("tab-new")
def tab_new(
    url: str = typer.Argument(None, help="Optional URL to open in the new tab."),
) -> None:
    """Open a new tab/window (optionally at URL) and switch the session to it."""
    env = _send_env("tab_new", {"url": url})
    result = env.get("result") or {}
    output.emit_envelope(
        env, table=f"opened tab {result['index']}: {str(result.get('title', ''))!r}"
    )


@app.command("tab-close")
def tab_close(
    index: int = typer.Argument(None, help="Tab index to close (omit = the active tab)."),
) -> None:
    """Close a tab/window by index (or the active one if omitted)."""
    env = _send_env("tab_close", {"index": index})
    result = env.get("result") or {}
    if result.get("remaining", 0) == 0:
        output.emit_envelope(env, table="closed the last tab — session stopped")
        return
    output.emit_envelope(
        env, table=f"closed tab {result['closed']} ({result['remaining']} remaining)"
    )
```

- [ ] **Step 4: Migrate the existing monkeypatches**

Add this helper to `tests/test_cli_session.py`, immediately after the `runner = CliRunner()` line:

```python
def _patch_client(monkeypatch: pytest.MonkeyPatch, fake: Any) -> None:
    """Point BOTH client entry points at one fake.

    `session_client.send` returns only `result`; `send_envelope` returns the whole
    reply. Mutating commands go through `send_envelope`, plain reads through
    `send`, so a test that stubs only one of them silently reaches a real socket.
    """
    monkeypatch.setattr(session_client, "send", fake)
    monkeypatch.setattr(
        session_client,
        "send_envelope",
        lambda op, args=None, **_: {"ok": True, "result": fake(op, args)},
    )
```

Then run `grep -n 'session_client, "send"' tests/test_cli_session.py` and rewrite each of the 18 hits from

```python
monkeypatch.setattr(session_client, "send", <FAKE>)
```

to

```python
_patch_client(monkeypatch, <FAKE>)
```

leaving `<FAKE>` byte-identical. Every existing fake already has the signature `(op, args=None)`, so `fake(op, args)` is a valid call for all of them. The one exception is `test_cli_send_error_exits_1` (rewritten in Task 2), which must keep `monkeypatch.setattr(session_client, "send", boom)` **and** gain a matching envelope stub, because it asserts the failure path:

```python
    monkeypatch.setattr(session_client, "send", boom)
    monkeypatch.setattr(session_client, "send_envelope", boom)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_agent_loop.py tests/test_cli_session.py -q --no-cov`
Expected: PASS

- [ ] **Step 6: Prove it against a real browser**

Append to `tests/test_cli_agent_loop.py`:

```python
@pytest.mark.browser
def test_real_daemon_click_echoes_the_new_page(base_url: str, tmp_path: Path) -> None:
    """The loop closes: a click that navigates reports the URL it produced."""
    info = session_client.start_daemon(
        "chrome", headless=True, url=f"{base_url}/links.html", cwd=tmp_path
    )
    assert info["pid"]
    try:
        env = session_client.send_envelope(
            "click", {"target_text": "Go to page two"}, start_dir=tmp_path
        )
        assert env["ok"] is True
        assert env["result"] == "clicked"
        assert env["page"]["url"].endswith("/page2.html")
        assert env["page"]["title"] == "page two"
    finally:
        session_client.stop(start_dir=tmp_path)
```

Create `tests/fixtures/links.html`:

```html
<!doctype html>
<html>
  <head><title>links fixture</title></head>
  <body>
    <h1>Start</h1>
    <a id="two" href="page2.html">Go to page two</a>
  </body>
</html>
```

- [ ] **Step 7: Run the browser test**

Run: `uv run pytest tests/test_cli_agent_loop.py::test_real_daemon_click_echoes_the_new_page -v --no-cov`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/visus/web/cli/session_client.py src/visus/web/cli/main.py \
        tests/test_cli_session.py tests/test_cli_agent_loop.py tests/fixtures/links.html
git commit -m "feat(cli): print the ### Page footer after every element action"
```

---

### Task 6: The generated-code echo (`### Code`)

`Field.code` is computed frame-aware at `driver_delegate.py:666-685` and assigned at `:709`, and today it is consumed in exactly one place: `console.py:83`. This task makes every action emit the concrete `visus.web` call it just ran, turning the live daemon into the recorder and demoting `visus codegen` (`main.py:170-194`, which calls `launch(...)` at `:180` and therefore cannot see the daemon's browser) from the only path to a fallback.

**Files:**
- Modify: `src/visus/web/cli/codegen.py` (`_target_expr` at `:55-60`, `generate_line` at `:63-72`)
- Modify: `src/visus/web/cli/session_server.py` (`__init__` at `:84-101`; `handle`; new `_field_code`, `_target_event`, `_generated_code`)
- Test: `tests/test_cli_session.py`, `tests/test_codegen.py`

**Interfaces:**
- Consumes: `Field.code` (`api/fields.py`), the envelope from Task 4.
- Produces:
  ```python
  # codegen.py
  def generate_line(event: dict) -> str: ...   # now honours event["target"]["expr"]
  # session_server.py
  def _field_code(self, index: int) -> str | None: ...
  def _target_event(self, args: dict[str, Any]) -> dict[str, Any] | None: ...
  def _generated_code(self, op: str, args: dict[str, Any]) -> str | None: ...
  SessionHandler._script: list[str]
  ```
- Note: CONVENTIONS.md pins `_resolve_field(self, index: int) -> Locator`, so the code string comes from the sibling `_field_code`, not from a changed return type.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_codegen.py`:

```python
def test_generate_line_prefers_an_explicit_expression() -> None:
    """A cached Field carries a full frame-aware expression; use it verbatim."""
    from visus.web.cli.codegen import generate_line

    event = {
        "action": "fill",
        "target": {"kind": "code", "expr": 'page.frame_locator("#f1").locator("#u")'},
        "value": "ada",
    }
    assert generate_line(event) == "page.frame_locator(\"#f1\").locator(\"#u\").fill('ada')"


def test_generate_line_covers_every_daemon_action() -> None:
    from visus.web.cli.codegen import generate_line

    target = {"kind": "css", "value": "#x"}
    assert generate_line({"action": "click", "target": target}) == "page.locator('#x').click()"
    assert generate_line({"action": "dblclick", "target": target}) == "page.locator('#x').dblclick()"
    assert generate_line({"action": "check", "target": target}) == "page.locator('#x').check()"
    assert generate_line({"action": "uncheck", "target": target}) == "page.locator('#x').uncheck()"
    assert generate_line({"action": "hover", "target": target}) == "page.locator('#x').hover()"
    assert generate_line({"action": "focus", "target": target}) == "page.locator('#x').focus()"
    assert generate_line({"action": "clear", "target": target}) == "page.locator('#x').clear()"
    assert (
        generate_line({"action": "press", "target": target, "value": "Enter"})
        == "page.locator('#x').press('Enter')"
    )
    assert (
        generate_line({"action": "set_input_files", "target": target, "value": ["/a.png"]})
        == "page.locator('#x').set_input_files(['/a.png'])"
    )


def test_target_expr_supports_a_text_target() -> None:
    from visus.web.cli.codegen import _target_expr

    assert _target_expr({"kind": "text", "value": "Save"}) == "get_by_text('Save')"
```

Append to `tests/test_cli_session.py`:

```python
def test_handle_click_by_index_echoes_the_field_code() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("list_fields", {})
    resp = h.handle("click", {"index": 1})
    assert resp["ok"] is True
    assert resp["code"] == 'page.frame_locator("#f1").locator("#b").click()'


def test_handle_fill_by_role_echoes_a_role_call() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("fill", {"role": "textbox", "name": "Email", "text": "a@b.c"})
    assert resp["code"] == "page.get_by_role('textbox', name='Email').fill('a@b.c')"


def test_handle_goto_echoes_a_goto_call() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    resp = h.handle("goto", {"url": "http://x"})
    assert resp["code"] == "page.goto('http://x')"


def test_handle_read_op_has_no_code() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    assert "code" not in h.handle("get_text", {"selector": "#x"})


def test_handle_records_a_replayable_script() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("goto", {"url": "http://x"})
    h.handle("fill", {"selector": "#u", "text": "ada"})
    h.handle("click", {"role": "button", "name": "Sign in"})
    assert h._script == [
        "page.goto('http://x')",
        "page.locator('#u').fill('ada')",
        "page.get_by_role('button', name='Sign in').click()",
    ]
```

Add `self.code = f'page.locator("{locator}")'` to the test's `_FakeField` so the fake matches the real `Field`. Replace `_FakeField.__init__` (at `tests/test_cli_session.py:118-125`) with:

```python
class _FakeField:
    def __init__(self, index: int, locator: str, frame: list[str], deep: bool) -> None:
        self.index = index
        self.locator = locator
        self.frame = frame
        self.deep = deep
        self.kind = "input"
        self.name = f"f{index}"
        self.role = None
        chain = "".join(f'.frame_locator("{sel}")' for sel in frame)
        self.code = f'page{chain}.locator("{locator}")'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_codegen.py tests/test_cli_session.py -k "generate_line or target_expr or echoes or replayable" -v --no-cov`
Expected: FAIL — `test_generate_line_prefers_an_explicit_expression` fails with `AssertionError` (the current `generate_line` builds `"page." + _target_expr(...)` and ignores `expr`, producing `page.locator('#x')…`); `test_handle_click_by_index_echoes_the_field_code` fails with `KeyError: 'code'`.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/codegen.py`, replace `_target_expr` and `generate_line` (`:55-72`):

```python
def _target_expr(t: dict) -> str:  # type: ignore[type-arg]
    """The locator expression (without the leading ``page.``) for one target."""
    if t["kind"] == "role":
        return f"get_by_role({t['role']!r}, name={t['name']!r})"
    if t["kind"] == "text":
        return f"get_by_text({t['value']!r})"
    if t["kind"] == "testid":
        return f"get_by_test_id({t['value']!r})"
    return f"locator({t['value']!r})"


# Actions whose generated call takes no argument.
_NO_ARG_ACTIONS: dict[str, str] = {
    "click": "click",
    "dblclick": "dblclick",
    "check": "check",
    "uncheck": "uncheck",
    "hover": "hover",
    "focus": "focus",
    "clear": "clear",
}


def generate_line(event: dict) -> str:  # type: ignore[type-arg]
    """Generate a single visus.web Python statement for one recorded event.

    ``event["target"]["expr"]`` short-circuits selector synthesis: the daemon's
    cached ``Field.code`` is already a complete, frame-aware expression and is
    strictly better than anything reconstructible from a bare selector.
    """
    target = event["target"]
    expr = target.get("expr") or ("page." + _target_expr(target))
    action = event["action"]
    if action in _NO_ARG_ACTIONS:
        return f"{expr}.{_NO_ARG_ACTIONS[action]}()"
    if action == "fill":
        return f"{expr}.fill({event.get('value', '')!r})"
    if action == "press":
        return f"{expr}.press({event.get('value', '')!r})"
    if action == "select_option":
        return f"{expr}.select_option(value={event.get('value', '')!r})"
    if action == "set_input_files":
        return f"{expr}.set_input_files({event.get('value', [])!r})"
    return f"# unsupported: {action}"
```

In `src/visus/web/cli/session_server.py`, add the op→codegen mapping next to `_MUTATING_OPS`:

```python
# op -> (codegen action, the args key holding its value)
_CODE_ACTIONS: dict[str, tuple[str, str | None]] = {
    "click": ("click", None),
    "dblclick": ("dblclick", None),
    "check": ("check", None),
    "uncheck": ("uncheck", None),
    "hover": ("hover", None),
    "focus": ("focus", None),
    "clear_input": ("clear", None),
    "fill": ("fill", "text"),
    "press": ("press", "key"),
    "select": ("select_option", "value"),
    "upload": ("set_input_files", "paths"),
}
```

Add `self._script: list[str] = []` to `SessionHandler.__init__` (after `self._fields: list[Field] = []`, line 99).

Add the three helpers directly below `_target` (i.e. after line 221):

```python
    def _field_code(self, index: int) -> str | None:
        """The cached field's ready-to-paste, frame-aware visus.web expression.

        ``_resolve_field`` returns a Locator (its signature is fixed); this is the
        sibling accessor for the same field's ``code``.
        """
        if index < 0 or index >= len(self._fields):
            return None
        return self._fields[index].code or None

    def _target_event(self, args: dict[str, Any]) -> dict[str, Any] | None:
        """The codegen ``target`` for an action's args, or None when unknowable."""
        if args.get("index") is not None:
            code = self._field_code(int(args["index"]))
            return None if code is None else {"kind": "code", "expr": code}
        if args.get("role"):
            return {"kind": "role", "role": args["role"], "name": args.get("name") or ""}
        if args.get("target_text"):
            return {"kind": "text", "value": args["target_text"]}
        if args.get("selector"):
            return {"kind": "css", "value": args["selector"]}
        return None

    def _generated_code(self, op: str, args: dict[str, Any]) -> str | None:
        """The visus.web line equivalent to this op, or None when it has none.

        Computed BEFORE the op runs, so an index target resolves against the cache
        the caller actually addressed. Never raises: a codegen failure must not
        turn a successful action into an error.
        """
        try:
            if op == "goto":
                return generate_script_goto(str(args.get("url", "")))
            entry = _CODE_ACTIONS.get(op)
            if entry is None:
                return None
            action, value_key = entry
            target = self._target_event(args)
            if target is None:
                return None
            event: dict[str, Any] = {"action": action, "target": target}
            if value_key is not None:
                event["value"] = args.get(value_key, "")
            return generate_line(event)
        except Exception:  # noqa: BLE001 — codegen is a convenience, never a failure
            return None
```

Add the tiny `goto` helper next to `_CODE_ACTIONS` (module level, so it is importable by the script exporter in Task 7):

```python
def generate_script_goto(url: str) -> str:
    """The generated line for a navigation."""
    return f"page.goto({url!r})"
```

Add the import at the top of `session_server.py`, next to the other `visus.web` imports (after line 34):

```python
from visus.web.cli.codegen import generate_line
```

Extend `handle` (the version written in Task 4) to compute and attach the code:

```python
        args = args or {}
        try:
            method = getattr(self, f"_op_{op}", None)
            if method is None:
                raise ValueError(f"unknown op {op!r}")
            code = self._generated_code(op, args)
            resp: dict[str, Any] = {"ok": True, "result": method(args)}
        except Exception as exc:  # noqa: BLE001 — daemon must never crash a client
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if op in _MUTATING_OPS:
            resp["page"] = self._post_state()
        if code:
            resp["code"] = code
            self._script.append(code)
        return resp
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_codegen.py tests/test_cli_session.py -q --no-cov`
Expected: PASS

- [ ] **Step 5: Prove the CLI prints it**

Append to `tests/test_cli_agent_loop.py`:

```python
def test_click_prints_the_generated_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _envelope(
        monkeypatch,
        {
            "ok": True,
            "result": "clicked",
            "code": "page.get_by_role('button', name='Sign in').click()",
            "page": {"url": "u", "title": "t"},
        },
    )
    r = runner.invoke(app, ["click", "--role", "button", "--name", "Sign in"])
    assert r.exit_code == 0
    assert "### Code" in r.output
    assert "page.get_by_role('button', name='Sign in').click()" in r.output


def test_raw_click_suppresses_the_generated_code(monkeypatch: pytest.MonkeyPatch) -> None:
    _envelope(
        monkeypatch,
        {"ok": True, "result": "clicked", "code": "page.locator('#go').click()", "page": {}},
    )
    r = runner.invoke(app, ["--raw", "click", "--selector", "#go"])
    assert r.output == "clicked\n"
```

Run: `uv run pytest tests/test_cli_agent_loop.py -k "generated_code" -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/codegen.py src/visus/web/cli/session_server.py \
        tests/test_codegen.py tests/test_cli_session.py tests/test_cli_agent_loop.py
git commit -m "feat(cli): echo the equivalent visus.web call after every action"
```

---

### Task 7: `visus session export-script`

**Files:**
- Modify: `src/visus/web/cli/session_server.py` (new `_op_export_script`)
- Modify: `src/visus/web/cli/main.py` (new `session_app` command)
- Test: `tests/test_cli_session.py`, `tests/test_cli_agent_loop.py`

**Interfaces:**
- Consumes: `SessionHandler._script` (Task 6), `output.emit`, `output.resolve_out` (Task 1).
- Produces: op `export_script` returning `{"script": str, "lines": int}`; command `visus session export-script [-o FILE]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_session.py`:

```python
def test_handle_export_script_wraps_the_recorded_lines() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("goto", {"url": "http://x"})
    h.handle("fill", {"selector": "#u", "text": "ada"})
    result = h.handle("export_script", {})["result"]
    assert result["lines"] == 2
    assert result["script"] == (
        "from visus.web import launch\n"
        "\n"
        "with launch(headless=False) as browser:\n"
        "    page = browser.new_page()\n"
        "    page.goto('http://x')\n"
        "    page.locator('#u').fill('ada')\n"
    )


def test_handle_export_script_with_nothing_recorded_is_still_runnable() -> None:
    h = _handler_with_fake_page(_FakePage())
    result = h.handle("export_script", {})["result"]
    assert result["lines"] == 0
    assert result["script"].endswith("    pass  # no recorded actions yet\n")
```

Append to `tests/test_cli_agent_loop.py`:

```python
def test_export_script_writes_the_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = "from visus.web import launch\n"
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: {"script": script, "lines": 1}
    )
    dest = tmp_path / "flow.py"
    r = runner.invoke(app, ["session", "export-script", "-o", str(dest)])
    assert r.exit_code == 0
    assert dest.read_text(encoding="utf-8") == script
    assert "saved" in r.output


def test_export_script_raw_prints_the_script(monkeypatch: pytest.MonkeyPatch) -> None:
    script = "from visus.web import launch\n"
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: {"script": script, "lines": 1}
    )
    r = runner.invoke(app, ["--raw", "session", "export-script"])
    assert r.exit_code == 0
    assert r.output == script + "\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py tests/test_cli_agent_loop.py -k "export_script" -v --no-cov`
Expected: FAIL — `test_handle_export_script_wraps_the_recorded_lines` fails on `resp["ok"] is False` / `"unknown op 'export_script'"`; the CLI tests fail with exit code 2 (`No such command 'export-script'`).

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/session_server.py`, add next to `_op_status` (before `_op_shutdown` at `:591`):

```python
    def _op_export_script(self, args: dict[str, Any]) -> dict[str, Any]:
        """Everything this session did, as a runnable visus.web script.

        The daemon has been the recorder since the first action: each op's
        generated line was appended to ``_script`` by :meth:`handle`.
        """
        body = list(self._script)
        lines = [
            "from visus.web import launch",
            "",
            "with launch(headless=False) as browser:",
            "    page = browser.new_page()",
        ]
        lines.extend("    " + line for line in body)
        if not body:
            lines.append("    pass  # no recorded actions yet")
        return {"script": "\n".join(lines) + "\n", "lines": len(body)}
```

In `src/visus/web/cli/main.py`, add below `session_status`:

```python
@session_app.command("export-script")
def session_export_script(
    output_path: str = typer.Option(
        None, "-o", "--output", help="Write the script here (default: print it)."
    ),
) -> None:
    """Emit a runnable visus.web script from everything this session did."""
    result = _send("export_script", {})
    code = str(result.get("script", ""))
    if output_path:
        dest = Path(output.resolve_out(output_path))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(code, encoding="utf-8")
        output.emit(code, table=f"saved {dest} ({result.get('lines', 0)} action(s))")
        return
    output.emit(code, table=code)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py tests/test_cli_agent_loop.py -k "export_script" -v --no-cov`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py \
        tests/test_cli_session.py tests/test_cli_agent_loop.py
git commit -m "feat(cli): add `visus session export-script` to replay a session as code"
```

---

### Task 8: Scoped and depth-limited snapshots (bundle + library)

`bundle.js:415-423` currently walks the whole `document` and emits `{role, name}` with no scope, no depth and no cheap way to shrink the result. This task adds the two token levers at their source.

**Files:**
- Modify: `src/visus/web/backends/selenium/js/bundle.js` (`snapshot` at `:415-423`)
- Modify: `src/visus/web/backends/selenium/driver_delegate.py` (`snapshot` at `:635-639`)
- Modify: `src/visus/web/backends/base.py` (`PageDelegate.snapshot` at `:77`)
- Modify: `src/visus/web/api/page.py` (`Page.snapshot` at `:225-227`)
- Modify: `src/visus/web/async_api/__init__.py` (`AsyncPage.snapshot` at `:392-393`)
- Modify: `tests/test_backend_protocols.py` (fake delegate at `:98-99`)
- Create: `tests/fixtures/snapshot_tree.html`
- Test: `tests/test_e2e_fields.py`

**Interfaces:**
- Produces:
  ```python
  # api/page.py
  def snapshot(self, selector: str | None = None, *, depth: int | None = None) -> list[dict]: ...
  # backends/base.py
  def snapshot(self, *, selector: str | None, depth: int | None) -> list[dict]: ...
  ```
  Each returned row is `{"role": str, "name": str, "depth": int}` where `depth` counts element ancestors between the row and the scope root (a direct child of the root is depth 0).

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/snapshot_tree.html`:

```html
<!doctype html>
<html>
  <head><title>snapshot tree fixture</title></head>
  <body>
    <button id="top">Top level</button>
    <nav>
      <a href="#a">Nav link</a>
    </nav>
    <div id="main">
      <h2>Main heading</h2>
      <div class="row">
        <div class="cell">
          <button id="deep">Deep button</button>
        </div>
      </div>
      <input id="q" aria-label="Search main" />
    </div>
    <footer>
      <a href="#f">Footer link</a>
    </footer>
  </body>
</html>
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_e2e_fields.py`:

```python
@pytest.mark.browser
def test_snapshot_scope_and_depth_shrink_the_result(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    page = browser.new_page()
    page.goto(f"{base_url}/snapshot_tree.html")

    full = page.snapshot()
    names = {e["name"] for e in full}
    assert {"Top level", "Nav link", "Main heading", "Deep button", "Footer link"} <= names
    assert all("depth" in e for e in full)

    scoped = page.snapshot("#main")
    scoped_names = {e["name"] for e in scoped}
    assert "Deep button" in scoped_names
    assert "Main heading" in scoped_names
    assert "Footer link" not in scoped_names  # scope really excludes the rest
    assert "Top level" not in scoped_names

    # Inside #main: h2 and the input are direct children (depth 0); the button is
    # two divs down (depth 2).
    shallow = page.snapshot("#main", depth=0)
    assert {e["name"] for e in shallow} == {"Main heading", "Search main"}

    deep_enough = page.snapshot("#main", depth=2)
    assert "Deep button" in {e["name"] for e in deep_enough}


@pytest.mark.browser
def test_snapshot_of_a_missing_scope_is_empty(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    page = browser.new_page()
    page.goto(f"{base_url}/snapshot_tree.html")
    assert page.snapshot("#nope") == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_e2e_fields.py -k "snapshot_scope or missing_scope" -v --no-cov`
Expected: FAIL — `TypeError: snapshot() takes 1 positional argument but 2 were given`

- [ ] **Step 4: Write minimal implementation**

In `src/visus/web/backends/selenium/js/bundle.js`, replace the `snapshot` function (`:415-423`):

```js
  function snapshot(opts) {
    opts = opts || {};
    var roles = ["button", "link", "textbox", "searchbox", "checkbox", "radio", "combobox",
                 "heading", "tab", "menuitem", "option", "switch", "slider", "spinbutton"];
    var root = document.body || document.documentElement;
    if (opts.selector) {
      root = document.querySelector(opts.selector);
      if (!root) return [];
    }
    var maxDepth = (typeof opts.depth === "number") ? opts.depth : null;
    var out = [], all = root.querySelectorAll("*");
    for (var i = 0; i < all.length; i++) {
      var e = all[i], r = computeRole(e);
      if (roles.indexOf(r) < 0 || !isVisible(e)) continue;
      var d = 0, p = e.parentNode;
      while (p && p !== root && p.nodeType === 1) { d++; p = p.parentNode; }
      if (maxDepth !== null && d > maxDepth) continue;
      out.push({ role: r, name: accessibleName(e), depth: d });
    }
    return out;
  }
```

In `src/visus/web/backends/selenium/driver_delegate.py`, replace `snapshot` (`:635-639`):

```python
    def snapshot(
        self, *, selector: str | None = None, depth: int | None = None
    ) -> list[dict]:  # type: ignore[type-arg]
        """Return interactive elements as {role, name, depth} dicts using the __visus bundle.

        ``selector`` scopes the walk to one subtree and ``depth`` caps how far
        below that root an element may sit — the two cheapest ways to shrink a
        snapshot on a large page.
        """
        self._activate()
        self._ensure_bundle()
        return cast(
            list[dict],  # type: ignore[type-arg]
            self._driver.execute_script(
                "return window.__visus.snapshot(arguments[0]);",
                {"selector": selector, "depth": depth},
            ),
        )
```

In `src/visus/web/backends/base.py`, replace line 77:

```python
    def snapshot(
        self, *, selector: str | None, depth: int | None
    ) -> list[dict]: ...  # type: ignore[type-arg]
```

In `src/visus/web/api/page.py`, replace `snapshot` (`:225-227`):

```python
    def snapshot(
        self, selector: str | None = None, *, depth: int | None = None
    ) -> list[dict]:  # type: ignore[type-arg]
        """Return the page's interactive elements as ``{role, name, depth}`` dicts.

        ``selector`` scopes the snapshot to one subtree (``page.snapshot("#main")``)
        and ``depth`` keeps only elements at most N element levels below that root
        (a direct child is depth 0). Both exist to keep a snapshot of a large page
        small enough to read.
        """
        return self._delegate.snapshot(selector=selector, depth=depth)
```

In `src/visus/web/async_api/__init__.py`, replace `snapshot` (`:392-393`):

```python
    async def snapshot(
        self, selector: str | None = None, *, depth: int | None = None
    ) -> list[dict]:  # type: ignore[type-arg]
        return await asyncio.to_thread(self._p.snapshot, selector, depth=depth)
```

In `tests/test_backend_protocols.py`, replace the fake's `snapshot` (`:98-99`):

```python
    def snapshot(self, *, selector=None, depth=None):
        return []
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_e2e_fields.py -k "snapshot_scope or missing_scope" -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 6: Run the suites that touch snapshots**

Run: `uv run pytest tests/test_backend_protocols.py tests/test_async_api_unit.py tests/test_e2e_mcp.py -q --no-cov -k "not slow"`
Expected: PASS

- [ ] **Step 7: Lint and typecheck**

Run: `uv run ruff check src tests && uv run mypy`
Expected: `All checks passed!` and `Success: no issues found`

- [ ] **Step 8: Commit**

```bash
git add src/visus/web/backends/selenium/js/bundle.js \
        src/visus/web/backends/selenium/driver_delegate.py \
        src/visus/web/backends/base.py src/visus/web/api/page.py \
        src/visus/web/async_api/__init__.py tests/test_backend_protocols.py \
        tests/test_e2e_fields.py tests/fixtures/snapshot_tree.html
git commit -m "feat(api): scope and depth-limit page snapshots"
```

---

### Task 9: Addressable `snapshot` — REF column, scope, depth, and the file sink

Closes C5 by ending the two disjoint enumerations: `snapshot` now (re)populates the same `_fields` cache `list-fields` writes at `session_server.py:242`, and each row carries the `list-fields` index that acts on it. Also delivers the `.visus/snapshots/` sink.

**The sink is OPT-IN, not default-on.** Justification in agent-token terms: playwright-cli writes a snapshot after every command because its snapshot *is* its addressing vocabulary — without it the agent has no refs. visus's addressing vocabulary is `list-fields`, an explicit command, so the default footer an agent needs after an action is two lines (URL + title), not a file. Writing the sink unconditionally would cost a full extra page round-trip plus a disk write on every `click` to produce a file the agent usually never opens. `visus --snapshot click 3` turns it on for a run; `visus snapshot --filename after-login.yml` captures one deliberately.

**Files:**
- Modify: `src/visus/web/cli/session_server.py` (`_op_snapshot` at `:323-324`; new `_snapshot_refs`, `_write_snapshot`, `render_snapshot_yaml`, `_yaml_scalar`; `handle`)
- Modify: `src/visus/web/cli/main.py` (`snapshot` at `:520-543`)
- Modify: `tests/test_cli_session.py` (`_FakePage.snapshot`, `test_handle_title_url_snapshot`)
- Test: `tests/test_cli_session.py`, `tests/test_cli_agent_loop.py`

**Interfaces:**
- Consumes: `Page.snapshot(selector, depth=…)` (Task 8); `SessionHandler._fields` / `_fields_url` (PLAN 3).
- Produces:
  ```python
  def render_snapshot_yaml(elements: list[dict[str, Any]], *, url: str, title: str) -> str: ...
  def _snapshot_refs(self, rows: list[dict[str, Any]]) -> list[int | None]: ...
  def _write_snapshot(self) -> str | None: ...
  ```
  Op `snapshot` now accepts `{selector, depth, refs}` and returns `{"elements": [...], "url": str, "title": str}` with `ref` on every element.

- [ ] **Step 1: Write the failing test**

First update the two test fakes in `tests/test_cli_session.py`. Replace `_FakePage.snapshot` (at `tests/test_cli_session.py:185-186`):

```python
    def snapshot(
        self, selector: str | None = None, *, depth: int | None = None
    ) -> list[dict[str, Any]]:
        self.log.append(f"snapshot:selector={selector}:depth={depth}")
        return [
            {"role": "button", "name": "Go", "depth": 0},
            {"role": "textbox", "name": "Email", "depth": 1},
        ]
```

and replace the snapshot assertion inside `test_handle_title_url_snapshot` (`tests/test_cli_session.py:349-350`):

```python
    snap = h.handle("snapshot", {})["result"]
    assert snap["elements"][0]["role"] == "button"
    assert snap["elements"][0]["name"] == "Go"
    assert "ref" in snap["elements"][0]
```

Then append the new tests to `tests/test_cli_session.py`:

```python
def test_handle_snapshot_forwards_scope_and_depth() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("snapshot", {"selector": "#main", "depth": 2, "refs": False})
    assert "snapshot:selector=#main:depth=2" in page.log


def test_handle_snapshot_shares_the_list_fields_numbering() -> None:
    """One numbering: a snapshot REF is a list-fields index you can act on."""
    page = _FakePage()
    page._fields[0].role = "button"
    page._fields[0].name = "Go"
    h = _handler_with_fake_page(page)
    result = h.handle("snapshot", {})["result"]
    assert result["elements"][0]["ref"] == 0     # matched the cached field
    assert result["elements"][1]["ref"] is None  # heading-ish row, not actionable
    assert len(h._fields) == 2                   # snapshot populated the cache


def test_handle_snapshot_no_refs_leaves_the_cache_alone() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    result = h.handle("snapshot", {"refs": False})["result"]
    assert h._fields == []
    assert all(e["ref"] is None for e in result["elements"])


def test_render_snapshot_yaml_is_parseable_and_quoted() -> None:
    text = session_server.render_snapshot_yaml(
        [{"ref": 0, "role": "button", "name": 'Say "hi"', "depth": 1}],
        url="http://x/a",
        title="A",
    )
    assert 'url: "http://x/a"' in text
    assert "count: 1" in text
    assert "  - ref: 0" in text
    assert '    name: "Say \\"hi\\""' in text
    assert text.endswith("\n")


def test_write_snapshot_lands_under_dot_visus(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    h = _handler_with_fake_page(_FakePage())
    rel = h._write_snapshot()
    assert rel is not None
    written = tmp_path / rel
    assert written.is_file()
    assert written.parent == tmp_path / ".visus" / "snapshots"
    assert written.name.startswith("page-") and written.suffix == ".yml"
    assert "role:" in written.read_text(encoding="utf-8")


def test_handle_writes_the_sink_only_when_asked(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.chdir(tmp_path)
    h = _handler_with_fake_page(_FakePage())
    assert "snapshot" not in h.handle("click", {"selector": "#go"})
    resp = h.handle("click", {"selector": "#go", "snapshot": True})
    assert resp["snapshot"] is not None
    assert (tmp_path / resp["snapshot"]).is_file()
```

Append to `tests/test_cli_agent_loop.py`:

```python
def test_snapshot_prints_a_ref_column(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: {
            "elements": [{"ref": 4, "role": "button", "name": "Go", "depth": 0}],
            "url": "http://x",
            "title": "X",
        },
    )
    r = runner.invoke(app, ["snapshot"])
    assert r.exit_code == 0
    assert "REF" in r.output and "button" in r.output and "Go" in r.output


def test_snapshot_forwards_scope_depth_and_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args))
        or {"elements": [], "url": "u", "title": "t"},
    )
    assert runner.invoke(app, ["snapshot", "#main", "--depth", "3", "--no-refs"]).exit_code == 0
    assert calls[-1] == ("snapshot", {"selector": "#main", "depth": 3, "refs": False})


def test_snapshot_filename_writes_yaml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: {
            "elements": [{"ref": 0, "role": "button", "name": "Go", "depth": 0}],
            "url": "http://x",
            "title": "X",
        },
    )
    dest = tmp_path / "after-click.yml"
    r = runner.invoke(app, ["snapshot", "--filename", str(dest)])
    assert r.exit_code == 0
    body = dest.read_text(encoding="utf-8")
    assert 'url: "http://x"' in body and "  - ref: 0" in body
    assert str(dest) in r.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py tests/test_cli_agent_loop.py -k "snapshot" -v --no-cov`
Expected: FAIL — `test_render_snapshot_yaml_is_parseable_and_quoted` fails with `AttributeError: module 'visus.web.cli.session_server' has no attribute 'render_snapshot_yaml'`; `test_snapshot_prints_a_ref_column` fails with `AssertionError: 'REF' not in ...`.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/session_server.py`, add the imports `import datetime as _dt` and `import re` at the top (after `import json`, line 17), then add the YAML renderer at module level, just above `def session_file(...)` (before line 601):

```python
def _yaml_scalar(value: object) -> str:
    """Render one scalar as YAML. Strings are always quoted — names contain colons."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def render_snapshot_yaml(
    elements: list[dict[str, Any]], *, url: str, title: str
) -> str:
    """Render a page snapshot as the YAML written to ``.visus/snapshots/``."""
    out = [
        "# visus page snapshot",
        f"url: {_yaml_scalar(url)}",
        f"title: {_yaml_scalar(title)}",
        f"count: {len(elements)}",
        "elements:",
    ]
    for e in elements:
        out.append(f"  - ref: {_yaml_scalar(e.get('ref'))}")
        out.append(f"    role: {_yaml_scalar(e.get('role') or '')}")
        out.append(f"    name: {_yaml_scalar(e.get('name') or '')}")
        if e.get("depth") is not None:
            out.append(f"    depth: {_yaml_scalar(e.get('depth'))}")
    return "\n".join(out) + "\n"
```

Add the two handler methods next to `_post_state`:

```python
    def _snapshot_refs(self, rows: list[dict[str, Any]]) -> list[int | None]:
        """Map each snapshot row to a ``list_fields`` index — ONE numbering.

        Both enumerations come from the same bundle helpers (``computeRole`` and
        ``accessibleName``), so ``(role, name)`` identifies a row that is also an
        actionable field. Rows with no actionable twin (headings, options) get None.
        """
        by_key: dict[tuple[str, str], int] = {}
        for f in self._fields:
            by_key.setdefault(((f.role or ""), (f.name or "")), f.index)
        return [by_key.get(((r.get("role") or ""), (r.get("name") or ""))) for r in rows]

    def _write_snapshot(self) -> str | None:
        """Write the current snapshot under ``.visus/snapshots/`` and return its path.

        The daemon owns ``.visus/`` (see :func:`session_file`), and its cwd is the
        directory ``visus session start`` ran in, so the returned path is relative
        to the project root. Never raises.
        """
        try:
            page = self.page()
            rows = page.snapshot()
            refs = self._snapshot_refs(rows)
            elements = [{**row, "ref": refs[i]} for i, row in enumerate(rows)]
            text = render_snapshot_yaml(elements, url=page.url, title=page.title())
            base = Path.cwd() / ".visus" / "snapshots"
            base.mkdir(parents=True, exist_ok=True)
            stamp = _dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S-%f")[:-3]
            path = base / f"page-{stamp}.yml"
            path.write_text(text, encoding="utf-8")
            try:
                return str(path.relative_to(Path.cwd()))
            except ValueError:
                return str(path)
        except Exception:  # noqa: BLE001 — the sink is a convenience, never a failure
            return None
```

Replace `_op_snapshot` (`:323-324`):

```python
    def _op_snapshot(self, args: dict[str, Any]) -> dict[str, Any]:
        """The page's interactive elements, numbered with list_fields indexes.

        ``refs`` (default on) re-enumerates the page so every row's ``ref`` is a
        live index an action can use immediately — this is what makes ``snapshot``
        addressable instead of a second, incompatible numbering. Pass
        ``refs=False`` for a pure read that leaves the field cache untouched.
        """
        page = self.page()
        depth = args.get("depth")
        rows = page.snapshot(
            args.get("selector"), depth=None if depth is None else int(depth)
        )
        if args.get("refs", True):
            fields = page.list_fields(kinds=None, include_hidden=False, highlight=False)
            self._fields = list(fields)
            self._fields_url = page.url
        refs = self._snapshot_refs(rows)
        elements = [{**row, "ref": refs[i]} for i, row in enumerate(rows)]
        return {"elements": elements, "url": page.url, "title": page.title()}
```

Extend `handle` (Task 6's version) with the sink:

```python
        if op in _MUTATING_OPS:
            resp["page"] = self._post_state()
            if args.get("snapshot"):
                resp["snapshot"] = self._write_snapshot()
```

In `src/visus/web/cli/main.py`, replace the `snapshot` command (`:520-543`):

```python
@app.command()
def snapshot(
    selector: str = typer.Argument(
        None, help='Scope the snapshot to a CSS selector, e.g. "#main".'
    ),
    depth: int = typer.Option(
        None, "--depth", help="Keep only elements at most N levels below the scope root."
    ),
    filename: str = typer.Option(
        None, "--filename", help="Write the snapshot as YAML here instead of printing it."
    ),
    refs: bool = typer.Option(
        True,
        "--refs/--no-refs",
        help="Number rows with list-fields indexes (re-enumerates the page).",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List the page's interactive elements as a REF/ROLE/NAME table.

    A REF is a `visus list-fields` index: `visus snapshot` then `visus click 4`
    works. Scope it (`visus snapshot "#main"`), cap it (`--depth 2`), or save it
    (`--filename after-login.yml`) when the page is large.
    """
    args: dict[str, Any] = {"selector": selector, "depth": depth, "refs": refs}
    result = _send("snapshot", args)
    elements = result.get("elements", [])
    if as_json:
        output.set_mode(as_json=True)

    if filename or output.snapshot_sink():
        from visus.web.cli.session_server import render_snapshot_yaml

        target = filename or f"page-{_dt.datetime.now():%Y-%m-%dT%H-%M-%S}.yml"
        dest = Path(output.resolve_out(target))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            render_snapshot_yaml(
                elements, url=str(result.get("url", "")), title=str(result.get("title", ""))
            ),
            encoding="utf-8",
        )
        output.emit(elements, table=f"Snapshot: {dest}")
        return

    if not elements:
        output.emit(elements, table="(no elements)")
        return
    output.emit(elements, table=_format_snapshot(elements))
```

Add the renderer next to `_format_fields` (`main.py:216-219`):

```python
def _format_snapshot(elements: list[dict[str, Any]]) -> str:
    """Render snapshot rows as a REF/ROLE/NAME table (REF = a list-fields index)."""
    from rich import box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=box.ASCII, header_style="bold", pad_edge=False)
    table.add_column("REF", justify="right", no_wrap=True)
    table.add_column("ROLE", no_wrap=True)
    table.add_column("NAME", overflow="fold")
    for e in elements:
        ref = e.get("ref")
        table.add_row("-" if ref is None else str(ref), str(e.get("role", "")),
                      str(e.get("name", "")))
    console_obj = Console()
    with console_obj.capture() as cap:
        console_obj.print(table)
    return cap.get().rstrip("\n")
```

Add `import datetime as _dt` at the top of `main.py` (next to `import json as _json`, line 5).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py tests/test_cli_agent_loop.py -k "snapshot" -v --no-cov`
Expected: PASS

- [ ] **Step 5: Prove the refs are actionable against a real browser**

Append to `tests/test_cli_agent_loop.py`:

```python
@pytest.mark.browser
def test_snapshot_ref_is_a_usable_field_index(base_url: str, tmp_path: Path) -> None:
    session_client.start_daemon(
        "chrome", headless=True, url=f"{base_url}/snapshot_tree.html", cwd=tmp_path
    )
    try:
        snap = session_client.send("snapshot", {}, start_dir=tmp_path)
        row = next(e for e in snap["elements"] if e["name"] == "Deep button")
        assert row["ref"] is not None, "an actionable button must carry a REF"
        env = session_client.send_envelope(
            "click", {"index": row["ref"]}, start_dir=tmp_path
        )
        assert env["ok"] is True and env["result"] == "clicked"
        assert "#deep" in env["code"] or "Deep button" in env["code"]
    finally:
        session_client.stop(start_dir=tmp_path)
```

Run: `uv run pytest tests/test_cli_agent_loop.py::test_snapshot_ref_is_a_usable_field_index -v --no-cov`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py \
        tests/test_cli_session.py tests/test_cli_agent_loop.py
git commit -m "feat(cli): make snapshot addressable with list-fields refs, scope, depth and a file sink"
```

---

### Task 10: `visus find` — grep the snapshot instead of printing it

**Files:**
- Modify: `src/visus/web/cli/session_server.py` (new `_op_find`)
- Modify: `src/visus/web/cli/main.py` (new `find` command, `_format_find`)
- Test: `tests/test_cli_session.py`, `tests/test_cli_agent_loop.py`

**Interfaces:**
- Consumes: `Page.snapshot(selector, depth=…)` (Task 8), `SessionHandler._snapshot_refs` (Task 9).
- Produces: op `find` accepting `{query, regex, context, selector, depth}` and returning
  `{"query": str, "regex": bool, "total": int, "matched": int, "rows": [{"line": int, "role": str, "name": str, "depth": int, "ref": int | None, "match": bool}]}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_session.py`:

```python
class _FindPage(_FakePage):
    """A page with enough rows to make grep-style context observable."""

    def snapshot(
        self, selector: str | None = None, *, depth: int | None = None
    ) -> list[dict[str, Any]]:
        self.log.append(f"snapshot:selector={selector}:depth={depth}")
        names = ["Home", "Products", "Blue widget", "Add to cart", "Red widget", "About", "Legal"]
        return [{"role": "link", "name": n, "depth": 1} for n in names]


def test_handle_find_returns_matches_with_context() -> None:
    h = _handler_with_fake_page(_FindPage())
    result = h.handle("find", {"query": "Add to cart", "context": 1})["result"]
    assert result["total"] == 7
    assert result["matched"] == 1
    assert [r["name"] for r in result["rows"]] == ["Blue widget", "Add to cart", "Red widget"]
    assert [r["match"] for r in result["rows"]] == [False, True, False]


def test_handle_find_is_case_insensitive_by_default() -> None:
    h = _handler_with_fake_page(_FindPage())
    result = h.handle("find", {"query": "WIDGET", "context": 0})["result"]
    assert result["matched"] == 2


def test_handle_find_regex_mode() -> None:
    h = _handler_with_fake_page(_FindPage())
    result = h.handle("find", {"query": r"^link (Blue|Red)", "regex": True, "context": 0})
    assert result["result"]["matched"] == 2


def test_handle_find_no_match_returns_no_rows() -> None:
    h = _handler_with_fake_page(_FindPage())
    result = h.handle("find", {"query": "nothing here"})["result"]
    assert result["matched"] == 0 and result["rows"] == []


def test_handle_find_forwards_scope_and_depth() -> None:
    page = _FindPage()
    h = _handler_with_fake_page(page)
    h.handle("find", {"query": "Home", "selector": "#main", "depth": 2})
    assert "snapshot:selector=#main:depth=2" in page.log
```

Append to `tests/test_cli_agent_loop.py`:

```python
def test_find_renders_matches_with_a_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: {
            "query": "cart",
            "regex": False,
            "total": 40,
            "matched": 1,
            "rows": [
                {"line": 6, "role": "link", "name": "Blue widget", "ref": 2, "match": False},
                {"line": 7, "role": "button", "name": "Add to cart", "ref": 3, "match": True},
            ],
        },
    )
    r = runner.invoke(app, ["find", "cart"])
    assert r.exit_code == 0
    assert "1 of 40 rows match 'cart'" in r.output
    assert "> " in r.output and "Add to cart" in r.output


def test_find_forwards_its_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args))
        or {"query": "x", "regex": True, "total": 0, "matched": 0, "rows": []},
    )
    r = runner.invoke(
        app, ["find", r"\$[0-9]+", "--regex", "-C", "1", "-s", "#main", "--depth", "4"]
    )
    assert r.exit_code == 0
    assert calls[-1] == (
        "find",
        {"query": r"\$[0-9]+", "regex": True, "context": 1, "selector": "#main", "depth": 4},
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py tests/test_cli_agent_loop.py -k "find" -v --no-cov`
Expected: FAIL — the daemon tests fail on `resp["ok"] is False` / `"unknown op 'find'"`; the CLI tests fail with exit code 2 (`No such command 'find'`).

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/session_server.py`, add next to `_op_snapshot`:

```python
    def _op_find(self, args: dict[str, Any]) -> dict[str, Any]:
        """Grep the page snapshot instead of printing all of it.

        Each row is matched as ``"<role> <name>"``. Substring matching is
        case-insensitive; ``regex`` switches to a Python regular expression.
        ``context`` rows around each hit are returned too, like ``grep -C``.
        """
        query = str(args.get("query") or "")
        use_regex = bool(args.get("regex", False))
        context = max(0, int(args.get("context") or 0))
        page = self.page()
        depth = args.get("depth")
        rows = page.snapshot(
            args.get("selector"), depth=None if depth is None else int(depth)
        )

        def _line(row: dict[str, Any]) -> str:
            return f"{row.get('role') or ''} {row.get('name') or ''}"

        if use_regex:
            pattern = re.compile(query)
            hits = [i for i, row in enumerate(rows) if pattern.search(_line(row))]
        else:
            needle = query.casefold()
            hits = [i for i, row in enumerate(rows) if needle in _line(row).casefold()]

        hit_set = set(hits)
        keep: set[int] = set()
        for i in hits:
            keep.update(range(max(0, i - context), min(len(rows), i + context + 1)))
        refs = self._snapshot_refs(rows)
        out: list[dict[str, Any]] = []
        for i in sorted(keep):
            out.append({**rows[i], "line": i, "ref": refs[i], "match": i in hit_set})
        return {
            "query": query,
            "regex": use_regex,
            "total": len(rows),
            "matched": len(hits),
            "rows": out,
        }
```

In `src/visus/web/cli/main.py`, add the renderer next to `_format_snapshot`:

```python
def _format_find(result: dict[str, Any]) -> str:
    """Render `find` output grep-style: `>` marks a hit, `--` separates groups."""
    rows = result.get("rows", [])
    if not rows:
        return f"no match for {result.get('query', '')!r} in {result.get('total', 0)} rows"
    lines = [f"{result.get('matched', 0)} of {result.get('total', 0)} rows "
             f"match {result.get('query', '')!r}"]
    prev: int | None = None
    for r in rows:
        if prev is not None and r["line"] != prev + 1:
            lines.append("--")
        prev = r["line"]
        mark = ">" if r.get("match") else " "
        ref = "-" if r.get("ref") is None else str(r["ref"])
        lines.append(f"{mark} {ref:>4}  {str(r.get('role', '')):<12} {r.get('name', '')}")
    return "\n".join(lines)
```

and the command, next to `snapshot`:

```python
@app.command()
def find(
    query: str = typer.Argument(..., help="Text to look for in the page snapshot."),
    regex: bool = typer.Option(
        False, "--regex", help="Treat QUERY as a Python regular expression."
    ),
    context: int = typer.Option(3, "--context", "-C", help="Rows of context around each hit."),
    selector: str = typer.Option(
        None, "--selector", "-s", help="Scope the search to a CSS selector."
    ),
    depth: int = typer.Option(
        None, "--depth", help="Keep only elements at most N levels below the scope root."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Search the page instead of snapshotting it — matching rows plus context.

    `visus find "Add to cart"` on a 400-element page returns a handful of rows
    with their REFs, so the next command is `visus click <REF>`.
    """
    result = _send(
        "find",
        {
            "query": query,
            "regex": regex,
            "context": context,
            "selector": selector,
            "depth": depth,
        },
    )
    if as_json:
        output.set_mode(as_json=True)
    output.emit(result, table=_format_find(result))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py tests/test_cli_agent_loop.py -k "find" -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py \
        tests/test_cli_session.py tests/test_cli_agent_loop.py
git commit -m "feat(cli): add `visus find` to grep the page snapshot with context"
```

---

### Task 11: Slim the `list-fields` table

`console.py:70` passes `show_lines=True`, so a 200-field page emits a rule between **every** row — 400+ lines before counting the six wrapping columns (CSS + XPATH + the Python expression each fold). The default table keeps what an agent acts on; `--full` restores the forensic columns.

**Files:**
- Modify: `src/visus/web/cli/console.py` (`format_fields` at `:56-93`)
- Modify: `src/visus/web/cli/main.py` (`_format_fields` at `:216-219`; `list_fields` at `:284-301`)
- Modify: `tests/test_cli_session.py` (`test_format_fields_table_shows_visus_css_xpath` at `:654-676`)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces: `console.format_fields(fields, *, width: int | None = None, full: bool = False) -> str`
- Produces: `main._format_fields(fields, *, full: bool = False) -> str`

- [ ] **Step 1: Write the failing test**

Update the existing `test_format_fields_table_shows_visus_css_xpath` in `tests/test_cli_session.py` (`:654`) so it asks for the forensic columns explicitly — add `full=True` to the call:

```python
    out = console.format_fields(
        [
            {
                "index": 0,
                "kind": "button",
                "name": "Submit",
                "frame": ["#f1"],
                "code": 'page.frame_locator("#f1").locator("#submit")',
                "css": "#submit",
                "xpath": '//*[@id="submit"]',
            }
        ],
        width=200,
        full=True,
    )
```

Then append the new tests:

```python
_ONE_FIELD = [
    {
        "index": 0,
        "kind": "button",
        "name": "Submit",
        "frame": [],
        "code": 'page.locator("#submit")',
        "css": "#submit",
        "xpath": '//*[@id="submit"]',
    }
]


def test_format_fields_default_drops_css_and_xpath() -> None:
    out = console.format_fields(_ONE_FIELD, width=200)
    assert "VISUS" in out and "KIND" in out
    assert "CSS" not in out and "XPATH" not in out


def test_format_fields_default_has_no_row_rules() -> None:
    """show_lines=True doubled the line count of every list-fields call."""
    two = [_ONE_FIELD[0], {**_ONE_FIELD[0], "index": 1}]
    out = console.format_fields(two, width=200)
    # header rule, header, header rule, 2 rows, closing rule -> 6 lines.
    assert len(out.splitlines()) == 6


def test_format_fields_full_restores_the_forensic_columns() -> None:
    out = console.format_fields(_ONE_FIELD, width=200, full=True)
    assert "CSS" in out and "XPATH" in out


def test_cli_list_fields_full_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, lambda op, args=None: {"fields": _ONE_FIELD})
    assert "XPATH" not in runner.invoke(app, ["list-fields"]).output
    assert "XPATH" in runner.invoke(app, ["list-fields", "--full"]).output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "format_fields or list_fields_full" -v --no-cov`
Expected: FAIL — `test_format_fields_default_drops_css_and_xpath` fails with `AssertionError: 'CSS' not in ...` inverted (CSS *is* present today); `test_format_fields_default_has_no_row_rules` fails with `assert 8 == 6`.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/console.py`, replace `format_fields` (`:56-93`):

```python
def format_fields(
    fields: list[dict[str, Any]], *, width: int | None = None, full: bool = False
) -> str:
    """Render fields as a table: #, KIND, NAME, and the ready-to-paste VISUS call.

    The VISUS column is copy-paste-ready and *frame-aware* — for an element inside
    an iframe it is wrapped in ``frame_locator(...)`` so a click/fill actually
    reaches it (a bare css/xpath would not). ``full=True`` adds the CSS and XPATH
    columns; they are off by default because on a large page they triple the
    output an agent has to read for no gain over the VISUS column. An ASCII box is
    used so the table renders on any console encoding.
    """
    if not fields:
        return "(no fields found)"
    from rich import box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=box.ASCII, header_style="bold", pad_edge=False)
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("KIND", no_wrap=True)
    table.add_column("NAME", overflow="fold")
    table.add_column("VISUS (copy-paste)", overflow="fold", style="green")
    if full:
        table.add_column("CSS", overflow="fold")
        table.add_column("XPATH", overflow="fold")
    for f in fields:
        name = str(f.get("name") or f.get("label") or f.get("placeholder") or "")
        row = [
            str(f.get("index", "")),
            str(f.get("kind", "")),
            name,
            str(f.get("code", "")),
        ]
        if full:
            row.extend([str(f.get("css", "")), str(f.get("xpath", ""))])
        table.add_row(*row)
    # Console() auto-detects the real terminal width (wide tables use the full
    # screen) and colour (TTY only); capture() preserves both. On a narrow pipe
    # rich folds long cells. `width` lets tests pin a deterministic size.
    console = Console(width=width) if width else Console()
    with console.capture() as cap:
        console.print(table)
    return cap.get().rstrip("\n")
```

In `src/visus/web/cli/main.py`, replace `_format_fields` (`:216-219`):

```python
def _format_fields(fields: list[dict[str, Any]], *, full: bool = False) -> str:
    from visus.web.cli.console import format_fields

    return format_fields(fields, full=full)
```

and add the flag plus its use to `list_fields`:

```python
    full: bool = typer.Option(
        False, "--full", help="Also print the CSS and XPATH columns."
    ),
```

```python
    output.emit(fields, table=_format_fields(fields, full=full))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "format_fields or list_fields" -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/visus/web/cli/console.py src/visus/web/cli/main.py tests/test_cli_session.py
git commit -m "fix(cli): stop list-fields from emitting a rule and two columns per field"
```

---

### Task 12: `list-fields` no longer mutates the page by default

Resolves row 25's divergence: `main.py:289`/`:295` pass `highlight: not no_highlight` (on) while `mcp/server.py:87-90` passes `highlight=False`.

**Decision: the CLI adopts the MCP's default — off.** The overlay appends `data-visus-field` divs to `body` (`bundle.js:800-825`), which corrupts every artifact an agent produces next: `session-screenshot`, `read-text` (OCR) and `find-image` (template matching) all read those pixels. Beyond that, a *read* command silently mutating the DOM breaks the read/write split the rest of the CLI keeps, and the numbered boxes only pay for themselves in two deliberate situations — a human watching a headed browser, or a vision model reading the numbers — both of which are worth one explicit flag. `--no-highlight` keeps working (it now names the default); `--highlight` opts in.

**Files:**
- Modify: `src/visus/web/cli/main.py` (`list_fields` at `:284-301`)
- Test: `tests/test_cli_session.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_session.py`:

```python
def test_cli_list_fields_does_not_draw_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """A read must not mutate the DOM: the overlay pollutes screenshots/OCR."""
    captured: dict[str, Any] = {}

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args or {}
        return {"fields": []}

    _patch_client(monkeypatch, fake)
    assert runner.invoke(app, ["list-fields"]).exit_code == 0
    assert captured["args"]["highlight"] is False


def test_cli_list_fields_highlight_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args or {}
        return {"fields": []}

    _patch_client(monkeypatch, fake)
    assert runner.invoke(app, ["list-fields", "--highlight"]).exit_code == 0
    assert captured["args"]["highlight"] is True


def test_cli_list_fields_no_highlight_still_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args or {}
        return {"fields": []}

    _patch_client(monkeypatch, fake)
    assert runner.invoke(app, ["list-fields", "--no-highlight"]).exit_code == 0
    assert captured["args"]["highlight"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_session.py -k "list_fields_does_not_draw or highlight_is_opt_in" -v --no-cov`
Expected: FAIL — `assert True is False` on `captured["args"]["highlight"]`, because `main.py:295` sends `highlight: not no_highlight` = `True`.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/main.py`, replace the `no_highlight` option in `list_fields` with a paired flag and update the payload:

```python
    highlight: bool = typer.Option(
        False,
        "--highlight/--no-highlight",
        help="Draw the numbered overlay on the page (off by default: it injects "
        "divs that would show up in a later screenshot / OCR / template match).",
    ),
```

```python
    result = _send(
        "list_fields",
        {"kinds": kinds, "include_hidden": show_all, "highlight": highlight},
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "list_fields" -v --no-cov`
Expected: PASS (the pre-existing `test_cli_list_fields_blocks_and_no_highlight`, which asserts `highlight is False` after `--no-highlight`, still passes unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/visus/web/cli/main.py tests/test_cli_session.py
git commit -m "fix(cli): make the list-fields overlay opt-in, matching the MCP default"
```

---

### Task 13: `--exact` and `--frame` reach the daemon

`session_server.py:213-221` already passes `exact=bool(args.get("exact", False))` and `frame=args.get("frame")` into `make_locator`, which resolves `page.frame_locator(frame)` at `:64`. The MCP exposes both on every action tool (`mcp/server.py:209-210`). `_target_args` (`main.py:222-235`) never emitted either, so from the shell an iframe was reachable only by `list-fields` index.

**Files:**
- Modify: `src/visus/web/cli/main.py` (`_target_args` at `:222-235`, plus every command that calls it)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces:
  ```python
  def _target_args(index, selector, role, name, text, *,
                   exact: bool = False, frame: str | None = None) -> dict[str, Any]: ...
  ```
  The two keys are added **only when non-default**, so the existing exact-equality assertions on the target dict (`tests/test_cli_session.py:1240-1245`, `:1430-1433`) keep passing.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_session.py`:

```python
def test_cli_target_flags_reach_the_daemon(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args or {}
        return "clicked"

    _patch_client(monkeypatch, fake)
    r = runner.invoke(
        app, ["click", "--role", "button", "--name", "Pay", "--exact", "--frame", "#checkout"]
    )
    assert r.exit_code == 0
    assert captured["args"]["exact"] is True
    assert captured["args"]["frame"] == "#checkout"


def test_cli_target_flags_are_absent_when_unused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defaults stay off the wire so the daemon payload does not grow."""
    captured: dict[str, Any] = {}

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args or {}
        return "3"

    _patch_client(monkeypatch, fake)
    assert runner.invoke(app, ["count", "--selector", ".item"]).exit_code == 0
    assert "exact" not in captured["args"] and "frame" not in captured["args"]


def test_cli_frame_flag_works_with_an_index_target(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args or {}
        return "ok"

    _patch_client(monkeypatch, fake)
    assert runner.invoke(app, ["get-text", "2", "--frame", "#f"]).exit_code == 0
    assert captured["args"] == {"index": 2, "frame": "#f"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_session.py -k "target_flags or frame_flag" -v --no-cov`
Expected: FAIL — exit code 2, `No such option: --exact`

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/main.py`, replace `_target_args` (`:222-235`):

```python
def _target_args(
    index: int | None,
    selector: str | None,
    role: str | None,
    name: str | None,
    text: str | None,
    *,
    exact: bool = False,
    frame: str | None = None,
) -> dict[str, Any]:
    """Build the {index|selector|role|name|text} target dict for an action op.

    ``exact`` and ``frame`` are only sent when set: the daemon reads them at
    ``session_server.py:213-221`` and the defaults would otherwise pad every
    payload.
    """
    if index is not None:
        args: dict[str, Any] = {"index": index}
    elif not (selector or role or text):
        output.emit_error(
            "error: no target. Use one of:\n"
            "  visus <cmd> <INDEX>              a number from `visus list-fields`\n"
            "  visus <cmd> --selector '#id'     a CSS or XPath selector\n"
            "  visus <cmd> --role button        an ARIA role (--name refines it)\n"
            "  visus <cmd> --text 'Sign in'     the element's visible text\n"
            "--name alone is NOT a target; it only qualifies --role.\n"
            "Run `visus list-fields` to see what is on the page."
        )
    else:
        args = {"selector": selector, "role": role, "name": name, "target_text": text}
    if exact:
        args["exact"] = True
    if frame is not None:
        args["frame"] = frame
    return args
```

Add the two shared option singletons next to `_UPLOAD_PATHS_ARG` (`main.py:653`) — the same module-level pattern, for the same B008 reason:

```python
# Module-level singletons (B008: a typer.Option() call cannot be an inline
# default when it is shared across commands; reading it from a module variable
# is the fix — same pattern as _UPLOAD_PATHS_ARG).
_EXACT_OPT = typer.Option(False, "--exact", help="Match --role/--text exactly, not by substring.")
_FRAME_OPT = typer.Option(
    None, "--frame", help="CSS selector of the iframe holding the target."
)
```

Add these two parameters to every command that calls `_target_args`, and pass them through. The commands are: `click`, `fill`, `check`, `uncheck`, `select`, `press`, `get_text`, `session_screenshot`, `get_attribute`, `count`, `hover`, `dblclick`, `focus`, `clear_input`, `drag`, `upload`, `wait`, `expect_text`, `read_text`, `solve_captcha`. For each, add

```python
    exact: bool = _EXACT_OPT,
    frame: str = _FRAME_OPT,
```

as the last two parameters, and change the call to

```python
    _target_args(index, selector, role, name, text, exact=exact, frame=frame)
```

(for `check` / `uncheck`, whose fifth argument is `None`; for `fill` / `select` / `press` / `expect_text`, whose fifth argument is `by_text`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "target_flags or frame_flag" -v --no-cov`
Expected: PASS (3 passed)

- [ ] **Step 5: Prove it reaches a real iframe**

Append to `tests/test_cli_agent_loop.py`:

```python
@pytest.mark.browser
def test_frame_flag_targets_an_element_inside_an_iframe(
    base_url: str, tmp_path: Path
) -> None:
    session_client.start_daemon(
        "chrome", headless=True, url=f"{base_url}/frames.html", cwd=tmp_path
    )
    try:
        env = session_client.send_envelope(
            "count", {"selector": "body", "frame": "iframe"}, start_dir=tmp_path
        )
        assert env["ok"] is True and env["result"] >= 1
    finally:
        session_client.stop(start_dir=tmp_path)
```

Run: `uv run pytest tests/test_cli_agent_loop.py::test_frame_flag_targets_an_element_inside_an_iframe -v --no-cov`
Expected: PASS

- [ ] **Step 6: Run the whole session suite**

Run: `uv run pytest tests/test_cli_session.py -q --no-cov`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/visus/web/cli/main.py tests/test_cli_session.py tests/test_cli_agent_loop.py
git commit -m "feat(cli): expose --exact and --frame on every targeted command"
```

---

### Task 14: The no-target error names the valid forms

`main.py:232-234` today prints `error: provide an index, or --selector / --role / --text` and exits 1 — it never says that `--name` alone is not a target (it only qualifies `--role`), and it never points at `list-fields`. Task 13 already replaced the message; this task locks the behaviour down with its own test so a future edit cannot quietly shrink it back.

**Files:**
- Modify: `src/visus/web/cli/main.py` (`_target_args`, already rewritten in Task 13)
- Test: `tests/test_cli_agent_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_agent_loop.py`:

```python
_NO_TARGET_SCRIPT = (
    "import sys; from visus.web.cli.main import app; "
    "sys.argv = ['visus', 'click', '--name', 'Sign in']; app()"
)


def test_no_target_error_names_every_valid_form(tmp_path: Path) -> None:
    """--name alone is not a target (main.py's guard checks selector/role/text)."""
    proc = subprocess.run(
        [sys.executable, "-c", _NO_TARGET_SCRIPT],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 1
    assert proc.stdout.strip() == ""
    for fragment in (
        "<INDEX>",
        "--selector",
        "--role",
        "--text",
        "--name alone is NOT a target",
        "visus list-fields",
    ):
        assert fragment in proc.stderr, f"missing {fragment!r} from the guidance"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_agent_loop.py::test_no_target_error_names_every_valid_form -v --no-cov`
Expected: PASS if Task 13 landed; FAIL with `AssertionError: missing '--name alone is NOT a target'` if the guard message is still the one-liner from `main.py:233`.

- [ ] **Step 3: Write minimal implementation**

If the test failed, apply the `_target_args` replacement exactly as written in Task 13, Step 3.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_agent_loop.py::test_no_target_error_names_every_valid_form -v --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/visus/web/cli/main.py tests/test_cli_agent_loop.py
git commit -m "test(cli): lock the no-target error to name every valid targeting form"
```

---

### Task 15: `--output-dir` controls where artifacts land

`main.py:424`/`:442` hardcode `screenshot.png` relative to the client cwd, and `rpa()`'s `outdir` concept (`rpa.py:56`) is unreachable from the CLI. The global flag from Task 2 already exists; this task wires the client-side writers to it.

**Files:**
- Modify: `src/visus/web/cli/main.py` (`screenshot` at `:117-130`, `pdf` at `:133-144`, `session_screenshot` at `:422-446`, `codegen` at `:170-194`)
- Test: `tests/test_cli_agent_loop.py`

**Interfaces:**
- Consumes: `output.resolve_out` (Task 1).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_agent_loop.py`:

```python
def test_output_dir_redirects_the_session_screenshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args or {}
        return (args or {}).get("path", "")

    monkeypatch.setattr(session_client, "send", fake)
    shots = tmp_path / "shots"
    shots.mkdir()
    r = runner.invoke(app, ["--output-dir", str(shots), "session-screenshot"])
    assert r.exit_code == 0
    assert captured["args"]["path"] == str((shots / "screenshot.png").resolve())


def test_output_dir_is_ignored_for_an_absolute_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["args"] = args or {}
        return (args or {}).get("path", "")

    monkeypatch.setattr(session_client, "send", fake)
    explicit = str((tmp_path / "here.png").resolve())
    r = runner.invoke(
        app, ["--output-dir", str(tmp_path / "elsewhere"), "session-screenshot", "-o", explicit]
    )
    assert r.exit_code == 0
    assert captured["args"]["path"] == explicit
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_agent_loop.py -k "output_dir" -v --no-cov`
Expected: FAIL — `test_output_dir_redirects_the_session_screenshot` fails because `main.py:442` uses `str(Path(output).resolve())`, producing a path under the test's cwd rather than under `shots/`.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/main.py`, make every client-side artifact path go through `output.resolve_out`. `session_screenshot` (its option was renamed to `input_path` in Task 3):

```python
    # Resolve the path against the CLIENT's cwd (or --output-dir), not the
    # daemon's, so the PNG lands where the user invoked the command.
    abs_output = output.resolve_out(input_path)
```

`screenshot`:

```python
@app.command()
def screenshot(
    url: str,
    input_path: str = typer.Option("screenshot.png", "-o", "--output"),
    full_page: bool = False,
    headless: bool = True,
    engine: str = "chrome",
) -> None:
    """Screenshot a URL to a PNG file."""
    dest = output.resolve_out(input_path)
    with launch(Engine.from_str(engine), headless=headless) as b:
        p = b.new_page()
        p.goto(url)
        p.screenshot(path=dest, full_page=full_page)
    output.emit(dest, table=f"saved {dest}")
```

`pdf`:

```python
@app.command()
def pdf(
    url: str,
    input_path: str = typer.Option("page.pdf", "-o", "--output"),
    engine: str = "chrome",
) -> None:
    """Print a URL to a PDF (Chromium)."""
    dest = output.resolve_out(input_path)
    with launch(Engine.from_str(engine), headless=True) as b:
        p = b.new_page()
        p.goto(url)
        p.pdf(path=dest)
    output.emit(dest, table=f"saved {dest}")
```

`codegen`'s write branch:

```python
    if input_path:
        dest = Path(output.resolve_out(input_path))
        dest.write_text(code, encoding="utf-8")
        output.emit(code, table=f"saved {dest}")
    else:
        output.emit(code, table=code)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_agent_loop.py -k "output_dir" -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the CLI suites**

Run: `uv run pytest tests/test_cli.py tests/test_cli_session.py -q --no-cov`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/main.py tests/test_cli_agent_loop.py
git commit -m "feat(cli): honour --output-dir for screenshots, PDFs and generated code"
```

---

### Task 16: The REPL twin

The REPL dispatches 32 of the 41 ops (`console.py:119-210`) and carries its own help text (`console.py:19-53`). Every output change above has a twin here, and `console.py:187` still resolves a screenshot path against the *daemon's* cwd while the non-interactive command (`main.py:440-442`) has the fix and the comment explaining it.

**Files:**
- Modify: `src/visus/web/cli/console.py` (`_HELP` at `:19-53`, `dispatch` at `:96-215`, `run_console` at `:218-249`)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces:
  ```python
  SendEnvFn = Callable[[str, dict[str, Any]], dict[str, Any]]
  def dispatch(line: str, send: SendFn, send_env: SendEnvFn | None = None) -> str: ...
  ```
  `send_env` is optional so the ~30 existing `dispatch(line, fake_send)` tests keep passing unchanged; `run_console` always supplies it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_session.py`:

```python
def test_repl_click_shows_page_and_code_when_an_envelope_sender_is_given() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        raise AssertionError("mutating REPL commands must use the envelope sender")

    def send_env(op: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "result": "clicked",
            "code": 'page.locator("#go").click()',
            "page": {"url": "http://x/next", "title": "Next", "fields_stale": False},
        }

    out = console.dispatch("click 3", send, send_env)
    assert out.splitlines() == [
        "clicked",
        "",
        "### Code",
        'page.locator("#go").click()',
        "",
        "### Page",
        "- URL: http://x/next",
        "- Title: Next",
    ]


def test_repl_without_an_envelope_sender_prints_the_bare_result() -> None:
    out = console.dispatch("click 3", lambda op, args: "clicked")
    assert out == "clicked"


def test_repl_read_command_is_unchanged_by_the_envelope_sender() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        assert op == "get_text"
        return "hello"

    def send_env(op: str, args: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("reads must not go through the envelope sender")

    assert console.dispatch("text 3", send, send_env) == "hello"


def test_repl_snapshot_shows_refs() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        return {
            "elements": [
                {"ref": 4, "role": "button", "name": "Go", "depth": 0},
                {"ref": None, "role": "heading", "name": "Title", "depth": 0},
            ],
            "url": "u",
            "title": "t",
        }

    out = console.dispatch("snapshot", send)
    assert out.splitlines() == ["   4  button           Go", "   -  heading          Title"]


def test_repl_find_renders_matches() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        assert args == {"query": "cart", "regex": False, "context": 3,
                        "selector": None, "depth": None}
        return {
            "query": "cart",
            "regex": False,
            "total": 9,
            "matched": 1,
            "rows": [{"line": 2, "role": "button", "name": "Add to cart", "ref": 1,
                      "match": True}],
        }

    out = console.dispatch("find cart", send)
    assert "1 of 9 rows match 'cart'" in out
    assert "Add to cart" in out


def test_repl_screenshot_path_resolves_against_the_client_cwd(tmp_path: Path) -> None:
    """console.py:187 sent a raw string, so the PNG landed in the DAEMON's cwd."""
    captured: dict[str, Any] = {}

    def send(op: str, args: dict[str, Any]) -> Any:
        captured["args"] = args
        return args["path"]

    console.dispatch("screenshot shot.png", send)
    assert Path(captured["args"]["path"]).is_absolute()
    assert Path(captured["args"]["path"]).name == "shot.png"


def test_repl_help_lists_the_new_commands() -> None:
    out = console.dispatch("help", lambda op, args: None)
    assert "find " in out
    assert "export-script" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "repl_" -v --no-cov`
Expected: FAIL — `test_repl_click_shows_page_and_code_when_an_envelope_sender_is_given` fails with `TypeError: dispatch() takes 2 positional arguments but 3 were given`.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/console.py`, add the type alias next to `SendFn` (after line 17):

```python
# An envelope send callable: (op, args) -> the daemon's full reply dict.
SendEnvFn = Callable[[str, dict[str, Any]], dict[str, Any]]

# REPL commands that change the page — they print the ### Code / ### Page footer.
_MUTATING_REPL_OPS: frozenset[str] = frozenset(
    {
        "click", "fill", "check", "uncheck", "select", "press", "hover",
        "dblclick", "focus", "clear_input", "goto", "back", "forward", "reload",
        "dialog", "tab", "tab_new", "tab_close", "eval",
    }
)
```

Replace `_HELP` (`:19-53`) with the version that documents the new commands:

```python
_HELP = """commands:
  list [full]          enumerate interactive fields (`full` adds CSS/XPATH)
  click N              click field N (or a previous list index)
  fill N text          fill field N with text
  check N              check field N
  uncheck N            uncheck field N
  select N value       select option `value` on field N
  press N key          press key on field N
  hover N              hover over field N
  dblclick N           double-click field N
  focus N              focus field N
  clear-input N        clear field N's value
  goto url             navigate to url
  back                 navigate back in history
  forward              navigate forward in history
  reload               reload the current page
  title                print the page title
  url                  print the current URL
  snapshot [sel]       list interactive elements (REF/role/name), optionally scoped
  find text            grep the snapshot, with 3 rows of context around each hit
  text N               print field N's text content
  attr name N          print field N's `name` attribute
  count N              count elements matching field N
  wait N [state]       wait until field N is visible/hidden
  expect N text...     assert field N contains text (PASSED/FAILED)
  cookies              list cookies for the context
  eval expr            evaluate a JS expression
  dialog [dismiss]     handle the next dialog (accept by default)
  screenshot [path]    save a screenshot (default screenshot.png)
  export-script [path] print (or save) this session as a runnable visus.web script
  clear                remove the field highlight overlay
  highlight            redraw the numbered field overlay
  tabs                 list open tabs/windows (active marked *)
  tab N                switch to tab/window N (omit N = newest)
  tab-new [url]        open a new tab (optionally at url)
  tab-close [N]        close tab N (omit N = active)
  help                 show this help
  quit                 exit the console (the session stays alive)"""
```

Add the footer renderer above `dispatch`:

```python
def _footer(env: dict[str, Any]) -> str:
    """The ### Code / ### Page sections for one envelope, ready to append.

    Returns "" when the envelope carries neither, otherwise a string that STARTS
    with a newline so ``result + _footer(env)`` leaves a blank line between the
    value and the first section — the same shape ``output.emit_envelope`` prints.
    """
    parts: list[str] = []
    code = env.get("code")
    if code:
        parts.extend(["", "### Code", str(code)])
    page = env.get("page") or {}
    if page:
        parts.extend(["", "### Page", f"- URL: {page.get('url', '')}",
                      f"- Title: {page.get('title', '')}"])
        snap = env.get("snapshot")
        if snap:
            parts.append(f"- Snapshot: {snap}")
        if page.get("fields_stale"):
            parts.append("- Fields: stale — run `list` again before using an index")
    if not parts:
        return ""
    return "\n" + "\n".join(parts)
```

Change `dispatch`'s signature and add the envelope path at the top of its `try` block:

```python
def dispatch(line: str, send: SendFn, send_env: SendEnvFn | None = None) -> str:
    """Parse one REPL line, run it via *send*, and return printable output.

    Pure aside from the injected callables — the unit of testing. ``send_env``
    returns the full daemon envelope so a mutating command can print the same
    ``### Code`` / ``### Page`` footer the non-interactive CLI prints; when it is
    omitted the REPL falls back to the bare result.
    """
    line = line.strip()
    if not line:
        return ""
    parts = line.split()
    cmd = parts[0].lower()
    rest = parts[1:]

    def _idx(token: str) -> dict[str, Any]:
        return {"index": int(token)}

    def _act(
        op: str, args: dict[str, Any], fmt: Callable[[Any], str] = str
    ) -> str:
        """Run a mutating op: render its result with *fmt*, then the ### footer.

        *fmt* keeps each command's existing human sentence ("navigated to …")
        while the footer is added uniformly — exactly how ``emit_envelope(env,
        table=…)`` works on the non-interactive side.
        """
        if send_env is None:
            return fmt(send(op, args))
        env = send_env(op, args)
        return fmt(env.get("result")) + _footer(env)
```

Then rewrite the mutating branches to go through `_act`, and add the new commands. Each block below **replaces** the branch of the same `cmd` in the current `dispatch` (`console.py:116-210`); the `find`, `export-script` and `highlight` blocks are new and go just before the closing `return f"unknown command {cmd!r} (try \`help\`)"`. The changed / added branches:

```python
        if cmd in ("list", "ls"):
            want_full = bool(rest and rest[0].lower() == "full")
            result = send("list_fields", {"highlight": False})
            return format_fields(result.get("fields", []), full=want_full)
        if cmd == "click":
            return _act("click", _idx(rest[0]))
        if cmd == "fill":
            return _act("fill", {**_idx(rest[0]), "text": " ".join(rest[1:])})
        if cmd == "check":
            return _act("check", _idx(rest[0]))
        if cmd == "uncheck":
            return _act("uncheck", _idx(rest[0]))
        if cmd == "select":
            return _act("select", {**_idx(rest[0]), "value": " ".join(rest[1:])})
        if cmd == "press":
            return _act("press", {**_idx(rest[0]), "key": " ".join(rest[1:])})
        if cmd == "hover":
            return _act("hover", _idx(rest[0]))
        if cmd == "dblclick":
            return _act("dblclick", _idx(rest[0]))
        if cmd == "focus":
            return _act("focus", _idx(rest[0]))
        if cmd == "clear-input":
            return _act("clear_input", _idx(rest[0]))
        if cmd == "goto":
            return _act("goto", {"url": rest[0]}, lambda r: f"navigated to {r}")
        if cmd == "back":
            return _act("back", {}, lambda r: f"went back to {r}")
        if cmd == "forward":
            return _act("forward", {}, lambda r: f"went forward to {r}")
        if cmd == "reload":
            return _act("reload", {}, lambda r: f"reloaded {r}")
        if cmd == "eval":
            return _act(
                "eval",
                {"expression": " ".join(rest)},
                lambda r: str((r or {}).get("result")),
            )
```

```python
        if cmd == "snapshot":
            snap_args: dict[str, Any] = {
                "selector": rest[0] if rest else None,
                "depth": None,
                "refs": True,
            }
            elements = send("snapshot", snap_args).get("elements", [])
            if not elements:
                return "(no elements)"
            return "\n".join(
                f"{('-' if e.get('ref') is None else str(e['ref'])):>4}  "
                f"{str(e.get('role', '')):<16} {e.get('name', '')}"
                for e in elements
            )
        if cmd == "find":
            result = send(
                "find",
                {
                    "query": " ".join(rest),
                    "regex": False,
                    "context": 3,
                    "selector": None,
                    "depth": None,
                },
            )
            rows = result.get("rows", [])
            if not rows:
                return f"no match for {result.get('query', '')!r} in {result.get('total', 0)} rows"
            lines = [
                f"{result.get('matched', 0)} of {result.get('total', 0)} rows "
                f"match {result.get('query', '')!r}"
            ]
            for r in rows:
                ref = "-" if r.get("ref") is None else str(r["ref"])
                lines.append(
                    f"{'>' if r.get('match') else ' '} {ref:>4}  "
                    f"{str(r.get('role', '')):<12} {r.get('name', '')}"
                )
            return "\n".join(lines)
```

```python
        if cmd == "screenshot":
            # Resolve against the CLIENT's cwd (not the daemon's) so the PNG lands
            # where the user is — same fix as main.py's session-screenshot.
            shot_args: dict[str, Any] = (
                {"path": str(Path(rest[0]).resolve())} if rest else {}
            )
            return f"saved {send('screenshot', shot_args)}"
        if cmd == "export-script":
            result = send("export_script", {})
            code = str(result.get("script", ""))
            if rest:
                dest = Path(rest[0]).resolve()
                dest.write_text(code, encoding="utf-8")
                return f"saved {dest} ({result.get('lines', 0)} action(s))"
            return code
        if cmd == "highlight":
            send("list_fields", {"highlight": True})
            return "overlay drawn"
```

```python
        if cmd == "dialog":
            accept = not (rest and rest[0].lower() in ("dismiss", "cancel", "no"))
            return _act("dialog", {"accept": accept, "prompt_text": None})
```

```python
        def _tab_line(r: Any) -> str:
            return f"switched to tab {r['active']}: {str(r.get('title', ''))!r}"

        def _tab_new_line(r: Any) -> str:
            return f"opened tab {r['index']}: {str(r.get('title', ''))!r}"

        def _tab_close_line(r: Any) -> str:
            if r.get("remaining", 0) == 0:
                return "closed the last tab — session stopped"
            return f"closed tab {r['closed']} ({r['remaining']} remaining)"

        if cmd == "tab":
            return _act("tab", {"index": int(rest[0]) if rest else None}, _tab_line)
        if cmd == "tab-new":
            return _act("tab_new", {"url": rest[0] if rest else None}, _tab_new_line)
        if cmd == "tab-close":
            return _act(
                "tab_close", {"index": int(rest[0]) if rest else None}, _tab_close_line
            )
```

The three `_tab_*_line` helpers are defined inside `dispatch`, next to `_idx` and `_act`, so they are in scope for the branches above.

Add `from pathlib import Path` to the imports at the top of `console.py`.

Finally, wire the envelope sender in `run_console` (`:235-245`):

```python
    def _send(op: str, args: dict[str, Any]) -> Any:
        return session_client.send(op, args, start_dir=start_dir)

    def _send_env(op: str, args: dict[str, Any]) -> dict[str, Any]:
        return session_client.send_envelope(op, args, start_dir=start_dir)

    output_fn("visus console — type `help` for commands, `quit` to exit.")
    while True:
        try:
            line = input_fn("visus> ")
        except (EOFError, KeyboardInterrupt):
            output_fn("")
            break
        out = dispatch(line, _send, _send_env)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "repl_ or dispatch" -v --no-cov`
Expected: PASS

- [ ] **Step 5: Prove the existing sentences survived the refactor**

The `fmt` callback exists precisely so `dispatch("goto …")` keeps saying `navigated to …` while gaining the footer. Append to `tests/test_cli_session.py`:

```python
def test_repl_goto_keeps_its_sentence_and_gains_the_footer() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        raise AssertionError("goto is mutating: it must use the envelope sender")

    def send_env(op: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": True,
            "result": "http://dest",
            "page": {"url": "http://dest", "title": "Dest", "fields_stale": False},
        }

    out = console.dispatch("goto http://dest", send, send_env)
    assert out.startswith("navigated to http://dest")
    assert "### Page" in out and "- Title: Dest" in out


def test_repl_tab_commands_keep_their_sentences() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        if op == "tab":
            return {"active": 0, "title": "A"}
        if op == "tab_new":
            return {"index": 1, "title": "B"}
        return {"closed": 1, "remaining": 1, "active": 0}

    assert "switched to tab 0" in console.dispatch("tab 0", send)
    assert "opened tab 1" in console.dispatch("tab-new http://x", send)
    assert "closed tab 1" in console.dispatch("tab-close 1", send)
```

- [ ] **Step 6: Run the whole session suite**

Run: `uv run pytest tests/test_cli_session.py -q --no-cov`
Expected: PASS — every pre-existing REPL assertion (`"navigated to http://dest"` at `tests/test_cli_session.py:633`, `"switched to tab 0"` at `:1941`, `"went back to …"` at `:1976-1978`, `"opened tab 1"` / `"closed tab 1"` at `:2021-2022`, `"RES"` from `eval` at `:2011`) still holds, because `_act`'s `fmt` reproduces each sentence verbatim.

- [ ] **Step 7: Commit**

```bash
git add src/visus/web/cli/console.py tests/test_cli_session.py
git commit -m "feat(cli): give the REPL the same page/code footer, find, refs and path fix"
```

---

### Task 17: The MCP action tools echo page state

`mcp/server.py:215` returns the bare string `"clicked"` — the same C1 defect, on the surface the skill actually documents today.

**Files:**
- Modify: `src/visus/web/mcp/server.py` (`browser_click` at `:203-217`, `browser_dblclick` at `:220-234`, `browser_fill` at `:237-252`, `browser_press` at `:255-270`, `browser_hover`, `browser_check`, `browser_uncheck`, `browser_select_option`, `browser_drag`, `browser_focus`, `browser_clear`, `browser_set_input_files`)
- Test: `tests/test_e2e_mcp.py`

**Interfaces:**
- Produces: `_acted(message: str) -> str` — a private helper, **not** an `@mcp.tool()`, so the 45-name inventory assertion at `tests/test_mcp_server.py:27-84` is unaffected.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_e2e_mcp.py`:

```python
@pytest.mark.browser
def test_click_result_reports_the_resulting_page(srv):  # type: ignore[no-untyped-def]
    """The MCP loop must close too: after an action, say what the page became."""
    server, base_url = srv
    server.browser_navigate(f"{base_url}/links.html")
    result = server.browser_click(text="Go to page two")
    assert result.startswith("clicked")
    assert "### Page" in result
    assert "/page2.html" in result
    assert "page two" in result


@pytest.mark.browser
def test_fill_result_reports_the_page(srv):  # type: ignore[no-untyped-def]
    server, base_url = srv
    server.browser_navigate(f"{base_url}/forms.html")
    result = server.browser_fill("ada99", role="textbox", name="Username")
    assert result.startswith("filled with 'ada99'")
    assert "- Title: forms fixture" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_e2e_mcp.py -k "reports_the" -v --no-cov`
Expected: FAIL — `AssertionError: '### Page' not in 'clicked'`

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/mcp/server.py`, add the helper directly below `_any_match_visible` (after line 33):

```python
def _acted(message: str) -> str:
    """An action's result plus the page state the agent needs for its next step.

    Without this an agent is blind after every action and must spend a whole extra
    tool call on browser_url/browser_title, or act on a stale mental model.
    """
    try:
        page = _session.page()
        return f"{message}\n\n### Page\n- URL: {page.url}\n- Title: {page.title()}"
    except Exception:  # noqa: BLE001 — page state is telemetry, never the result
        return message
```

Then wrap the return value of every action tool. `browser_click` becomes:

```python
    """Click an element targeted by role+name, text, or css/xpath selector."""
    page = _session.page()
    make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    ).click()
    return _acted("clicked")
```

Apply the identical wrap to the remaining action tools, changing only the final `return`:

| Tool | New return |
|---|---|
| `browser_dblclick` | `return _acted("double-clicked")` |
| `browser_fill` | `return _acted(f"filled with {text_value!r}")` |
| `browser_press` | `return _acted(f"pressed {key!r}")` |
| `browser_hover` | `return _acted("hovered")` |
| `browser_check` | `return _acted("checked")` |
| `browser_uncheck` | `return _acted("unchecked")` |
| `browser_select_option` | `return _acted(f"selected {value!r}")` |
| `browser_drag` | `return _acted(<its current message>)` |
| `browser_focus` | `return _acted("focused")` |
| `browser_clear` | `return _acted("cleared")` |
| `browser_set_input_files` | `return _acted(<its current message>)` |

For `browser_drag` and `browser_set_input_files`, wrap whatever message the function returns today rather than inventing a new one — open the file and reuse the exact f-string already there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_e2e_mcp.py -k "reports_the" -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 5: Verify the tool inventory is unchanged**

Run: `uv run pytest tests/test_mcp_server.py -q --no-cov`
Expected: PASS — `_acted` is not decorated, so the 45-name equality assertion still holds.

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/mcp/server.py tests/test_e2e_mcp.py
git commit -m "feat(mcp): report the resulting page after every action tool"
```

---

### Task 18: Full-suite verification and gate pass

**Files:**
- Test: the whole suite

- [ ] **Step 1: Run ruff**

Run: `uv run ruff check src tests`
Expected: `All checks passed!`

- [ ] **Step 2: Run mypy**

Run: `uv run mypy`
Expected: `Success: no issues found in N source files`

- [ ] **Step 3: Run the non-browser suite**

Run: `uv run pytest -q -m "not browser" --no-cov`
Expected: PASS, 0 failures

- [ ] **Step 4: Run the browser suite**

Run: `uv run pytest -q -m browser --no-cov`
Expected: PASS, 0 failures

- [ ] **Step 5: Run the full suite with the coverage gate**

Run: `uv run pytest -q`
Expected: PASS with `Required test coverage of 90% reached`

- [ ] **Step 6: Drive the loop by hand once, end to end**

Run, from a scratch directory:

```bash
visus session start --headless https://example.com
visus list-fields
visus snapshot --depth 1
visus find "More information"
visus click --text "More information"
visus session export-script -o flow.py
visus session stop
```

Expected: `visus click` prints `clicked`, then a `### Code` block containing a `page.…click()` line, then a `### Page` block whose `- URL:` is `https://www.iana.org/help/example-domains`; `flow.py` contains `page.goto('https://example.com')` followed by that same click line.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore(cli): verify the agent-driving loop against the full gate"
```
