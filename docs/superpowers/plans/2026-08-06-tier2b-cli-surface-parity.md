# Tier 2b — CLI Surface Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose, as `visus` CLI commands and REPL commands, the ~20 capabilities the `visus.web` library already implements but the shell cannot reach.

**Architecture:** Every session command in this repo is a three-part mirror: a `@app.command()` in `src/visus/web/cli/main.py` that calls `_send(op, args)`, a matching `_op_<op>` method on `SessionHandler` in `src/visus/web/cli/session_server.py` (dispatched by `getattr(self, f"_op_{op}")`), and a dispatch branch plus a help line in `src/visus/web/cli/console.py` (the REPL). A fifth place, the command tables in `README.md`, documents it. Almost every task here adds all five and nothing else — the browser work already exists in `api/`, `backends/` and `network.py`. Three tasks deliberately reach one layer deeper: Task 9 adds a `button` parameter to the mouse device (Selenium's `pointer_down` has always taken one), Task 11 surfaces the bounding rect the JS bundle already computes, and Task 17 adds a non-context-manager tracing session so `_steps.run_step` can actually see a Recorder.

**Tech Stack:** Python 3.10+, Typer, Rich, Selenium 4.38, pytest + pytest-xdist, hatchling, mypy --strict, ruff

## Global Constraints

- Gates before every commit: `uv run ruff check src tests`, `uv run mypy` (strict), `uv run pytest -q` (≥90% coverage).
- **THE HIDDEN-ENGINE RULE (inviolable):** no `selenium.*` type may appear in any public signature/return/exception/docstring. Selenium imports allowed ONLY in `backends/browsers/*.py`, `backends/selenium/*.py`, `backends/selenium_backend.py`.
- Test convention: **real browser, no fakes**, `@pytest.mark.browser`, fixtures in `tests/fixtures/*.html` served by the session-scoped `base_url` fixture. Test doubles isolate a unit ONLY when its real behaviour is also covered by an integration test. No `skip`/`xfail`/mock-to-pass.
- Ruff: line-length 100, select `["E","F","I","UP","B"]`.
- mypy: `strict = true`, python_version 3.10.
- Commits: small, TDD (failing test → minimal impl → green → commit), semantic messages `label(scope): description`. Labels: `fix`, `feat`, `chore`, `docs`, `test`, `devops`.
- **Never** add `Co-Authored-By` lines to commits.
- Single-test runs use `--no-cov` (the repo pins `--cov-fail-under=90` in `addopts`; the gate only makes sense on a full run).
- `visus.web` version is `0.2.0` (`src/visus/web/__init__.py:17`). Do not bump it in this plan.

## Prerequisites

**PLAN 4 (`2026-08-06-tier2c-agent-driving-loop.md`) MUST land before this plan.** This plan consumes these symbols from it and never redefines them:

```python
# src/visus/web/cli/output.py  — owned by PLAN 4
class Mode(str, Enum):
    TEXT = "text"      # default: human/agent readable, includes ### Page footer
    JSON = "json"      # one JSON object per invocation, no decoration
    RAW  = "raw"       # bare value only; no ### Page, no ### Code, no table

def set_mode(*, as_json: bool = False, raw: bool = False) -> None: ...
def mode() -> Mode: ...
def emit(value: Any, *, table: str | None = None) -> None: ...
def emit_error(message: str, *, code: int = 1) -> NoReturn: ...
def emit_envelope(env: dict[str, Any], *, table: str | None = None) -> None: ...
```

Rules this plan follows so it never collides with PLAN 4:

1. **Every new command prints through `output.emit(...)` and fails through `output.emit_error(...)`.** No new `typer.echo` calls for command output (the two exceptions are Task 2's deprecation notice, which is a side-channel warning, and the pre-existing `typer.echo` lines this plan does not touch).
2. **`output.emit_envelope` is NOT called by this plan.** PLAN 4 owns the envelope and the `_MUTATING_OPS` frozenset in `session_server.py`. Where a task adds a *mutating* op, its implementation step appends the new op name to that existing frozenset — one string, nothing else.
3. **Where the brief specifies a per-command `--json`, this plan adds a local `--json` flag whose only job is `output.set_mode(as_json=True)`, guarded by `if as_json:`** so it can never clobber a globally-set mode. This is required because Click parses group-level options *before* the subcommand (`visus --json requests`), while agents and the existing 8 commands write `visus requests --json`.
4. **`--session` / `-S` is reserved** by the conventions contract for PLAN 6's named sessions. Task 14 therefore spells the sessionStorage switch `--session-storage`, not `--session`.

Symbols this plan consumes from the **existing** codebase (all verified present):

```python
# src/visus/web/cli/session_server.py
def make_locator(page, *, selector=None, role=None, name=None, text=None,
                 exact=False, frame=None) -> Locator: ...
class SessionHandler:
    def handle(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]: ...
    def page(self) -> Page: ...
    def context(self) -> Context: ...
    def close(self) -> None: ...
    def _resolve_field(self, index: int) -> Locator: ...
    @staticmethod
    def _has_target(args: dict[str, Any]) -> bool: ...
    def _target(self, args: dict[str, Any]) -> Locator: ...
    def _driver(self) -> Any: ...
    def _resolve_active(self, handles: list[str]) -> str: ...

# src/visus/web/cli/main.py
def _send(op: str, args: dict[str, Any] | None = None) -> Any: ...
def _target_args(index, selector, role, name, text) -> dict[str, Any]: ...

# src/visus/web/cli/console.py
def format_fields(fields: list[dict[str, Any]], *, width: int | None = None) -> str: ...
def dispatch(line: str, send: SendFn) -> str: ...
SendFn = Callable[[str, dict[str, Any]], Any]

# src/visus/web/api/page.py
Page.network_requests() -> list[NetworkResponse]
Page.console_messages() -> list[ConsoleMessage]
Page.evaluate(expression: str, arg: object = None) -> object
Page.pdf(*, path: str | None = None) -> bytes
Page.set_viewport_size(width: int, height: int) -> None
Page.set_device_metrics(width, height, *, device_scale_factor=1.0, mobile=False) -> None
Page.snapshot() -> list[dict]
Page.mouse -> Mouse        # api/input.py
Page.keyboard -> Keyboard  # api/input.py

# src/visus/web/api/context.py
Context.storage_state(*, path: str | None = None) -> dict
Context.restore_storage_state(state: dict | str) -> None
Context.cookies() -> list[dict]
Context.add_cookies(cookies: list[dict]) -> None
Context.clear_cookies() -> None

# src/visus/web/api/locator.py
Locator.evaluate(expression: str, arg: object = None) -> object
Locator.highlight() -> None
Locator.bounding_box() -> dict[str, float] | None
Locator.scroll_into_view_if_needed() -> None
Locator.first() -> Locator

# src/visus/web/api/events.py
NetworkResponse: .url .status .method .resource_type .ok .body()
ConsoleMessage:  .level .text

# src/visus/web/network.py
class NetworkCapture:
    def __init__(self, page: Any, use_cdp: bool = True) -> None: ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def get_requests(self, filter_type: list[str] | None = None) -> list[dict[str, Any]]: ...
    def export_enriched(self, path: str) -> None: ...

# src/visus/web/tracing.py
def enable(**opts: Any) -> None: ...
def is_enabled() -> bool: ...
def current_recorder() -> Recorder | None: ...
def render_report(zip_path: str, output: str = "report.html") -> str: ...

# src/visus/web/observability/recorder.py
class Recorder:
    run_id: str
    def write_zip(self, path: str) -> None: ...
    def close(self) -> None: ...

# src/visus/web/cli/session_client.py
def start_daemon(engine="chrome", headless=False, url=None, *, cwd=None, timeout=20.0) -> dict[str, Any]: ...
def send(op, args=None, *, start_dir=None) -> Any: ...
class SessionError(RuntimeError): ...
```

Symbols **this plan produces** that later plans may rely on:

```python
# src/visus/web/cli/console.py
def _target(tokens: list[str]) -> tuple[dict[str, Any], list[str]]: ...   # Task 1

# src/visus/web/tracing.py
def start_recording(**opts: Any) -> Recorder: ...                          # Task 17
def stop_recording(zip_path: str | None = None,
                   report: str | None = None) -> dict[str, str]: ...       # Task 17

# src/visus/web/network.py
NetworkCapture.rebind(self, page: Any) -> None                             # Task 18

# src/visus/web/api/fields.py
Field.box: dict[str, float] | None = None                                  # Task 11

# src/visus/web/api/input.py
Mouse.down(self, *, button: str = "left") -> None                          # Task 9
Mouse.up(self, *, button: str = "left") -> None                            # Task 9
Mouse.click(self, x: float, y: float, *, button: str = "left") -> None     # Task 9
Mouse.dblclick(self, x: float, y: float, *, button: str = "left") -> None  # Task 9
```

---

## File Structure

| File | Change | Single responsibility |
|---|---|---|
| `src/visus/web/cli/console.py` | Modify | REPL: target parsing (`_target`), dispatch branches, `_HELP` text |
| `src/visus/web/cli/main.py` | Modify | Typer commands: one per new capability, all rendering via `output.emit` |
| `src/visus/web/cli/session_server.py` | Modify | Daemon: new `_op_*` handlers + the session-start options they need |
| `src/visus/web/cli/session_client.py` | Modify | `start_daemon` forwards `user_data_dir` / `remote_url` / `slow_mo` |
| `src/visus/web/mcp/server.py` | Modify | `browser_evaluate` gains element scoping (the same gap as the CLI's `eval`) |
| `src/visus/web/tracing.py` | Modify | `start_recording` / `stop_recording` — a tracing session without a `with` block |
| `src/visus/web/network.py` | Modify | `NetworkCapture.rebind` so a long-lived daemon can survive navigation/tab switches |
| `src/visus/web/api/fields.py` | Modify | `Field.box` — the geometry the bundle already computes |
| `src/visus/web/api/input.py` | Modify | `Mouse` gains `button=` on down/up/click/dblclick |
| `src/visus/web/backends/base.py` | Modify | `PageDelegate` mouse protocol gains `button` |
| `src/visus/web/backends/selenium/driver_delegate.py` | Modify | Selenium mouse-button mapping; `Field.box` from the bundle's `rect` |
| `src/visus/web/backends/selenium/js/bundle.js` | Modify | `snapshot()` emits `rect` (it already does for `listFields`); `highlight()` takes a style |
| `src/visus/web/api/locator.py` | Modify | `Locator.highlight(*, style=None)` — the per-element box the CLI exposes |
| `src/visus/web/cli/codegen.py` | Modify | `locator_expr` — the copy-paste expression for a non-index target |
| `src/visus/web/async_api/__init__.py` | Modify | Async mirror of the two signature changes (`Mouse` button, `Locator.highlight` style) |
| `README.md` | Modify | Command tables + the corrected `VISUS_WEB_TRACING` row |
| `tests/fixtures/mouse.html` | Create | Context-menu / middle-click / wheel fixture |
| `tests/fixtures/storage.html` | Create | Seeded localStorage + sessionStorage fixture |
| `tests/test_cli_repl_parity.py` | Create | REPL target parsing + the previously-missing REPL commands |
| `tests/test_cli_devtools.py` | Create | `logs`, `requests`, `request N`, `network start/stop/export` |
| `tests/test_cli_tabs_state.py` | Create | `tab-activate`, `tab-follow`, `state-save`, `state-load`, session-start options |
| `tests/test_cli_input_devices.py` | Create | keyboard + mouse commands, `--button`, `--submit` |
| `tests/test_cli_page_ops.py` | Create | `resize`, `highlight`, `--boxes`, scoped `eval`, pdf/screenshot, storage, cookies, generate-locator |
| `tests/test_cli_tracing.py` | Create | `tracing-start` / `tracing-stop` / `report` |
| `tests/test_input_wiring.py` | Modify | The `PageDelegate` fake gains `button=` on the four mouse methods |
| `tests/test_backend_protocols.py` | Modify | The same fake-signature sync, so the protocol stub documents the real shape |

---

### Task 1: REPL target parsing + the seven missing REPL commands

Closes gap **row 27**. Today `console.py:108-109` is `def _idx(token): return {"index": int(token)}`, so `click #submit` raises an uncaught `ValueError` (`console.py:212-215` catches only `IndexError` and `SessionError`), and the REPL covers 32 of the daemon's 41 ops. This task installs one shared target parser so every REPL verb accepts an index, a bare selector, or `--role/--name/--text/--selector/--exact` — and adds the seven missing verbs. Every later task in this plan adds its REPL branch on top of `_target`.

**Files:**
- Modify: `src/visus/web/cli/console.py:19-53` (`_HELP`), `:96-215` (`dispatch`)
- Test: `tests/test_cli_repl_parity.py`

**Interfaces:**
- Consumes: `console.SendFn`, `console.format_fields`, `session_client.SessionError`
- Produces: `def _target(tokens: list[str]) -> tuple[dict[str, Any], list[str]]`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_repl_parity.py`:

```python
"""REPL parity: target parsing and the previously-missing console commands.

The REPL's dispatch is a pure function over an injected `send`, so these are
unit tests; the same ops are exercised against a real browser by the daemon
tests in tests/test_cli_session.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from visus.web.cli import console


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
    assert calls[0] == ("add_cookies", {"cookies": [{"name": "a", "value": "b", "url": "http://x"}]})
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_repl_parity.py -v --no-cov`
Expected: FAIL with `AttributeError: module 'visus.web.cli.console' has no attribute '_target'`

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/console.py`, add `import json` and `from pathlib import Path` to the imports at the top (after `from collections.abc import Callable`):

```python
from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from visus.web.cli import session_client
```

Replace the `_HELP` block (`console.py:19-53`) with:

```python
_HELP = """targets: a field index (`3`), a bare selector (`#submit`, `//button[1]`),
         or flags (`--selector #go`, `--role button --name Save`, `--text Save [--exact]`).

commands:
  list                 enumerate + highlight interactive fields
  click TARGET         click the target
  fill TARGET text     fill the target with text
  check TARGET         check the target
  uncheck TARGET       uncheck the target
  select TARGET value  select option `value` on the target
  press [TARGET] key   press a key on the target, or on the page with no target
  hover TARGET         hover over the target
  dblclick TARGET      double-click the target
  focus TARGET         focus the target
  clear-input TARGET   clear the target's value
  upload TARGET p...   set file(s) on a file input (paths resolved locally)
  drag TARGET TARGET   drag the first target onto the second
  goto url             navigate to url
  back                 navigate back in history
  forward              navigate forward in history
  reload               reload the current page
  title                print the page title
  url                  print the current URL
  snapshot             list interactive elements (role/name)
  text TARGET          print the target's text content
  attr name TARGET     print the target's `name` attribute
  count TARGET         count elements matching the target
  wait TARGET [state]  wait until the target is visible/hidden
  expect TARGET text   assert the target contains text (PASSED/FAILED)
  cookies              list cookies for the context
  add-cookies json     add cookies from a JSON list
  clear-cookies        clear every cookie in the context
  eval expr            evaluate a JS expression on the page
  dialog [dismiss]     handle the next dialog (accept by default)
  screenshot [path]    save a screenshot (default screenshot.png)
  read-text TARGET     OCR the target and print the text
  solve-captcha TARGET OCR-solve a text CAPTCHA in the target
  find-image f [T] [c] find template image `f` (optional target, confidence)
  clear                remove the field highlight overlay
  tabs                 list open tabs/windows (active marked *)
  tab N                switch to tab/window N (omit N = newest)
  tab-new [url]        open a new tab (optionally at url)
  tab-close [N]        close tab N (omit N = active)
  help                 show this help
  quit                 exit the console (the session stays alive)"""


_TARGET_FLAGS = {
    "--selector": "selector",
    "-s": "selector",
    "--role": "role",
    "--name": "name",
    "--text": "target_text",
}


def _target(tokens: list[str]) -> tuple[dict[str, Any], list[str]]:
    """Split a leading target off *tokens*; return ``(target_args, remaining)``.

    Accepted forms, checked in this order:

    * flags      -- ``--selector #go`` / ``--role button --name Save``
                    / ``--text Save`` / ``-s #go`` / ``--exact``
    * an index   -- ``3`` (a field index from the last ``list``)
    * a selector -- anything else (``#submit``, ``.btn``, ``//button[1]``)

    ``--name`` alone is not a target (it only qualifies ``--role``), matching the
    non-interactive CLI's guard in ``main._target_args``.
    Raises :class:`ValueError` with an actionable message when no target is given.
    """
    if not tokens:
        raise ValueError("provide a field index, a selector, or --selector/--role/--text")
    if tokens[0].startswith("-"):
        args: dict[str, Any] = {}
        i = 0
        while i < len(tokens) and tokens[i].startswith("-"):
            flag = tokens[i]
            if flag == "--exact":
                args["exact"] = True
                i += 1
                continue
            key = _TARGET_FLAGS.get(flag)
            if key is None:
                raise ValueError(f"unknown target flag {flag!r}")
            if i + 1 >= len(tokens):
                raise ValueError(f"{flag} needs a value")
            args[key] = tokens[i + 1]
            i += 2
        if not any(args.get(k) for k in ("selector", "role", "target_text")):
            raise ValueError("--name alone is not a target — add --role")
        return args, tokens[i:]
    token = tokens[0]
    if token.isdigit():
        return {"index": int(token)}, tokens[1:]
    return {"selector": token}, tokens[1:]


def _drag_target(tokens: list[str]) -> dict[str, Any]:
    """Turn a parsed target into drag's *destination* keys."""
    args, _ = _target(tokens)
    if "index" in args:
        return {"target_index": args["index"]}
    if "selector" in args:
        return {"target_selector": args["selector"]}
    raise ValueError("drag's destination must be an index or a selector")
```

Now rewrite the body of `dispatch` (`console.py:96-215`). Delete the inner `_idx` helper and replace every `_idx(rest[...])` call. The full replacement body:

```python
def dispatch(line: str, send: SendFn) -> str:
    """Parse one REPL line, run it via *send*, and return printable output.

    Pure aside from the injected *send* callable -- the unit of testing.
    """
    line = line.strip()
    if not line:
        return ""
    parts = line.split()
    cmd = parts[0].lower()
    rest = parts[1:]

    try:
        if cmd in ("help", "?"):
            return _HELP
        if cmd in ("quit", "exit", "q"):
            return "__QUIT__"
        if cmd in ("list", "ls"):
            result = send("list_fields", {})
            return format_fields(result.get("fields", []))
        if cmd == "click":
            tgt, _ = _target(rest)
            return str(send("click", tgt))
        if cmd == "fill":
            tgt, tail = _target(rest)
            return str(send("fill", {**tgt, "text": " ".join(tail)}))
        if cmd == "check":
            tgt, _ = _target(rest)
            return str(send("check", tgt))
        if cmd == "uncheck":
            tgt, _ = _target(rest)
            return str(send("uncheck", tgt))
        if cmd == "select":
            tgt, tail = _target(rest)
            return str(send("select", {**tgt, "value": " ".join(tail)}))
        if cmd == "press":
            if len(rest) == 1 and not rest[0].isdigit():
                return str(send("press", {"key": rest[0]}))
            tgt, tail = _target(rest)
            return str(send("press", {**tgt, "key": " ".join(tail)}))
        if cmd == "hover":
            tgt, _ = _target(rest)
            return str(send("hover", tgt))
        if cmd == "dblclick":
            tgt, _ = _target(rest)
            return str(send("dblclick", tgt))
        if cmd == "focus":
            tgt, _ = _target(rest)
            return str(send("focus", tgt))
        if cmd == "clear-input":
            tgt, _ = _target(rest)
            return str(send("clear_input", tgt))
        if cmd == "upload":
            tgt, tail = _target(rest)
            if not tail:
                return "missing file path(s) for `upload` (try `help`)"
            paths = [str(Path(p).resolve()) for p in tail]
            return str(send("upload", {**tgt, "paths": paths}))
        if cmd == "drag":
            tgt, tail = _target(rest)
            return str(send("drag", {**tgt, **_drag_target(tail)}))
        if cmd == "goto":
            return f"navigated to {send('goto', {'url': rest[0]})}"
        if cmd == "back":
            return f"went back to {send('back', {})}"
        if cmd == "forward":
            return f"went forward to {send('forward', {})}"
        if cmd == "reload":
            return f"reloaded {send('reload', {})}"
        if cmd == "title":
            return str(send("title", {}))
        if cmd == "url":
            return str(send("url", {}))
        if cmd == "snapshot":
            elements = send("snapshot", {}).get("elements", [])
            if not elements:
                return "(no elements)"
            return "\n".join(
                f"{str(e.get('role', '')):16} {e.get('name', '')}" for e in elements
            )
        if cmd in ("text", "get-text"):
            tgt, _ = _target(rest)
            return str(send("get_text", tgt))
        if cmd in ("attr", "get-attribute"):
            tgt, _ = _target(rest[1:])
            return str(send("get_attribute", {**tgt, "attr_name": rest[0]}))
        if cmd == "count":
            tgt, _ = _target(rest)
            return str(send("count", tgt))
        if cmd == "wait":
            tgt, tail = _target(rest)
            args: dict[str, Any] = dict(tgt)
            if tail:
                args["state"] = tail[0]
            return str(send("wait", args))
        if cmd in ("expect", "expect-text"):
            tgt, tail = _target(rest)
            return str(send("expect_text", {**tgt, "expected_text": " ".join(tail)}))
        if cmd == "cookies":
            items = send("cookies", {}).get("cookies", [])
            if not items:
                return "(no cookies)"
            return "\n".join(
                f"{c.get('name', '')}={c.get('value', '')}  ({c.get('domain', '')})"
                for c in items
            )
        if cmd == "add-cookies":
            try:
                parsed = json.loads(" ".join(rest))
            except json.JSONDecodeError as exc:
                return f"invalid JSON for `add-cookies`: {exc}"
            if not isinstance(parsed, list):
                return "invalid JSON for `add-cookies`: expected a list of cookie objects"
            return str(send("add_cookies", {"cookies": parsed}))
        if cmd == "clear-cookies":
            return str(send("clear_cookies", {}))
        if cmd == "eval":
            return str(send("eval", {"expression": " ".join(rest)}).get("result"))
        if cmd == "dialog":
            accept = not (rest and rest[0].lower() in ("dismiss", "cancel", "no"))
            return str(send("dialog", {"accept": accept, "prompt_text": None}))
        if cmd == "screenshot":
            args = {"path": rest[0]} if rest else {}
            return f"saved {send('screenshot', args)}"
        if cmd == "read-text":
            tgt, _ = _target(rest)
            return str(send("read_text", tgt))
        if cmd == "solve-captcha":
            tgt, _ = _target(rest)
            return str(send("solve_captcha", tgt))
        if cmd == "find-image":
            if not rest:
                return "missing template path for `find-image` (try `help`)"
            args = {"template_path": str(Path(rest[0]).resolve())}
            tail = rest[1:]
            if tail and _is_confidence(tail[-1]):
                args["confidence"] = float(tail[-1])
                tail = tail[:-1]
            if tail:
                tgt, _ = _target(tail)
                args.update(tgt)
            found = send("find_image", args)
            if not found.get("found"):
                return "not found"
            return (
                f"found at ({found['x']}, {found['y']}) "
                f"confidence={found['confidence']:.3f}"
            )
        if cmd == "clear":
            return str(send("clear_highlights", {}))
        if cmd == "tabs":
            items = send("tabs", {}).get("tabs", [])
            if not items:
                return "(no tabs)"
            return "\n".join(
                ("* " if t.get("active") else "  ")
                + f"[{t['index']}] {str(t.get('title', ''))!r}  {t.get('url', '')}"
                for t in items
            )
        if cmd == "tab":
            r = send("tab", {"index": int(rest[0]) if rest else None})
            return f"switched to tab {r['active']}: {str(r.get('title', ''))!r}"
        if cmd == "tab-new":
            r = send("tab_new", {"url": rest[0] if rest else None})
            return f"opened tab {r['index']}: {str(r.get('title', ''))!r}"
        if cmd == "tab-close":
            r = send("tab_close", {"index": int(rest[0]) if rest else None})
            if r.get("remaining", 0) == 0:
                return "closed the last tab — session stopped"
            return f"closed tab {r['closed']} ({r['remaining']} remaining)"
        return f"unknown command {cmd!r} (try `help`)"
    except IndexError:
        return f"missing argument for `{cmd}` (try `help`)"
    except ValueError as exc:
        return f"bad argument for `{cmd}`: {exc}"
    except session_client.SessionError as exc:
        return f"error: {exc}"
```

Add the small predicate `find-image` needs, right after `_drag_target`:

```python
def _is_confidence(token: str) -> bool:
    """True when *token* looks like a 0-1 match threshold (``find-image``'s last arg)."""
    try:
        return 0.0 <= float(token) <= 1.0 and ("." in token or token in ("0", "1"))
    except ValueError:
        return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_repl_parity.py -v --no-cov`
Expected: PASS (13 passed)

- [ ] **Step 5: Verify the pre-existing REPL tests still pass**

Run: `uv run pytest tests/test_cli_session.py -k console -v --no-cov`
Expected: PASS — no failures. If a test asserted `dispatch("click 3", ...)` sends `{"index": 3}`, that still holds.

- [ ] **Step 6: Run the gates**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: `All checks passed!` and `Success: no issues found`

- [ ] **Step 7: Commit**

```bash
git add src/visus/web/cli/console.py tests/test_cli_repl_parity.py
git commit -m "feat(cli): REPL accepts selector/role/text targets and the 7 missing commands"
```

---

### Task 2: `visus repl` as the canonical name, `visus console` as a deprecated alias

Closes the **D2 name collision**. `main.py:897-906` defines `visus console` as the REPL, which blocks the natural name for browser console messages. The conventions contract fixes this: browser logs become `visus logs` (Task 3), the REPL becomes `visus repl`, and `visus console` keeps working as a deprecated alias printing a stderr notice — silently repurposing it would break users mid-session.

**Files:**
- Modify: `src/visus/web/cli/main.py:897-906`
- Modify: `README.md` (Session & lifecycle table)
- Test: `tests/test_cli_repl_parity.py`

**Interfaces:**
- Consumes: `visus.web.cli.console.run_console(url, *, engine, headless, start_dir, input_fn, output_fn)`
- Produces: `visus repl` command; `visus console` deprecated alias

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_repl_parity.py`:

```python
# ---------------------------------------------------------------------------
# `visus repl` (canonical) and `visus console` (deprecated alias)
# ---------------------------------------------------------------------------

import pytest
from typer.testing import CliRunner

from visus.web.cli.main import app

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_repl_parity.py -k "repl_command or console_alias or deprecation" -v --no-cov`
Expected: FAIL — the first test errors with `Error: No such command 'repl'.` (exit code 2)

- [ ] **Step 3: Write minimal implementation**

Replace `main.py:897-906` entirely with:

```python
@app.command("repl")
def repl(
    url: str = typer.Argument(None, help="Optional URL to open."),
    engine: str = typer.Option("chrome", "--engine", "-e"),
    headless: bool = typer.Option(False, "--headless"),
) -> None:
    """Open an interactive REPL attached to the session (starts one if none)."""
    from visus.web.cli.console import run_console

    run_console(url, engine=engine, headless=headless)


@app.command("console")
def console(
    url: str = typer.Argument(None, help="Optional URL to open."),
    engine: str = typer.Option("chrome", "--engine", "-e"),
    headless: bool = typer.Option(False, "--headless"),
) -> None:
    """DEPRECATED alias for `visus repl`. Browser console messages are `visus logs`."""
    typer.echo(
        "warning: `visus console` is deprecated — use `visus repl`. "
        "(Browser console messages are `visus logs`.)",
        err=True,
    )
    from visus.web.cli.console import run_console

    run_console(url, engine=engine, headless=headless)
```

Note: `run_console` is imported inside both functions, so the test's `monkeypatch.setattr(console, "run_console", ...)` (patching the `visus.web.cli.console` module attribute) is what the command resolves at call time.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_repl_parity.py -k "repl_command or console_alias or deprecation" -v --no-cov`
Expected: PASS (3 passed)

- [ ] **Step 5: Update the README**

In `README.md`, in the **Session & lifecycle** table, replace the `visus console` row with these two rows:

```markdown
| `visus repl [URL] --engine <e> --headless` | Open an interactive REPL attached to the session. |
| `visus console [URL]` | Deprecated alias for `visus repl` (prints a notice on stderr). |
```

And in the paragraph just above the `<details>` block, change

```
Run `visus --help` (or `visus <command> --help`) for inline help. Use `visus console` for an
interactive REPL attached to the session.
```

to

```
Run `visus --help` (or `visus <command> --help`) for inline help. Use `visus repl` for an
interactive REPL attached to the session, and `visus logs` for the browser's console messages.
```

- [ ] **Step 6: Run the gates**

Run: `uv run ruff check src tests` then `uv run mypy` then `uv run pytest tests/test_cli.py -q --no-cov`
Expected: clean; `test_help_lists_commands` still passes (it does not assert on `console`).

- [ ] **Step 7: Commit**

```bash
git add src/visus/web/cli/main.py tests/test_cli_repl_parity.py README.md
git commit -m "feat(cli): add `visus repl`, keep `visus console` as a deprecated alias"
```

---

### Task 3: `visus logs [LEVEL]` — the browser's console messages

Closes half of **D2** and one of the four **D3** MCP-only capabilities. `Page.console_messages()` exists at `api/page.py:377-384` and is already exposed as `browser_console_messages` (`mcp/server.py:588-599`); the CLI has zero hits.

**Files:**
- Modify: `src/visus/web/cli/session_server.py` (new `_op_console_messages`, after `_op_eval`)
- Modify: `src/visus/web/cli/main.py` (new `logs` command)
- Modify: `src/visus/web/cli/console.py` (REPL `logs` branch + help line)
- Modify: `README.md` (Dialogs / cookies / JS table)
- Test: `tests/test_cli_devtools.py`

**Interfaces:**
- Consumes: `Page.console_messages() -> list[ConsoleMessage]` (`.level`, `.text`), `output.emit`, `output.set_mode`, `main._send`, `console._target`
- Produces: daemon op `console_messages` → `{"messages": [{"level": str, "text": str}]}`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_devtools.py`:

```python
"""CLI devtools surface: console logs, network requests, NetworkCapture export."""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


class _FakeConsoleMessage:
    def __init__(self, level: str, text: str) -> None:
        self.level = level
        self.text = text


class _LogPage:
    """Minimal page exposing console_messages (the only surface `logs` needs)."""

    url = "http://x/"

    def console_messages(self) -> list[_FakeConsoleMessage]:
        return [
            _FakeConsoleMessage("INFO", "hello"),
            _FakeConsoleMessage("SEVERE", "boom"),
        ]


class _FakeBrowser:
    def close(self) -> None:
        pass

    @property
    def contexts(self) -> list[Any]:
        return []


def _handler(page: Any) -> session_server.SessionHandler:
    h = session_server.SessionHandler(engine="chrome", headless=True)
    h._browser = _FakeBrowser()  # type: ignore[assignment]
    h._page = page
    return h


def test_op_console_messages_returns_all() -> None:
    h = _handler(_LogPage())
    resp = h.handle("console_messages", {})
    assert resp["ok"] is True
    assert resp["result"]["messages"] == [
        {"level": "INFO", "text": "hello"},
        {"level": "SEVERE", "text": "boom"},
    ]


def test_op_console_messages_filters_by_level_case_insensitively() -> None:
    h = _handler(_LogPage())
    resp = h.handle("console_messages", {"level": "severe"})
    assert resp["result"]["messages"] == [{"level": "SEVERE", "text": "boom"}]


def test_cli_logs_sends_level_and_prints_a_table(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["op"], captured["args"] = op, args
        return {"messages": [{"level": "SEVERE", "text": "boom"}]}

    monkeypatch.setattr(session_client, "send", fake_send)
    r = runner.invoke(app, ["logs", "SEVERE"])
    assert r.exit_code == 0, r.output
    assert captured["op"] == "console_messages"
    assert captured["args"] == {"level": "SEVERE"}
    assert "SEVERE" in r.output and "boom" in r.output


def test_cli_logs_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: {"messages": [{"level": "INFO", "text": "x"}]}
    )
    r = runner.invoke(app, ["logs", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output) == [{"level": "INFO", "text": "x"}]


def test_cli_logs_empty_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None: {"messages": []})
    r = runner.invoke(app, ["logs"])
    assert r.exit_code == 0 and "no console messages" in r.output


def test_repl_logs_branch() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return {"messages": [{"level": "SEVERE", "text": "boom"}]}

    out = console.dispatch("logs severe", send)
    assert calls == [("console_messages", {"level": "severe"})]
    assert "boom" in out
    assert "logs" in console.dispatch("help", send)


@pytest.mark.browser
def test_logs_op_against_a_real_page(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/forms.html"
    )
    try:
        h.handle("eval", {"expression": "() => console.error('boom-from-cli-test')"})
        resp = h.handle("console_messages", {"level": "SEVERE"})
        assert resp["ok"] is True, resp
        texts = [m["text"] for m in resp["result"]["messages"]]
        assert any("boom-from-cli-test" in t for t in texts), texts
    finally:
        h.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_devtools.py -m "not browser" -v --no-cov`
Expected: FAIL — `test_op_console_messages_returns_all` asserts `resp["ok"] is True` but gets `False` with `error: "ValueError: unknown op 'console_messages'"`.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/session_server.py`, add this method immediately after `_op_eval` (currently `:486-489`):

```python
    # --- devtools: console / network -------------------------------------
    def _op_console_messages(self, args: dict[str, Any]) -> dict[str, Any]:
        """Browser console messages captured so far (mirrors browser_console_messages).

        ``level`` filters case-insensitively on the WebDriver level
        (SEVERE / WARNING / INFO). Chromium engines only.
        """
        level = str(args.get("level") or "")
        out = [{"level": m.level, "text": m.text} for m in self.page().console_messages()]
        if level:
            out = [m for m in out if m["level"] == level.upper()]
        return {"messages": out}
```

In `src/visus/web/cli/main.py`, add after the `eval_js` command (currently ending at `:830`):

```python
# ---------------------------------------------------------------------------
# DevTools: console messages
# ---------------------------------------------------------------------------


def _logs_text(messages: list[dict[str, Any]]) -> str:
    """Render console messages one per line: LEVEL then text."""
    if not messages:
        return "(no console messages)"
    return "\n".join(
        f"{str(m.get('level', '')):8} {m.get('text', '')}" for m in messages
    )


@app.command()
def logs(
    level: str = typer.Argument(None, help="Filter by level: SEVERE, WARNING or INFO."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Print the browser console messages captured so far (Chromium)."""
    from visus.web.cli import output

    result = _send("console_messages", {"level": level})
    messages = result.get("messages", [])
    if as_json:
        output.set_mode(as_json=True)
    output.emit(messages, table=_logs_text(messages))
```

In `src/visus/web/cli/console.py`, add this branch to `dispatch` right after the `eval` branch:

```python
        if cmd == "logs":
            messages = send(
                "console_messages", {"level": rest[0] if rest else None}
            ).get("messages", [])
            if not messages:
                return "(no console messages)"
            return "\n".join(
                f"{str(m.get('level', '')):8} {m.get('text', '')}" for m in messages
            )
```

And add this line to `_HELP`, right after the `eval expr` line:

```
  logs [LEVEL]         browser console messages (SEVERE/WARNING/INFO)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_devtools.py -m "not browser" -v --no-cov`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the browser test**

Run: `uv run pytest tests/test_cli_devtools.py::test_logs_op_against_a_real_page -v --no-cov`
Expected: PASS (1 passed) — a real headless Chrome loads `forms.html`, `console.error` fires, and the SEVERE message comes back.

- [ ] **Step 6: Update the README**

In `README.md`, in the **Dialogs / cookies / JS** table, add a row after the `visus eval` row:

```markdown
| `visus logs [LEVEL] [--json]` | Browser console messages captured so far (Chromium). |
```

- [ ] **Step 7: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_devtools.py README.md
git commit -m "feat(cli): add `visus logs` for browser console messages"
```

---

### Task 4: `visus requests [--filter]` and `visus request <N>`

Closes the other half of **D2**. `Page.network_requests()` (`api/page.py:369-375`) is already exposed as `browser_network_requests` (`mcp/server.py:570-585`) but not in the CLI. `request <N>` adds what MCP does not have: the response body, via the `NetworkResponse.body()` already on the object.

**Files:**
- Modify: `src/visus/web/cli/session_server.py` (`_op_network_requests`, `_op_network_request`)
- Modify: `src/visus/web/cli/main.py` (`requests`, `request` commands)
- Modify: `src/visus/web/cli/console.py` (REPL `requests` / `request` branches + help)
- Modify: `README.md`
- Test: `tests/test_cli_devtools.py`

**Interfaces:**
- Consumes: `Page.network_requests()`, `NetworkResponse.url/.method/.status/.resource_type/.body()`
- Produces: daemon ops `network_requests` → `{"requests": [...]}`, `network_request` → `{"index", "url", "method", "status", "resource_type", "body"}`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_devtools.py`:

```python
# ---------------------------------------------------------------------------
# requests / request N
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, url: str, status: int, body: str | None) -> None:
        self.url = url
        self.method = "GET"
        self.status = status
        self.resource_type = "Document"
        self._body = body

    def body(self) -> str:
        if self._body is None:
            raise RuntimeError("body evicted")
        return self._body


class _NetPage:
    url = "http://x/"

    def network_requests(self) -> list[_FakeResponse]:
        return [
            _FakeResponse("http://x/index.html", 200, "<html>"),
            _FakeResponse("http://x/api/orders", 500, None),
        ]


def test_op_network_requests_lists_and_filters() -> None:
    h = _handler(_NetPage())
    all_rows = h.handle("network_requests", {})["result"]["requests"]
    assert [r["url"] for r in all_rows] == [
        "http://x/index.html",
        "http://x/api/orders",
    ]
    assert all_rows[1]["status"] == 500
    filtered = h.handle("network_requests", {"url_filter": "/api/"})["result"]["requests"]
    assert len(filtered) == 1 and filtered[0]["url"].endswith("/api/orders")


def test_op_network_request_returns_body_and_survives_eviction() -> None:
    h = _handler(_NetPage())
    first = h.handle("network_request", {"index": 0})["result"]
    assert first["body"] == "<html>" and first["status"] == 200
    evicted = h.handle("network_request", {"index": 1})["result"]
    assert evicted["body"] is None  # eviction is reported, not raised
    bad = h.handle("network_request", {"index": 9})
    assert bad["ok"] is False and "out of range" in bad["error"]


def test_cli_requests_filter_and_table(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["op"], captured["args"] = op, args
        return {
            "requests": [
                {
                    "url": "http://x/api/orders",
                    "method": "GET",
                    "status": 200,
                    "resource_type": "XHR",
                }
            ]
        }

    monkeypatch.setattr(session_client, "send", fake_send)
    r = runner.invoke(app, ["requests", "--filter", "/api/"])
    assert r.exit_code == 0, r.output
    assert captured["op"] == "network_requests"
    assert captured["args"] == {"url_filter": "/api/"}
    assert "200" in r.output and "/api/orders" in r.output


def test_cli_request_by_index_prints_body(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        captured["op"], captured["args"] = op, args
        return {
            "index": 2,
            "url": "http://x/api",
            "method": "POST",
            "status": 201,
            "resource_type": "Fetch",
            "body": '{"id": 7}',
        }

    monkeypatch.setattr(session_client, "send", fake_send)
    r = runner.invoke(app, ["request", "2"])
    assert r.exit_code == 0
    assert captured["op"] == "network_request" and captured["args"] == {"index": 2}
    assert '{"id": 7}' in r.output and "201" in r.output


def test_repl_requests_and_request() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "network_requests":
            return {"requests": [{"url": "http://x/a", "method": "GET", "status": 200}]}
        return {"index": 0, "url": "http://x/a", "method": "GET", "status": 200, "body": "hi"}

    assert "http://x/a" in console.dispatch("requests /a", send)
    assert "hi" in console.dispatch("request 0", send)
    assert calls[0] == ("network_requests", {"url_filter": "/a"})
    assert calls[1] == ("network_request", {"index": 0})


@pytest.mark.browser
def test_requests_op_against_a_real_page(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/network.html"
    )
    try:
        h.handle(
            "eval",
            {
                "expression": "() => new Promise(r => {"
                " const t = setInterval(() => {"
                " if (document.getElementById('r').textContent !== 'pending')"
                " { clearInterval(t); r(true); } }, 50); })"
            },
        )
        rows = h.handle("network_requests", {})["result"]["requests"]
        urls = [r["url"] for r in rows]
        assert any(u.endswith("/network.html") for u in urls), urls
        assert any(u.endswith("/forms.html") for u in urls), urls
        idx = next(i for i, r in enumerate(rows) if r["url"].endswith("/forms.html"))
        one = h.handle("network_request", {"index": idx})["result"]
        assert one["status"] == 200
        assert "Username" in (one["body"] or "")
    finally:
        h.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_devtools.py -m "not browser" -k "network_requests or network_request or requests or request" -v --no-cov`
Expected: FAIL with `unknown op 'network_requests'` on the first daemon test.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/session_server.py`, add after `_op_console_messages`:

```python
    def _op_network_requests(self, args: dict[str, Any]) -> dict[str, Any]:
        """Network responses captured so far (mirrors browser_network_requests).

        ``url_filter`` is a plain substring test on the URL. Chromium only.
        """
        url_filter = str(args.get("url_filter") or "")
        out = [
            {
                "index": i,
                "url": r.url,
                "method": r.method,
                "status": r.status,
                "resource_type": r.resource_type,
            }
            for i, r in enumerate(self.page().network_requests())
        ]
        if url_filter:
            out = [r for r in out if url_filter in str(r["url"])]
        return {"requests": out}

    def _op_network_request(self, args: dict[str, Any]) -> dict[str, Any]:
        """One captured response by index, including its body.

        The body is fetched lazily over CDP and can be evicted after a
        navigation; an unavailable body is reported as ``None``, never raised.
        """
        index = int(args.get("index", 0))
        responses = self.page().network_requests()
        if index < 0 or index >= len(responses):
            raise IndexError(
                f"request index {index} out of range "
                f"(have {len(responses)}; run `visus requests` first)"
            )
        r = responses[index]
        try:
            body: str | None = r.body()
        except Exception:  # noqa: BLE001 — an evicted body is data, not a failure
            body = None
        return {
            "index": index,
            "url": r.url,
            "method": r.method,
            "status": r.status,
            "resource_type": r.resource_type,
            "body": body,
        }
```

In `src/visus/web/cli/main.py`, add after the `logs` command:

```python
def _requests_text(rows: list[dict[str, Any]]) -> str:
    """Render captured responses as `# STATUS METHOD URL` lines."""
    if not rows:
        return "(no requests captured)"
    return "\n".join(
        f"[{r.get('index', i)}] {r.get('status', '')!s:>4} "
        f"{str(r.get('method', '')):6} {r.get('url', '')}"
        for i, r in enumerate(rows)
    )


@app.command()
def requests(
    url_filter: str = typer.Option(
        None, "--filter", "-F", help="Keep only URLs containing this substring."
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """List the network responses captured so far (Chromium)."""
    from visus.web.cli import output

    rows = _send("network_requests", {"url_filter": url_filter}).get("requests", [])
    if as_json:
        output.set_mode(as_json=True)
    output.emit(rows, table=_requests_text(rows))


@app.command()
def request(
    index: int = typer.Argument(..., help="Index from `visus requests`."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show one captured response in full, including its body."""
    from visus.web.cli import output

    r = _send("network_request", {"index": index})
    if as_json:
        output.set_mode(as_json=True)
    text = "\n".join(
        [
            f"{r.get('method', '')} {r.get('url', '')}",
            f"status : {r.get('status', '')}",
            f"type   : {r.get('resource_type', '')}",
            "",
            r.get("body") if r.get("body") is not None else "(body unavailable)",
        ]
    )
    output.emit(r, table=text)
```

Note `-F` is used for `--filter`: `-f` is already `--file` on `translate` and `-s` is `--selector` everywhere.

In `src/visus/web/cli/console.py`, add these branches right after the `logs` branch:

```python
        if cmd == "requests":
            rows = send(
                "network_requests", {"url_filter": rest[0] if rest else None}
            ).get("requests", [])
            if not rows:
                return "(no requests captured)"
            return "\n".join(
                f"[{r.get('index', i)}] {r.get('status', '')!s:>4} "
                f"{str(r.get('method', '')):6} {r.get('url', '')}"
                for i, r in enumerate(rows)
            )
        if cmd == "request":
            r = send("network_request", {"index": int(rest[0])})
            body = r.get("body")
            return (
                f"{r.get('method', '')} {r.get('url', '')}\n"
                f"status : {r.get('status', '')}\n\n"
                + (body if body is not None else "(body unavailable)")
            )
```

And these two `_HELP` lines, right after the `logs [LEVEL]` line:

```
  requests [FILTER]    captured network responses (substring URL filter)
  request N            one captured response, with its body
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_devtools.py -m "not browser" -v --no-cov`
Expected: PASS (11 passed)

- [ ] **Step 5: Run the browser test**

Run: `uv run pytest tests/test_cli_devtools.py::test_requests_op_against_a_real_page -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 6: Update the README**

In `README.md`, in the **Dialogs / cookies / JS** table, add after the `visus logs` row:

```markdown
| `visus requests [--filter <s>] [--json]` | Network responses captured so far (Chromium). |
| `visus request <N> [--json]` | One captured response in full, including its body. |
```

- [ ] **Step 7: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_devtools.py README.md
git commit -m "feat(cli): add `visus requests` and `visus request N`"
```

---

### Task 5: `visus tab-activate` and `visus tab-follow --on/--off`

Closes the remaining two **D3** MCP-only capabilities. `browser_tab_activate` (`mcp/server.py:510-514`) focuses a tab by its stable handle — the CLI's `visus tab N` uses a positional index that shifts when tabs close. `browser_set_tab_follow` (`mcp/server.py:525-538`) lets the agent choose whether a popup silently steals the context; the CLI daemon hard-codes auto-follow at `session_server.py:157`.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:84-101` (`__init__`), `:151-160` (`_resolve_active`), new `_op_tab_activate` / `_op_tab_follow`, `_op_status`
- Modify: `src/visus/web/cli/main.py` (`tab-activate`, `tab-follow`)
- Modify: `src/visus/web/cli/console.py` (REPL branches + help)
- Modify: `README.md` (Tabs / windows table)
- Test: `tests/test_cli_tabs_state.py`

**Interfaces:**
- Consumes: `SessionHandler._driver()`, `SessionHandler._resolve_active`
- Produces: `SessionHandler._follow: bool`; daemon ops `tab_activate` → `{"active": int, "handle": str, "title": str}`, `tab_follow` → `{"follow": bool}`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_tabs_state.py`:

```python
"""Tab handle targeting, tab-follow mode, storage state, and session-start options."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


@pytest.mark.browser
def test_tab_follow_off_keeps_the_context_on_the_current_tab() -> None:
    """With follow off, a newly-opened window must NOT steal the session context."""
    h = session_server.SessionHandler(
        engine="chrome",
        headless=True,
        url="data:text/html,<button id=firstbtn>First</button>",
    )
    try:
        first = h.handle("list_fields", {"highlight": False})
        assert "#firstbtn" in {f["locator"] for f in first["result"]["fields"]}

        assert h.handle("tab_follow", {"enabled": False})["result"] == {"follow": False}

        driver = h._page._delegate._driver  # type: ignore[attr-defined]
        driver.switch_to.new_window("tab")
        driver.get("data:text/html,<button id=secondbtn>Second</button>")

        stayed = h.handle("list_fields", {"highlight": False})
        assert "#firstbtn" in {f["locator"] for f in stayed["result"]["fields"]}

        # Re-enabling follow adopts the newest tab again.
        assert h.handle("tab_follow", {"enabled": True})["result"] == {"follow": True}
        driver.switch_to.new_window("tab")
        driver.get("data:text/html,<button id=thirdbtn>Third</button>")
        followed = h.handle("list_fields", {"highlight": False})
        assert "#thirdbtn" in {f["locator"] for f in followed["result"]["fields"]}
    finally:
        h.close()


@pytest.mark.browser
def test_tab_activate_by_handle_survives_index_shift() -> None:
    h = session_server.SessionHandler(
        engine="chrome",
        headless=True,
        url="data:text/html,<button id=firstbtn>First</button>",
    )
    try:
        h.handle("list_fields", {"highlight": False})
        tabs = h.handle("tabs", {})["result"]["tabs"]
        first_handle = tabs[0]["handle"]

        driver = h._page._delegate._driver  # type: ignore[attr-defined]
        driver.switch_to.new_window("tab")
        driver.get("data:text/html,<button id=secondbtn>Second</button>")
        h.handle("list_fields", {"highlight": False})  # auto-follows tab 1

        back = h.handle("tab_activate", {"handle": first_handle})
        assert back["ok"] is True, back
        assert back["result"]["handle"] == first_handle
        fields = h.handle("list_fields", {"highlight": False})["result"]["fields"]
        assert "#firstbtn" in {f["locator"] for f in fields}

        bad = h.handle("tab_activate", {"handle": "no-such-handle"})
        assert bad["ok"] is False and "no open tab" in bad["error"]
    finally:
        h.close()


def test_cli_tab_activate_and_tab_follow(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        if op == "tab_activate":
            return {"active": 0, "handle": "H1", "title": "First"}
        return {"follow": args["enabled"] if args else True}

    monkeypatch.setattr(session_client, "send", fake_send)
    r1 = runner.invoke(app, ["tab-activate", "H1"])
    assert r1.exit_code == 0 and "H1" in r1.output
    r2 = runner.invoke(app, ["tab-follow", "--off"])
    assert r2.exit_code == 0 and "manual" in r2.output
    r3 = runner.invoke(app, ["tab-follow", "--on"])
    assert r3.exit_code == 0 and "auto" in r3.output
    assert calls[0] == ("tab_activate", {"handle": "H1"})
    assert calls[1] == ("tab_follow", {"enabled": False})
    assert calls[2] == ("tab_follow", {"enabled": True})


def test_repl_tab_activate_and_tab_follow() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "tab_activate":
            return {"active": 1, "handle": "H2", "title": "T"}
        return {"follow": args["enabled"]}

    console.dispatch("tab-activate H2", send)
    console.dispatch("tab-follow off", send)
    console.dispatch("tab-follow on", send)
    assert calls[0] == ("tab_activate", {"handle": "H2"})
    assert calls[1] == ("tab_follow", {"enabled": False})
    assert calls[2] == ("tab_follow", {"enabled": True})
    assert "tab-follow" in console.dispatch("help", send)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_tabs_state.py -m "not browser" -v --no-cov`
Expected: FAIL — `test_cli_tab_activate_and_tab_follow` exits 2 with `Error: No such command 'tab-activate'.`

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/session_server.py`, add `self._follow: bool = True` to `__init__`, right after `self._active_handle: str | None = None` (`:101`):

```python
        self._active_handle: str | None = None
        # Auto-follow a newly-opened tab/popup (the daemon's historical default).
        # `tab_follow` flips it to MANUAL, matching the MCP server's default and
        # giving an agent a predictable context that a popup cannot steal.
        self._follow: bool = True
```

Replace `_resolve_active` (`:151-160`) with:

```python
    def _resolve_active(self, handles: list[str]) -> str:
        """Pick the active handle: auto-follow a newly-opened tab/window when follow
        mode is on, else stay on the last-active one (sticky), else the newest.
        The ``tab``/``tab_activate`` ops override."""
        new = [h for h in handles if h not in self._known_handles]
        self._known_handles = list(handles)
        if new and self._follow:
            self._active_handle = new[-1]  # follow the newest new tab/popup
        if self._active_handle not in handles:
            self._active_handle = handles[-1]
        return self._active_handle
```

Add these two ops immediately after `_op_tab` (currently ending at `:569`):

```python
    def _op_tab_activate(self, args: dict[str, Any]) -> dict[str, Any]:
        """Focus a tab by its stable window handle (from ``tabs``).

        Handles survive reordering and tab closes; indices do not.
        """
        self._ensure()
        driver = self._driver()
        if driver is None:
            raise RuntimeError("no live browser")
        handle = str(args.get("handle") or "")
        handles = list(driver.window_handles)
        if handle not in handles:
            raise ValueError(f"no open tab with handle {handle!r}")
        self._known_handles = list(handles)
        self._active_handle = handle
        self._fields = []  # cached field indices belonged to the previous tab
        try:
            driver.switch_to.window(handle)
            title = driver.title
        except Exception:  # noqa: BLE001
            title = ""
        return {"active": handles.index(handle), "handle": handle, "title": title}

    def _op_tab_follow(self, args: dict[str, Any]) -> dict[str, Any]:
        """Choose how new tabs/popups are handled.

        ``enabled=True`` (the daemon default): AUTO-FOLLOW — subsequent ops target
        the most recently opened tab/popup. ``enabled=False``: MANUAL — a click that
        opens a popup does not change the context; steer with ``tabs``/``tab``.
        """
        enabled = bool(args.get("enabled", True))
        self._follow = enabled
        if not enabled:
            # Pin the context where it is now so the next op cannot drift.
            driver = self._driver()
            if driver is not None:
                try:
                    handles = list(driver.window_handles)
                except Exception:  # noqa: BLE001
                    handles = []
                if handles:
                    self._known_handles = list(handles)
                    if self._active_handle not in handles:
                        self._active_handle = handles[-1]
        return {"follow": self._follow}
```

Add `"follow": self._follow,` to the `info` dict in `_op_status` (`:573-578`), after `"headless": self._headless,`.

In `src/visus/web/cli/main.py`, add after the `tab_close` command (currently ending at `:746`):

```python
@app.command("tab-activate")
def tab_activate(
    handle: str = typer.Argument(..., help="Stable window handle from `visus tabs --json`."),
) -> None:
    """Focus a tab by its stable handle (survives reordering, unlike an index)."""
    from visus.web.cli import output

    result = _send("tab_activate", {"handle": handle})
    output.emit(
        result,
        table=(
            f"activated tab {result['active']} "
            f"({result['handle']}): {str(result.get('title', ''))!r}"
        ),
    )


@app.command("tab-follow")
def tab_follow(
    enabled: bool = typer.Option(
        True, "--on/--off", help="Auto-follow new tabs/popups (--on) or stay put (--off)."
    ),
) -> None:
    """Choose whether a newly-opened tab/popup takes over the session context."""
    from visus.web.cli import output

    result = _send("tab_follow", {"enabled": enabled})
    state = "enabled (auto)" if result["follow"] else "disabled (manual)"
    output.emit(result, table=f"tab-follow {state}")
```

In `src/visus/web/cli/console.py`, add these branches right after the `tab-close` branch:

```python
        if cmd == "tab-activate":
            r = send("tab_activate", {"handle": rest[0]})
            return f"activated tab {r['active']} ({r['handle']}): {str(r.get('title', ''))!r}"
        if cmd == "tab-follow":
            on = not (rest and rest[0].lower() in ("off", "false", "no", "manual"))
            r = send("tab_follow", {"enabled": on})
            return f"tab-follow {'enabled (auto)' if r['follow'] else 'disabled (manual)'}"
```

And these `_HELP` lines right after `tab-close [N]`:

```
  tab-activate H       focus the tab with stable handle H (from `tabs`)
  tab-follow on|off    auto-follow new tabs/popups, or stay put
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_tabs_state.py -m "not browser" -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the browser tests**

Run: `uv run pytest tests/test_cli_tabs_state.py -m browser -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 6: Verify the existing tab tests still pass**

Run: `uv run pytest tests/test_cli_session.py -k tab -v --no-cov`
Expected: PASS — `_follow` defaults to `True`, so `test_handler_follows_focus_to_a_new_window` and `test_handler_manual_tab_switch_lists_and_acts_on_chosen_tab` are unchanged.

- [ ] **Step 7: Update the README**

In `README.md`, in the **Tabs / windows** table, add after the `visus tab-close` row:

```markdown
| `visus tab-activate <handle>` | Focus a tab by its stable handle (from `visus tabs --json`). |
| `visus tab-follow --on/--off` | Auto-follow newly-opened tabs/popups, or stay on the current one. |
```

- [ ] **Step 8: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_tabs_state.py README.md
git commit -m "feat(cli): add tab-activate by handle and tab-follow mode"
```

---

### Task 6: `visus state-save [FILE]` and `visus state-load <FILE>`

Closes **D5**. `Context.storage_state(path=...)` (`api/context.py:47-56`) and `Context.restore_storage_state(dict | str)` (`:58-69`) both exist, and `SessionHandler.context()` (`session_server.py:170-182`) already hands the daemon the right context. Without this, reusing an authenticated session from the shell is impossible and every SPA that keeps its session in `localStorage` has to be logged into again.

**Files:**
- Modify: `src/visus/web/cli/session_server.py` (`_op_state_save`, `_op_state_load`)
- Modify: `src/visus/web/cli/main.py` (`state-save`, `state-load`)
- Modify: `src/visus/web/cli/console.py` (REPL branches + help)
- Modify: `README.md` (Dialogs / cookies / JS table)
- Create: `tests/fixtures/storage.html`
- Test: `tests/test_cli_tabs_state.py`

**Interfaces:**
- Consumes: `Context.storage_state(*, path)`, `Context.restore_storage_state(state)`
- Produces: daemon ops `state_save` → `{"path", "cookies", "origins"}`, `state_load` → `str`

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/storage.html` with exactly this content:

```html
<!doctype html>
<html>
  <head><title>storage fixture</title></head>
  <body>
    <h1>Storage</h1>
    <div id="ls"></div>
    <div id="ss"></div>
    <script>
      // Seed both web storages so storage_state() has something to snapshot and
      // the `visus storage` commands have something to read.
      localStorage.setItem('token', 'seed-local');
      sessionStorage.setItem('tab', 'seed-session');
      document.getElementById('ls').textContent = localStorage.getItem('token');
      document.getElementById('ss').textContent = sessionStorage.getItem('tab');
    </script>
  </body>
</html>
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_cli_tabs_state.py`:

```python
# ---------------------------------------------------------------------------
# storage state save / load
# ---------------------------------------------------------------------------


@pytest.mark.browser
def test_state_save_then_load_round_trips_local_storage(
    base_url: str, tmp_path: Path
) -> None:
    """A saved snapshot restores localStorage into a fresh session — the login-reuse flow."""
    state_file = tmp_path / "state.json"
    first = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/storage.html"
    )
    try:
        first.handle(
            "eval", {"expression": "() => localStorage.setItem('token', 'saved-value')"}
        )
        saved = first.handle("state_save", {"path": str(state_file)})
        assert saved["ok"] is True, saved
        assert saved["result"]["path"] == str(state_file.resolve())
        assert saved["result"]["origins"] >= 1
    finally:
        first.close()

    doc = json.loads(state_file.read_text(encoding="utf-8"))
    assert any(
        any(item["name"] == "token" and item["value"] == "saved-value"
            for item in origin.get("localStorage", []))
        for origin in doc.get("origins", [])
    ), doc

    second = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/storage.html"
    )
    try:
        # The fixture re-seeds 'seed-local' on every load; restoring overwrites it.
        loaded = second.handle("state_load", {"path": str(state_file)})
        assert loaded["ok"] is True, loaded
        value = second.handle(
            "eval", {"expression": "() => localStorage.getItem('token')"}
        )["result"]["result"]
        assert value == "saved-value"
    finally:
        second.close()


def test_cli_state_save_and_load_resolve_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        if op == "state_save":
            return {"path": (args or {}).get("path"), "cookies": 2, "origins": 1}
        return "restored storage state"

    monkeypatch.setattr(session_client, "send", fake_send)
    target = tmp_path / "auth.json"
    r1 = runner.invoke(app, ["state-save", str(target)])
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(app, ["state-load", str(target)])
    assert r2.exit_code == 0
    assert calls[0] == ("state_save", {"path": str(target.resolve())})
    assert calls[1] == ("state_load", {"path": str(target.resolve())})


def test_cli_state_save_defaults_to_storage_state_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {}))
        or {"path": (args or {}).get("path"), "cookies": 0, "origins": 0},
    )
    r = runner.invoke(app, ["state-save"])
    assert r.exit_code == 0
    assert calls[0][1]["path"].endswith("storage-state.json")


def test_repl_state_commands() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return {"path": args.get("path"), "cookies": 1, "origins": 1}

    console.dispatch("state-save auth.json", send)
    console.dispatch("state-load auth.json", send)
    assert calls[0][0] == "state_save"
    assert calls[0][1]["path"] == str(Path("auth.json").resolve())
    assert calls[1][0] == "state_load"
    assert "state-save" in console.dispatch("help", send)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_tabs_state.py -m "not browser" -k state -v --no-cov`
Expected: FAIL — `Error: No such command 'state-save'.` (exit code 2)

- [ ] **Step 4: Write minimal implementation**

In `src/visus/web/cli/session_server.py`, add after `_op_clear_cookies` (`:481-483`):

```python
    # --- storage state (context-level) -----------------------------------
    def _op_state_save(self, args: dict[str, Any]) -> dict[str, Any]:
        """Snapshot cookies + web storage to a JSON file (reuse it to skip a login)."""
        path = args.get("path")
        state = self.context().storage_state(path=path)
        return {
            "path": str(Path(path).resolve()) if path else None,
            "cookies": len(state.get("cookies", [])),
            "origins": len(state.get("origins", [])),
        }

    def _op_state_load(self, args: dict[str, Any]) -> str:
        """Apply a snapshot written by ``state_save``.

        Cookies only apply to the currently-loaded domain and web storage is
        per-origin, so navigate to the target origin BEFORE loading.
        """
        path = str(args["path"])
        self.context().restore_storage_state(path)
        return f"restored storage state from {path}"
```

Add `"state_load"` to the `_MUTATING_OPS` frozenset PLAN 4 created in this module (`state_save` is a read).

In `src/visus/web/cli/main.py`, add after the `clear_cookies` command (`:801-804`):

```python
# ---------------------------------------------------------------------------
# Storage state (cookies + localStorage/sessionStorage)
# ---------------------------------------------------------------------------


@app.command("state-save")
def state_save(
    file: str = typer.Argument("storage-state.json", help="Where to write the snapshot."),
) -> None:
    """Save cookies + web storage to a JSON file (reuse it to skip a login)."""
    from visus.web.cli import output

    # Resolve against the CLIENT's cwd — the daemon's cwd may differ.
    path = str(Path(file).resolve())
    result = _send("state_save", {"path": path})
    output.emit(
        result,
        table=(
            f"saved {result['path']} "
            f"({result['cookies']} cookie(s), {result['origins']} origin(s))"
        ),
    )


@app.command("state-load")
def state_load(
    file: str = typer.Argument(..., help="A snapshot written by `visus state-save`."),
) -> None:
    """Restore cookies + web storage from a JSON file.

    Navigate to the target origin first (`visus goto <url>`): cookies only apply
    to the loaded domain and web storage is per-origin.
    """
    from visus.web.cli import output

    output.emit(_send("state_load", {"path": str(Path(file).resolve())}))
```

In `src/visus/web/cli/console.py`, add these branches right after the `clear-cookies` branch:

```python
        if cmd == "state-save":
            path = str(Path(rest[0] if rest else "storage-state.json").resolve())
            r = send("state_save", {"path": path})
            return (
                f"saved {r['path']} "
                f"({r['cookies']} cookie(s), {r['origins']} origin(s))"
            )
        if cmd == "state-load":
            return str(send("state_load", {"path": str(Path(rest[0]).resolve())}))
```

And these `_HELP` lines right after `clear-cookies`:

```
  state-save [file]    save cookies + web storage (default storage-state.json)
  state-load file      restore a snapshot (navigate to the origin first)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_tabs_state.py -m "not browser" -k state -v --no-cov`
Expected: PASS (3 passed)

- [ ] **Step 6: Run the browser test**

Run: `uv run pytest tests/test_cli_tabs_state.py::test_state_save_then_load_round_trips_local_storage -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 7: Update the README**

In `README.md`, in the **Dialogs / cookies / JS** table, add after the `visus add-cookies` row:

```markdown
| `visus state-save [FILE]` / `visus state-load <FILE>` | Save / restore cookies + web storage (skip a login next run). |
```

- [ ] **Step 8: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: `All checks passed!` and `Success: no issues found`

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_tabs_state.py tests/fixtures/storage.html README.md
git commit -m "feat(cli): add state-save / state-load for cookies + web storage"
```

---

### Task 7: `session start --user-data-dir / --remote-url / --slow-mo`

Closes **D6**. `launch()` already takes all three (`__init__.py:59-66`, documented at `:69-77`), but `session_server.py:106` calls `launch(Engine.from_str(self._engine), headless=self._headless)` and drops them. Every daemon session is therefore a throwaway profile: MFA has to be redone every run, and a Selenium Grid is unreachable from the shell.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:84-119` (`__init__` / `_ensure`), `:571-589` (`_op_status`), `:697-710` (session-file payload), `:738-773` (`main`)
- Modify: `src/visus/web/cli/session_client.py:129-176` (`start_daemon`)
- Modify: `src/visus/web/cli/main.py:238-252` (`session start`)
- Modify: `README.md` (Session table + env-var table)
- Test: `tests/test_cli_tabs_state.py`

**Interfaces:**
- Consumes: `launch(engine, *, headless, slow_mo, user_data_dir, remote_url) -> Browser`
- Produces: `SessionHandler(..., user_data_dir=None, remote_url=None, slow_mo=0)`;
  `session_client.start_daemon(engine, headless, url, *, user_data_dir=None, remote_url=None, slow_mo=0, cwd=None, timeout=20.0)`;
  env vars `VISUS_WEB_USER_DATA_DIR`, `VISUS_WEB_REMOTE_URL`, `VISUS_WEB_SLOW_MO`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_tabs_state.py`:

```python
# ---------------------------------------------------------------------------
# session start options: --user-data-dir / --remote-url / --slow-mo
# ---------------------------------------------------------------------------


def test_handler_forwards_launch_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """_ensure must pass every launch option through, not drop them."""
    seen: dict[str, Any] = {}

    class _Page:
        def goto(self, url: str) -> None:
            seen["goto"] = url

    class _Browser:
        def new_page(self) -> _Page:
            return _Page()

        def close(self) -> None:
            pass

    def fake_launch(engine: Any, **kwargs: Any) -> _Browser:
        seen["engine"] = engine
        seen["kwargs"] = kwargs
        return _Browser()

    monkeypatch.setattr(session_server, "launch", fake_launch)
    h = session_server.SessionHandler(
        engine="chrome",
        headless=True,
        url="http://x",
        user_data_dir="/profiles/p1",
        remote_url="http://grid:4444/wd/hub",
        slow_mo=250,
    )
    h._ensure()
    assert seen["kwargs"] == {
        "headless": True,
        "slow_mo": 250,
        "user_data_dir": "/profiles/p1",
        "remote_url": "http://grid:4444/wd/hub",
    }
    assert seen["goto"] == "http://x"


def test_daemon_main_reads_launch_options_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    built: dict[str, Any] = {}

    class _Handler:
        def __init__(self, **kwargs: Any) -> None:
            built.update(kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VISUS_WEB_USER_DATA_DIR", "/profiles/p2")
    monkeypatch.setenv("VISUS_WEB_REMOTE_URL", "http://grid:4444")
    monkeypatch.setenv("VISUS_WEB_SLOW_MO", "120")
    monkeypatch.setattr(session_server, "SessionHandler", _Handler)
    monkeypatch.setattr(session_server, "serve", lambda handler, **kwargs: None)

    session_server.main(["chrome", "1", ""])
    assert built["user_data_dir"] == "/profiles/p2"
    assert built["remote_url"] == "http://grid:4444"
    assert built["slow_mo"] == 120


def test_start_daemon_exports_launch_options(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    class _Popen:
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            captured["argv"] = argv
            captured["env"] = kwargs["env"]

    monkeypatch.setattr(session_client.subprocess, "Popen", _Popen)
    monkeypatch.setattr(session_client, "find_session", lambda base: None)
    monkeypatch.setattr(session_client, "_socket_open", lambda port: False)
    try:
        session_client.start_daemon(
            "chrome",
            True,
            None,
            cwd=tmp_path,
            timeout=0.2,
            user_data_dir="/profiles/p3",
            remote_url="http://grid:4444",
            slow_mo=75,
        )
    except session_client.SessionError:
        pass  # the fake daemon never comes up — we only assert on the spawn
    env = captured["env"]
    assert env["VISUS_WEB_USER_DATA_DIR"].endswith("p3")
    assert env["VISUS_WEB_REMOTE_URL"] == "http://grid:4444"
    assert env["VISUS_WEB_SLOW_MO"] == "75"


def test_cli_session_start_passes_the_new_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_start(engine: str, headless: bool, url: str | None, **kwargs: Any) -> dict[str, Any]:
        captured["engine"], captured["headless"], captured["url"] = engine, headless, url
        captured["kwargs"] = kwargs
        return {"pid": 1, "port": 2}

    monkeypatch.setattr(session_client, "start_daemon", fake_start)
    r = runner.invoke(
        app,
        [
            "session", "start", "http://x",
            "--user-data-dir", "/profiles/p4",
            "--remote-url", "http://grid:4444",
            "--slow-mo", "50",
        ],
    )
    assert r.exit_code == 0, r.output
    assert captured["kwargs"]["user_data_dir"] == "/profiles/p4"
    assert captured["kwargs"]["remote_url"] == "http://grid:4444"
    assert captured["kwargs"]["slow_mo"] == 50
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_tabs_state.py -k "launch_options or session_start_passes or daemon_main_reads or start_daemon_exports" -v --no-cov`
Expected: FAIL with `TypeError: SessionHandler.__init__() got an unexpected keyword argument 'user_data_dir'`

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/session_server.py`, replace `__init__` (`:84-101`) with:

```python
    def __init__(
        self,
        *,
        engine: str | None = None,
        headless: bool | None = None,
        url: str | None = None,
        user_data_dir: str | None = None,
        remote_url: str | None = None,
        slow_mo: int = 0,
    ) -> None:
        self._engine = engine or os.environ.get("VISUS_WEB_ENGINE", "chrome")
        if headless is None:
            headless = os.environ.get("VISUS_WEB_HEADLESS", "0") != "0"
        self._headless = headless
        self._url = url
        self._user_data_dir = user_data_dir
        self._remote_url = remote_url
        self._slow_mo = slow_mo
        self._browser: Browser | None = None
        self._context: Context | None = None
        self._page: Page | None = None
        self._fields: list[Field] = []
        self._known_handles: list[str] = []
        self._active_handle: str | None = None
        # Auto-follow a newly-opened tab/popup (the daemon's historical default).
        # `tab_follow` flips it to MANUAL, matching the MCP server's default and
        # giving an agent a predictable context that a popup cannot steal.
        self._follow: bool = True
```

Replace the `launch(...)` call in `_ensure` (`:106`) with:

```python
            self._browser = launch(
                Engine.from_str(self._engine),
                headless=self._headless,
                slow_mo=self._slow_mo,
                user_data_dir=self._user_data_dir,
                remote_url=self._remote_url,
            )
```

In `_op_status`, extend the `info` dict — add these three entries right after `"follow": self._follow,`:

```python
            "user_data_dir": self._user_data_dir,
            "remote_url": self._remote_url,
            "slow_mo": self._slow_mo,
```

In `serve()`, extend the session-file payload (`:697-707`) with the three keys, right after `"url": handler._url,`:

```python
            "user_data_dir": handler._user_data_dir,
            "remote_url": handler._remote_url,
            "slow_mo": handler._slow_mo,
```

In `main()`, read the three from env right after the `token` line (`:750`):

```python
    user_data_dir = os.environ.get("VISUS_WEB_USER_DATA_DIR") or None
    remote_url = os.environ.get("VISUS_WEB_REMOTE_URL") or None
    try:
        slow_mo = int(os.environ.get("VISUS_WEB_SLOW_MO") or 0)
    except ValueError:
        slow_mo = 0
```

Replace the startup log line (`:760`) and the handler construction (`:761`) with:

```python
    _log(
        f"daemon starting engine={engine} headless={headless} url={url!r} "
        f"user_data_dir={user_data_dir!r} remote_url={remote_url!r} "
        f"slow_mo={slow_mo} pid={os.getpid()}"
    )
    handler = SessionHandler(
        engine=engine,
        headless=headless,
        url=url,
        user_data_dir=user_data_dir,
        remote_url=remote_url,
        slow_mo=slow_mo,
    )
```

In `src/visus/web/cli/session_client.py`, replace `start_daemon`'s signature, docstring and env block (`:129-153`) with:

```python
def start_daemon(
    engine: str = "chrome",
    headless: bool = False,
    url: str | None = None,
    *,
    user_data_dir: str | None = None,
    remote_url: str | None = None,
    slow_mo: int = 0,
    cwd: str | Path | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Spawn a detached daemon and block until its socket accepts.

    ``user_data_dir`` reuses a persistent browser profile (cookies/logins survive
    across runs), ``remote_url`` targets a Selenium Grid instead of a local
    browser, and ``slow_mo`` delays every action by that many milliseconds.

    Returns the session dict. Raises :class:`SessionError` if an existing live
    session is already present or the daemon does not come up in time.
    """
    base = Path(cwd) if cwd is not None else Path.cwd()
    existing = find_session(base)
    if existing is not None:
        raise SessionError(
            f"a session is already running (pid {existing['pid']}, port {existing['port']})"
        )

    env = dict(os.environ)
    env["VISUS_WEB_ENGINE"] = engine
    env["VISUS_WEB_HEADLESS"] = "1" if headless else "0"
    if url:
        env["VISUS_WEB_URL"] = url
    if user_data_dir:
        # Resolve against the CLIENT's cwd — the daemon is spawned elsewhere.
        env["VISUS_WEB_USER_DATA_DIR"] = str(Path(user_data_dir).resolve())
    if remote_url:
        env["VISUS_WEB_REMOTE_URL"] = remote_url
    if slow_mo:
        env["VISUS_WEB_SLOW_MO"] = str(slow_mo)
```

The rest of `start_daemon` — the `creationflags` block, the `Popen` call and the poll loop — is unchanged.

In `src/visus/web/cli/main.py`, replace `session_start` (`:238-252`) with:

```python
@session_app.command("start")
def session_start(
    url: str = typer.Argument(None, help="URL to open once the browser starts."),
    engine: str = typer.Option("chrome", "--engine", "-e"),
    headless: bool = typer.Option(False, "--headless", help="Run headless (default: headed)."),
    user_data_dir: str = typer.Option(
        None,
        "--user-data-dir",
        help="Reuse a persistent browser profile — cookies and logins survive runs.",
    ),
    remote_url: str = typer.Option(
        None,
        "--remote-url",
        help="Drive a Selenium Grid / Remote WebDriver, e.g. http://grid:4444/wd/hub.",
    ),
    slow_mo: int = typer.Option(
        0, "--slow-mo", help="Delay every action by this many milliseconds."
    ),
) -> None:
    """Start a persistent browser session (detached daemon)."""
    from visus.web.cli import output, session_client

    try:
        info = session_client.start_daemon(
            engine,
            headless,
            url,
            user_data_dir=user_data_dir,
            remote_url=remote_url,
            slow_mo=slow_mo,
        )
    except session_client.SessionError as exc:
        output.emit_error(str(exc))
    output.emit(
        info,
        table=f"session started (pid {info['pid']}, port {info['port']}, engine {engine})",
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_tabs_state.py -k "launch_options or session_start_passes or daemon_main_reads or start_daemon_exports" -v --no-cov`
Expected: PASS (4 passed)

- [ ] **Step 5: Verify the existing daemon suites still pass**

Run: `uv run pytest tests/test_cli_session.py tests/test_e2e_cli_session.py -q --no-cov`
Expected: PASS — every `SessionHandler(...)` call site is keyword-only and the three new parameters default to inert values.

- [ ] **Step 6: Update the README**

In `README.md`, in the **Session & lifecycle** table, replace the `visus session start` row with:

```markdown
| `visus session start [URL] --engine <e> --headless --user-data-dir <dir> --remote-url <url> --slow-mo <ms>` | Start the persistent browser daemon (headed by default); optionally on a persistent profile, a Selenium Grid, or slowed down. |
```

In the environment-variable table, add three rows after `VISUS_WEB_URL`:

```markdown
| `VISUS_WEB_USER_DATA_DIR` | CLI session | — | Persistent browser profile directory for the daemon. |
| `VISUS_WEB_REMOTE_URL` | CLI session | — | Selenium Grid / Remote WebDriver URL for the daemon. |
| `VISUS_WEB_SLOW_MO` | CLI session | `0` | Delay every daemon action by this many milliseconds. |
```

- [ ] **Step 7: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/session_client.py src/visus/web/cli/main.py tests/test_cli_tabs_state.py README.md
git commit -m "feat(cli): session start accepts --user-data-dir, --remote-url and --slow-mo"
```

---

### Task 8: Standalone keyboard — `visus type`, `keydown`, `keyup`, targetless `press`, and `fill --submit`

Closes half of **D7** plus **row 28**'s `--submit`. `Keyboard.down/up/press/type/insert_text` exist (`api/input.py:52-70`) and `Page.keyboard` exposes them (`api/page.py:303-308`), but `visus press Enter` is impossible today: `press` funnels through `_target_args` (`main.py:395`), which exits 1 without a target, and `Enter` would fail the `index: int` positional anyway.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:249-252` (`_op_fill`), `:267-270` (`_op_press`), new `_op_type` / `_op_key_down` / `_op_key_up`
- Modify: `src/visus/web/cli/main.py:316-335` (`fill`), `:382-401` (`press`), new `type` / `keydown` / `keyup`
- Modify: `src/visus/web/cli/console.py` (REPL branches + help)
- Modify: `README.md` (Actions table)
- Test: `tests/test_cli_input_devices.py`

**Interfaces:**
- Consumes: `Page.keyboard` → `Keyboard.down/up/press/type`, `SessionHandler._has_target`, `SessionHandler._target`
- Produces: daemon ops `type`, `key_down`, `key_up`; `press` accepts no target; `fill` accepts `submit: bool`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_input_devices.py`:

```python
"""Standalone keyboard and mouse: daemon ops, CLI wiring, REPL, real browser."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


class _RecordingKeyboard:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def down(self, key: str) -> None:
        self._log.append(f"kb.down:{key}")

    def up(self, key: str) -> None:
        self._log.append(f"kb.up:{key}")

    def press(self, key: str) -> None:
        self._log.append(f"kb.press:{key}")

    def type(self, text: str) -> None:
        self._log.append(f"kb.type:{text}")


class _RecordingLocator:
    def __init__(self, log: list[str], label: str) -> None:
        self._log = log
        self._label = label

    def first(self) -> _RecordingLocator:
        return self

    def focus(self) -> None:
        self._log.append(f"focus:{self._label}")

    def press(self, key: str) -> None:
        self._log.append(f"press:{self._label}:{key}")

    def fill(self, text: str) -> None:
        self._log.append(f"fill:{self._label}:{text}")


class _KeyPage:
    url = "http://x/"

    def __init__(self) -> None:
        self.log: list[str] = []

    @property
    def keyboard(self) -> _RecordingKeyboard:
        return _RecordingKeyboard(self.log)

    def locator(self, selector: str, *, deep: bool = False) -> _RecordingLocator:
        return _RecordingLocator(self.log, f"loc({selector})")


class _FakeBrowser:
    def close(self) -> None:
        pass

    @property
    def contexts(self) -> list[Any]:
        return []


def _handler(page: Any) -> session_server.SessionHandler:
    h = session_server.SessionHandler(engine="chrome", headless=True)
    h._browser = _FakeBrowser()  # type: ignore[assignment]
    h._page = page
    return h


def test_op_press_without_a_target_uses_the_page_keyboard() -> None:
    page = _KeyPage()
    h = _handler(page)
    assert h.handle("press", {"key": "Enter"})["result"] == "pressed 'Enter'"
    assert page.log == ["kb.press:Enter"]


def test_op_press_with_a_target_still_targets_the_element() -> None:
    page = _KeyPage()
    h = _handler(page)
    assert h.handle("press", {"selector": "#i", "key": "Tab"})["result"] == "pressed 'Tab'"
    assert page.log == ["press:loc(#i):Tab"]


def test_op_type_focuses_the_target_then_types() -> None:
    page = _KeyPage()
    h = _handler(page)
    assert h.handle("type", {"selector": "#i", "text": "abc"})["result"] == "typed 'abc'"
    assert page.log == ["focus:loc(#i)", "kb.type:abc"]
    page.log.clear()
    assert h.handle("type", {"text": "xyz"})["result"] == "typed 'xyz'"
    assert page.log == ["kb.type:xyz"]


def test_op_key_down_and_up() -> None:
    page = _KeyPage()
    h = _handler(page)
    assert h.handle("key_down", {"key": "Shift"})["result"] == "key down 'Shift'"
    assert h.handle("key_up", {"key": "Shift"})["result"] == "key up 'Shift'"
    assert page.log == ["kb.down:Shift", "kb.up:Shift"]


def test_op_fill_submit_presses_enter_and_keeps_the_old_message() -> None:
    page = _KeyPage()
    h = _handler(page)
    assert h.handle("fill", {"selector": "#q", "text": "hi"})["result"] == "filled with 'hi'"
    assert page.log == ["fill:loc(#q):hi"]
    page.log.clear()
    out = h.handle("fill", {"selector": "#q", "text": "hi", "submit": True})["result"]
    assert out == "filled with 'hi' and pressed Enter"
    assert page.log == ["fill:loc(#q):hi", "press:loc(#q):Enter"]


def test_cli_press_standalone_and_by_index(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: calls.append((op, args or {})) or "ok"
    )
    assert runner.invoke(app, ["press", "Enter"]).exit_code == 0
    assert runner.invoke(app, ["press", "3", "Tab"]).exit_code == 0
    assert runner.invoke(app, ["press", "--selector", "#i", "--key", "Escape"]).exit_code == 0
    assert calls[0] == ("press", {"key": "Enter"})
    assert calls[1] == ("press", {"index": 3, "key": "Tab"})
    assert calls[2][1]["selector"] == "#i" and calls[2][1]["key"] == "Escape"


def test_cli_type_keydown_keyup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: calls.append((op, args or {})) or "ok"
    )
    assert runner.invoke(app, ["type", "hello world"]).exit_code == 0
    assert runner.invoke(app, ["type", "scoped", "--selector", "#i"]).exit_code == 0
    assert runner.invoke(app, ["keydown", "Shift"]).exit_code == 0
    assert runner.invoke(app, ["keyup", "Shift"]).exit_code == 0
    assert calls[0] == ("type", {"text": "hello world"})
    assert calls[1][1]["text"] == "scoped" and calls[1][1]["selector"] == "#i"
    assert calls[2] == ("key_down", {"key": "Shift"})
    assert calls[3] == ("key_up", {"key": "Shift"})


def test_cli_fill_submit_only_sent_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: calls.append((op, args or {})) or "ok"
    )
    assert runner.invoke(app, ["fill", "1", "hello"]).exit_code == 0
    assert runner.invoke(app, ["fill", "1", "hello", "--submit"]).exit_code == 0
    assert calls[0] == ("fill", {"index": 1, "text": "hello"})
    assert calls[1] == ("fill", {"index": 1, "text": "hello", "submit": True})


def test_repl_keyboard_commands() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return "ok"

    console.dispatch("press Enter", send)
    console.dispatch("press 3 Tab", send)
    console.dispatch("type hello world", send)
    console.dispatch("keydown Shift", send)
    console.dispatch("keyup Shift", send)
    assert calls[0] == ("press", {"key": "Enter"})
    assert calls[1] == ("press", {"index": 3, "key": "Tab"})
    assert calls[2] == ("type", {"text": "hello world"})
    assert calls[3] == ("key_down", {"key": "Shift"})
    assert calls[4] == ("key_up", {"key": "Shift"})
    help_text = console.dispatch("help", send)
    for cmd in ("type", "keydown", "keyup"):
        assert cmd in help_text


@pytest.mark.browser
def test_keyboard_ops_against_a_real_page(base_url: str) -> None:
    """input.html reports Enter on #k and a held Shift on #shift."""
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/input.html"
    )
    try:
        assert h.handle("focus", {"selector": "#k"})["ok"] is True
        assert h.handle("type", {"text": "abc"})["ok"] is True
        value = h.handle("eval", {"expression": "() => document.getElementById('k').value"})
        assert value["result"]["result"] == "abc"

        assert h.handle("press", {"key": "Enter"})["ok"] is True
        marker = h.handle(
            "eval", {"expression": "() => document.getElementById('k2').textContent"}
        )
        assert marker["result"]["result"] == "enter"

        assert h.handle("focus", {"selector": "#shift"})["ok"] is True
        assert h.handle("key_down", {"key": "Shift"})["ok"] is True
        assert h.handle("press", {"key": "a"})["ok"] is True
        assert h.handle("key_up", {"key": "Shift"})["ok"] is True
        held = h.handle(
            "eval", {"expression": "() => document.getElementById('k3').textContent"}
        )
        assert held["result"]["result"] == "shift-held"
    finally:
        h.close()


@pytest.mark.browser
def test_fill_submit_against_a_real_page(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/interactions.html"
    )
    try:
        out = h.handle("fill", {"selector": "#txt", "text": "typed", "submit": True})
        assert out["ok"] is True and "pressed Enter" in out["result"]
        marker = h.handle(
            "eval", {"expression": "() => document.getElementById('pressres').textContent"}
        )
        assert marker["result"]["result"] == "enter"
    finally:
        h.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_input_devices.py -m "not browser" -v --no-cov`
Expected: FAIL — `test_op_press_without_a_target_uses_the_page_keyboard` raises `KeyError: 'result'` because `handle` returned `{"ok": False, "error": "ValueError: provide one of: index, role, text, selector"}`.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/session_server.py`, replace `_op_fill` (`:249-252`):

```python
    def _op_fill(self, args: dict[str, Any]) -> str:
        text = args.get("text", "")
        loc = self._target(args)
        loc.fill(text)
        if args.get("submit"):
            loc.press("Enter")
            return f"filled with {text!r} and pressed Enter"
        return f"filled with {text!r}"
```

Replace `_op_press` (`:267-270`) and add the three new ops right after it:

```python
    def _op_press(self, args: dict[str, Any]) -> str:
        """Press a key on a target, or on the page itself when no target is given."""
        key = args.get("key", "")
        if self._has_target(args):
            self._target(args).press(key)
        else:
            self.page().keyboard.press(key)
        return f"pressed {key!r}"

    def _op_type(self, args: dict[str, Any]) -> str:
        """Type text with real key events. With a target, focus it first."""
        text = str(args.get("text", ""))
        page = self.page()
        if self._has_target(args):
            self._target(args).first().focus()
        page.keyboard.type(text)
        return f"typed {text!r}"

    def _op_key_down(self, args: dict[str, Any]) -> str:
        """Hold a key down (e.g. Shift, Control) until ``key_up``."""
        key = str(args.get("key", ""))
        self.page().keyboard.down(key)
        return f"key down {key!r}"

    def _op_key_up(self, args: dict[str, Any]) -> str:
        """Release a key held by ``key_down``."""
        key = str(args.get("key", ""))
        self.page().keyboard.up(key)
        return f"key up {key!r}"
```

Add `"type"`, `"key_down"` and `"key_up"` to the `_MUTATING_OPS` frozenset PLAN 4 created in this module.

In `src/visus/web/cli/main.py`, replace `fill` (`:316-335`) with:

```python
@app.command()
def fill(
    index: int = typer.Argument(None, help="Field index from the last list-fields."),
    text: str = typer.Argument(None, help="Text to fill, e.g. `visus fill 7 hello`."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    by_text: str = typer.Option(None, "--text", help="Target a field by its visible text."),
    value: str = typer.Option(
        None, "--value", help="Text to fill when targeting by --selector/--role/--text."
    ),
    submit: bool = typer.Option(
        False, "--submit", help="Press Enter after filling (submits most forms)."
    ),
) -> None:
    """Fill a field. By index: `visus fill 7 hello`. By selector: `-s "#u" --value hello`."""
    from visus.web.cli import output

    args = _target_args(index, selector, role, name, by_text)
    fill_value = text if text is not None else value
    if fill_value is None:
        output.emit_error("no text to fill — use `visus fill <index> <text>` or `--value`")
    args["text"] = fill_value
    if submit:
        args["submit"] = True  # only sent when asked, so the payload stays minimal
    output.emit(_send("fill", args))
```

Replace `press` (`:382-401`) with these four commands:

```python
@app.command()
def press(
    target: str = typer.Argument(
        None, help="Field index, OR the key itself for a page-level press."
    ),
    key: str = typer.Argument(None, help="Key to press when the first argument is an index."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    by_text: str = typer.Option(None, "--text", help="Target a field by its visible text."),
    key_value: str = typer.Option(
        None, "--key", help="Key when targeting by --selector/--role/--text."
    ),
) -> None:
    """Press a key. On a field: `visus press 7 Enter`. On the page: `visus press Enter`."""
    from visus.web.cli import output

    has_option_target = bool(selector or role or by_text)
    index = int(target) if target is not None and target.isdigit() else None
    k = key if key is not None else key_value
    if k is None and index is None and target is not None and not has_option_target:
        k = target  # `visus press Enter` — the whole argument was the key
    if k is None:
        output.emit_error(
            "no key — use `visus press <index> <key>`, `--key`, or `visus press <key>`"
        )
    if index is None and not has_option_target:
        output.emit(_send("press", {"key": k}))
        return
    args = _target_args(index, selector, role, name, by_text)
    args["key"] = k
    output.emit(_send("press", args))


@app.command("type")
def type_text(
    text: str = typer.Argument(..., help="Text to type with real key events."),
    index: int = typer.Option(None, "--index", "-i", help="Focus this field first."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    by_text: str = typer.Option(None, "--text", help="Target a field by its visible text."),
) -> None:
    """Type text into the focused element (or focus a target first)."""
    from visus.web.cli import output

    args: dict[str, Any] = {"text": text}
    if index is not None or selector or role or by_text:
        args.update(_target_args(index, selector, role, name, by_text))
    output.emit(_send("type", args))


@app.command()
def keydown(key: str = typer.Argument(..., help="Key to hold, e.g. Shift or Control.")) -> None:
    """Hold a key down until `visus keyup` releases it."""
    from visus.web.cli import output

    output.emit(_send("key_down", {"key": key}))


@app.command()
def keyup(key: str = typer.Argument(..., help="Key to release.")) -> None:
    """Release a key held by `visus keydown`."""
    from visus.web.cli import output

    output.emit(_send("key_up", {"key": key}))
```

In `src/visus/web/cli/console.py`, add these branches right after the existing `press` branch:

```python
        if cmd == "type":
            return str(send("type", {"text": " ".join(rest)}))
        if cmd == "keydown":
            return str(send("key_down", {"key": rest[0]}))
        if cmd == "keyup":
            return str(send("key_up", {"key": rest[0]}))
```

And these `_HELP` lines right after the `press [TARGET] key` line:

```
  type text...         type into the focused element (real key events)
  keydown key          hold a key down (e.g. Shift)
  keyup key            release a held key
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_input_devices.py -m "not browser" -v --no-cov`
Expected: PASS (9 passed)

- [ ] **Step 5: Run the browser tests**

Run: `uv run pytest tests/test_cli_input_devices.py -m browser -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 6: Verify the existing press/fill tests still pass**

Run: `uv run pytest tests/test_cli_session.py -k "fill or press" -v --no-cov`
Expected: PASS — `test_cli_fill_select_press` still records `("press", {"index": 3, "key": "Enter"})` and `("fill", {"index": 1, "text": "hello"})`.

- [ ] **Step 7: Update the README**

In `README.md`, in the **Actions** table, replace the `visus fill` and `visus press` rows and add two more:

```markdown
| `visus fill [idx] <text> [--submit]` / `… -s <sel> --value <v>` | Fill an input; `--submit` presses Enter afterwards. |
| `visus press [idx] <key>` / `visus press <key>` | Press a key on a field, or on the page with no target. |
| `visus type <text> [target]` | Type with real key events (focuses the target first, if given). |
| `visus keydown <key>` / `visus keyup <key>` | Hold / release a modifier across several actions. |
```

- [ ] **Step 8: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_input_devices.py README.md
git commit -m "feat(cli): standalone keyboard commands and fill --submit"
```

---

### Task 9: Standalone mouse — `mousemove`/`mousedown`/`mouseup`/`mousewheel`, and `--button` on click/dblclick

Closes the other half of **D7**. `Mouse.move/down/up/click/dblclick/wheel` exist (`api/input.py:21-43`) and `Page.mouse` exposes them (`api/page.py:296-301`), but the shell cannot reach any of them, and `visus click` is left-button only — so context menus, middle-click-to-open and wheel-driven lazy loading are unautomatable.

This task reaches one layer deeper than the rest of the plan, on purpose: the delegate's `mouse_down`/`mouse_up`/`mouse_click`/`mouse_dblclick` (`driver_delegate.py:775-809`) hard-code the primary button, even though Selenium's `pointer_down`/`pointer_up` have always taken a button index. Adding a public `button: str` (`"left"`/`"middle"`/`"right"`) that maps to that index inside `driver_delegate.py` keeps the hidden-engine rule intact — no `selenium.*` type appears in any public signature.

`--button` on `click`/`dblclick` does **not** touch the actionability path (`Locator.click` → `locator_click` → `run_action`), which is left-only by construction. A non-left click resolves the target's bounding box and goes through the pointer device at its centre. The default `left` path is byte-for-byte the code that runs today, so every existing click test keeps passing.

**Files:**
- Modify: `src/visus/web/api/input.py:25-39` (`Mouse.down/up/click/dblclick`)
- Modify: `src/visus/web/backends/base.py:87-90` (`PageDelegate` mouse protocol)
- Modify: `src/visus/web/backends/selenium/driver_delegate.py:35-49` (button map), `:775-809` (the four methods)
- Modify: `src/visus/web/async_api/__init__.py:729-739` (`AsyncMouse`)
- Modify: `src/visus/web/cli/session_server.py:245-247` (`_op_click`), `:338-340` (`_op_dblclick`), new `_op_mouse_*`
- Modify: `src/visus/web/cli/main.py:304-313` (`click`), `:590-599` (`dblclick`), new mouse commands
- Modify: `src/visus/web/cli/console.py` (REPL branches + `_HELP`)
- Modify: `README.md` (Actions table)
- Modify: `tests/test_input_wiring.py:118-128`, `tests/test_backend_protocols.py:111-114`
- Create: `tests/fixtures/mouse.html`
- Test: `tests/test_cli_input_devices.py`

**Interfaces:**
- Consumes: `Page.mouse`, `SessionHandler._target`, `Locator.first`, `Locator.scroll_into_view_if_needed`, `Locator.bounding_box`, `main._target_args`, `console._target`, `output.emit`
- Produces:
  ```python
  Mouse.down(self, *, button: str = "left") -> None
  Mouse.up(self, *, button: str = "left") -> None
  Mouse.click(self, x: float, y: float, *, button: str = "left") -> None
  Mouse.dblclick(self, x: float, y: float, *, button: str = "left") -> None
  SessionHandler._pointer_center(self, args: dict[str, Any]) -> tuple[float, float]
  ```
  daemon ops `mouse_move`, `mouse_down`, `mouse_up`, `mouse_wheel`; `click`/`dblclick` accept `button`

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/mouse.html` with exactly this content:

```html
<!doctype html>
<html>
  <head>
    <title>mouse fixture</title>
    <style>
      #pad { position: absolute; left: 0; top: 60px; width: 300px; height: 160px; background: #eee; }
    </style>
  </head>
  <body>
    <div id="pad">pad</div>
    <div id="ctxres"></div>
    <div id="auxres"></div>
    <div id="downres"></div>
    <div id="upres"></div>
    <div id="wheelres"></div>
    <script>
      // e.button: 0 = left, 1 = middle, 2 = right. Every result div records the
      // button index so a test can prove WHICH button the CLI actually sent.
      var pad = document.getElementById('pad');
      pad.addEventListener('contextmenu', function (e) {
        e.preventDefault();
        document.getElementById('ctxres').textContent = 'context';
      });
      pad.addEventListener('auxclick', function (e) {
        document.getElementById('auxres').textContent = 'aux-' + e.button;
      });
      pad.addEventListener('mousedown', function (e) {
        document.getElementById('downres').textContent = 'down-' + e.button;
      });
      pad.addEventListener('mouseup', function (e) {
        document.getElementById('upres').textContent = 'up-' + e.button;
      });
      window.addEventListener('wheel', function (e) {
        document.getElementById('wheelres').textContent = 'wheel-' + Math.round(e.deltaY);
      }, { passive: true });
    </script>
  </body>
</html>
```

- [ ] **Step 2: Write the failing test**

Append to `tests/test_cli_input_devices.py`:

```python
# ---------------------------------------------------------------------------
# Mouse device: mousemove / mousedown / mouseup / mousewheel, and --button
# ---------------------------------------------------------------------------


class _RecordingMouse:
    def __init__(self, log: list[str]) -> None:
        self._log = log

    def move(self, x: float, y: float) -> None:
        self._log.append(f"mouse.move:{x},{y}")

    def down(self, *, button: str = "left") -> None:
        self._log.append(f"mouse.down:{button}")

    def up(self, *, button: str = "left") -> None:
        self._log.append(f"mouse.up:{button}")

    def click(self, x: float, y: float, *, button: str = "left") -> None:
        self._log.append(f"mouse.click:{x},{y},{button}")

    def dblclick(self, x: float, y: float, *, button: str = "left") -> None:
        self._log.append(f"mouse.dblclick:{x},{y},{button}")

    def wheel(self, delta_x: float, delta_y: float) -> None:
        self._log.append(f"mouse.wheel:{delta_x},{delta_y}")


class _BoxLocator:
    """Locator stub that reports a bounding box — what a non-left click needs."""

    def __init__(self, log: list[str], label: str) -> None:
        self._log = log
        self._label = label

    def first(self) -> _BoxLocator:
        return self

    def click(self) -> None:
        self._log.append(f"click:{self._label}")

    def dblclick(self) -> None:
        self._log.append(f"dblclick:{self._label}")

    def scroll_into_view_if_needed(self) -> None:
        self._log.append(f"scroll:{self._label}")

    def bounding_box(self) -> dict[str, float]:
        return {"x": 10.0, "y": 20.0, "width": 40.0, "height": 10.0}


class _MousePage:
    url = "http://x/"

    def __init__(self) -> None:
        self.log: list[str] = []

    @property
    def mouse(self) -> _RecordingMouse:
        return _RecordingMouse(self.log)

    def locator(self, selector: str, *, deep: bool = False) -> _BoxLocator:
        return _BoxLocator(self.log, f"loc({selector})")


def test_mouse_facade_forwards_the_button() -> None:
    """Mouse.down/up/click/dblclick must pass `button` down to the delegate."""
    from visus.web.api.input import Mouse

    calls: list[tuple[str, object]] = []

    class _Delegate:
        def mouse_move(self, x: float, y: float) -> None:
            calls.append(("move", (x, y)))

        def mouse_down(self, *, button: str = "left") -> None:
            calls.append(("down", button))

        def mouse_up(self, *, button: str = "left") -> None:
            calls.append(("up", button))

        def mouse_click(self, x: float, y: float, *, button: str = "left") -> None:
            calls.append(("click", (x, y, button)))

        def mouse_dblclick(self, x: float, y: float, *, button: str = "left") -> None:
            calls.append(("dblclick", (x, y, button)))

        def mouse_wheel(self, delta_x: float, delta_y: float) -> None:
            calls.append(("wheel", (delta_x, delta_y)))

    m = Mouse(_Delegate())  # type: ignore[arg-type]
    m.down(button="right")
    m.up(button="right")
    m.click(1.0, 2.0, button="middle")
    m.dblclick(3.0, 4.0)
    m.wheel(0.0, 120.0)
    assert calls == [
        ("down", "right"),
        ("up", "right"),
        ("click", (1.0, 2.0, "middle")),
        ("dblclick", (3.0, 4.0, "left")),
        ("wheel", (0.0, 120.0)),
    ]


def test_op_mouse_move_down_up_wheel() -> None:
    page = _MousePage()
    h = _handler(page)
    assert h.handle("mouse_move", {"x": 5, "y": 6})["result"] == "moved to (5.0, 6.0)"
    assert h.handle("mouse_down", {"button": "right"})["result"] == "right button down"
    assert h.handle("mouse_up", {"button": "right"})["result"] == "right button up"
    assert h.handle("mouse_wheel", {"delta_x": 0, "delta_y": 120})["result"] == (
        "scrolled by (0.0, 120.0)"
    )
    assert page.log == [
        "mouse.move:5.0,6.0",
        "mouse.down:right",
        "mouse.up:right",
        "mouse.wheel:0.0,120.0",
    ]


def test_op_click_default_button_still_uses_the_locator() -> None:
    """The left path must stay on the actionability click — no pointer geometry."""
    page = _MousePage()
    h = _handler(page)
    assert h.handle("click", {"selector": "#b"})["result"] == "clicked"
    assert h.handle("dblclick", {"selector": "#b"})["result"] == "double-clicked"
    assert page.log == ["click:loc(#b)", "dblclick:loc(#b)"]


def test_op_click_and_dblclick_with_a_non_left_button() -> None:
    page = _MousePage()
    h = _handler(page)
    out = h.handle("click", {"selector": "#b", "button": "right"})["result"]
    assert out == "clicked with the right button"
    # centre of {x:10, y:20, w:40, h:10}
    assert page.log == ["scroll:loc(#b)", "mouse.click:30.0,25.0,right"]
    page.log.clear()
    out = h.handle("dblclick", {"selector": "#b", "button": "middle"})["result"]
    assert out == "double-clicked with the middle button"
    assert page.log == ["scroll:loc(#b)", "mouse.dblclick:30.0,25.0,middle"]


def test_cli_mouse_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: calls.append((op, args or {})) or "ok"
    )
    assert runner.invoke(app, ["mousemove", "12", "34"]).exit_code == 0
    assert runner.invoke(app, ["mousedown", "--button", "right"]).exit_code == 0
    assert runner.invoke(app, ["mouseup", "--button", "right"]).exit_code == 0
    assert runner.invoke(app, ["mousewheel", "0", "240"]).exit_code == 0
    assert calls[0] == ("mouse_move", {"x": 12.0, "y": 34.0})
    assert calls[1] == ("mouse_down", {"button": "right"})
    assert calls[2] == ("mouse_up", {"button": "right"})
    assert calls[3] == ("mouse_wheel", {"delta_x": 0.0, "delta_y": 240.0})


def test_cli_click_button_flag_only_sent_when_not_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default payload must stay `{"index": N}` so existing tests still hold."""
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: calls.append((op, args or {})) or "ok"
    )
    assert runner.invoke(app, ["click", "2"]).exit_code == 0
    assert runner.invoke(app, ["click", "2", "--button", "right"]).exit_code == 0
    assert runner.invoke(app, ["dblclick", "2", "-b", "middle"]).exit_code == 0
    assert calls[0] == ("click", {"index": 2})
    assert calls[1] == ("click", {"index": 2, "button": "right"})
    assert calls[2] == ("dblclick", {"index": 2, "button": "middle"})


def test_repl_mouse_and_button_clicks() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return "ok"

    console.dispatch("mousemove 12 34", send)
    console.dispatch("mousedown right", send)
    console.dispatch("mouseup right", send)
    console.dispatch("mousewheel 0 240", send)
    console.dispatch("click 3 right", send)
    console.dispatch("dblclick #b middle", send)
    console.dispatch("click 3", send)
    assert calls[0] == ("mouse_move", {"x": 12.0, "y": 34.0})
    assert calls[1] == ("mouse_down", {"button": "right"})
    assert calls[2] == ("mouse_up", {"button": "right"})
    assert calls[3] == ("mouse_wheel", {"delta_x": 0.0, "delta_y": 240.0})
    assert calls[4] == ("click", {"index": 3, "button": "right"})
    assert calls[5] == ("dblclick", {"selector": "#b", "button": "middle"})
    assert calls[6] == ("click", {"index": 3})
    help_text = console.dispatch("help", send)
    for cmd in ("mousemove", "mousedown", "mouseup", "mousewheel"):
        assert cmd in help_text


@pytest.mark.browser
def test_mouse_buttons_against_a_real_page(base_url: str) -> None:
    """mouse.html records e.button, so this proves the right index reached the DOM."""
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/mouse.html"
    )

    def text(el: str) -> object:
        return h.handle(
            "eval", {"expression": f"() => document.getElementById('{el}').textContent"}
        )["result"]["result"]

    try:
        assert h.handle("mouse_move", {"x": 150, "y": 140})["ok"] is True
        assert h.handle("mouse_down", {"button": "middle"})["ok"] is True
        assert h.handle("mouse_up", {"button": "middle"})["ok"] is True
        assert text("downres") == "down-1"
        assert text("upres") == "up-1"
        assert text("auxres") == "aux-1"

        assert h.handle("mouse_wheel", {"delta_x": 0, "delta_y": 200})["ok"] is True
        assert str(text("wheelres")).startswith("wheel-")
    finally:
        h.close()


@pytest.mark.browser
def test_right_click_opens_the_context_menu(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/mouse.html"
    )
    try:
        out = h.handle("click", {"selector": "#pad", "button": "right"})
        assert out["ok"] is True, out
        assert out["result"] == "clicked with the right button"
        marker = h.handle(
            "eval", {"expression": "() => document.getElementById('ctxres').textContent"}
        )
        assert marker["result"]["result"] == "context"
        down = h.handle(
            "eval", {"expression": "() => document.getElementById('downres').textContent"}
        )
        assert down["result"]["result"] == "down-2"
    finally:
        h.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_input_devices.py -m "not browser" -k "mouse or button" -v --no-cov`
Expected: FAIL — `test_mouse_facade_forwards_the_button` raises `TypeError: Mouse.down() got an unexpected keyword argument 'button'`.

- [ ] **Step 4: Widen the mouse device down to the driver**

In `src/visus/web/api/input.py`, replace `Mouse.down`/`up`/`click`/`dblclick` (`:25-39`) with:

```python
    def down(self, *, button: str = "left") -> None:
        """Press (hold) a mouse button at the current position.

        ``button`` is ``"left"`` (default), ``"middle"`` or ``"right"``.
        """
        self._d.mouse_down(button=button)

    def up(self, *, button: str = "left") -> None:
        """Release a held mouse button (``"left"``, ``"middle"`` or ``"right"``)."""
        self._d.mouse_up(button=button)

    def click(self, x: float, y: float, *, button: str = "left") -> None:
        """Move to (x, y) and perform a single click with ``button``."""
        self._d.mouse_click(x, y, button=button)

    def dblclick(self, x: float, y: float, *, button: str = "left") -> None:
        """Move to (x, y) and perform a double click with ``button``."""
        self._d.mouse_dblclick(x, y, button=button)
```

In `src/visus/web/backends/base.py`, replace the four protocol lines (`:87-90`) with:

```python
    def mouse_down(self, *, button: str = "left") -> None: ...
    def mouse_up(self, *, button: str = "left") -> None: ...
    def mouse_click(self, x: float, y: float, *, button: str = "left") -> None: ...
    def mouse_dblclick(self, x: float, y: float, *, button: str = "left") -> None: ...
```

In `src/visus/web/backends/selenium/driver_delegate.py`, add the import next to the other selenium imports (after `from selenium.webdriver.common.actions.action_builder import ActionBuilder`, `:19`):

```python
from selenium.webdriver.common.actions.mouse_button import MouseButton
```

and the button map + helper immediately after `_MODMAP` (`:49`):

```python
# Public button names → the W3C pointer button index. Kept here (never in a
# public signature) so the hidden-engine rule holds: callers pass a plain str.
_BUTTONS = {"left": MouseButton.LEFT, "middle": MouseButton.MIDDLE, "right": MouseButton.RIGHT}


def _pointer_button(name: str) -> int:
    """Map ``"left"``/``"middle"``/``"right"`` to the pointer button index (0/1/2)."""
    try:
        return int(_BUTTONS[name.lower()])
    except KeyError:
        raise errors.VisusWebError(
            f"unknown mouse button {name!r} — use 'left', 'middle' or 'right'"
        ) from None
```

Replace `mouse_down`/`mouse_up`/`mouse_click`/`mouse_dblclick` (`:775-809`) with:

```python
    def mouse_down(self, *, button: str = "left") -> None:
        self._activate()
        ab = ActionBuilder(self._driver)
        ab.pointer_action.pointer_down(_pointer_button(button))  # type: ignore[no-untyped-call]
        ab.perform()

    def mouse_up(self, *, button: str = "left") -> None:
        self._activate()
        ab = ActionBuilder(self._driver)
        ab.pointer_action.pointer_up(_pointer_button(button))  # type: ignore[no-untyped-call]
        ab.perform()

    def mouse_click(self, x: float, y: float, *, button: str = "left") -> None:
        self._activate()
        self._mouse_x, self._mouse_y = int(x), int(y)
        b = _pointer_button(button)
        ab = ActionBuilder(self._driver)
        ab.pointer_action.move_to_location(  # type: ignore[no-untyped-call]
            self._mouse_x, self._mouse_y
        ).pointer_down(b).pointer_up(b)
        ab.perform()

    def mouse_dblclick(self, x: float, y: float, *, button: str = "left") -> None:
        self._activate()
        self._mouse_x, self._mouse_y = int(x), int(y)
        b = _pointer_button(button)
        ab = ActionBuilder(self._driver)
        (
            ab.pointer_action.move_to_location(  # type: ignore[no-untyped-call]
                self._mouse_x, self._mouse_y
            )
            .pointer_down(b)
            .pointer_up(b)
            .pointer_down(b)
            .pointer_up(b)
        )
        ab.perform()
```

In `src/visus/web/async_api/__init__.py`, replace `AsyncMouse.down`/`up`/`click`/`dblclick` (`:729-739`) so the async mirror keeps the same parameter names:

```python
    async def down(self, *, button: str = "left") -> None:
        await asyncio.to_thread(lambda: self._m.down(button=button))

    async def up(self, *, button: str = "left") -> None:
        await asyncio.to_thread(lambda: self._m.up(button=button))

    async def click(self, x: float, y: float, *, button: str = "left") -> None:
        await asyncio.to_thread(lambda: self._m.click(x, y, button=button))

    async def dblclick(self, x: float, y: float, *, button: str = "left") -> None:
        await asyncio.to_thread(lambda: self._m.dblclick(x, y, button=button))
```

- [ ] **Step 5: Keep the two pre-existing delegate fakes in sync**

In `tests/test_input_wiring.py`, replace the four mouse stubs (`:118-128`) — without this the fake raises `TypeError` and `TestMouseProperty` fails:

```python
    def mouse_down(self, *, button="left"):
        self.calls.append(("mouse_down", button))

    def mouse_up(self, *, button="left"):
        self.calls.append(("mouse_up", button))

    def mouse_click(self, x, y, *, button="left"):
        self.calls.append(("mouse_click", x, y, button))

    def mouse_dblclick(self, x, y, *, button="left"):
        self.calls.append(("mouse_dblclick", x, y, button))
```

and the four assertions that read them (`:174-188`):

```python
    def test_mouse_down_delegates(self, page, fake_page):
        page.mouse.down()
        assert ("mouse_down", "left") in fake_page.calls

    def test_mouse_up_delegates(self, page, fake_page):
        page.mouse.up()
        assert ("mouse_up", "left") in fake_page.calls

    def test_mouse_click_delegates(self, page, fake_page):
        page.mouse.click(100.0, 200.0)
        assert ("mouse_click", 100.0, 200.0, "left") in fake_page.calls

    def test_mouse_dblclick_delegates(self, page, fake_page):
        page.mouse.dblclick(50.0, 75.0)
        assert ("mouse_dblclick", 50.0, 75.0, "left") in fake_page.calls
```

In `tests/test_backend_protocols.py`, replace `:111-114` so the conformance fake documents the real shape:

```python
    def mouse_down(self, *, button="left"): ...
    def mouse_up(self, *, button="left"): ...
    def mouse_click(self, x, y, *, button="left"): ...
    def mouse_dblclick(self, x, y, *, button="left"): ...
```

- [ ] **Step 6: Add the daemon ops**

In `src/visus/web/cli/session_server.py`, replace `_op_click` (`:245-247`):

```python
    def _op_click(self, args: dict[str, Any]) -> str:
        """Click the target.

        ``button`` is ``left`` (default), ``middle`` or ``right``. A non-left
        click goes through the pointer device at the target's centre, because
        the actionability click path is left-button only.
        """
        button = str(args.get("button") or "left")
        if button == "left":
            self._target(args).click()
            return "clicked"
        x, y = self._pointer_center(args)
        self.page().mouse.click(x, y, button=button)
        return f"clicked with the {button} button"
```

replace `_op_dblclick` (`:338-340`):

```python
    def _op_dblclick(self, args: dict[str, Any]) -> str:
        """Double-click the target (``button``: left, middle or right)."""
        button = str(args.get("button") or "left")
        if button == "left":
            self._target(args).dblclick()
            return "double-clicked"
        x, y = self._pointer_center(args)
        self.page().mouse.dblclick(x, y, button=button)
        return f"double-clicked with the {button} button"
```

and add the pointer helper plus the four device ops immediately after `_op_upload` (`:365-368`):

```python
    # --- pointer device --------------------------------------------------
    def _pointer_center(self, args: dict[str, Any]) -> tuple[float, float]:
        """Viewport centre of the action target, scrolled into view first.

        ``Locator.bounding_box`` and ``Page.mouse`` both work in viewport
        coordinates, so no conversion is needed between them.
        """
        loc = self._target(args).first()
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        if box is None:
            raise ValueError("target has no bounding box — it may be hidden or detached")
        return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    def _op_mouse_move(self, args: dict[str, Any]) -> str:
        """Move the pointer to absolute viewport coordinates."""
        x, y = float(args.get("x", 0)), float(args.get("y", 0))
        self.page().mouse.move(x, y)
        return f"moved to ({x}, {y})"

    def _op_mouse_down(self, args: dict[str, Any]) -> str:
        """Hold a mouse button down at the current pointer position."""
        button = str(args.get("button") or "left")
        self.page().mouse.down(button=button)
        return f"{button} button down"

    def _op_mouse_up(self, args: dict[str, Any]) -> str:
        """Release a mouse button held by ``mouse_down``."""
        button = str(args.get("button") or "left")
        self.page().mouse.up(button=button)
        return f"{button} button up"

    def _op_mouse_wheel(self, args: dict[str, Any]) -> str:
        """Scroll by a wheel delta at the current pointer position."""
        dx, dy = float(args.get("delta_x", 0)), float(args.get("delta_y", 0))
        self.page().mouse.wheel(dx, dy)
        return f"scrolled by ({dx}, {dy})"
```

Add `"mouse_move"`, `"mouse_down"`, `"mouse_up"` and `"mouse_wheel"` to the `_MUTATING_OPS` frozenset PLAN 4 created in this module.

- [ ] **Step 7: Add the CLI commands**

In `src/visus/web/cli/main.py`, replace `click` (`:304-313`) and `dblclick` (`:590-599`) with:

```python
@app.command()
def click(
    index: int = typer.Argument(None, help="Field index from the last list-fields."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    button: str = typer.Option(
        "left", "--button", "-b", help="Mouse button: left (default), middle or right."
    ),
) -> None:
    """Click a field by index or by --selector/--role/--text."""
    from visus.web.cli import output

    args = _target_args(index, selector, role, name, text)
    if button != "left":
        args["button"] = button  # keep the default payload minimal
    output.emit(_send("click", args))
```

```python
@app.command()
def dblclick(
    index: int = typer.Argument(None),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    button: str = typer.Option(
        "left", "--button", "-b", help="Mouse button: left (default), middle or right."
    ),
) -> None:
    """Double-click a field by index or by --selector/--role/--text."""
    from visus.web.cli import output

    args = _target_args(index, selector, role, name, text)
    if button != "left":
        args["button"] = button
    output.emit(_send("dblclick", args))
```

and add the four device commands right after `keyup`:

```python
# ---------------------------------------------------------------------------
# Mouse device (absolute viewport coordinates)
# ---------------------------------------------------------------------------


@app.command()
def mousemove(
    x: float = typer.Argument(..., help="Viewport X coordinate."),
    y: float = typer.Argument(..., help="Viewport Y coordinate."),
) -> None:
    """Move the pointer to absolute viewport coordinates."""
    from visus.web.cli import output

    output.emit(_send("mouse_move", {"x": x, "y": y}))


@app.command()
def mousedown(
    button: str = typer.Option("left", "--button", "-b", help="left, middle or right."),
) -> None:
    """Hold a mouse button down at the current pointer position."""
    from visus.web.cli import output

    output.emit(_send("mouse_down", {"button": button}))


@app.command()
def mouseup(
    button: str = typer.Option("left", "--button", "-b", help="left, middle or right."),
) -> None:
    """Release a mouse button held by `visus mousedown`."""
    from visus.web.cli import output

    output.emit(_send("mouse_up", {"button": button}))


@app.command()
def mousewheel(
    delta_x: float = typer.Argument(..., help="Horizontal scroll delta in pixels."),
    delta_y: float = typer.Argument(..., help="Vertical scroll delta in pixels."),
) -> None:
    """Scroll by a wheel delta at the current pointer position."""
    from visus.web.cli import output

    output.emit(_send("mouse_wheel", {"delta_x": delta_x, "delta_y": delta_y}))
```

- [ ] **Step 8: Add the REPL branches**

In `src/visus/web/cli/console.py`, add this predicate right after `_is_confidence`:

```python
_MOUSE_BUTTONS = ("left", "middle", "right")


def _button_arg(tokens: list[str]) -> dict[str, Any]:
    """An optional trailing ``left``/``middle``/``right`` word after a click target.

    The REPL cannot spell this as ``--button`` — ``_target`` consumes leading
    flags and would reject an unknown one — so it is a positional word, the same
    shape as ``press TARGET key``.
    """
    if tokens and tokens[0].lower() in _MOUSE_BUTTONS:
        return {"button": tokens[0].lower()}
    return {}
```

Replace the `click` and `dblclick` branches in `dispatch` with:

```python
        if cmd == "click":
            tgt, tail = _target(rest)
            return str(send("click", {**tgt, **_button_arg(tail)}))
```

```python
        if cmd == "dblclick":
            tgt, tail = _target(rest)
            return str(send("dblclick", {**tgt, **_button_arg(tail)}))
```

and add these branches right after the `keyup` branch:

```python
        if cmd == "mousemove":
            return str(send("mouse_move", {"x": float(rest[0]), "y": float(rest[1])}))
        if cmd == "mousedown":
            return str(send("mouse_down", {"button": rest[0] if rest else "left"}))
        if cmd == "mouseup":
            return str(send("mouse_up", {"button": rest[0] if rest else "left"}))
        if cmd == "mousewheel":
            return str(
                send("mouse_wheel", {"delta_x": float(rest[0]), "delta_y": float(rest[1])})
            )
```

In `_HELP`, replace these two lines

```
  click TARGET         click the target
```
```
  dblclick TARGET      double-click the target
```

with

```
  click TARGET [btn]   click the target (btn: left|middle|right)
  dblclick TARGET [btn] double-click the target (btn: left|middle|right)
```

and add these four lines right after `keyup key`:

```
  mousemove x y        move the pointer to viewport coordinates
  mousedown [btn]      hold a mouse button down at the pointer
  mouseup [btn]        release a held mouse button
  mousewheel dx dy     scroll by a wheel delta at the pointer
```

- [ ] **Step 9: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_input_devices.py -m "not browser" -k "mouse or button" -v --no-cov`
Expected: PASS (7 passed)

- [ ] **Step 10: Run the browser tests**

Run: `uv run pytest tests/test_cli_input_devices.py -m browser -k "mouse or context_menu" -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 11: Verify the pre-existing input and click suites still pass**

Run: `uv run pytest tests/test_input_wiring.py tests/test_backend_protocols.py -q --no-cov`
Expected: PASS

Run: `uv run pytest tests/test_cli_session.py -k "click" -v --no-cov`
Expected: PASS — the default payload is still `{"index": N}` and `_op_click` still returns `"clicked"`.

Run: `uv run pytest tests/test_e2e_input.py -q --no-cov`
Expected: PASS — `page.mouse.click(x, y)` keeps its old meaning (`button="left"`).

- [ ] **Step 12: Update the README**

In `README.md`, in the **Actions** table, replace the `visus click` and `visus dblclick` rows with:

```markdown
| `visus click [idx] [target] [--button <b>]` | Click a field (`--button left`/`middle`/`right`). |
| `visus dblclick [idx] [target] [--button <b>]` | Double-click a field. |
```

and add these three rows at the end of the same table:

```markdown
| `visus mousemove <x> <y>` | Move the pointer to absolute viewport coordinates. |
| `visus mousedown [--button <b>]` / `visus mouseup [--button <b>]` | Press / release a mouse button at the pointer. |
| `visus mousewheel <dx> <dy>` | Scroll by a wheel delta at the pointer (lazy-load lists, canvases). |
```

- [ ] **Step 13: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: `All checks passed!` and `Success: no issues found`

```bash
git add src/visus/web/api/input.py src/visus/web/backends/base.py src/visus/web/backends/selenium/driver_delegate.py src/visus/web/async_api/__init__.py src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/fixtures/mouse.html tests/test_cli_input_devices.py tests/test_input_wiring.py tests/test_backend_protocols.py README.md
git commit -m "feat(cli): standalone mouse commands and --button on click/dblclick"
```

---

### Task 10: `visus highlight [idx] [--style] [--hide]`

Closes the first half of **row 26**. The primitive already exists — `bundle.js:426-445` defines `highlight(el)` and exports it at `:879`, `bundle.js:446-449` defines `unhighlight` (exported `:880`), and `api/locator.py:479-482` already wraps the draw call. The CLI has only the all-or-nothing pair: `list-fields` highlights *everything* and `visus clear` erases *everything*. There is no way to point at one element, which is exactly what a human reviewing an agent's choice needs.

`--style` needs one small bundle change: `highlight(el)` hard-codes its border and glow, so it takes an optional second argument that replaces them.

**Files:**
- Modify: `src/visus/web/backends/selenium/js/bundle.js:426-445` (`highlight(el, style)`)
- Modify: `src/visus/web/api/locator.py:479-482` (`Locator.highlight(*, style=None)`)
- Modify: `src/visus/web/async_api/__init__.py:912-913` (`AsyncLocator.highlight`)
- Modify: `src/visus/web/cli/session_server.py` (new `_op_highlight`)
- Modify: `src/visus/web/cli/main.py` (new `highlight` command)
- Modify: `src/visus/web/cli/console.py` (REPL branch + `_HELP`)
- Modify: `README.md` (Capture / vision / utilities table)
- Test: `tests/test_cli_page_ops.py`

**Interfaces:**
- Consumes: `Locator.evaluate`, `Locator.first`, `Page.locator`, `Page.evaluate`, `SessionHandler._target`, `main._target_args`, `console._target`, `output.emit`
- Produces: `Locator.highlight(self, *, style: str | None = None) -> None`; daemon op `highlight` → `"highlighted"` / `"highlight cleared"`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_page_ops.py`:

```python
"""Page-level CLI surface: highlight, boxes, scoped eval, resize, storage,
cookies, generate-locator, session pdf/screenshot."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


class _FakeBrowser:
    def close(self) -> None:
        pass

    @property
    def contexts(self) -> list[Any]:
        return []


def _handler(page: Any) -> session_server.SessionHandler:
    h = session_server.SessionHandler(engine="chrome", headless=True)
    h._browser = _FakeBrowser()  # type: ignore[assignment]
    h._page = page
    return h


class _HighlightLocator:
    def __init__(self, log: list[str], label: str) -> None:
        self._log = log
        self._label = label

    def first(self) -> _HighlightLocator:
        return self

    def count(self) -> int:
        self._log.append(f"count:{self._label}")
        return 1

    def highlight(self, *, style: str | None = None) -> None:
        self._log.append(f"highlight:{self._label}:{style}")


class _HighlightPage:
    url = "http://x/"

    def __init__(self) -> None:
        self.log: list[str] = []

    def locator(self, selector: str, *, deep: bool = False) -> _HighlightLocator:
        return _HighlightLocator(self.log, f"loc({selector})")

    def evaluate(self, expression: str, arg: object = None) -> object:
        self.log.append(f"eval:{expression}")
        return None


def test_op_highlight_targets_one_element() -> None:
    page = _HighlightPage()
    h = _handler(page)
    assert h.handle("highlight", {"selector": "#b"})["result"] == "highlighted"
    assert page.log == ["highlight:loc(#b):None"]
    page.log.clear()
    h.handle("highlight", {"selector": "#b", "style": "2px dashed #0a0"})
    assert page.log == ["highlight:loc(#b):2px dashed #0a0"]


def test_op_highlight_hide_forces_the_bundle_then_unhighlights() -> None:
    page = _HighlightPage()
    h = _handler(page)
    assert h.handle("highlight", {"hide": True})["result"] == "highlight cleared"
    assert page.log[0] == "count:loc(html)"  # forces window.__visus to exist
    assert "unhighlight" in page.log[1]


def test_cli_highlight_and_hide(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: calls.append((op, args or {})) or "ok"
    )
    assert runner.invoke(app, ["highlight", "3"]).exit_code == 0
    assert runner.invoke(app, ["highlight", "-s", "#b", "--style", "2px solid red"]).exit_code == 0
    assert runner.invoke(app, ["highlight", "--hide"]).exit_code == 0
    assert calls[0] == ("highlight", {"index": 3})
    assert calls[1][1]["selector"] == "#b" and calls[1][1]["style"] == "2px solid red"
    assert calls[2] == ("highlight", {"hide": True})


def test_repl_highlight() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return "ok"

    console.dispatch("highlight 3", send)
    console.dispatch("highlight #b 2px dashed #0a0", send)
    console.dispatch("highlight hide", send)
    assert calls[0] == ("highlight", {"index": 3})
    assert calls[1] == ("highlight", {"selector": "#b", "style": "2px dashed #0a0"})
    assert calls[2] == ("highlight", {"hide": True})
    assert "highlight" in console.dispatch("help", send)


@pytest.mark.browser
def test_highlight_draws_and_hides_a_box_on_a_real_page(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )

    def js(expr: str) -> object:
        return h.handle("eval", {"expression": expr})["result"]["result"]

    try:
        assert h.handle("highlight", {"selector": "#btn"})["ok"] is True
        # highlight() appends the box AND a centre dot, both tagged.
        assert js("() => document.querySelectorAll('[data-visus-highlight]').length") == 2

        styled = h.handle("highlight", {"selector": "#btn", "style": "2px dashed rgb(0, 170, 0)"})
        assert styled["ok"] is True, styled
        assert js("() => document.querySelector('[data-visus-highlight]').style.borderStyle") == (
            "dashed"
        )

        assert h.handle("highlight", {"hide": True})["result"] == "highlight cleared"
        assert js("() => document.querySelectorAll('[data-visus-highlight]').length") == 0
    finally:
        h.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k highlight -v --no-cov`
Expected: FAIL — `test_op_highlight_targets_one_element` gets `{"ok": False, "error": "ValueError: unknown op 'highlight'"}`, so `resp["result"]` raises `KeyError: 'result'`.

- [ ] **Step 3: Teach the bundle and the locator about `style`**

In `src/visus/web/backends/selenium/js/bundle.js`, replace `highlight` (`:426-445`) with:

```js
  function highlight(el, style) {
    unhighlight();
    if (!el || !el.getBoundingClientRect) return null;
    var r = el.getBoundingClientRect();
    // `style` (optional) replaces the default border + glow, e.g. "2px dashed #0a0".
    var edge = style
      ? "border:" + style + ";"
      : "border:3px solid #cc785c;box-shadow:0 0 0 2px rgba(204,120,92,.35);";
    var box = document.createElement("div");
    box.setAttribute("data-visus-highlight", "1");
    box.style.cssText =
      "position:fixed;z-index:2147483647;pointer-events:none;box-sizing:border-box;" + edge +
      "left:" + r.left + "px;top:" + r.top + "px;width:" + r.width + "px;height:" + r.height + "px;";
    var cx = document.createElement("div");
    cx.setAttribute("data-visus-highlight", "1");
    cx.style.cssText =
      "position:fixed;z-index:2147483647;pointer-events:none;width:10px;height:10px;" +
      "border:2px solid #cc785c;border-radius:50%;" +
      "left:" + (r.left + r.width / 2 - 5) + "px;top:" + (r.top + r.height / 2 - 5) + "px;";
    document.documentElement.appendChild(box);
    document.documentElement.appendChild(cx);
    return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
  }
```

In `src/visus/web/api/locator.py`, replace `highlight` (`:479-482`) with:

```python
    def highlight(self, *, style: str | None = None) -> None:
        """Draw the debug highlight box around the element (remove with the next
        highlight, or via ``page.clear_highlights()`` for the numbered overlay).

        ``style`` replaces the default border, e.g. ``"2px dashed #0a0"``.
        """
        self.evaluate("(el, style) => window.__visus.highlight(el, style)", style)
```

In `src/visus/web/async_api/__init__.py`, replace `AsyncLocator.highlight` (`:912-913`):

```python
    async def highlight(self, *, style: str | None = None) -> None:
        await asyncio.to_thread(lambda: self._loc.highlight(style=style))
```

- [ ] **Step 4: Add the daemon op, command and REPL branch**

In `src/visus/web/cli/session_server.py`, add after `_op_clear_highlights` (`:296-298`):

```python
    def _op_highlight(self, args: dict[str, Any]) -> str:
        """Draw (or clear) the single-element debug highlight box.

        Distinct from ``clear_highlights``, which removes the NUMBERED overlay
        drawn by ``list_fields``. ``style`` replaces the default border;
        ``hide=True`` removes the box.
        """
        page = self.page()
        if args.get("hide"):
            # A page that never ran a locator has no window.__visus yet; resolving
            # one forces the bundle in (same trick as cli/codegen.py:40-41).
            page.locator("html").count()
            page.evaluate("() => window.__visus.unhighlight()")
            return "highlight cleared"
        style = args.get("style")
        self._target(args).first().highlight(style=str(style) if style else None)
        return "highlighted"
```

`highlight` is deliberately **not** added to `_MUTATING_OPS`: it draws a debug overlay and changes no page state worth echoing, exactly like the existing `clear_highlights`.

In `src/visus/web/cli/main.py`, add after the `clear_highlights` command (`:449-452`):

```python
@app.command()
def highlight(
    index: int = typer.Argument(None, help="Field index from the last list-fields."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    style: str = typer.Option(None, "--style", help='CSS border, e.g. "2px dashed #0a0".'),
    hide: bool = typer.Option(False, "--hide", help="Remove the box instead of drawing it."),
) -> None:
    """Draw a highlight box around ONE element (`--hide` removes it)."""
    from visus.web.cli import output

    if hide:
        output.emit(_send("highlight", {"hide": True}))
        return
    args = _target_args(index, selector, role, name, text)
    if style:
        args["style"] = style
    output.emit(_send("highlight", args))
```

In `src/visus/web/cli/console.py`, add this branch right after the `clear` branch:

```python
        if cmd == "highlight":
            if rest and rest[0].lower() in ("hide", "off", "--hide"):
                return str(send("highlight", {"hide": True}))
            hl_target, hl_tail = _target(rest)
            hl_args: dict[str, Any] = dict(hl_target)
            if hl_tail:
                hl_args["style"] = " ".join(hl_tail)
            return str(send("highlight", hl_args))
```

and this `_HELP` line right after `clear`:

```
  highlight TGT [style] box one element (`highlight hide` removes it)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k highlight -v --no-cov`
Expected: PASS (4 passed)

- [ ] **Step 6: Run the browser test**

Run: `uv run pytest tests/test_cli_page_ops.py::test_highlight_draws_and_hides_a_box_on_a_real_page -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 7: Verify the pre-existing highlight tests still pass**

Run: `uv run pytest tests/test_e2e_locators_more.py tests/test_e2e_fields.py -q --no-cov`
Expected: PASS — `Locator.highlight()` with no argument passes `style=None`, and the bundle falls back to the original border + glow.

- [ ] **Step 8: Update the README**

In `README.md`, in the **Capture / vision / utilities** table, add a row right after the `visus clear` row:

```markdown
| `visus highlight [idx] [target] [--style <css>] [--hide]` | Box a single element on the live page (`visus clear` erases the numbered overlay). |
```

- [ ] **Step 9: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/backends/selenium/js/bundle.js src/visus/web/api/locator.py src/visus/web/async_api/__init__.py src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_page_ops.py README.md
git commit -m "feat(cli): add `visus highlight` for a single element"
```

---

### Task 11: `--boxes` on `list-fields` and `snapshot`

Closes the second half of **row 26**. `bundle.js:668` already computes `el.getBoundingClientRect()` for every enumerated field and ships it as `rect` at `:695` — and `driver_delegate.py:688-712` builds the `Field` from that dict **without ever reading `rect`**, so the geometry is computed and thrown away on every `list-fields`. Surfacing it turns `visus find-image`/`read-text` from "search the whole screenshot" into "look here", and gives a vision model the pixel coordinates behind each number in the overlay.

The rect is **opt-in**: it is stripped from both payloads unless `boxes` is asked for, because it roughly doubles the JSON an agent normally reads for `#`/`kind`/`name` only.

**Files:**
- Modify: `src/visus/web/api/fields.py:37` (`Field.box`)
- Modify: `src/visus/web/backends/selenium/driver_delegate.py:663-712` (read `rect`)
- Modify: `src/visus/web/backends/selenium/js/bundle.js:415-424` (`snapshot()` emits `rect`)
- Modify: `src/visus/web/cli/session_server.py:235-243` (`_op_list_fields`), `:323-324` (`_op_snapshot`)
- Modify: `src/visus/web/cli/console.py:56-93` (`format_fields`), REPL branches + `_HELP`
- Modify: `src/visus/web/cli/main.py:216-219` (`_format_fields`), `:284-301` (`list-fields`), `:520-543` (`snapshot`)
- Modify: `README.md` (Inspect table)
- Test: `tests/test_cli_page_ops.py`

**Interfaces:**
- Consumes: `Field.to_dict`, `Page.list_fields`, `Page.snapshot`, `output.emit`
- Produces: `Field.box: dict[str, float] | None = None`; `session_server._norm_rect(rect: Any) -> dict[str, float] | None`; `console.format_fields(..., boxes: bool = False)`; `list_fields`/`snapshot` ops accept `boxes: bool`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_page_ops.py`:

```python
# ---------------------------------------------------------------------------
# --boxes on list-fields / snapshot
# ---------------------------------------------------------------------------

from visus.web.api.fields import Field  # noqa: E402


def _field(index: int, name: str, box: dict[str, float] | None) -> Field:
    return Field(
        index=index,
        kind="button",
        tag="button",
        type=None,
        role="button",
        name=name,
        label=None,
        placeholder=None,
        value=None,
        checked=None,
        disabled=False,
        visible=True,
        frame=[],
        shadow=False,
        locator="#b",
        locator_kind="id",
        css="#b",
        xpath="//button",
        code='page.get_by_role("button", name="Go")',
        deep=False,
        box=box,
    )


class _BoxPage:
    url = "http://x/"

    def list_fields(
        self, *, kinds: Any = None, include_hidden: bool = False, highlight: bool = True
    ) -> list[Field]:
        return [_field(0, "Go", {"x": 1.0, "y": 2.0, "width": 30.0, "height": 12.0})]

    def snapshot(self) -> list[dict[str, Any]]:
        return [
            {"role": "button", "name": "Go", "rect": {"x": 1.0, "y": 2.0, "w": 30.0, "h": 12.0}}
        ]


def test_norm_rect_maps_the_bundle_keys_to_bounding_box_keys() -> None:
    assert session_server._norm_rect({"x": 1, "y": 2, "w": 3, "h": 4}) == {
        "x": 1.0,
        "y": 2.0,
        "width": 3.0,
        "height": 4.0,
    }
    assert session_server._norm_rect(None) is None
    assert session_server._norm_rect("nope") is None


def test_op_list_fields_strips_the_box_unless_asked() -> None:
    h = _handler(_BoxPage())
    plain = h.handle("list_fields", {})["result"]["fields"][0]
    assert "box" not in plain
    boxed = h.handle("list_fields", {"boxes": True})["result"]["fields"][0]
    assert boxed["box"] == {"x": 1.0, "y": 2.0, "width": 30.0, "height": 12.0}


def test_op_snapshot_strips_the_rect_unless_asked() -> None:
    h = _handler(_BoxPage())
    plain = h.handle("snapshot", {})["result"]["elements"][0]
    assert plain == {"role": "button", "name": "Go"}
    boxed = h.handle("snapshot", {"boxes": True})["result"]["elements"][0]
    assert boxed == {
        "role": "button",
        "name": "Go",
        "box": {"x": 1.0, "y": 2.0, "width": 30.0, "height": 12.0},
    }


def test_format_fields_adds_a_box_column() -> None:
    rows = [_field(0, "Go", {"x": 1.4, "y": 2.6, "width": 30.0, "height": 12.0}).to_dict()]
    plain = console.format_fields(rows, width=200)
    assert "BOX" not in plain
    boxed = console.format_fields(rows, width=200, boxes=True)
    assert "BOX" in boxed and "1,3,30,12" in boxed


def test_cli_list_fields_and_snapshot_boxes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        if op == "list_fields":
            return {
                "fields": [
                    _field(0, "Go", {"x": 1.0, "y": 2.0, "width": 30.0, "height": 12.0}).to_dict()
                ]
            }
        return {
            "elements": [
                {
                    "role": "button",
                    "name": "Go",
                    "box": {"x": 1.0, "y": 2.0, "width": 30.0, "height": 12.0},
                }
            ]
        }

    monkeypatch.setattr(session_client, "send", fake_send)
    r1 = runner.invoke(app, ["list-fields", "--boxes", "--no-highlight"])
    assert r1.exit_code == 0, r1.output
    assert calls[0][1]["boxes"] is True
    assert "BOX" in r1.output
    r2 = runner.invoke(app, ["snapshot", "--boxes"])
    assert r2.exit_code == 0
    assert calls[1] == ("snapshot", {"boxes": True})
    assert "BOX" in r2.output and "1,2,30,12" in r2.output


def test_repl_boxes() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "list_fields":
            return {"fields": []}
        return {"elements": []}

    console.dispatch("list --boxes", send)
    console.dispatch("snapshot --boxes", send)
    assert calls[0] == ("list_fields", {"boxes": True})
    assert calls[1] == ("snapshot", {"boxes": True})


@pytest.mark.browser
def test_boxes_come_from_a_real_page(base_url: str) -> None:
    """fields.html's #btn is a laid-out button, so its rect must be non-degenerate."""
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )
    try:
        fields = h.handle("list_fields", {"highlight": False, "boxes": True})["result"]["fields"]
        btn = next(f for f in fields if f["locator"] == "#btn")
        box = btn["box"]
        assert box is not None and box["width"] > 0 and box["height"] > 0

        elements = h.handle("snapshot", {"boxes": True})["result"]["elements"]
        go = next(e for e in elements if e["name"] == "Click me")
        assert go["box"]["width"] > 0
    finally:
        h.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k "box or rect" -v --no-cov`
Expected: FAIL — `_field(...)` raises `TypeError: Field.__init__() got an unexpected keyword argument 'box'`.

- [ ] **Step 3: Carry the rect through the foundation**

In `src/visus/web/api/fields.py`, add one field at the end of the dataclass (after `deep`, `:37`):

```python
    box: dict[str, float] | None = None
    """Viewport rect ``{x, y, width, height}`` at enumeration time, or ``None``.

    Same key names as :meth:`Locator.bounding_box`. Frozen at capture: it is the
    geometry the numbered overlay was drawn from, not a live measurement.
    """
```

In `src/visus/web/backends/selenium/driver_delegate.py`, add this helper right after the `_code` closure inside `list_fields` (after `:685`):

```python
        def _box(d: dict[str, object]) -> dict[str, float] | None:
            """The bundle's ``{x,y,w,h}`` rect, renamed to bounding_box()'s keys."""
            r = d.get("rect")
            if not isinstance(r, dict):
                return None
            return {
                "x": float(cast(float, r.get("x", 0))),
                "y": float(cast(float, r.get("y", 0))),
                "width": float(cast(float, r.get("w", 0))),
                "height": float(cast(float, r.get("h", 0))),
            }
```

and one argument to the `Field(...)` construction, right after `deep=bool(d.get("deep", False)),` (`:710`):

```python
                    box=_box(d),
```

In `src/visus/web/backends/selenium/js/bundle.js`, replace `snapshot` (`:415-424`) with:

```js
  function snapshot() {
    var roles = ["button", "link", "textbox", "searchbox", "checkbox", "radio", "combobox",
                 "heading", "tab", "menuitem", "option", "switch", "slider", "spinbutton"];
    var out = [], all = document.querySelectorAll("*");
    for (var i = 0; i < all.length; i++) {
      var e = all[i], r = computeRole(e);
      if (roles.indexOf(r) >= 0 && isVisible(e)) {
        // Same rect shape listFields already emits; callers drop it unless asked.
        var b = e.getBoundingClientRect();
        out.push({ role: r, name: accessibleName(e),
                   rect: { x: b.left, y: b.top, w: b.width, h: b.height } });
      }
    }
    return out;
  }
```

- [ ] **Step 4: Gate it behind `boxes` in the daemon**

In `src/visus/web/cli/session_server.py`, add this module-level helper right after `make_locator` (`:71`):

```python
def _norm_rect(rect: Any) -> dict[str, float] | None:
    """Normalise the JS bundle's ``{x,y,w,h}`` to ``bounding_box()``'s key names."""
    if not isinstance(rect, dict):
        return None
    return {
        "x": float(rect.get("x", 0)),
        "y": float(rect.get("y", 0)),
        "width": float(rect.get("w", 0)),
        "height": float(rect.get("h", 0)),
    }
```

Replace `_op_list_fields` (`:235-243`):

```python
    def _op_list_fields(self, args: dict[str, Any]) -> dict[str, Any]:
        """Enumerate interactive fields. ``boxes`` keeps each field's viewport rect.

        The rect is stripped by default: it roughly doubles the payload an agent
        usually reads for index/kind/name only.
        """
        kinds = args.get("kinds")
        include_hidden = bool(args.get("include_hidden", False))
        highlight = bool(args.get("highlight", True))
        fields = self.page().list_fields(
            kinds=kinds, include_hidden=include_hidden, highlight=highlight
        )
        self._fields = list(fields)
        rows = [f.to_dict() for f in fields]
        if not args.get("boxes"):
            for row in rows:
                row.pop("box", None)
        return {"fields": rows}
```

Replace `_op_snapshot` (`:323-324`):

```python
    def _op_snapshot(self, args: dict[str, Any]) -> dict[str, Any]:
        """Interactive elements as role/name dicts; ``boxes`` adds the viewport rect."""
        elements = self.page().snapshot()
        if not args.get("boxes"):
            return {
                "elements": [
                    {k: v for k, v in e.items() if k != "rect"} for e in elements
                ]
            }
        return {
            "elements": [
                {"role": e.get("role"), "name": e.get("name"), "box": _norm_rect(e.get("rect"))}
                for e in elements
            ]
        }
```

- [ ] **Step 5: Render the column**

In `src/visus/web/cli/console.py`, change `format_fields`'s signature and body (`:56-93`) — the header, the column set and the row loop:

```python
def format_fields(
    fields: list[dict[str, Any]], *, width: int | None = None, boxes: bool = False
) -> str:
    """Render fields as a pretty table: #, KIND, NAME, the ready VISUS call, CSS, XPATH.

    The VISUS column is copy-paste-ready and *frame-aware* — for an element inside
    an iframe it is wrapped in ``frame_locator(...)`` so a click/fill actually
    reaches it (a bare css/xpath would not). An ASCII box is used so the table
    renders correctly on any console encoding. ``boxes`` appends the field's
    viewport rect as ``x,y,w,h`` (from ``visus list-fields --boxes``).
    """
    if not fields:
        return "(no fields found)"
    from rich import box as rich_box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=rich_box.ASCII, header_style="bold", pad_edge=False, show_lines=True)
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("KIND", no_wrap=True)
    table.add_column("NAME", overflow="fold")
    table.add_column("VISUS (copy-paste)", overflow="fold", style="green")
    table.add_column("CSS", overflow="fold")
    table.add_column("XPATH", overflow="fold")
    if boxes:
        table.add_column("BOX x,y,w,h", no_wrap=True)
    for f in fields:
        name = str(f.get("name") or f.get("label") or f.get("placeholder") or "")
        cells = [
            str(f.get("index", "")),
            str(f.get("kind", "")),
            name,
            str(f.get("code", "")),
            str(f.get("css", "")),
            str(f.get("xpath", "")),
        ]
        if boxes:
            b = f.get("box")
            cells.append(
                f"{b['x']:.0f},{b['y']:.0f},{b['width']:.0f},{b['height']:.0f}"
                if isinstance(b, dict)
                else "-"
            )
        table.add_row(*cells)
    # Console() auto-detects the real terminal width (wide tables use the full
    # screen) and colour (TTY only); capture() preserves both. On a narrow pipe
    # rich folds long cells. `width` lets tests pin a deterministic size.
    console = Console(width=width) if width else Console()
    with console.capture() as cap:
        console.print(table)
    return cap.get().rstrip("\n")
```

Note the `from rich import box as rich_box` rename: the row variable `b` and the new `boxes` parameter would otherwise shadow nothing, but `box` as a module name next to a `box` column reads badly — the alias keeps both unambiguous.

Add the `--boxes` word to the REPL's `list` and `snapshot` branches — replace both with:

```python
        if cmd in ("list", "ls"):
            lf_args = {"boxes": True} if "--boxes" in rest else {}
            result = send("list_fields", lf_args)
            return format_fields(result.get("fields", []), boxes="--boxes" in rest)
```

```python
        if cmd == "snapshot":
            snap_args = {"boxes": True} if "--boxes" in rest else {}
            elements = send("snapshot", snap_args).get("elements", [])
            if not elements:
                return "(no elements)"
            if "--boxes" in rest:
                return "\n".join(
                    f"{str(e.get('role', '')):16} {str(e.get('name', '')):32} "
                    + _box_cell(e.get("box"))
                    for e in elements
                )
            return "\n".join(
                f"{str(e.get('role', '')):16} {e.get('name', '')}" for e in elements
            )
```

with this helper right after `_button_arg`:

```python
def _box_cell(b: Any) -> str:
    """Render a ``{x,y,width,height}`` rect as a compact ``x,y,w,h`` cell."""
    if not isinstance(b, dict):
        return "-"
    return f"{b['x']:.0f},{b['y']:.0f},{b['width']:.0f},{b['height']:.0f}"
```

and these two `_HELP` lines replacing the existing `list` and `snapshot` lines:

```
  list [--boxes]       enumerate + highlight interactive fields
  snapshot [--boxes]   list interactive elements (role/name)
```

In `src/visus/web/cli/main.py`, replace `_format_fields` (`:216-219`):

```python
def _format_fields(fields: list[dict[str, Any]], *, boxes: bool = False) -> str:
    from visus.web.cli.console import format_fields

    return format_fields(fields, boxes=boxes)
```

Add `boxes` to `list_fields` (`:284-301`) — the new option and the two lines that use it:

```python
@app.command("list-fields")
def list_fields(
    kind: str = typer.Option(None, "--kind", help="Comma-separated kinds (e.g. input,button)."),
    show_all: bool = typer.Option(False, "--all", help="Include hidden/disabled fields."),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
    no_highlight: bool = typer.Option(False, "--no-highlight", help="Skip the numbered overlay."),
    boxes: bool = typer.Option(False, "--boxes", help="Include each field's viewport rect."),
) -> None:
    """Enumerate interactive fields on the current page (numbered, highlighted)."""
    from visus.web.cli import output

    kinds = [k.strip() for k in kind.split(",") if k.strip()] if kind else None
    result = _send(
        "list_fields",
        {
            "kinds": kinds,
            "include_hidden": show_all,
            "highlight": not no_highlight,
            "boxes": boxes,
        },
    )
    fields = result.get("fields", [])
    if as_json:
        output.set_mode(as_json=True)
    output.emit(fields, table=_format_fields(fields, boxes=boxes))
```

and replace `snapshot` (`:520-543`):

```python
@app.command()
def snapshot(
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
    boxes: bool = typer.Option(False, "--boxes", help="Include each element's viewport rect."),
) -> None:
    """List the page's interactive elements as a role/name table."""
    from visus.web.cli import output

    result = _send("snapshot", {"boxes": boxes})
    elements = result.get("elements", [])
    if as_json:
        output.set_mode(as_json=True)
    if not elements:
        output.emit(elements, table="(no elements)")
        return
    from rich import box as rich_box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=rich_box.ASCII, header_style="bold", pad_edge=False)
    table.add_column("ROLE", no_wrap=True)
    table.add_column("NAME", overflow="fold")
    if boxes:
        table.add_column("BOX x,y,w,h", no_wrap=True)
    for e in elements:
        cells = [str(e.get("role", "")), str(e.get("name", ""))]
        if boxes:
            b = e.get("box")
            cells.append(
                f"{b['x']:.0f},{b['y']:.0f},{b['width']:.0f},{b['height']:.0f}"
                if isinstance(b, dict)
                else "-"
            )
        table.add_row(*cells)
    console_obj = Console()
    with console_obj.capture() as cap:
        console_obj.print(table)
    output.emit(elements, table=cap.get().rstrip("\n"))
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k "box or rect" -v --no-cov`
Expected: PASS (6 passed)

- [ ] **Step 7: Run the browser test**

Run: `uv run pytest tests/test_cli_page_ops.py::test_boxes_come_from_a_real_page -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 8: Verify nothing that reads fields or snapshots regressed**

Run: `uv run pytest tests/test_cli_session.py tests/test_e2e_fields.py tests/test_mcp_list_fields.py tests/test_mcp_server.py -q --no-cov`
Expected: PASS — `Field.box` defaults to `None`, `list_fields`/`snapshot` strip it unless asked, and the MCP tool inventory is a name list, unchanged by a payload key.

- [ ] **Step 9: Update the README**

In `README.md`, in the **Inspect / search the DOM** table, replace the `visus snapshot` and `visus list-fields` rows with:

```markdown
| `visus snapshot [--boxes] [--json]` | List interactive elements as a role/name table (`--boxes` adds each viewport rect). |
| `visus list-fields --kind <k> --all --no-highlight [--boxes] [--json]` | Enumerate interactive fields, numbered + highlighted (`--boxes` adds each viewport rect). |
```

- [ ] **Step 10: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: `All checks passed!` and `Success: no issues found`

```bash
git add src/visus/web/api/fields.py src/visus/web/backends/selenium/driver_delegate.py src/visus/web/backends/selenium/js/bundle.js src/visus/web/cli/session_server.py src/visus/web/cli/console.py src/visus/web/cli/main.py tests/test_cli_page_ops.py README.md
git commit -m "feat(cli): surface element geometry via --boxes on list-fields and snapshot"
```

---

### Task 12: Element-scoped `eval` — in the CLI **and** in the MCP server

Closes **row 4**, in both places it is broken. `visus eval` (`main.py:812-830`) forwards to `_op_eval` (`session_server.py:486-489`), which always calls `page.evaluate(...)`; there is no way to say "run this on element 3". `Locator.evaluate` exists (`api/locator.py:439-440`, delegated at `driver_delegate.py:533-544`, which resolves the element and calls `(expression)(el, arg)`), and `SessionHandler._has_target` (`:198-203`) already answers "did the caller give me a target?".

**The same gap exists in the MCP server** (`mcp/server.py:646-652`): `browser_evaluate(expression, arg)` has no target parameters at all, while every other tool in that file takes `(selector, role, name, text, exact, frame)`. Both are fixed here — one task, because leaving the MCP half undone would reintroduce the D3-shaped "the CLI can do something MCP cannot" asymmetry this plan exists to remove.

The element form receives **two** arguments — `(el, arg)` — while the page form receives one, `(arg)`. That difference is in every docstring and help string this task writes.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:486-489` (`_op_eval`)
- Modify: `src/visus/web/cli/main.py:812-830` (`eval`)
- Modify: `src/visus/web/cli/console.py` (REPL `eval-on` branch + `_HELP`)
- Modify: `src/visus/web/mcp/server.py:646-652` (`browser_evaluate`)
- Modify: `README.md` (Dialogs / cookies / JS table)
- Test: `tests/test_cli_page_ops.py`

**Interfaces:**
- Consumes: `Locator.evaluate`, `Locator.first`, `SessionHandler._has_target`, `SessionHandler._target`, `mcp.session.make_locator`, `main._target_args`, `console._target`, `output.emit`
- Produces: `eval` op accepts a target; `browser_evaluate` accepts `(selector, role, name, text, exact, frame)`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_page_ops.py`:

```python
# ---------------------------------------------------------------------------
# element-scoped eval (CLI + MCP)
# ---------------------------------------------------------------------------


class _EvalLocator:
    def __init__(self, log: list[str], label: str) -> None:
        self._log = log
        self._label = label

    def first(self) -> _EvalLocator:
        return self

    def evaluate(self, expression: str, arg: object = None) -> object:
        self._log.append(f"loc.evaluate:{self._label}:{expression}:{arg!r}")
        return "element-value"


class _EvalPage:
    url = "http://x/"

    def __init__(self) -> None:
        self.log: list[str] = []

    def locator(self, selector: str, *, deep: bool = False) -> _EvalLocator:
        return _EvalLocator(self.log, f"loc({selector})")

    def evaluate(self, expression: str, arg: object = None) -> object:
        self.log.append(f"page.evaluate:{expression}:{arg!r}")
        return "page-value"


def test_op_eval_without_a_target_stays_on_the_page() -> None:
    page = _EvalPage()
    h = _handler(page)
    out = h.handle("eval", {"expression": "() => document.title", "arg": None})
    assert out["result"] == {"result": "page-value"}
    assert page.log == ["page.evaluate:() => document.title:None"]


def test_op_eval_with_a_target_runs_on_the_element() -> None:
    page = _EvalPage()
    h = _handler(page)
    out = h.handle("eval", {"expression": "(el) => el.id", "selector": "#b", "arg": 7})
    assert out["result"] == {"result": "element-value"}
    assert page.log == ["loc.evaluate:loc(#b):(el) => el.id:7"]


def test_cli_eval_forwards_the_target(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {})) or {"result": "v"},
    )
    assert runner.invoke(app, ["eval", "() => document.title"]).exit_code == 0
    assert runner.invoke(app, ["eval", "(el) => el.id", "--index", "3"]).exit_code == 0
    assert runner.invoke(app, ["eval", "(el) => el.id", "-s", "#b"]).exit_code == 0
    assert calls[0] == ("eval", {"expression": "() => document.title", "arg": None})
    assert calls[1][1]["index"] == 3 and calls[1][1]["expression"] == "(el) => el.id"
    assert calls[2][1]["selector"] == "#b"


def test_repl_eval_and_eval_on() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return {"result": "v"}

    console.dispatch("eval () => document.title", send)
    console.dispatch("eval-on 3 (el) => el.id", send)
    console.dispatch("eval-on #b (el) => el.id", send)
    assert calls[0] == ("eval", {"expression": "() => document.title"})
    assert calls[1] == ("eval", {"index": 3, "expression": "(el) => el.id"})
    assert calls[2] == ("eval", {"selector": "#b", "expression": "(el) => el.id"})
    assert "eval-on" in console.dispatch("help", send)


def test_mcp_browser_evaluate_accepts_a_target() -> None:
    """The MCP tool must gain the same scoping, not just the CLI."""
    import inspect

    from visus.web.mcp import server as mcp_server

    params = inspect.signature(mcp_server.browser_evaluate).parameters
    for want in ("selector", "role", "name", "text", "exact", "frame"):
        assert want in params, f"browser_evaluate is missing {want!r}"


@pytest.mark.browser
def test_scoped_eval_against_a_real_page(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )
    try:
        page_level = h.handle("eval", {"expression": "() => document.title"})
        assert page_level["result"]["result"] == "fields fixture"

        scoped = h.handle(
            "eval", {"expression": "(el) => el.textContent", "selector": "#btn"}
        )
        assert scoped["ok"] is True, scoped
        assert scoped["result"]["result"] == "Click me"

        with_arg = h.handle(
            "eval",
            {"expression": "(el, n) => el.id.repeat(n)", "selector": "#btn", "arg": 2},
        )
        assert with_arg["result"]["result"] == "btnbtn"
    finally:
        h.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k "eval" -v --no-cov`
Expected: FAIL — `test_op_eval_with_a_target_runs_on_the_element` sees `page.evaluate` in the log instead of `loc.evaluate`.

- [ ] **Step 3: Scope the daemon op**

In `src/visus/web/cli/session_server.py`, replace `_op_eval` (`:486-489`):

```python
    def _op_eval(self, args: dict[str, Any]) -> dict[str, Any]:
        """Evaluate a JS function, on the page or on a targeted element.

        With no target the function is called as ``(expression)(arg)``. With a
        target (index / selector / role / target_text) it is called as
        ``(expression)(element, arg)`` — the first parameter is the DOM element.
        """
        expression = args.get("expression", "")
        arg = args.get("arg")
        if self._has_target(args):
            return {"result": self._target(args).first().evaluate(expression, arg)}
        return {"result": self.page().evaluate(expression, arg)}
```

- [ ] **Step 4: Give the CLI command a target**

In `src/visus/web/cli/main.py`, replace `eval_js` (`:812-830`):

```python
@app.command("eval")
def eval_js(
    expression: str = typer.Argument(..., help="A JS function, e.g. '() => document.title'."),
    arg: str = typer.Argument(None, help="Optional JSON argument passed to the function."),
    index: int = typer.Option(None, "--index", "-i", help="Run on this field instead of the page."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text", help="Target an element by its visible text."),
    as_json: bool = typer.Option(False, "--json", help="Emit the result as JSON."),
) -> None:
    """Evaluate JavaScript and print the result.

    On the page: `visus eval '() => document.title'` — the function takes the
    optional argument. On an element: `visus eval '(el) => el.id' -s "#u"` — the
    function takes the ELEMENT first, then the optional argument.
    """
    from visus.web.cli import output

    parsed_arg: Any = None
    if arg is not None:
        try:
            parsed_arg = _json.loads(arg)
        except _json.JSONDecodeError:
            parsed_arg = arg  # treat as a plain string when not valid JSON
    args: dict[str, Any] = {"expression": expression, "arg": parsed_arg}
    if index is not None or selector or role or text:
        args.update(_target_args(index, selector, role, name, text))
    result = _send("eval", args)
    if as_json:
        output.set_mode(as_json=True)
    output.emit(result.get("result"))
```

In `src/visus/web/cli/console.py`, add this branch right after the existing `eval` branch:

```python
        if cmd == "eval-on":
            ev_target, ev_tail = _target(rest)
            return str(
                send("eval", {**ev_target, "expression": " ".join(ev_tail)}).get("result")
            )
```

and this `_HELP` line right after `eval expr`:

```
  eval-on TGT expr     evaluate `(el, arg) => …` on one element
```

- [ ] **Step 5: Close the same gap in the MCP server**

In `src/visus/web/mcp/server.py`, replace `browser_evaluate` (`:646-652`):

```python
@mcp.tool()
def browser_evaluate(
    expression: str,
    arg: object = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> object:
    """Evaluate a JavaScript function in the browser and return the result.

    With no target the function runs on the page and is called as
    '(expression)(arg)', e.g. '() => document.title'.

    With a target (selector / role+name / text) it runs on that ELEMENT and is
    called as '(expression)(element, arg)', e.g. '(el) => el.value' — this is
    how you read id/class/dataset or any property list_fields does not return.
    """
    page = _session.page()
    if selector is None and role is None and text is None:
        return page.evaluate(expression, arg)
    loc = make_locator(
        page, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )
    return loc.first().evaluate(expression, arg)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k "eval" -v --no-cov`
Expected: PASS (5 passed)

- [ ] **Step 7: Run the browser test**

Run: `uv run pytest tests/test_cli_page_ops.py::test_scoped_eval_against_a_real_page -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 8: Verify the MCP and CLI eval suites still pass**

Run: `uv run pytest tests/test_mcp_server.py tests/test_e2e_mcp.py -q --no-cov`
Expected: PASS — the tool-name inventory is unchanged and `browser_evaluate(expr)` with no target still hits the page.

Run: `uv run pytest tests/test_cli_session.py -k eval -v --no-cov`
Expected: PASS — `{"expression": ..., "arg": ...}` is still the payload when no target is given.

- [ ] **Step 9: Update the README**

In `README.md`, in the **Dialogs / cookies / JS** table, replace the `visus eval` row with:

```markdown
| `visus eval "<fn>" [arg] [target] [--json]` | Evaluate JS. On the page `'() => document.title'`; on an element `'(el) => el.id' -s "#u"`. |
```

- [ ] **Step 10: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py src/visus/web/mcp/server.py tests/test_cli_page_ops.py README.md
git commit -m "feat(cli,mcp): scope eval to an element in both surfaces"
```

---

### Task 13: `visus resize <w> <h>`

Closes **row 8**. `Page.set_viewport_size` (`api/page.py:457-460`) resizes the window until the viewport is exactly `width × height` and works on every engine (`driver_delegate.py:1127-1137` corrects for chrome), but nothing in `cli/` calls it. Without it a shell agent cannot reproduce a layout bug that only appears at a given width, and cannot make a screenshot deterministic across machines.

The op returns the **achieved** inner size, not the requested one: window-manager constraints and minimum window widths mean a request can land short, and silently reporting the request would be a lie.

**Files:**
- Modify: `src/visus/web/cli/session_server.py` (new `_op_resize`)
- Modify: `src/visus/web/cli/main.py` (new `resize` command)
- Modify: `src/visus/web/cli/console.py` (REPL branch + `_HELP`)
- Modify: `README.md` (Capture / vision / utilities table)
- Test: `tests/test_cli_page_ops.py`

**Interfaces:**
- Consumes: `Page.set_viewport_size`, `Page.evaluate`, `output.emit`
- Produces: daemon op `resize` → `{"width": int, "height": int}` (the achieved viewport)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_page_ops.py`:

```python
# ---------------------------------------------------------------------------
# resize
# ---------------------------------------------------------------------------


class _ResizePage:
    url = "http://x/"

    def __init__(self) -> None:
        self.sized: tuple[int, int] | None = None

    def set_viewport_size(self, width: int, height: int) -> None:
        self.sized = (width, height)

    def evaluate(self, expression: str, arg: object = None) -> object:
        # The window manager clamped the width — the op must report what it got.
        return {"w": 900, "h": 720}


def test_op_resize_reports_the_achieved_size() -> None:
    page = _ResizePage()
    h = _handler(page)
    out = h.handle("resize", {"width": 1024, "height": 720})
    assert out["ok"] is True, out
    assert page.sized == (1024, 720)
    assert out["result"] == {"width": 900, "height": 720}


def test_cli_resize(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {}))
        or {"width": 1024, "height": 720},
    )
    r = runner.invoke(app, ["resize", "1024", "720"])
    assert r.exit_code == 0, r.output
    assert calls[0] == ("resize", {"width": 1024, "height": 720})
    assert "1024x720" in r.output


def test_repl_resize() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return {"width": 800, "height": 600}

    out = console.dispatch("resize 800 600", send)
    assert calls[0] == ("resize", {"width": 800, "height": 600})
    assert "800x600" in out
    assert "resize" in console.dispatch("help", send)


@pytest.mark.browser
def test_resize_changes_the_real_viewport(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )
    try:
        out = h.handle("resize", {"width": 900, "height": 600})
        assert out["ok"] is True, out
        assert out["result"]["width"] == 900
        assert out["result"]["height"] == 600
        inner = h.handle("eval", {"expression": "() => window.innerWidth"})
        assert inner["result"]["result"] == 900
    finally:
        h.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k resize -v --no-cov`
Expected: FAIL — `test_op_resize_reports_the_achieved_size` gets `{"ok": False, "error": "ValueError: unknown op 'resize'"}`.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/session_server.py`, add after `_op_url` (`:320-321`):

```python
    def _op_resize(self, args: dict[str, Any]) -> dict[str, Any]:
        """Resize the window so the viewport is width × height.

        Returns the size actually achieved: a window manager can clamp the
        request (minimum widths, screen size), and reporting the request back
        would hide that.
        """
        width, height = int(args.get("width", 0)), int(args.get("height", 0))
        if width <= 0 or height <= 0:
            raise ValueError("resize needs a positive width and height")
        page = self.page()
        page.set_viewport_size(width, height)
        got = cast(
            "dict[str, Any]",
            page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})"),
        )
        return {"width": int(got["w"]), "height": int(got["h"])}
```

Add `"resize"` to the `_MUTATING_OPS` frozenset PLAN 4 created in this module — a viewport change re-lays-out the page, so the `### Page` footer is worth reprinting.

In `src/visus/web/cli/main.py`, add after the `url` command (`:514-517`):

```python
@app.command()
def resize(
    width: int = typer.Argument(..., help="Viewport width in CSS pixels."),
    height: int = typer.Argument(..., help="Viewport height in CSS pixels."),
) -> None:
    """Resize the session window so the viewport is exactly width × height."""
    from visus.web.cli import output

    result = _send("resize", {"width": width, "height": height})
    output.emit(result, table=f"viewport is now {result['width']}x{result['height']}")
```

In `src/visus/web/cli/console.py`, add this branch right after the `url` branch:

```python
        if cmd == "resize":
            r = send("resize", {"width": int(rest[0]), "height": int(rest[1])})
            return f"viewport is now {r['width']}x{r['height']}"
```

and this `_HELP` line right after `url`:

```
  resize w h           resize the window so the viewport is w×h
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k resize -v --no-cov`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the browser test**

Run: `uv run pytest tests/test_cli_page_ops.py::test_resize_changes_the_real_viewport -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 6: Update the README**

In `README.md`, in the **Capture / vision / utilities** table, add a row right after the `visus highlight` row:

```markdown
| `visus resize <w> <h>` | Resize the window so the viewport is exactly `w × h` (prints what was achieved). |
```

- [ ] **Step 7: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_page_ops.py README.md
git commit -m "feat(cli): add `visus resize` for the session viewport"
```

---

### Task 14: `visus storage list/get/set/delete/clear [--session-storage]`

Closes **row 2**. localStorage and sessionStorage are reachable from the shell today only through `visus eval` with a hand-written JS closure — and this is a Windows-first project (`pyproject.toml:15`) where PowerShell mangles the quotes that closure needs (`main.py:53-57` documents that exact problem as the reason `visus translate` exists). Ten commands collapse into one sub-app over `Page.evaluate` (`api/page.py:287-288`).

Per the Prerequisites, the switch is `--session-storage`, **not** `--session`: `--session`/`-S` is reserved by the conventions contract for PLAN 6's named sessions.

`get` returns the `{"value": …, "present": …}` shape PLAN 3 introduced for `get_text`/`get_attribute`, for the same reason: a key holding `""` and a key that does not exist must not print the same empty line.

**Files:**
- Modify: `src/visus/web/cli/session_server.py` (new `_op_storage_*`)
- Modify: `src/visus/web/cli/main.py` (new `storage` Typer sub-app)
- Modify: `src/visus/web/cli/console.py` (REPL `storage` / `session-storage` branches + `_HELP`)
- Modify: `README.md` (Dialogs / cookies / JS table)
- Test: `tests/test_cli_page_ops.py` (uses `tests/fixtures/storage.html` from Task 6)

**Interfaces:**
- Consumes: `Page.evaluate`, `output.emit`, `output.emit_error`
- Produces: daemon ops `storage_list` → `{"items": [{"name", "value"}], "kind": str}`, `storage_get` → `{"value": str | None, "present": bool}`, `storage_set` → `str`, `storage_delete` → `{"deleted": bool}`, `storage_clear` → `{"cleared": int}`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_page_ops.py`:

```python
# ---------------------------------------------------------------------------
# web storage
# ---------------------------------------------------------------------------


class _StoragePage:
    """Evaluates the storage helpers against two in-memory dicts."""

    url = "http://x/"

    def __init__(self) -> None:
        self.local: dict[str, str] = {"token": "abc", "empty": ""}
        self.session: dict[str, str] = {"tab": "1"}
        self.seen: list[str] = []

    def evaluate(self, expression: str, arg: object = None) -> object:
        self.seen.append(expression)
        a = arg if isinstance(arg, dict) else {}
        store = self.session if a.get("session") else self.local
        key = str(a.get("key", ""))
        if "st.key(" in expression:
            return [{"name": k, "value": v} for k, v in store.items()]
        if "setItem" in expression:
            store[key] = str(a.get("value", ""))
            return True
        if "removeItem" in expression:
            had = key in store
            store.pop(key, None)
            return had
        if "st.clear()" in expression:
            n = len(store)
            store.clear()
            return n
        v = store.get(key)
        return {"value": v, "present": v is not None}


def test_op_storage_round_trip_on_local_and_session() -> None:
    page = _StoragePage()
    h = _handler(page)

    listed = h.handle("storage_list", {})["result"]
    assert listed["kind"] == "localStorage"
    assert {i["name"] for i in listed["items"]} == {"token", "empty"}

    assert h.handle("storage_get", {"key": "token"})["result"] == {
        "value": "abc",
        "present": True,
    }
    # An empty value and a missing key must be distinguishable.
    assert h.handle("storage_get", {"key": "empty"})["result"] == {"value": "", "present": True}
    assert h.handle("storage_get", {"key": "nope"})["result"] == {
        "value": None,
        "present": False,
    }

    assert h.handle("storage_set", {"key": "k", "value": "v"})["result"] == (
        "localStorage['k'] = 'v'"
    )
    assert page.local["k"] == "v"
    assert h.handle("storage_delete", {"key": "k"})["result"] == {"deleted": True}
    assert h.handle("storage_delete", {"key": "k"})["result"] == {"deleted": False}

    assert h.handle("storage_list", {"session": True})["result"]["kind"] == "sessionStorage"
    assert h.handle("storage_get", {"key": "tab", "session": True})["result"]["value"] == "1"
    assert h.handle("storage_clear", {"session": True})["result"] == {"cleared": 1}
    assert page.session == {}
    assert page.local  # clearing sessionStorage must not touch localStorage


def test_cli_storage_subcommands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        if op == "storage_list":
            return {"kind": "localStorage", "items": [{"name": "token", "value": "abc"}]}
        if op == "storage_get":
            return {"value": "abc", "present": True}
        if op == "storage_delete":
            return {"deleted": True}
        if op == "storage_clear":
            return {"cleared": 3}
        return "localStorage['k'] = 'v'"

    monkeypatch.setattr(session_client, "send", fake_send)
    assert runner.invoke(app, ["storage", "list"]).exit_code == 0
    r_get = runner.invoke(app, ["storage", "get", "token"])
    assert r_get.exit_code == 0 and "abc" in r_get.output
    assert runner.invoke(app, ["storage", "set", "k", "v"]).exit_code == 0
    assert runner.invoke(app, ["storage", "delete", "k"]).exit_code == 0
    assert runner.invoke(app, ["storage", "clear", "--session-storage"]).exit_code == 0
    assert calls[0] == ("storage_list", {"session": False})
    assert calls[1] == ("storage_get", {"key": "token", "session": False})
    assert calls[2] == ("storage_set", {"key": "k", "value": "v", "session": False})
    assert calls[3] == ("storage_delete", {"key": "k", "session": False})
    assert calls[4] == ("storage_clear", {"session": True})


def test_cli_storage_get_missing_key_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None: {"value": None, "present": False}
    )
    r = runner.invoke(app, ["storage", "get", "nope"])
    assert r.exit_code == 1


def test_repl_storage_branches() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "storage_list":
            return {"kind": "localStorage", "items": []}
        if op == "storage_get":
            return {"value": "abc", "present": True}
        return {"deleted": True, "cleared": 0}

    console.dispatch("storage list", send)
    console.dispatch("storage get token", send)
    console.dispatch("storage set k some value", send)
    console.dispatch("session-storage delete tab", send)
    assert calls[0] == ("storage_list", {"session": False})
    assert calls[1] == ("storage_get", {"key": "token", "session": False})
    assert calls[2] == ("storage_set", {"key": "k", "value": "some value", "session": False})
    assert calls[3] == ("storage_delete", {"key": "tab", "session": True})
    assert "storage" in console.dispatch("help", send)


@pytest.mark.browser
def test_storage_ops_against_a_real_page(base_url: str) -> None:
    """storage.html seeds token=seed-local and tab=seed-session on every load."""
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/storage.html"
    )
    try:
        assert h.handle("storage_get", {"key": "token"})["result"] == {
            "value": "seed-local",
            "present": True,
        }
        assert h.handle("storage_get", {"key": "tab", "session": True})["result"] == {
            "value": "seed-session",
            "present": True,
        }
        assert h.handle("storage_get", {"key": "absent"})["result"]["present"] is False

        h.handle("storage_set", {"key": "token", "value": "written"})
        assert h.handle("storage_get", {"key": "token"})["result"]["value"] == "written"

        names = {
            i["name"] for i in h.handle("storage_list", {})["result"]["items"]
        }
        assert "token" in names

        assert h.handle("storage_delete", {"key": "token"})["result"] == {"deleted": True}
        assert h.handle("storage_get", {"key": "token"})["result"]["present"] is False

        cleared = h.handle("storage_clear", {"session": True})["result"]["cleared"]
        assert cleared >= 1
        assert h.handle("storage_get", {"key": "tab", "session": True})["result"][
            "present"
        ] is False
    finally:
        h.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k storage -v --no-cov`
Expected: FAIL — `test_op_storage_round_trip_on_local_and_session` gets `{"ok": False, "error": "ValueError: unknown op 'storage_list'"}`.

- [ ] **Step 3: Add the daemon ops**

In `src/visus/web/cli/session_server.py`, add after `_op_eval`:

```python
    # --- web storage (localStorage / sessionStorage) ----------------------
    # Each helper is a one-arg arrow function: Page.evaluate wraps the
    # expression as ``(<expr>)(arg)``, so the whole payload travels in one dict.
    _STORAGE_LIST_JS = (
        "(a) => { const st = a.session ? sessionStorage : localStorage;"
        " const out = []; for (let i = 0; i < st.length; i++)"
        " { const k = st.key(i); out.push({name: k, value: st.getItem(k)}); }"
        " return out; }"
    )
    _STORAGE_GET_JS = (
        "(a) => { const st = a.session ? sessionStorage : localStorage;"
        " const v = st.getItem(a.key); return {value: v, present: v !== null}; }"
    )
    _STORAGE_SET_JS = (
        "(a) => { const st = a.session ? sessionStorage : localStorage;"
        " st.setItem(a.key, a.value); return true; }"
    )
    _STORAGE_DELETE_JS = (
        "(a) => { const st = a.session ? sessionStorage : localStorage;"
        " const had = st.getItem(a.key) !== null; st.removeItem(a.key); return had; }"
    )
    _STORAGE_CLEAR_JS = (
        "(a) => { const st = a.session ? sessionStorage : localStorage;"
        " const n = st.length; st.clear(); return n; }"
    )

    @staticmethod
    def _storage_kind(args: dict[str, Any]) -> str:
        return "sessionStorage" if args.get("session") else "localStorage"

    def _op_storage_list(self, args: dict[str, Any]) -> dict[str, Any]:
        """Every key/value in the current origin's local or session storage."""
        payload = {"session": bool(args.get("session"))}
        items = self.page().evaluate(self._STORAGE_LIST_JS, payload)
        return {"kind": self._storage_kind(args), "items": items}

    def _op_storage_get(self, args: dict[str, Any]) -> dict[str, Any]:
        """One key. ``present`` distinguishes a stored ``""`` from a missing key."""
        payload = {"session": bool(args.get("session")), "key": str(args.get("key", ""))}
        return cast("dict[str, Any]", self.page().evaluate(self._STORAGE_GET_JS, payload))

    def _op_storage_set(self, args: dict[str, Any]) -> str:
        key, value = str(args.get("key", "")), str(args.get("value", ""))
        payload = {"session": bool(args.get("session")), "key": key, "value": value}
        self.page().evaluate(self._STORAGE_SET_JS, payload)
        return f"{self._storage_kind(args)}[{key!r}] = {value!r}"

    def _op_storage_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        payload = {"session": bool(args.get("session")), "key": str(args.get("key", ""))}
        return {"deleted": bool(self.page().evaluate(self._STORAGE_DELETE_JS, payload))}

    def _op_storage_clear(self, args: dict[str, Any]) -> dict[str, Any]:
        """Clear ONE store — clearing sessionStorage never touches localStorage."""
        payload = {"session": bool(args.get("session"))}
        return {"cleared": int(cast(int, self.page().evaluate(self._STORAGE_CLEAR_JS, payload)))}
```

Add `"storage_set"`, `"storage_delete"` and `"storage_clear"` to the `_MUTATING_OPS` frozenset PLAN 4 created in this module (`storage_list` and `storage_get` are reads).

- [ ] **Step 4: Add the `storage` sub-app**

In `src/visus/web/cli/main.py`, add after the `clear_cookies` command (`:801-804`):

```python
# ---------------------------------------------------------------------------
# Web storage (localStorage / sessionStorage)
# ---------------------------------------------------------------------------

storage_app = typer.Typer(help="Read and write localStorage / sessionStorage.")
app.add_typer(storage_app, name="storage")

# `--session` / `-S` is reserved for named sessions, so the switch is spelled out.
_SESSION_STORAGE_OPT = typer.Option(
    False, "--session-storage", help="Use sessionStorage instead of localStorage."
)


@storage_app.command("list")
def storage_list(session: bool = _SESSION_STORAGE_OPT) -> None:
    """List every key/value in the current origin's storage."""
    from visus.web.cli import output

    result = _send("storage_list", {"session": session})
    items = result.get("items", [])
    table = (
        "(empty)"
        if not items
        else "\n".join(f"{i.get('name', '')}={i.get('value', '')}" for i in items)
    )
    output.emit(items, table=table)


@storage_app.command("get")
def storage_get(
    key: str = typer.Argument(..., help="Storage key."),
    session: bool = _SESSION_STORAGE_OPT,
) -> None:
    """Print one storage value (exits 1 when the key is absent)."""
    from visus.web.cli import output

    result = _send("storage_get", {"key": key, "session": session})
    if not result.get("present"):
        output.emit_error(f"no such key: {key!r}")
    output.emit(result.get("value"))


@storage_app.command("set")
def storage_set(
    key: str = typer.Argument(..., help="Storage key."),
    value: str = typer.Argument(..., help="Value to store."),
    session: bool = _SESSION_STORAGE_OPT,
) -> None:
    """Write one storage value."""
    from visus.web.cli import output

    output.emit(_send("storage_set", {"key": key, "value": value, "session": session}))


@storage_app.command("delete")
def storage_delete(
    key: str = typer.Argument(..., help="Storage key."),
    session: bool = _SESSION_STORAGE_OPT,
) -> None:
    """Remove one storage key."""
    from visus.web.cli import output

    result = _send("storage_delete", {"key": key, "session": session})
    output.emit(result, table="deleted" if result.get("deleted") else "no such key")


@storage_app.command("clear")
def storage_clear(session: bool = _SESSION_STORAGE_OPT) -> None:
    """Clear the whole store for the current origin."""
    from visus.web.cli import output

    result = _send("storage_clear", {"session": session})
    output.emit(result, table=f"cleared {result.get('cleared', 0)} key(s)")
```

- [ ] **Step 5: Add the REPL branches**

In `src/visus/web/cli/console.py`, add these branches right after the `clear-cookies` branch:

```python
        if cmd in ("storage", "session-storage"):
            if not rest:
                return "usage: storage list|get KEY|set KEY VALUE|delete KEY|clear"
            in_session = cmd == "session-storage"
            sub, tail = rest[0].lower(), rest[1:]
            if sub == "list":
                listed = send("storage_list", {"session": in_session})
                items = listed.get("items", [])
                if not items:
                    return "(empty)"
                return "\n".join(f"{i.get('name', '')}={i.get('value', '')}" for i in items)
            if sub == "clear":
                return f"cleared {send('storage_clear', {'session': in_session})['cleared']} key(s)"
            if sub == "get":
                got = send("storage_get", {"key": tail[0], "session": in_session})
                return str(got["value"]) if got.get("present") else f"no such key: {tail[0]!r}"
            if sub == "set":
                return str(
                    send(
                        "storage_set",
                        {"key": tail[0], "value": " ".join(tail[1:]), "session": in_session},
                    )
                )
            if sub == "delete":
                gone = send("storage_delete", {"key": tail[0], "session": in_session})
                return "deleted" if gone.get("deleted") else "no such key"
            return f"unknown storage subcommand {sub!r} (list|get|set|delete|clear)"
```

and these two `_HELP` lines right after `clear-cookies`:

```
  storage SUB [k] [v]  localStorage: list|get k|set k v|delete k|clear
  session-storage SUB  the same five subcommands on sessionStorage
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k storage -v --no-cov`
Expected: PASS (4 passed)

- [ ] **Step 7: Run the browser test**

Run: `uv run pytest tests/test_cli_page_ops.py::test_storage_ops_against_a_real_page -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 8: Update the README**

In `README.md`, in the **Dialogs / cookies / JS** table, add a row right after the `visus state-save` row:

```markdown
| `visus storage list/get/set/delete/clear [--session-storage]` | Read/write the origin's localStorage (or sessionStorage). |
```

- [ ] **Step 9: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: `All checks passed!` and `Success: no issues found`

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_page_ops.py README.md
git commit -m "feat(cli): add `visus storage` for localStorage and sessionStorage"
```

---

### Task 15: `visus cookie-get/set/delete` and `--domain`/`--path` on `visus cookies`

Closes **row 3**. The CLI's cookie surface is all-or-nothing: `visus cookies` dumps every cookie (`main.py:770-782`), `visus add-cookies` takes a whole JSON list (`:785-798`), `visus clear-cookies` wipes everything (`:801-804`). Reading one token means `visus cookies --json | jq`, which needs `jq` — and PowerShell quoting for the JSON that `add-cookies` wants is exactly the pain `visus translate` exists to avoid.

`Context.cookies()` / `add_cookies()` / `clear_cookies()` (`api/context.py:71-78`) are all that is needed. There is no per-cookie delete in WebDriver, so **delete = read, filter, clear, re-add** — and that has a real, unavoidable caveat: `driver.add_cookie` (`driver_delegate.py:1251-1253`) only accepts a cookie for the currently-loaded document's domain, so a cookie belonging to another domain cannot be put back. The op re-adds one at a time and **reports how many it could not restore** rather than losing them silently.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:473-483` (`_op_cookies`), new `_op_cookie_*`
- Modify: `src/visus/web/cli/main.py:770-782` (`cookies`), new `cookie-get`/`cookie-set`/`cookie-delete`
- Modify: `src/visus/web/cli/console.py` (REPL branches + `_HELP`)
- Modify: `README.md` (Dialogs / cookies / JS table)
- Test: `tests/test_cli_page_ops.py`

**Interfaces:**
- Consumes: `Context.cookies`, `Context.add_cookies`, `Context.clear_cookies`, `SessionHandler.context`, `output.emit`, `output.emit_error`
- Produces: `session_server._cookie_matches(cookie, *, name, domain, path) -> bool`; daemon ops `cookie_get` → `{"value", "present", "cookie"}`, `cookie_set` → `str`, `cookie_delete` → `{"deleted", "restored", "dropped"}`; `cookies` accepts `domain`/`path`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_page_ops.py`:

```python
# ---------------------------------------------------------------------------
# cookie-get / cookie-set / cookie-delete, and cookies --domain/--path
# ---------------------------------------------------------------------------


class _CookieContext:
    def __init__(self) -> None:
        self.store: list[dict[str, Any]] = [
            {"name": "sid", "value": "abc", "domain": "example.com", "path": "/"},
            {"name": "sid", "value": "xyz", "domain": "other.com", "path": "/"},
            {"name": "pref", "value": "", "domain": "example.com", "path": "/app"},
        ]
        self.rejects: set[str] = set()

    def cookies(self) -> list[dict[str, Any]]:
        return [dict(c) for c in self.store]

    def add_cookies(self, cookies: list[dict[str, Any]]) -> None:
        for c in cookies:
            if c.get("domain") in self.rejects:
                raise RuntimeError(f"cannot set a cookie for {c.get('domain')}")
            self.store.append(dict(c))

    def clear_cookies(self) -> None:
        self.store.clear()


class _CookiePage:
    url = "http://example.com/"


def _cookie_handler(ctx: _CookieContext) -> session_server.SessionHandler:
    h = _handler(_CookiePage())
    h.context = lambda: ctx  # type: ignore[assignment,method-assign,return-value]
    return h


def test_cookie_matches_filters_on_name_domain_and_path() -> None:
    c = {"name": "sid", "domain": "example.com", "path": "/app"}
    assert session_server._cookie_matches(c, name="sid", domain=None, path=None) is True
    assert session_server._cookie_matches(c, name="nope", domain=None, path=None) is False
    assert session_server._cookie_matches(c, name=None, domain="example.com", path=None) is True
    # A leading dot on the stored domain must not defeat the filter.
    assert session_server._cookie_matches(
        {"name": "sid", "domain": ".example.com", "path": "/"},
        name=None,
        domain="example.com",
        path=None,
    ) is True
    assert session_server._cookie_matches(c, name=None, domain=None, path="/app") is True
    assert session_server._cookie_matches(c, name=None, domain=None, path="/") is False


def test_op_cookies_filters_by_domain_and_path() -> None:
    h = _cookie_handler(_CookieContext())
    everything = h.handle("cookies", {})["result"]["cookies"]
    assert len(everything) == 3
    by_domain = h.handle("cookies", {"domain": "example.com"})["result"]["cookies"]
    assert {c["name"] for c in by_domain} == {"sid", "pref"}
    by_path = h.handle("cookies", {"path": "/app"})["result"]["cookies"]
    assert [c["name"] for c in by_path] == ["pref"]


def test_op_cookie_get_distinguishes_empty_from_missing() -> None:
    h = _cookie_handler(_CookieContext())
    hit = h.handle("cookie_get", {"name": "sid", "domain": "other.com"})["result"]
    assert hit == {"value": "xyz", "present": True, "cookie": {
        "name": "sid", "value": "xyz", "domain": "other.com", "path": "/"
    }}
    empty = h.handle("cookie_get", {"name": "pref"})["result"]
    assert empty["value"] == "" and empty["present"] is True
    missing = h.handle("cookie_get", {"name": "nope"})["result"]
    assert missing == {"value": None, "present": False, "cookie": None}


def test_op_cookie_set_uses_the_context() -> None:
    ctx = _CookieContext()
    h = _cookie_handler(ctx)
    out = h.handle("cookie_set", {"name": "tok", "value": "1", "path": "/"})["result"]
    assert out == "set cookie 'tok'"
    assert any(c["name"] == "tok" and c["path"] == "/" for c in ctx.store)


def test_op_cookie_delete_readds_the_survivors_and_reports_drops() -> None:
    ctx = _CookieContext()
    ctx.rejects = {"other.com"}  # WebDriver refuses a foreign-domain cookie
    h = _cookie_handler(ctx)
    out = h.handle("cookie_delete", {"name": "pref"})["result"]
    assert out == {"deleted": 1, "restored": 1, "dropped": 1}
    names = {c["name"] for c in ctx.store}
    assert names == {"sid"}  # the example.com sid survived; pref is gone
    assert len(ctx.store) == 1  # the other.com sid could not be restored


def test_cli_cookie_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        if op == "cookie_get":
            return {"value": "abc", "present": True, "cookie": {"name": "sid"}}
        if op == "cookie_delete":
            return {"deleted": 1, "restored": 2, "dropped": 0}
        if op == "cookies":
            return {"cookies": [{"name": "sid", "value": "abc", "domain": "example.com"}]}
        return "set cookie 'tok'"

    monkeypatch.setattr(session_client, "send", fake_send)
    r_get = runner.invoke(app, ["cookie-get", "sid", "--domain", "example.com"])
    assert r_get.exit_code == 0 and "abc" in r_get.output
    assert runner.invoke(app, ["cookie-set", "tok", "1", "--path", "/api"]).exit_code == 0
    assert runner.invoke(app, ["cookie-delete", "sid"]).exit_code == 0
    assert runner.invoke(app, ["cookies", "--domain", "example.com"]).exit_code == 0
    assert calls[0] == ("cookie_get", {"name": "sid", "domain": "example.com", "path": None})
    assert calls[1][0] == "cookie_set" and calls[1][1]["path"] == "/api"
    assert calls[2] == ("cookie_delete", {"name": "sid", "domain": None, "path": None})
    assert calls[3] == ("cookies", {"domain": "example.com", "path": None})


def test_cli_cookie_get_missing_exits_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: {"value": None, "present": False, "cookie": None},
    )
    assert runner.invoke(app, ["cookie-get", "nope"]).exit_code == 1


def test_repl_cookie_commands() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "cookie_get":
            return {"value": "abc", "present": True, "cookie": {}}
        if op == "cookie_delete":
            return {"deleted": 1, "restored": 0, "dropped": 0}
        return "set cookie 'tok'"

    assert console.dispatch("cookie-get sid", send) == "abc"
    console.dispatch("cookie-set tok 1", send)
    console.dispatch("cookie-delete sid", send)
    assert calls[0] == ("cookie_get", {"name": "sid", "domain": None, "path": None})
    assert calls[1] == ("cookie_set", {"name": "tok", "value": "1", "path": "/", "domain": None})
    assert calls[2] == ("cookie_delete", {"name": "sid", "domain": None, "path": None})
    assert "cookie-get" in console.dispatch("help", send)


@pytest.mark.browser
def test_cookie_ops_against_a_real_browser(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )
    try:
        assert h.handle("cookie_set", {"name": "tok", "value": "v1", "path": "/"})["ok"] is True
        got = h.handle("cookie_get", {"name": "tok"})["result"]
        assert got["present"] is True and got["value"] == "v1"

        assert h.handle("cookie_set", {"name": "other", "value": "v2", "path": "/"})["ok"] is True
        assert len(h.handle("cookies", {})["result"]["cookies"]) >= 2

        deleted = h.handle("cookie_delete", {"name": "tok"})["result"]
        assert deleted["deleted"] == 1
        assert h.handle("cookie_get", {"name": "tok"})["result"]["present"] is False
        assert h.handle("cookie_get", {"name": "other"})["result"]["present"] is True
    finally:
        h.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k cookie -v --no-cov`
Expected: FAIL — `test_cookie_matches_filters_on_name_domain_and_path` raises `AttributeError: module 'visus.web.cli.session_server' has no attribute '_cookie_matches'`.

- [ ] **Step 3: Add the matcher and the daemon ops**

In `src/visus/web/cli/session_server.py`, add this module-level helper right after `_norm_rect`:

```python
def _cookie_matches(
    cookie: dict[str, Any],
    *,
    name: str | None,
    domain: str | None,
    path: str | None,
) -> bool:
    """True when *cookie* satisfies every filter that was given.

    A stored domain may carry a leading dot (``.example.com``) for a
    subdomain-wide cookie; the comparison strips it so ``--domain example.com``
    matches both spellings.
    """
    if name is not None and cookie.get("name") != name:
        return False
    if domain is not None:
        have = str(cookie.get("domain") or "").lstrip(".")
        if have != domain.lstrip("."):
            return False
    if path is not None and cookie.get("path") != path:
        return False
    return True
```

Replace `_op_cookies` (`:473-474`) and add the three new ops after `_op_clear_cookies` (`:481-483`):

```python
    def _op_cookies(self, args: dict[str, Any]) -> dict[str, Any]:
        """List cookies, optionally filtered by ``domain`` and/or ``path``."""
        domain = args.get("domain")
        path = args.get("path")
        cookies = self.context().cookies()
        if domain is None and path is None:
            return {"cookies": cookies}
        return {
            "cookies": [
                c
                for c in cookies
                if _cookie_matches(c, name=None, domain=domain, path=path)
            ]
        }
```

```python
    def _op_cookie_get(self, args: dict[str, Any]) -> dict[str, Any]:
        """One cookie by name (optionally scoped by domain/path).

        ``present`` distinguishes a cookie holding ``""`` from no cookie at all.
        """
        name = str(args.get("name", ""))
        matches = [
            c
            for c in self.context().cookies()
            if _cookie_matches(c, name=name, domain=args.get("domain"), path=args.get("path"))
        ]
        if not matches:
            return {"value": None, "present": False, "cookie": None}
        hit = matches[0]
        return {"value": hit.get("value", ""), "present": True, "cookie": hit}

    def _op_cookie_set(self, args: dict[str, Any]) -> str:
        """Set one cookie on the current document's domain."""
        name = str(args.get("name", ""))
        cookie: dict[str, Any] = {"name": name, "value": str(args.get("value", ""))}
        for key in ("domain", "path", "url"):
            if args.get(key):
                cookie[key] = args[key]
        cookie.setdefault("path", "/")
        self.context().add_cookies([cookie])
        return f"set cookie {name!r}"

    def _op_cookie_delete(self, args: dict[str, Any]) -> dict[str, Any]:
        """Delete cookies by name (optionally scoped by domain/path).

        WebDriver has no per-cookie delete, so this reads every cookie, drops
        the matches, clears the jar and re-adds the survivors ONE AT A TIME.
        ``driver.add_cookie`` only accepts a cookie for the currently-loaded
        document's domain, so a survivor from another domain cannot be put back
        — those are counted in ``dropped`` instead of vanishing silently.
        """
        name = str(args.get("name", ""))
        ctx = self.context()
        cookies = ctx.cookies()
        keep = [
            c
            for c in cookies
            if not _cookie_matches(
                c, name=name, domain=args.get("domain"), path=args.get("path")
            )
        ]
        deleted = len(cookies) - len(keep)
        if deleted == 0:
            return {"deleted": 0, "restored": len(keep), "dropped": 0}
        ctx.clear_cookies()
        restored = 0
        for c in keep:
            try:
                ctx.add_cookies([c])
                restored += 1
            except Exception:  # noqa: BLE001 — a foreign-domain cookie is data, not a crash
                continue
        return {"deleted": deleted, "restored": restored, "dropped": len(keep) - restored}
```

Add `"cookie_set"` and `"cookie_delete"` to the `_MUTATING_OPS` frozenset PLAN 4 created in this module.

- [ ] **Step 4: Add the CLI commands**

In `src/visus/web/cli/main.py`, replace `cookies` (`:770-782`) and add the three commands after it:

```python
@app.command()
def cookies(
    as_json: bool = typer.Option(False, "--json", help="Emit JSON."),
    domain: str = typer.Option(None, "--domain", help="Only cookies for this domain."),
    path: str = typer.Option(None, "--path", help="Only cookies with this exact path."),
) -> None:
    """List cookies for the session's context, optionally filtered."""
    from visus.web.cli import output

    result = _send("cookies", {"domain": domain, "path": path})
    items = result.get("cookies", [])
    if as_json:
        output.set_mode(as_json=True)
    table = (
        "(no cookies)"
        if not items
        else "\n".join(
            f"{c.get('name', '')}={c.get('value', '')}  ({c.get('domain', '')}{c.get('path', '')})"
            for c in items
        )
    )
    output.emit(items, table=table)


@app.command("cookie-get")
def cookie_get(
    name: str = typer.Argument(..., help="Cookie name."),
    domain: str = typer.Option(None, "--domain"),
    path: str = typer.Option(None, "--path"),
) -> None:
    """Print one cookie's value (exits 1 when there is no such cookie)."""
    from visus.web.cli import output

    result = _send("cookie_get", {"name": name, "domain": domain, "path": path})
    if not result.get("present"):
        output.emit_error(f"no such cookie: {name!r}")
    output.emit(result.get("value"))


@app.command("cookie-set")
def cookie_set(
    name: str = typer.Argument(..., help="Cookie name."),
    value: str = typer.Argument(..., help="Cookie value."),
    domain: str = typer.Option(None, "--domain"),
    path: str = typer.Option("/", "--path"),
    url: str = typer.Option(None, "--url", help="Set for this URL instead of a domain/path."),
) -> None:
    """Set one cookie on the session's context (current document's domain)."""
    from visus.web.cli import output

    output.emit(
        _send(
            "cookie_set",
            {"name": name, "value": value, "domain": domain, "path": path, "url": url},
        )
    )


@app.command("cookie-delete")
def cookie_delete(
    name: str = typer.Argument(..., help="Cookie name."),
    domain: str = typer.Option(None, "--domain"),
    path: str = typer.Option(None, "--path"),
) -> None:
    """Delete cookies by name (WebDriver has no per-cookie delete: see the note)."""
    from visus.web.cli import output

    result = _send("cookie_delete", {"name": name, "domain": domain, "path": path})
    table = f"deleted {result['deleted']} cookie(s), restored {result['restored']}"
    if result.get("dropped"):
        table += (
            f" — {result['dropped']} cookie(s) for other domains could not be"
            " restored (WebDriver only accepts cookies for the loaded domain)"
        )
    output.emit(result, table=table)
```

- [ ] **Step 5: Add the REPL branches**

In `src/visus/web/cli/console.py`, add these branches right after the `cookies` branch:

```python
        if cmd == "cookie-get":
            ck = send("cookie_get", {"name": rest[0], "domain": None, "path": None})
            return str(ck["value"]) if ck.get("present") else f"no such cookie: {rest[0]!r}"
        if cmd == "cookie-set":
            return str(
                send(
                    "cookie_set",
                    {
                        "name": rest[0],
                        "value": " ".join(rest[1:]),
                        "path": "/",
                        "domain": None,
                    },
                )
            )
        if cmd == "cookie-delete":
            gone = send("cookie_delete", {"name": rest[0], "domain": None, "path": None})
            out = f"deleted {gone['deleted']} cookie(s), restored {gone['restored']}"
            if gone.get("dropped"):
                out += f" ({gone['dropped']} from other domains could not be restored)"
            return out
```

and these three `_HELP` lines right after `cookies`:

```
  cookie-get name      print one cookie's value
  cookie-set name val  set one cookie on the current domain
  cookie-delete name   delete cookies by name (re-adds the survivors)
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k cookie -v --no-cov`
Expected: PASS (8 passed)

- [ ] **Step 7: Run the browser test**

Run: `uv run pytest tests/test_cli_page_ops.py::test_cookie_ops_against_a_real_browser -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 8: Verify the existing cookie tests still pass**

Run: `uv run pytest tests/test_cli_session.py -k cookie -v --no-cov`
Expected: PASS — with no filters `_op_cookies` returns the context's list unchanged.

- [ ] **Step 9: Update the README**

In `README.md`, in the **Dialogs / cookies / JS** table, replace the `visus cookies` row and add two more:

```markdown
| `visus cookies [--domain <d>] [--path <p>] [--json]` | List cookies, optionally filtered. |
| `visus cookie-get <name> [--domain] [--path]` / `visus cookie-set <name> <value>` | Read / write one cookie. |
| `visus cookie-delete <name> [--domain] [--path]` | Delete cookies by name (re-adds the survivors; reports any it could not restore). |
```

- [ ] **Step 10: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: `All checks passed!` and `Success: no issues found`

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_page_ops.py README.md
git commit -m "feat(cli): add per-cookie get/set/delete and cookie filters"
```

---

### Task 16: `visus generate-locator [idx] [--raw]`

Closes **row 13**. `Field.code` is computed frame-aware on every enumeration (`driver_delegate.py:666-685`, assigned at `:709`) and consumed in exactly one place — the VISUS column of `format_fields` (`console.py:83`). There is no way to ask for *one* expression, so the agent's move today is `visus list-fields --json | jq '.[3].code'`, which needs `jq`. And for a `--selector`/`--role`/`--text` target there is no expression at all: `codegen.py:55-72` can build one, but nothing calls it outside the recorder.

`--raw` here is the per-command spelling of PLAN 4's global `--raw`, exactly as the per-command `--json` in Tasks 3-6: it only ever *sets* the mode, guarded so it can never clobber a globally-set one.

**Files:**
- Modify: `src/visus/web/cli/codegen.py:55-72` (new `locator_expr` + `_pystr`)
- Modify: `src/visus/web/cli/session_server.py` (new `_op_generate_locator`)
- Modify: `src/visus/web/cli/main.py` (new `generate-locator` command)
- Modify: `src/visus/web/cli/console.py` (REPL branch + `_HELP`)
- Modify: `README.md` (Tooling table)
- Test: `tests/test_cli_page_ops.py`

**Interfaces:**
- Consumes: `Field.code`, `Field.css`, `Field.xpath`, `SessionHandler._fields`, `output.emit`, `output.set_mode`
- Produces: `codegen.locator_expr(*, selector, role, name, text, exact, frame) -> str`; daemon op `generate_locator` → `{"code": str, "css": str | None, "xpath": str | None}`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_page_ops.py`:

```python
# ---------------------------------------------------------------------------
# generate-locator
# ---------------------------------------------------------------------------


def test_locator_expr_mirrors_make_locator_branch_order() -> None:
    from visus.web.cli.codegen import locator_expr

    assert locator_expr(role="button", name="Save") == 'page.get_by_role("button", name="Save")'
    assert locator_expr(role="button", name="Save", exact=True) == (
        'page.get_by_role("button", name="Save", exact=True)'
    )
    assert locator_expr(text="Sign in") == 'page.get_by_text("Sign in")'
    assert locator_expr(selector="#u") == 'page.locator("#u")'
    # role wins over text wins over selector — the same order as make_locator.
    assert locator_expr(selector="#u", role="button") == 'page.get_by_role("button")'
    assert locator_expr(selector="#u", frame="#f1") == 'page.frame_locator("#f1").locator("#u")'
    with pytest.raises(ValueError, match="provide one of"):
        locator_expr()


def test_op_generate_locator_from_the_field_cache() -> None:
    h = _handler(_BoxPage())
    h.handle("list_fields", {})  # populates the cache
    out = h.handle("generate_locator", {"index": 0})["result"]
    assert out == {
        "code": 'page.get_by_role("button", name="Go")',
        "css": "#b",
        "xpath": "//button",
    }
    bad = h.handle("generate_locator", {"index": 5})
    assert bad["ok"] is False and "out of range" in bad["error"]


def test_op_generate_locator_from_a_selector_target() -> None:
    h = _handler(_BoxPage())
    out = h.handle("generate_locator", {"role": "button", "name": "Save"})["result"]
    assert out == {
        "code": 'page.get_by_role("button", name="Save")',
        "css": None,
        "xpath": None,
    }


def test_cli_generate_locator(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {}))
        or {"code": 'page.locator("#u")', "css": "#u", "xpath": "//input"},
    )
    r = runner.invoke(app, ["generate-locator", "3"])
    assert r.exit_code == 0, r.output
    assert calls[0] == ("generate_locator", {"index": 3})
    assert 'page.locator("#u")' in r.output
    assert "//input" in r.output


def test_repl_generate_locator() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return {"code": 'page.locator("#u")', "css": None, "xpath": None}

    out = console.dispatch("generate-locator #u", send)
    assert calls[0] == ("generate_locator", {"selector": "#u"})
    assert out == 'page.locator("#u")'
    assert "generate-locator" in console.dispatch("help", send)


@pytest.mark.browser
def test_generate_locator_matches_the_list_fields_column(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )
    try:
        fields = h.handle("list_fields", {"highlight": False})["result"]["fields"]
        i = next(n for n, f in enumerate(fields) if f["locator"] == "#btn")
        out = h.handle("generate_locator", {"index": i})["result"]
        assert out["code"] == fields[i]["code"]
        assert out["css"] == fields[i]["css"]
    finally:
        h.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k "locator_expr or generate_locator" -v --no-cov`
Expected: FAIL — `ImportError: cannot import name 'locator_expr' from 'visus.web.cli.codegen'`.

- [ ] **Step 3: Add the expression builder**

In `src/visus/web/cli/codegen.py`, add after `_target_expr` (`:55-60`):

```python
def _pystr(s: str) -> str:
    """A double-quoted Python string literal.

    Deliberately not ``repr``: this must match how ``Field.code`` is spelled
    (``driver_delegate.py:663-664``) so ``visus generate-locator`` prints the
    same text as the VISUS column of ``visus list-fields`` for the same element.
    ``_target_expr`` above keeps ``repr`` — its output is the golden text asserted
    in ``tests/test_codegen.py``.
    """
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def locator_expr(
    *,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """The copy-paste ``visus.web`` expression for a CLI target.

    Mirrors ``session_server.make_locator``'s branch order exactly — role, then
    text, then selector — so the printed line resolves the element the CLI would
    actually act on, and is frame-aware like ``Field.code``.
    """
    expr = "page" if frame is None else f"page.frame_locator({_pystr(frame)})"
    if role is not None:
        parts = [_pystr(role)]
        if name is not None:
            parts.append(f"name={_pystr(name)}")
        if exact:
            parts.append("exact=True")
        return f"{expr}.get_by_role({', '.join(parts)})"
    if text is not None:
        parts = [_pystr(text)]
        if exact:
            parts.append("exact=True")
        return f"{expr}.get_by_text({', '.join(parts)})"
    if selector is not None:
        return f"{expr}.locator({_pystr(selector)})"
    raise ValueError("provide one of: role, text, selector")
```

- [ ] **Step 4: Add the daemon op, command and REPL branch**

In `src/visus/web/cli/session_server.py`, add after `_op_count` (`:330-331`):

```python
    def _op_generate_locator(self, args: dict[str, Any]) -> dict[str, Any]:
        """The copy-paste visus.web expression for a target.

        For a cached index this is ``Field.code`` verbatim — the same
        frame-aware string ``list_fields`` puts in its VISUS column — plus that
        field's css/xpath. For a selector/role/text target the expression is
        built by ``codegen.locator_expr`` and there is no css/xpath to report.
        """
        from visus.web.cli.codegen import locator_expr

        index = args.get("index")
        if index is not None:
            i = int(index)
            if i < 0 or i >= len(self._fields):
                raise IndexError(
                    f"field index {i} out of range "
                    f"(have {len(self._fields)}; run list_fields first)"
                )
            field = self._fields[i]
            return {"code": field.code, "css": field.css, "xpath": field.xpath}
        return {
            "code": locator_expr(
                selector=args.get("selector"),
                role=args.get("role"),
                name=args.get("name"),
                text=args.get("target_text"),
                exact=bool(args.get("exact", False)),
                frame=args.get("frame"),
            ),
            "css": None,
            "xpath": None,
        }
```

In `src/visus/web/cli/main.py`, add after the `count` command (`:561-570`):

```python
@app.command("generate-locator")
def generate_locator(
    index: int = typer.Argument(None, help="Field index from the last list-fields."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    raw: bool = typer.Option(False, "--raw", help="Print only the expression."),
) -> None:
    """Print the copy-paste `visus.web` expression for one element."""
    from visus.web.cli import output

    result = _send("generate_locator", _target_args(index, selector, role, name, text))
    if raw:
        output.set_mode(raw=True)
    lines = [str(result.get("code", ""))]
    if result.get("css"):
        lines.append(f"css   : {result['css']}")
    if result.get("xpath"):
        lines.append(f"xpath : {result['xpath']}")
    output.emit(result.get("code"), table="\n".join(lines))
```

In `src/visus/web/cli/console.py`, add this branch right after the `count` branch:

```python
        if cmd == "generate-locator":
            gl_target, _ = _target(rest)
            return str(send("generate_locator", gl_target).get("code"))
```

and this `_HELP` line right after `count TARGET`:

```
  generate-locator TGT print the copy-paste visus.web expression
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k "locator_expr or generate_locator" -v --no-cov`
Expected: PASS (5 passed)

- [ ] **Step 6: Run the browser test**

Run: `uv run pytest tests/test_cli_page_ops.py::test_generate_locator_matches_the_list_fields_column -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 7: Verify the codegen suite still passes**

Run: `uv run pytest tests/test_codegen.py -q --no-cov`
Expected: PASS — `_target_expr` and `generate_script` are untouched.

- [ ] **Step 8: Update the README**

In `README.md`, in the **Tooling** table, add a row right after the `visus codegen` row:

```markdown
| `visus generate-locator [idx] [target] [--raw]` | Print the copy-paste `visus.web` expression for one element (plus its css/xpath by index). |
```

- [ ] **Step 9: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/cli/codegen.py src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_page_ops.py README.md
git commit -m "feat(cli): add `visus generate-locator`"
```

---

### Task 17: `visus tracing-start` / `tracing-stop` / `report` — and make `VISUS_WEB_TRACING` honest

Closes **D11** and **row 1**. Tracing is the strongest thing in this codebase and the shell cannot reach any of it: a grep for `tracing|trace|report` across all of `src/visus/web/cli/` returns zero hits.

**Read this before writing any code — the variable is a silent no-op today.** `tracing.py:15-16` reads `VISUS_WEB_TRACING` at import, and `README.md:864` advertises it as *"Enable tracing globally without code."* But `api/_steps.py:166` requires **both** conditions:

```python
if not tracing.is_enabled() or tracing.current_recorder() is None:
    _run_plain(delegate, action, backtrack)
    return
```

and `_STATE.recorder` is assigned in exactly one place — inside `tracing.record()` (`tracing.py:107-108`). Nothing in `cli/` or `mcp/` ever constructs a `Recorder`. So `VISUS_WEB_TRACING=1 visus session start` flips `is_enabled()` to `True`, the second condition still fails, and **nothing is ever recorded**. The env var does nothing and the README claims it does everything.

This task fixes both halves: it builds a real `Recorder` inside the daemon so `_steps.run_step` takes the traced branch, and it rewrites the README row to say what the variable actually does.

**Why a new pair of functions and not `record()`.** `tracing.record` is a `@contextmanager`: its save/restore lives in a `finally`, which is precisely what makes it correct for library code and unusable for a daemon, where `start` and `stop` arrive as two separate socket messages minutes apart. `start_recording`/`stop_recording` are the same body split in two.

**Recorder lifecycle in a long-lived, multi-threaded daemon** — stated explicitly, because getting this wrong leaks a handler onto the root logger forever:

1. **The recorder is process-global, not per-connection.** `tracing._STATE` is a module-level object with no thread-locality, and `_steps.run_step` looks the recorder up through it. There can be exactly one, owned by the daemon process.
2. **Ops never interleave.** PLAN 3 wraps `SessionHandler.handle()` in an `RLock`, so `tracing_start`, `tracing_stop` and every action that records can never run concurrently even though `serve()` spawns a thread per connection (`session_server.py:720-724`).
3. **`SessionHandler` holds the only reference** (`self._recorder`) plus the zip path chosen at start (`self._trace_zip`). `_op_tracing_start` refuses a second start and names the live `run_id`, so a recorder can never be orphaned with its `_LogTailHandler` still attached to the root logger (`recorder.py:79-80`).
4. **Shutdown always flushes.** `SessionHandler.close()` — reached from `_op_shutdown` (`:591-593`), from `serve()`'s `finally` (`:727`), and from `_op_tab_close` when the last tab goes (`:445`) — stops any live recording first, writing the zip if one was requested and otherwise calling `Recorder.close()` to detach the handler. A daemon that dies mid-trace never leaves the handler behind.
5. **Screenshots are opt-out.** `screenshot_each_action` defaults to `True` (`tracing.py:22`) and every shot is buffered in memory until the zip is written (`recorder.py:73`, `:225-226`). `visus tracing-start --no-screenshots` exists for long runs.

**Files:**
- Modify: `src/visus/web/tracing.py` (new `start_recording` / `stop_recording`)
- Modify: `src/visus/web/cli/session_server.py:84-101` (`__init__`), `:162-168` (`close`), new `_op_tracing_*`
- Modify: `src/visus/web/cli/main.py` (new `tracing-start`, `tracing-stop`, `report`)
- Modify: `src/visus/web/cli/console.py` (REPL branches + `_HELP`)
- Modify: `README.md` (Tooling table + the `VISUS_WEB_TRACING` env row)
- Test: `tests/test_cli_tracing.py`

**Interfaces:**
- Consumes: `Recorder` (`run_id`, `summary`, `write_zip`, `close`), `tracing.enable`, `tracing.render_report`, `tracing._STATE`, `output.emit`
- Produces:
  ```python
  tracing.start_recording(**opts: Any) -> Recorder
  tracing.stop_recording(zip_path: str | None = None, report: str | None = None) -> dict[str, str]
  ```
  daemon ops `tracing_start` → `{"run_id", "zip_path"}`, `tracing_stop` → `{"run_id", "zip", "report"?, "actions", "failures"}`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_tracing.py`:

```python
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
    """_steps.py:166 needs is_enabled() AND current_recorder() — today only the first."""
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_tracing.py -m "not browser" -v --no-cov`
Expected: FAIL — `test_start_recording_satisfies_both_conditions_run_step_checks` raises `AttributeError: module 'visus.web.tracing' has no attribute 'start_recording'`.

- [ ] **Step 3: Split `record()` into start/stop**

In `src/visus/web/tracing.py`, extend the imports at the top:

```python
from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
```

and add this block immediately after `_STATE = _Tracing()` (`:29`):

```python
@dataclass
class _RecordingSession:
    """The global state ``start_recording`` took over, so ``stop`` can give it back."""

    recorder: Recorder
    prev_enabled: bool
    prev_recorder: Recorder | None
    prev_sink: Any


_SESSION: _RecordingSession | None = None


def start_recording(**opts: Any) -> Recorder:
    """Begin a tracing session WITHOUT a ``with`` block, and return the Recorder.

    :func:`record` is a context manager: its restore lives in a ``finally``,
    which is exactly right for library code and unusable for a long-lived
    process where "start" and "stop" arrive as two separate commands. This is
    the same body split in two — it enables tracing AND installs a live
    :class:`~visus.web.observability.recorder.Recorder`, which is what
    ``api/_steps.run_step`` requires before it will record anything
    (``VISUS_WEB_TRACING`` alone only satisfies half of that check).

    Raises :class:`RuntimeError` if a session is already recording: two live
    recorders would both attach a handler to the ROOT logger and only one of
    them could ever be detached.
    """
    global _SESSION
    from visus.web.observability.recorder import Recorder

    if _SESSION is not None:
        raise RuntimeError(
            f"a tracing session is already recording (run_id {_SESSION.recorder.run_id})"
        )
    prev_enabled, prev_recorder, prev_sink = _STATE.enabled, _STATE.recorder, _STATE.step_sink
    enable(**opts)
    rec = Recorder()
    _STATE.recorder = rec
    _SESSION = _RecordingSession(
        recorder=rec,
        prev_enabled=prev_enabled,
        prev_recorder=prev_recorder,
        prev_sink=prev_sink,
    )
    return rec


def stop_recording(
    zip_path: str | None = None, report: str | None = None
) -> dict[str, str]:
    """End the session started by :func:`start_recording` and restore prior state.

    Writes the zip when *zip_path* is given, and the HTML report when *report*
    is too. With no *zip_path* it only releases the recorder's root-logger
    handler — use that when a run should be discarded rather than saved.

    Returns ``{"run_id": ...}`` plus ``"zip"`` / ``"report"`` when written.
    Raises :class:`RuntimeError` when nothing is recording.
    """
    global _SESSION
    session = _SESSION
    if session is None:
        raise RuntimeError(
            "no tracing session is recording — call start_recording() first"
        )
    # Restore FIRST, so a failing write cannot leave the globals pointing at a
    # recorder that has already been detached.
    _SESSION = None
    _STATE.recorder = session.prev_recorder
    _STATE.enabled = session.prev_enabled
    _STATE.step_sink = session.prev_sink
    out: dict[str, str] = {"run_id": session.recorder.run_id}
    if zip_path is None:
        session.recorder.close()
        return out
    session.recorder.write_zip(zip_path)
    out["zip"] = str(Path(zip_path).resolve())
    if report:
        out["report"] = render_report(zip_path, report)
    return out
```

`record()` is left exactly as it is: it must save and restore around a body that may raise, and folding it onto these two would change that behaviour for every existing caller.

- [ ] **Step 4: Own the recorder in the daemon**

In `src/visus/web/cli/session_server.py`, add two attributes to `__init__`, right after `self._follow: bool = True`:

```python
        # A tracing session is process-global (tracing._STATE has no thread
        # locality), so the handler owns at most one and flushes it on close().
        self._recorder: Any = None
        self._trace_zip: str | None = None
```

Add this helper and replace `close` (`:162-168`):

```python
    def _stop_tracing_if_running(self) -> None:
        """Flush a live tracing session so shutdown never orphans its log handler."""
        if self._recorder is None:
            return
        from visus.web import tracing

        try:
            tracing.stop_recording(self._trace_zip, None)
        except Exception:  # noqa: BLE001 — shutdown must not fail on a trace flush
            pass
        self._recorder = None
        self._trace_zip = None

    def close(self) -> None:
        self._stop_tracing_if_running()
        if self._browser is not None:
            self._browser.close()
        self._browser = None
        self._context = None
        self._page = None
        self._fields = []
```

Add the two ops after `_op_eval`:

```python
    # --- tracing ---------------------------------------------------------
    def _op_tracing_start(self, args: dict[str, Any]) -> dict[str, Any]:
        """Start recording every action into an in-memory Recorder.

        This is what makes ``VISUS_WEB_TRACING`` meaningful from the shell:
        ``api/_steps.run_step`` only records when tracing is enabled AND a
        Recorder is installed, and nothing outside ``tracing.record()`` ever
        installed one before this op existed.

        ``screenshots=False`` turns off the per-action PNG — every shot is held
        in memory until the zip is written, so a long run should opt out.
        """
        from visus.web import tracing

        if self._recorder is not None:
            raise RuntimeError(
                f"tracing is already recording (run_id {self._recorder.run_id}) — "
                "run `visus tracing-stop` first"
            )
        zip_path = args.get("zip_path")
        self._trace_zip = str(Path(zip_path).resolve()) if zip_path else None
        self._recorder = tracing.start_recording(
            screenshot_each_action=bool(args.get("screenshots", True))
        )
        return {"run_id": self._recorder.run_id, "zip_path": self._trace_zip}

    def _op_tracing_stop(self, args: dict[str, Any]) -> dict[str, Any]:
        """Write the trace zip (and optionally the HTML report) and stop recording."""
        from visus.web import tracing

        if self._recorder is None:
            raise RuntimeError("tracing is not recording — run `visus tracing-start` first")
        summary = self._recorder.summary()
        zip_path = args.get("zip_path") or self._trace_zip or "run.zip"
        report = args.get("report")
        written = tracing.stop_recording(str(Path(zip_path).resolve()), report)
        self._recorder = None
        self._trace_zip = None
        out: dict[str, Any] = dict(written)
        out["actions"] = summary["total"]
        out["failures"] = summary["failures"]
        return out
```

- [ ] **Step 5: Add the CLI commands**

In `src/visus/web/cli/main.py`, add after the `codegen` command (`:170-194`):

```python
# ---------------------------------------------------------------------------
# Tracing & reports
# ---------------------------------------------------------------------------


@app.command("tracing-start")
def tracing_start(
    output_zip: str = typer.Option("run.zip", "-o", "--output", help="Where to write the trace."),
    screenshots: bool = typer.Option(
        True, "--screenshots/--no-screenshots", help="Capture a PNG per action (held in memory)."
    ),
) -> None:
    """Record every session action into a trace (stop with `visus tracing-stop`)."""
    from visus.web.cli import output

    # Resolve against the CLIENT's cwd — the daemon's may differ.
    result = _send(
        "tracing_start",
        {"zip_path": str(Path(output_zip).resolve()), "screenshots": screenshots},
    )
    output.emit(result, table=f"tracing run {result['run_id']} → {result['zip_path']}")


@app.command("tracing-stop")
def tracing_stop(
    output_zip: str = typer.Option(
        None, "-o", "--output", help="Override the path chosen at tracing-start."
    ),
    report_html: str = typer.Option(
        None, "--report", help="Also render a single-file HTML report to this path."
    ),
) -> None:
    """Stop recording, write the trace zip (and optionally the HTML report)."""
    from visus.web.cli import output

    args: dict[str, Any] = {"report": str(Path(report_html).resolve()) if report_html else None}
    if output_zip:
        args["zip_path"] = str(Path(output_zip).resolve())
    result = _send("tracing_stop", args)
    lines = [
        f"tracing run {result['run_id']} stopped: "
        f"{result['actions']} action(s), {result['failures']} failure(s)",
        f"trace  : {result.get('zip', '')}",
    ]
    if result.get("report"):
        lines.append(f"report : {result['report']}")
    output.emit(result, table="\n".join(lines))


@app.command()
def report(
    trace_zip: str = typer.Argument(..., help="A trace written by `visus tracing-stop`."),
    output_html: str = typer.Option("report.html", "-o", "--output"),
) -> None:
    """Render a self-contained HTML report from a trace zip (no session needed)."""
    from visus.web import tracing
    from visus.web.cli import output

    path = tracing.render_report(
        str(Path(trace_zip).resolve()), str(Path(output_html).resolve())
    )
    output.emit(path, table=f"saved {path}")
```

- [ ] **Step 6: Add the REPL branches**

In `src/visus/web/cli/console.py`, add these branches right after the `eval-on` branch:

```python
        if cmd == "tracing-start":
            tr = send(
                "tracing_start",
                {
                    "zip_path": str(Path(rest[0] if rest else "run.zip").resolve()),
                    "screenshots": True,
                },
            )
            return f"tracing run {tr['run_id']} → {tr['zip_path']}"
        if cmd == "tracing-stop":
            tr = send("tracing_stop", {"report": str(Path(rest[0]).resolve()) if rest else None})
            line = (
                f"tracing run {tr['run_id']} stopped: "
                f"{tr['actions']} action(s), {tr['failures']} failure(s) → {tr.get('zip', '')}"
            )
            return line + (f"\nreport : {tr['report']}" if tr.get("report") else "")
```

and these two `_HELP` lines right after `eval-on`:

```
  tracing-start [zip]  record every action (default run.zip)
  tracing-stop [html]  stop; write the zip (+ an HTML report if given)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_tracing.py -m "not browser" -v --no-cov`
Expected: PASS (10 passed)

- [ ] **Step 8: Run the browser test**

Run: `uv run pytest tests/test_cli_tracing.py::test_tracing_records_real_daemon_actions_and_renders_a_report -v --no-cov`
Expected: PASS (1 passed) — this is the D11 regression guard: before this task the zip's `events.jsonl` would be empty.

- [ ] **Step 9: Verify the tracing suites still pass**

Run: `uv run pytest tests/test_tracing_unit.py tests/test_e2e_observability.py -q --no-cov`
Expected: PASS — `record()` is byte-for-byte unchanged, and `start_recording`/`stop_recording` only touch `_SESSION` plus the same three `_STATE` fields `record()` already saved and restored.

- [ ] **Step 10: Correct the README**

In `README.md`, in the environment-variable table, replace the `VISUS_WEB_TRACING` row (`:864`) — the current wording promises something the variable has never done:

```markdown
| `VISUS_WEB_TRACING` | tracing | off | Pre-enables the tracing flag. **A recorder is still required**: use `tracing.record(...)` in code, or `visus tracing-start` from the shell. On its own it records nothing. |
```

In the **Tooling** table, add three rows after `visus codegen`:

```markdown
| `visus tracing-start -o <zip> [--no-screenshots]` | Record every session action (screenshots, logs, ARIA snapshot on failure). |
| `visus tracing-stop [-o <zip>] [--report <html>]` | Stop recording; write the trace and optionally a single-file HTML report. |
| `visus report <trace.zip> -o <html>` | Render a self-contained HTML report from a trace (no session needed). |
```

- [ ] **Step 11: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: `All checks passed!` and `Success: no issues found`

```bash
git add src/visus/web/tracing.py src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_tracing.py README.md
git commit -m "feat(cli): add tracing-start/tracing-stop/report and fix the inert VISUS_WEB_TRACING claim"
```

---

### Task 18: `visus network start` / `stop` / `export` — give `NetworkCapture` its first production call site

Closes **D10**. `src/visus/web/network.py` is 444 lines of working subsystem with **no production caller anywhere**: a grep finds the file itself, two explanatory comments (`backends/browsers/chrome.py:29`, `edge.py:29`) and two test modules. It is absent from the README, both skills, the CLI and all 45 MCP tools.

**Read `network.py` in full before writing this task's code.** Two facts from it drive every decision below.

**Fact 1 — two layers, only one of them is safe to run inside the daemon.**
`NetworkCapture` merges a JS hook with a CDP drain (`network.py:381-437`):

* the **JS hook** (`_HOOK_JS`, `:62-122`) patches `fetch`, `XMLHttpRequest`, `navigator.sendBeacon` and dynamically-set `<script>`/`<img>` `src`, recording into `window.__vcm_capture`. Reading it (`_READ_JS`, `:124`) is a plain `page.evaluate` — **non-destructive**, repeatable, and it captures **request bodies**, JSONP, beacons and pixel pings that nothing else in this repo sees.
* the **CDP drain** (`_drain_cdp`, `:246-314`) calls `driver.get_log("performance")` at `:262`.

`get_log("performance")` **returns and clears**. And the page delegate already drains that exact log for its own buffer — `SeleniumPageDelegate._drain_logs` (`driver_delegate.py:961-972`), which is what `page.network_requests()` (`:1013-1017`) and therefore Task 4's `visus requests` are built on. Two consumers of one destructive log means whoever calls first wins and the other silently loses entries: running both inside one daemon would make `visus requests` and `visus network export` intermittently lie about each other's traffic.

**Decision: the daemon constructs `NetworkCapture(page, use_cdp=False)`.** That removes the shared destructive resource by construction and gives the two commands a clean, statable division of labour:

| Command | Source | Sees |
|---|---|---|
| `visus requests` / `visus request N` (Task 4) | the delegate's CDP buffer | **every** response — documents, assets, XHR/fetch — with status, resource type, redirect legs, and response bodies via `Network.getResponseBody` |
| `visus network export` (this task) | the JS hook | every request the **page itself initiated**, with **request bodies**, plus JSONP `<script>`, `sendBeacon` and `<img>` pings, and same-origin fetch/XHR response bodies — in the `{target_url, entries}` document shape, headers already scrubbed (`network.py:33-53`, applied at `:427-428`) |

Redirect hops are the one thing CDP alone sees; `visus requests` shows them. Both commands exist, neither is redundant, and neither can starve the other.

**Fact 2 — a daemon breaks two of `NetworkCapture`'s assumptions**, which is why it needs `rebind`:

* `self.page` is bound once, in `__init__` (`:169`). But `SessionHandler._active_page` (`session_server.py:133-149`) constructs a **brand-new `Page`** whenever the active window handle differs from the cached one, so a capture created on tab 0 would keep evaluating against tab 0 after a `tab` switch.
* the hook lives in the JS world, and a navigation wipes `window.__vcm_installed`. The hook is idempotent (`network.py:63`), so re-running it is free.

`rebind(page)` does both — re-point and re-arm — and every capture-touching op calls it first.

**Lifecycle ownership:** `SessionHandler` holds `self._capture`; `_op_network_capture_start` is idempotent (a second start rebinds rather than dropping the buffer); `close()` drops the reference, because a capture without a browser is meaningless. Ops are serialised by PLAN 3's `RLock`, so no two touch the capture at once.

**Files:**
- Modify: `src/visus/web/network.py` (new `NetworkCapture.rebind`)
- Modify: `src/visus/web/cli/session_server.py:84-101` (`__init__`), `:162-168` (`close`), new `_op_network_capture_*`
- Modify: `src/visus/web/cli/main.py` (new `network` Typer sub-app)
- Modify: `src/visus/web/cli/console.py` (REPL `network` branch + `_HELP`)
- Modify: `README.md` (Dialogs / cookies / JS table)
- Test: `tests/test_cli_devtools.py`

**Interfaces:**
- Consumes: `NetworkCapture.__init__(page, use_cdp)`, `.start()`, `.stop()`, `.get_requests(filter_type)`, `.export_enriched(path)`, `Page.evaluate`, `output.emit`
- Produces: `NetworkCapture.rebind(self, page: Any) -> None`; daemon ops `network_capture_start` → `{"started": bool}`, `network_capture_stop` → `{"stopped": bool, "captured": int}`, `network_capture_export` → `{"path": str, "entries": int}`

- [ ] **Step 1: Write the failing test**

First add one import to the top of `tests/test_cli_devtools.py` (Task 3 created it without one), so the block below type-checks and lints:

```python
from pathlib import Path
```

Then append:

```python
# ---------------------------------------------------------------------------
# NetworkCapture: start / stop / export
# ---------------------------------------------------------------------------


class _CapturePage:
    """Page stub that records every evaluate — the hook install is an evaluate."""

    def __init__(self, url: str = "http://x/") -> None:
        self.url = url
        self.evaluated: list[str] = []

    def evaluate(self, expression: str, arg: object = None) -> object:
        self.evaluated.append(expression)
        if expression.startswith("() => JSON"):  # the _READ_JS drain
            return json.dumps(
                [
                    {
                        "url": "http://x/api",
                        "method": "POST",
                        "status": 200,
                        "reqBody": '{"q": 1}',
                        "respBody": '{"ok": true}',
                        "headers": {"authorization": "Bearer s3cret"},
                        "resourceType": "fetch",
                    }
                ]
            )
        return True  # the _HOOK_JS install


def test_rebind_repoints_and_rearms_the_hook() -> None:
    from visus.web.network import NetworkCapture

    first, second = _CapturePage("http://a/"), _CapturePage("http://b/")
    cap = NetworkCapture(first, use_cdp=False)
    cap.start()
    assert len(first.evaluated) == 1  # the hook install

    cap.rebind(second)
    assert cap.page is second
    assert len(second.evaluated) == 1  # re-armed on the new page

    # Before start(), rebind must not install anything.
    third = _CapturePage("http://c/")
    idle = NetworkCapture(third, use_cdp=False)
    idle.rebind(_CapturePage("http://d/"))
    assert third.evaluated == []


def test_op_network_capture_lifecycle_and_export(tmp_path: Path) -> None:
    page = _CapturePage()
    h = _handler(page)

    started = h.handle("network_capture_start", {})
    assert started["ok"] is True, started
    assert started["result"] == {"started": True}

    out_file = tmp_path / "capture.json"
    exported = h.handle("network_capture_export", {"path": str(out_file)})["result"]
    assert exported["path"] == str(out_file.resolve())
    assert exported["entries"] == 1

    doc = json.loads(out_file.read_text(encoding="utf-8"))
    assert doc["target_url"] == "http://x/"
    entry = doc["entries"][0]
    assert entry["reqBody"] == '{"q": 1}'
    assert entry["headers"]["authorization"] == "REDACTED"  # scrubbed on the way out

    stopped = h.handle("network_capture_stop", {})["result"]
    assert stopped == {"stopped": True, "captured": 1}


def test_op_network_export_without_a_capture_is_a_clean_error(tmp_path: Path) -> None:
    h = _handler(_CapturePage())
    bad = h.handle("network_capture_export", {"path": str(tmp_path / "c.json")})
    assert bad["ok"] is False
    assert "visus network start" in bad["error"]


def test_close_drops_the_capture() -> None:
    h = _handler(_CapturePage())
    h.handle("network_capture_start", {})
    assert h._capture is not None
    h.close()
    assert h._capture is None


def test_cli_network_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        if op == "network_capture_export":
            return {"path": str(tmp_path / "capture.json"), "entries": 12}
        if op == "network_capture_stop":
            return {"stopped": True, "captured": 12}
        return {"started": True}

    monkeypatch.setattr(session_client, "send", fake_send)
    assert runner.invoke(app, ["network", "start"]).exit_code == 0
    r = runner.invoke(app, ["network", "export", "-o", str(tmp_path / "capture.json")])
    assert r.exit_code == 0, r.output
    assert "12" in r.output
    assert runner.invoke(app, ["network", "stop"]).exit_code == 0
    assert calls[0] == ("network_capture_start", {})
    assert calls[1] == (
        "network_capture_export",
        {"path": str((tmp_path / "capture.json").resolve())},
    )
    assert calls[2] == ("network_capture_stop", {})


def test_repl_network_branches() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "network_capture_export":
            return {"path": "capture.json", "entries": 3}
        if op == "network_capture_stop":
            return {"stopped": True, "captured": 3}
        return {"started": True}

    console.dispatch("network start", send)
    console.dispatch("network export capture.json", send)
    console.dispatch("network stop", send)
    assert calls[0] == ("network_capture_start", {})
    assert calls[1][0] == "network_capture_export"
    assert calls[1][1]["path"] == str(Path("capture.json").resolve())
    assert calls[2] == ("network_capture_stop", {})
    assert "network" in console.dispatch("help", send)


@pytest.mark.browser
def test_network_capture_export_against_a_real_page(base_url: str, tmp_path: Path) -> None:
    """The JS hook records the REQUEST body — the thing `visus requests` cannot show."""
    import time

    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/network.html"
    )
    try:
        assert h.handle("network_capture_start", {})["ok"] is True
        h.handle(
            "eval",
            {
                "expression": "() => { window.__t = false;"
                " fetch('/forms.html', {method: 'POST', body: 'q=visus'})"
                " .then(r => r.text()).then(() => { window.__t = true; }); return true; }"
            },
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if h.handle("eval", {"expression": "() => window.__t === true"})["result"]["result"]:
                break
            time.sleep(0.1)

        out_file = tmp_path / "capture.json"
        exported = h.handle("network_capture_export", {"path": str(out_file)})
        assert exported["ok"] is True, exported
        assert exported["result"]["entries"] >= 1
    finally:
        h.close()

    doc = json.loads(out_file.read_text(encoding="utf-8"))
    assert doc["target_url"].endswith("/network.html")
    posted = [e for e in doc["entries"] if e["method"] == "POST"]
    assert posted, doc["entries"]
    assert posted[0]["reqBody"] == "q=visus"
    assert "Fields" in (posted[0]["respBody"] or "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_devtools.py -m "not browser" -k "rebind or network_capture or network_export or network_commands or network_branches or drops_the_capture" -v --no-cov`
Expected: FAIL — `test_rebind_repoints_and_rearms_the_hook` raises `AttributeError: 'NetworkCapture' object has no attribute 'rebind'`.

- [ ] **Step 3: Add `rebind`**

In `src/visus/web/network.py`, add this method to `NetworkCapture` right after `stop` (`:217-227`):

```python
    def rebind(self, page: Any) -> None:
        """Point this capture at *page* and re-arm the JS hook on it.

        A long-lived driver (the CLI daemon) breaks two assumptions this class
        makes when it is used as a short-lived ``start() → drive → export()``
        block:

        * ``self.page`` is bound once in ``__init__``, but the daemon builds a
          NEW ``Page`` object whenever the active tab changes, so the capture
          would keep evaluating against the old tab;
        * the hook lives in the JS world and a navigation wipes
          ``window.__vcm_installed``.

        Re-arming is free — the hook returns early when it is already installed
        — and harmless before :meth:`start`, where it is skipped entirely. A
        page that is mid-navigation simply gets re-armed on the next call.
        """
        self.page = page
        if not self._started:
            return
        try:
            self.page.evaluate(_HOOK_JS)
        except Exception:
            pass  # mid-navigation: the next rebind re-arms it
```

- [ ] **Step 4: Own the capture in the daemon**

In `src/visus/web/cli/session_server.py`, add one attribute to `__init__`, right after `self._trace_zip: str | None = None`:

```python
        # NetworkCapture is created with use_cdp=False on purpose: the delegate
        # already drains driver.get_log("performance") for page.network_requests(),
        # and that read is DESTRUCTIVE — two drainers would silently split the log.
        self._capture: Any = None
```

Add `self._capture = None` to `close`, right after `self._fields = []`:

```python
    def close(self) -> None:
        self._stop_tracing_if_running()
        if self._browser is not None:
            self._browser.close()
        self._browser = None
        self._context = None
        self._page = None
        self._fields = []
        self._capture = None  # a capture without a browser is meaningless
```

Add the three ops right after `_op_network_request`:

```python
    def _op_network_capture_start(self, args: dict[str, Any]) -> dict[str, Any]:
        """Install the JS traffic hook on the current page.

        Complements ``network_requests``: that op reads the delegate's CDP
        buffer (every response, incl. assets and redirect legs); this one records
        what the PAGE initiated — request bodies, JSONP ``<script>``,
        ``sendBeacon`` and ``<img>`` pings — which CDP response logging cannot
        give. ``use_cdp=False`` keeps the two off the same destructive
        ``get_log("performance")`` stream.

        Idempotent: starting twice rebinds and re-arms without losing the buffer.
        """
        from visus.web.network import NetworkCapture

        page = self.page()
        if self._capture is None:
            self._capture = NetworkCapture(page, use_cdp=False)
            self._capture.start()
        else:
            self._capture.rebind(page)
        return {"started": True}

    def _op_network_capture_stop(self, args: dict[str, Any]) -> dict[str, Any]:
        """Uninstall the hook and report how many entries were captured."""
        if self._capture is None:
            raise RuntimeError("no capture is running — run `visus network start` first")
        self._capture.rebind(self.page())
        captured = len(self._capture.get_requests())
        self._capture.stop()
        self._capture = None
        return {"stopped": True, "captured": captured}

    def _op_network_capture_export(self, args: dict[str, Any]) -> dict[str, Any]:
        """Write the captured traffic as ``{target_url, entries}`` JSON (scrubbed)."""
        if self._capture is None:
            raise RuntimeError("no capture is running — run `visus network start` first")
        path = str(args.get("path") or "capture.json")
        self._capture.rebind(self.page())
        entries = len(self._capture.get_requests())
        self._capture.export_enriched(path)
        return {"path": str(Path(path).resolve()), "entries": entries}
```

- [ ] **Step 5: Add the `network` sub-app**

In `src/visus/web/cli/main.py`, add after the `request` command:

```python
# ---------------------------------------------------------------------------
# Full traffic capture (request bodies, JSONP, beacons, pixel pings)
# ---------------------------------------------------------------------------

network_app = typer.Typer(
    help="Capture what the page itself sends (complements `visus requests`)."
)
app.add_typer(network_app, name="network")


@network_app.command("start")
def network_start() -> None:
    """Start capturing the page's own traffic (install the hook before you interact)."""
    from visus.web.cli import output

    _send("network_capture_start", {})
    output.emit({"started": True}, table="capture started")


@network_app.command("stop")
def network_stop() -> None:
    """Stop capturing and report how many entries were recorded."""
    from visus.web.cli import output

    result = _send("network_capture_stop", {})
    output.emit(result, table=f"capture stopped ({result['captured']} entr(y|ies))")


@network_app.command("export")
def network_export(
    output_file: str = typer.Option("capture.json", "-o", "--output"),
) -> None:
    """Write the captured traffic to JSON: `{target_url, entries}`, secrets redacted."""
    from visus.web.cli import output

    # Resolve against the CLIENT's cwd — the daemon's may differ.
    result = _send("network_capture_export", {"path": str(Path(output_file).resolve())})
    output.emit(result, table=f"saved {result['path']} ({result['entries']} entries)")
```

- [ ] **Step 6: Add the REPL branch**

In `src/visus/web/cli/console.py`, add this branch right after the `request` branch:

```python
        if cmd == "network":
            sub = rest[0].lower() if rest else ""
            if sub == "start":
                send("network_capture_start", {})
                return "capture started"
            if sub == "stop":
                stopped = send("network_capture_stop", {})
                return f"capture stopped ({stopped['captured']} entries)"
            if sub == "export":
                target = str(Path(rest[1] if len(rest) > 1 else "capture.json").resolve())
                saved = send("network_capture_export", {"path": target})
                return f"saved {saved['path']} ({saved['entries']} entries)"
            return "usage: network start|stop|export [path]"
```

and this `_HELP` line right after `request N`:

```
  network SUB [path]   full traffic capture: start|stop|export [path]
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_devtools.py -m "not browser" -k "rebind or network_capture or network_export or network_commands or network_branches or drops_the_capture" -v --no-cov`
Expected: PASS (6 passed)

- [ ] **Step 8: Run the browser test**

Run: `uv run pytest tests/test_cli_devtools.py::test_network_capture_export_against_a_real_page -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 9: Verify the NetworkCapture suites still pass**

Run: `uv run pytest tests/test_network_capture.py tests/test_network_capture_cdp.py -q --no-cov`
Expected: PASS — `rebind` is purely additive and no existing method changed.

Run: `uv run pytest tests/test_cli_devtools.py -m "not browser" -q --no-cov`
Expected: PASS — `visus requests` is untouched and still reads the delegate's buffer.

- [ ] **Step 10: Update the README**

In `README.md`, in the **Dialogs / cookies / JS** table, add a row after the `visus request <N>` row:

```markdown
| `visus network start` / `stop` / `export -o <json>` | Capture what the page itself sends — request bodies, JSONP, `sendBeacon`, pixel pings — and export it scrubbed. Complements `visus requests`, which reads the CDP response log. |
```

- [ ] **Step 11: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: `All checks passed!` and `Success: no issues found`

```bash
git add src/visus/web/network.py src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_devtools.py README.md
git commit -m "feat(cli): expose NetworkCapture via `visus network start/stop/export`"
```

---

### Task 19: `visus session-pdf -o <file>`

Closes **row 5**. `visus pdf <URL>` (`main.py:133-144`) launches its own throwaway browser, so a PDF of the page the agent just logged into and navigated is impossible — the one-shot browser has none of that state. `Page.pdf(path=)` exists (`api/page.py:310-315`, delegated at `driver_delegate.py:724-737`, W3C `print_page` with a CDP fallback), and `_op_screenshot` (`session_server.py:281-294`) is the exact three-line template: the client resolves the path against **its** cwd, the daemon writes the file and returns the absolute path it wrote.

**Files:**
- Modify: `src/visus/web/cli/session_server.py` (new `_op_pdf`)
- Modify: `src/visus/web/cli/main.py` (new `session-pdf` command)
- Modify: `src/visus/web/cli/console.py` (REPL `pdf` branch + `_HELP`)
- Modify: `README.md` (Capture / vision / utilities table)
- Test: `tests/test_cli_page_ops.py`

**Interfaces:**
- Consumes: `Page.pdf(*, path)`, `output.emit`
- Produces: daemon op `pdf` → the absolute path written

- [ ] **Step 1: Write the failing test**

First add one import to the top of `tests/test_cli_page_ops.py` — this is the first block in that file to need it (Tasks 20 and 21 use it too):

```python
from pathlib import Path
```

Then append:

```python
# ---------------------------------------------------------------------------
# session pdf
# ---------------------------------------------------------------------------


class _PdfPage:
    url = "http://x/"

    def __init__(self) -> None:
        self.written: str | None = None

    def pdf(self, *, path: str | None = None) -> bytes:
        self.written = path
        if path is not None:
            Path(path).write_bytes(b"%PDF-1.4\n")
        return b"%PDF-1.4\n"


def test_op_pdf_writes_and_returns_the_absolute_path(tmp_path: Path) -> None:
    page = _PdfPage()
    h = _handler(page)
    target = tmp_path / "out.pdf"
    out = h.handle("pdf", {"path": str(target)})
    assert out["ok"] is True, out
    assert out["result"] == str(target.resolve())
    assert page.written == str(target)
    assert target.read_bytes().startswith(b"%PDF")


def test_cli_session_pdf_resolves_against_the_client_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {})) or str(tmp_path / "out.pdf"),
    )
    r = runner.invoke(app, ["session-pdf", "-o", str(tmp_path / "out.pdf")])
    assert r.exit_code == 0, r.output
    assert calls[0] == ("pdf", {"path": str((tmp_path / "out.pdf").resolve())})
    assert "out.pdf" in r.output


def test_repl_pdf_resolves_against_the_client_cwd() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return "/abs/page.pdf"

    out = console.dispatch("pdf report.pdf", send)
    assert calls[0] == ("pdf", {"path": str(Path("report.pdf").resolve())})
    assert "saved /abs/page.pdf" == out
    console.dispatch("pdf", send)
    assert calls[1][1]["path"].endswith("page.pdf")
    assert "pdf" in console.dispatch("help", send)


@pytest.mark.browser
def test_session_pdf_against_a_real_page(base_url: str, tmp_path: Path) -> None:
    target = tmp_path / "page.pdf"
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/forms.html"
    )
    try:
        out = h.handle("pdf", {"path": str(target)})
        assert out["ok"] is True, out
        assert out["result"] == str(target.resolve())
    finally:
        h.close()
    assert target.read_bytes().startswith(b"%PDF")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k pdf -v --no-cov`
Expected: FAIL — `test_op_pdf_writes_and_returns_the_absolute_path` gets `{"ok": False, "error": "ValueError: unknown op 'pdf'"}`.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/session_server.py`, add right after `_op_screenshot` (`:281-294`):

```python
    def _op_pdf(self, args: dict[str, Any]) -> str:
        """Print the session's current page to a PDF file (Chromium/W3C print).

        Same contract as ``_op_screenshot``: the client resolves the path
        against ITS cwd, the daemon writes the file and returns the absolute
        path it wrote.
        """
        path = args.get("path") or "page.pdf"
        self.page().pdf(path=path)
        return str(Path(path).resolve())
```

In `src/visus/web/cli/main.py`, add right after `session_screenshot` (`:422-446`):

```python
@app.command("session-pdf")
def session_pdf(
    output_file: str = typer.Option("page.pdf", "-o", "--output"),
) -> None:
    """Print the session's current page to a PDF (keeps your login and navigation)."""
    from visus.web.cli import output

    # Resolve the path against the CLIENT's cwd (not the daemon's).
    result = _send("pdf", {"path": str(Path(output_file).resolve())})
    output.emit(result, table=f"saved {result}")
```

In `src/visus/web/cli/console.py`, add this branch right after the `screenshot` branch:

```python
        if cmd == "pdf":
            pdf_path = str(Path(rest[0] if rest else "page.pdf").resolve())
            return f"saved {send('pdf', {'path': pdf_path})}"
```

and this `_HELP` line right after `screenshot [path]`:

```
  pdf [path]           print the page to a PDF (default page.pdf)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k pdf -v --no-cov`
Expected: PASS (3 passed)

- [ ] **Step 5: Run the browser test**

Run: `uv run pytest tests/test_cli_page_ops.py::test_session_pdf_against_a_real_page -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 6: Update the README**

In `README.md`, in the **Capture / vision / utilities** table, add a row right after the `visus pdf <URL>` row:

```markdown
| `visus session-pdf -o <pdf>` | Print the **session's** current page to a PDF (keeps login + navigation). |
```

- [ ] **Step 7: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_page_ops.py README.md
git commit -m "feat(cli): add `visus session-pdf` for the live session's page"
```

---

### Task 20: `--hires` on the session screenshot

Closes half of **row 28**. `_op_screenshot` (`session_server.py:281-294`) captures at the device pixel ratio the browser happens to be running at — 1 in headless Chrome. A vision model reading a numbered `list-fields` overlay, or OCR via `visus read-text`, works markedly better at 2×. `Page.set_device_metrics` (`api/page.py:442-455` → `Emulation.setDeviceMetricsOverride`, `driver_delegate.py:1108-1125`) already takes a `device_scale_factor`.

There is **no** `clearDeviceMetricsOverride` in the delegate, so the op restores by re-overriding at the same size with `device_scale_factor=1.0` — the state it started from — inside a `finally`, so a failed capture cannot leave the session stuck at 2×.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:281-294` (`_op_screenshot`)
- Modify: `src/visus/web/cli/main.py:422-446` (`session-screenshot`)
- Modify: `src/visus/web/cli/console.py` (REPL `screenshot` branch + `_HELP`)
- Modify: `README.md` (Capture / vision / utilities table)
- Test: `tests/test_cli_page_ops.py`

**Interfaces:**
- Consumes: `Page.set_device_metrics`, `Page.evaluate`, `Page.screenshot`, `Locator.screenshot`, `SessionHandler._has_target`
- Produces: `screenshot` op accepts `hires: bool`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_page_ops.py`:

```python
# ---------------------------------------------------------------------------
# --hires
# ---------------------------------------------------------------------------


def _png_size(path: Path) -> tuple[int, int]:
    """Width/height straight out of the PNG IHDR chunk — no image library needed."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


class _HiresPage:
    url = "http://x/"

    def __init__(self, *, fail: bool = False) -> None:
        self.metrics: list[tuple[int, int, float]] = []
        self.shots = 0
        self._fail = fail

    def evaluate(self, expression: str, arg: object = None) -> object:
        return {"w": 800, "h": 600}

    def set_device_metrics(
        self, width: int, height: int, *, device_scale_factor: float = 1.0, mobile: bool = False
    ) -> None:
        self.metrics.append((width, height, device_scale_factor))

    def screenshot(self, *, path: str | None = None, full_page: bool = False) -> bytes:
        if self._fail:
            raise RuntimeError("capture blew up")
        self.shots += 1
        if path is not None:
            Path(path).write_bytes(b"png")
        return b"png"


def test_op_screenshot_hires_sets_then_restores_the_scale(tmp_path: Path) -> None:
    page = _HiresPage()
    h = _handler(page)
    out = h.handle("screenshot", {"path": str(tmp_path / "s.png"), "hires": True})
    assert out["ok"] is True, out
    assert page.shots == 1
    assert page.metrics == [(800, 600, 2.0), (800, 600, 1.0)]


def test_op_screenshot_without_hires_touches_no_metrics(tmp_path: Path) -> None:
    page = _HiresPage()
    h = _handler(page)
    h.handle("screenshot", {"path": str(tmp_path / "s.png")})
    assert page.metrics == []


def test_op_screenshot_hires_restores_even_when_the_capture_fails(tmp_path: Path) -> None:
    page = _HiresPage(fail=True)
    h = _handler(page)
    bad = h.handle("screenshot", {"path": str(tmp_path / "s.png"), "hires": True})
    assert bad["ok"] is False and "capture blew up" in bad["error"]
    assert page.metrics == [(800, 600, 2.0), (800, 600, 1.0)]


def test_cli_session_screenshot_hires(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {})) or str(tmp_path / "s.png"),
    )
    assert runner.invoke(app, ["session-screenshot", "-o", str(tmp_path / "s.png")]).exit_code == 0
    assert (
        runner.invoke(
            app, ["session-screenshot", "-o", str(tmp_path / "s.png"), "--hires"]
        ).exit_code
        == 0
    )
    assert "hires" not in calls[0][1]  # default payload unchanged
    assert calls[1][1]["hires"] is True


def test_repl_screenshot_hires() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return "/abs/s.png"

    console.dispatch("screenshot s.png", send)
    console.dispatch("screenshot s.png --hires", send)
    assert "hires" not in calls[0][1]
    assert calls[1][1]["hires"] is True
    assert calls[1][1]["path"] == str(Path("s.png").resolve())


@pytest.mark.browser
def test_hires_doubles_the_pixel_dimensions(base_url: str, tmp_path: Path) -> None:
    normal, hires = tmp_path / "n.png", tmp_path / "h.png"
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )
    try:
        h.handle("resize", {"width": 800, "height": 600})
        assert h.handle("screenshot", {"path": str(normal)})["ok"] is True
        assert h.handle("screenshot", {"path": str(hires), "hires": True})["ok"] is True
        # And the session is back at 1x afterwards.
        after = tmp_path / "after.png"
        assert h.handle("screenshot", {"path": str(after)})["ok"] is True
    finally:
        h.close()

    nw, nh = _png_size(normal)
    hw, hh = _png_size(hires)
    aw, _ = _png_size(after)
    assert hw >= nw * 2 - 2 and hh >= nh * 2 - 2, (nw, nh, hw, hh)
    assert abs(aw - nw) <= 2, (nw, aw)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k hires -v --no-cov`
Expected: FAIL — `test_op_screenshot_hires_sets_then_restores_the_scale` sees `page.metrics == []` because `hires` is ignored.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/session_server.py`, replace `_op_screenshot` (`:281-294`):

```python
    def _op_screenshot(self, args: dict[str, Any]) -> str:
        """Screenshot the page (optionally full-page) or a single element.

        Mirrors ``browser_screenshot`` in the MCP server: when a target
        (index/selector/role/target_text) is given, screenshot that element via
        ``Locator.screenshot``; otherwise screenshot the page, honouring
        ``full_page``.

        ``hires`` captures at device-pixel-ratio 2 — markedly better for OCR and
        for a vision model reading the numbered overlay. There is no
        "clear override" in the delegate, so the scale is restored by
        re-overriding at the same size with DPR 1, in a ``finally`` so a failed
        capture cannot leave the session stuck at 2x.
        """
        path = args.get("path") or "screenshot.png"
        page = self.page()
        hires = bool(args.get("hires"))
        size: dict[str, Any] | None = None
        if hires:
            size = cast(
                "dict[str, Any]",
                page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})"),
            )
            page.set_device_metrics(int(size["w"]), int(size["h"]), device_scale_factor=2.0)
        try:
            if self._has_target(args):
                self._target(args).screenshot(path=path)
            else:
                page.screenshot(path=path, full_page=bool(args.get("full_page")))
        finally:
            if size is not None:
                page.set_device_metrics(
                    int(size["w"]), int(size["h"]), device_scale_factor=1.0
                )
        return str(Path(path).resolve())
```

In `src/visus/web/cli/main.py`, add the option to `session_screenshot` (`:422-446`) — the new parameter and the one line that uses it:

```python
    hires: bool = typer.Option(
        False, "--hires", help="Capture at device-pixel-ratio 2 (better for OCR / vision)."
    ),
```

```python
    args: dict[str, Any] = {"path": abs_output, "full_page": full_page}
    if hires:
        args["hires"] = True  # only sent when asked, so the payload stays minimal
```

In `src/visus/web/cli/console.py`, replace the `screenshot` branch:

```python
        if cmd == "screenshot":
            shot_rest = [t for t in rest if t != "--hires"]
            shot_args: dict[str, Any] = {
                "path": str(Path(shot_rest[0] if shot_rest else "screenshot.png").resolve())
            }
            if "--hires" in rest:
                shot_args["hires"] = True
            return f"saved {send('screenshot', shot_args)}"
```

and update the `screenshot` `_HELP` line to:

```
  screenshot [path] [--hires]  save a screenshot (default screenshot.png)
```

Note this branch also carries PLAN 3's B9 fix: the REPL now resolves the path against the **client's** cwd, exactly as `main.py:440-442` already does.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k hires -v --no-cov`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the browser test**

Run: `uv run pytest tests/test_cli_page_ops.py::test_hires_doubles_the_pixel_dimensions -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 6: Verify the existing screenshot tests still pass**

Run: `uv run pytest tests/test_cli_session.py -k screenshot -v --no-cov`
Expected: PASS — with `hires` absent the op takes the original path and the payload is unchanged.

- [ ] **Step 7: Update the README**

In `README.md`, in the **Capture / vision / utilities** table, replace the `visus session-screenshot` row with:

```markdown
| `visus session-screenshot [idx] -o <png> --full-page [--hires]` | Screenshot the session's page or a single element (`--hires` = DPR 2, better for OCR). |
```

- [ ] **Step 8: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_page_ops.py README.md
git commit -m "feat(cli): add --hires to the session screenshot"
```

---

### Task 21: Resolve the `screenshot` name collision (and `pdf` with it)

Closes **row 10**. `screenshot` means three different things in this product today:

| Spelling | Where | What it does |
|---|---|---|
| `visus screenshot <URL>` | `main.py:117-130` | launches a **throwaway** browser, navigates, shoots, quits |
| `visus session-screenshot` | `main.py:422-446` | shoots the **live daemon session** — and is the *only* session command in the whole CLI carrying a `session-` prefix (every other one is `click`, `fill`, `goto`, `tabs`, …) |
| `screenshot` in the REPL | `console.py:186-188` | the session one, under the *short* name |

So the name an agent reaches for first — `visus screenshot` — is the one that silently ignores the session it just logged into, and the REPL teaches the opposite convention. `visus pdf` (`main.py:133-144`) has the identical shape.

**Resolution:** the URL becomes optional and decides which browser is used.

* `visus screenshot <URL> -o out.png` — unchanged, byte for byte: a one-off browser.
* `visus screenshot -o out.png` — the live session (what `session-screenshot` does).
* `visus pdf <URL>` / `visus pdf` — the same split.
* `visus session-screenshot` and `visus session-pdf` keep working as **deprecated aliases** that print a notice on stderr, exactly like `visus console` in Task 2. Silently repurposing or deleting a name mid-session would break users, and `session-screenshot` appears in the README and in existing tests.

After this task the REPL's `screenshot`/`pdf` and the CLI's `screenshot`/`pdf` mean the same thing, and no session command carries a `session-` prefix.

The session bodies move into two shared helpers so the canonical command and its alias cannot drift apart.

**Files:**
- Modify: `src/visus/web/cli/main.py:117-130` (`screenshot`), `:133-144` (`pdf`), `:422-446` (`session-screenshot`), `session-pdf` (added in Task 19)
- Modify: `README.md` (Capture / vision / utilities table)
- Test: `tests/test_cli_page_ops.py`

**Interfaces:**
- Consumes: `launch`, `Engine.from_str`, `main._send`, `main._target_args`, `output.emit`
- Produces: `main._session_screenshot(...)`, `main._session_pdf(*, output_path)`; `visus screenshot`/`visus pdf` accept an optional URL

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_page_ops.py`:

```python
# ---------------------------------------------------------------------------
# screenshot / pdf: URL = one-off browser, no URL = the live session
# ---------------------------------------------------------------------------


def _all_output(result: Any) -> str:
    """stdout + stderr, across Click versions.

    Click < 8.2 mixes stderr into ``output`` and raises on ``.stderr``;
    Click >= 8.2 captures them separately.
    """
    try:
        return result.output + result.stderr
    except ValueError:
        return result.output


class _OneShotPage:
    def __init__(self, seen: dict[str, Any]) -> None:
        self._seen = seen

    def goto(self, url: str) -> None:
        self._seen["goto"] = url

    def screenshot(self, *, path: str | None = None, full_page: bool = False) -> bytes:
        self._seen["shot"] = path
        Path(path or "s.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return b"png"

    def pdf(self, *, path: str | None = None) -> bytes:
        self._seen["pdf"] = path
        Path(path or "p.pdf").write_bytes(b"%PDF-1.4\n")
        return b"pdf"


class _OneShotBrowser:
    def __init__(self, seen: dict[str, Any]) -> None:
        self._seen = seen

    def new_page(self) -> _OneShotPage:
        return _OneShotPage(self._seen)

    def __enter__(self) -> _OneShotBrowser:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def close(self) -> None:
        pass


def _patch_one_shot(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from visus.web.cli import main as cli_main

    seen: dict[str, Any] = {}
    monkeypatch.setattr(cli_main, "launch", lambda engine, **kw: _OneShotBrowser(seen))
    return seen


def test_screenshot_with_a_url_uses_a_one_off_browser(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _patch_one_shot(monkeypatch)
    sent: list[str] = []
    monkeypatch.setattr(session_client, "send", lambda op, args=None: sent.append(op))
    out = tmp_path / "s.png"
    r = runner.invoke(app, ["screenshot", "http://example.com", "-o", str(out)])
    assert r.exit_code == 0, r.output
    assert seen["goto"] == "http://example.com"
    assert seen["shot"] == str(out)
    assert sent == [], "a URL must never touch the daemon"


def test_screenshot_without_a_url_hits_the_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {})) or str(tmp_path / "s.png"),
    )
    out = tmp_path / "s.png"
    r = runner.invoke(app, ["screenshot", "-o", str(out), "--full-page", "--hires"])
    assert r.exit_code == 0, r.output
    assert calls[0][0] == "screenshot"
    assert calls[0][1]["path"] == str(out.resolve())
    assert calls[0][1]["full_page"] is True
    assert calls[0][1]["hires"] is True


def test_screenshot_without_a_url_accepts_a_session_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {})) or "ok",
    )
    r = runner.invoke(app, ["screenshot", "-o", str(tmp_path / "s.png"), "-i", "4"])
    assert r.exit_code == 0, r.output
    assert calls[0][1]["index"] == 4


def test_pdf_with_and_without_a_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _patch_one_shot(monkeypatch)
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {})) or str(tmp_path / "p.pdf"),
    )
    out = tmp_path / "p.pdf"
    assert runner.invoke(app, ["pdf", "http://example.com", "-o", str(out)]).exit_code == 0
    assert seen["pdf"] == str(out)
    assert calls == []

    assert runner.invoke(app, ["pdf", "-o", str(out)]).exit_code == 0
    assert calls[0] == ("pdf", {"path": str(out.resolve())})


def test_deprecated_aliases_still_work_and_warn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {})) or "ok",
    )
    r1 = runner.invoke(app, ["session-screenshot", "-o", str(tmp_path / "s.png"), "2"])
    assert r1.exit_code == 0, r1.output
    text1 = _all_output(r1)
    assert "deprecated" in text1 and "visus screenshot" in text1
    assert calls[0][0] == "screenshot" and calls[0][1]["index"] == 2

    r2 = runner.invoke(app, ["session-pdf", "-o", str(tmp_path / "p.pdf")])
    assert r2.exit_code == 0
    text2 = _all_output(r2)
    assert "deprecated" in text2 and "visus pdf" in text2
    assert calls[1][0] == "pdf"


def test_deprecation_notices_go_to_stderr() -> None:
    """A piped `visus session-screenshot > out` must not get the warning in its stdout."""
    import inspect

    from visus.web.cli import main as cli_main

    for fn in (cli_main.session_screenshot, cli_main.session_pdf):
        assert "err=True" in inspect.getsource(fn), f"{fn.__name__} must warn on stderr"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k "one_off or without_a_url or with_and_without or deprecat" -v --no-cov`
Expected: FAIL — `test_screenshot_without_a_url_hits_the_session` exits 2 with `Error: Missing argument 'URL'.`

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/main.py`, add these two shared helpers immediately before the `screenshot` command (`:117`):

```python
def _session_screenshot(
    *,
    output_path: str,
    full_page: bool,
    hires: bool,
    index: int | None,
    selector: str | None,
    role: str | None,
    name: str | None,
    text: str | None,
) -> None:
    """Screenshot the LIVE session's page (or one element) and print the path.

    Shared by `visus screenshot` (no URL) and the deprecated
    `visus session-screenshot`, so the two can never drift apart.
    """
    from visus.web.cli import output

    # Resolve the path against the CLIENT's cwd (not the daemon's) so the PNG
    # lands where the user invoked the command, not under the daemon's base dir.
    args: dict[str, Any] = {"path": str(Path(output_path).resolve()), "full_page": full_page}
    if hires:
        args["hires"] = True  # only sent when asked, so the payload stays minimal
    if index is not None or selector or role or text:
        args.update(_target_args(index, selector, role, name, text))
    result = _send("screenshot", args)
    output.emit(result, table=f"saved {result}")


def _session_pdf(*, output_path: str) -> None:
    """Print the LIVE session's page to a PDF and print the path."""
    from visus.web.cli import output

    result = _send("pdf", {"path": str(Path(output_path).resolve())})
    output.emit(result, table=f"saved {result}")
```

Replace `screenshot` (`:117-130`):

```python
@app.command()
def screenshot(
    url: str = typer.Argument(
        None, help="URL for a one-off browser. Omit it to shoot the LIVE session."
    ),
    output: str = typer.Option("screenshot.png", "-o", "--output"),
    full_page: bool = False,
    headless: bool = True,
    engine: str = "chrome",
    hires: bool = typer.Option(
        False, "--hires", help="Session only: capture at device-pixel-ratio 2."
    ),
    index: int = typer.Option(None, "--index", "-i", help="Session only: field index to shoot."),
    selector: str = typer.Option(None, "--selector", "-s", help="Session only."),
    role: str = typer.Option(None, "--role", help="Session only."),
    name: str = typer.Option(None, "--name", help="Session only."),
    text: str = typer.Option(None, "--text", help="Session only."),
) -> None:
    """Screenshot to a PNG. With a URL: a one-off browser. Without: the live session."""
    if url is None:
        _session_screenshot(
            output_path=output,
            full_page=full_page,
            hires=hires,
            index=index,
            selector=selector,
            role=role,
            name=name,
            text=text,
        )
        return
    with launch(Engine.from_str(engine), headless=headless) as b:
        p = b.new_page()
        p.goto(url)
        p.screenshot(path=output, full_page=full_page)
    typer.echo(f"saved {output}")
```

Replace `pdf` (`:133-144`):

```python
@app.command()
def pdf(
    url: str = typer.Argument(
        None, help="URL for a one-off browser. Omit it to print the LIVE session."
    ),
    output: str = typer.Option("page.pdf", "-o", "--output"),
    engine: str = "chrome",
) -> None:
    """Print to a PDF (Chromium). With a URL: a one-off browser. Without: the live session."""
    if url is None:
        _session_pdf(output_path=output)
        return
    with launch(Engine.from_str(engine), headless=True) as b:
        p = b.new_page()
        p.goto(url)
        p.pdf(path=output)
    typer.echo(f"saved {output}")
```

Replace `session_screenshot` (`:422-446`, as extended in Task 20) with the deprecated alias — note the positional `index` stays exactly where it is, because `tests/test_cli_session.py:1330` invokes `session-screenshot -o <out> 2`:

```python
@app.command("session-screenshot")
def session_screenshot(
    output: str = typer.Option("screenshot.png", "-o", "--output"),
    full_page: bool = typer.Option(
        False, "--full-page", help="Capture the full scrollable page, not just the viewport."
    ),
    hires: bool = typer.Option(False, "--hires", help="Capture at device-pixel-ratio 2."),
    index: int = typer.Argument(None, help="Field index to screenshot (omit = whole page)."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text", help="Target an element by its visible text."),
) -> None:
    """DEPRECATED alias for `visus screenshot` with no URL."""
    typer.echo(
        "warning: `visus session-screenshot` is deprecated — use `visus screenshot` "
        "(with no URL it shoots the live session).",
        err=True,
    )
    _session_screenshot(
        output_path=output,
        full_page=full_page,
        hires=hires,
        index=index,
        selector=selector,
        role=role,
        name=name,
        text=text,
    )
```

Replace `session_pdf` (added in Task 19) with:

```python
@app.command("session-pdf")
def session_pdf(
    output_file: str = typer.Option("page.pdf", "-o", "--output"),
) -> None:
    """DEPRECATED alias for `visus pdf` with no URL."""
    typer.echo(
        "warning: `visus session-pdf` is deprecated — use `visus pdf` "
        "(with no URL it prints the live session).",
        err=True,
    )
    _session_pdf(output_path=output_file)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_page_ops.py -m "not browser" -k "one_off or without_a_url or with_and_without or deprecat" -v --no-cov`
Expected: PASS (6 passed)

- [ ] **Step 5: Verify every pre-existing screenshot/pdf test still passes**

Run: `uv run pytest tests/test_cli.py -q --no-cov`
Expected: PASS — `visus screenshot <URL>` and `visus pdf <URL>` are unchanged, and both names still appear in `--help`.

Run: `uv run pytest tests/test_cli_session.py -k "screenshot or pdf" -v --no-cov`
Expected: PASS — the alias sends the same `screenshot` op with the same payload, including the positional index form.

- [ ] **Step 6: Update the README**

In `README.md`, in the **Capture / vision / utilities** table, replace the four rows for `visus screenshot`, `visus session-screenshot`, `visus pdf` and `visus session-pdf` with:

```markdown
| `visus screenshot [URL] -o <png> --full-page [--hires] [target]` | Screenshot to a PNG. **With** a URL: a one-off browser (`--headless`, `--engine`). **Without**: the live session (or one element). |
| `visus pdf [URL] -o <pdf>` | Print to a PDF (Chromium). With a URL: a one-off browser. Without: the live session. |
| `visus session-screenshot` / `visus session-pdf` | Deprecated aliases for the two above (print a notice on stderr). |
```

In the paragraph above the `<details>` block, no change is needed — but in the **Session & lifecycle** table, nothing references these commands, so the tables are now consistent: **no session command carries a `session-` prefix.**

- [ ] **Step 7: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: `All checks passed!` and `Success: no issues found`

```bash
git add src/visus/web/cli/main.py tests/test_cli_page_ops.py README.md
git commit -m "feat(cli): unify screenshot/pdf on the session, keep session-* as deprecated aliases"
```

---

### Task 22: Full-suite verification

**Files:**
- Test: the whole suite

**Interfaces:**
- Consumes: everything above
- Produces: nothing

- [ ] **Step 1: Run the full gate trio**

Run: `uv run ruff check src tests`
Expected: `All checks passed!`

Run: `uv run mypy`
Expected: `Success: no issues found in <N> source files`

Run: `uv run pytest -q`
Expected: all tests pass and `Required test coverage of 90% reached.` — no `FAILED`, no `ERROR`, no `xfail`, no `skipped`.

- [ ] **Step 2: Prove every new command is registered and documented**

Run:

```bash
uv run python -c "import re, pathlib; from visus.web.cli.main import app; names = sorted({c.name or (c.callback.__name__ if c.callback else '') for c in app.registered_commands}); readme = pathlib.Path('README.md').read_text(encoding='utf-8'); missing = [n for n in names if f'visus {n}' not in readme]; print('commands:', len(names)); print('undocumented:', missing)"
```

Expected: `undocumented: []`. Every command added by this plan (`repl`, `logs`, `requests`, `request`, `tab-activate`, `tab-follow`, `state-save`, `state-load`, `type`, `keydown`, `keyup`, `mousemove`, `mousedown`, `mouseup`, `mousewheel`, `highlight`, `resize`, `generate-locator`, `tracing-start`, `tracing-stop`, `report`, `session-pdf`) has a README row. The three sub-apps (`session`, `storage`, `network`) are documented by their own rows.

- [ ] **Step 3: Prove every new REPL verb is reachable and in the help**

Run:

```bash
uv run python -c "from visus.web.cli import console; h = console.dispatch('help', lambda op, args: None); missing = [c for c in ('type','keydown','keyup','mousemove','mousedown','mouseup','mousewheel','logs','requests','request','network','tab-activate','tab-follow','state-save','state-load','storage','session-storage','cookie-get','cookie-set','cookie-delete','highlight','resize','generate-locator','eval-on','tracing-start','tracing-stop','pdf') if c not in h]; print('missing from REPL help:', missing)"
```

Expected: `missing from REPL help: []`

- [ ] **Step 4: Drive the finished CLI by hand once**

Run these in order from the repo root and confirm each printed line:

```bash
uv run visus session start --headless "data:text/html,<title>one</title><button id=go>Go</button><input id=q>"
uv run visus list-fields --no-highlight --boxes
uv run visus generate-locator 0
uv run visus highlight 0
uv run visus resize 900 600
uv run visus storage set token abc
uv run visus storage get token
uv run visus eval "(el) => el.id" -s "#go"
uv run visus screenshot -o shot.png --hires
uv run visus tracing-start -o run.zip
uv run visus click --role button --name Go --button right
uv run visus tracing-stop --report report.html
uv run visus report run.zip -o report2.html
uv run visus session stop
```

Expected, in order: a `session started` line; a field table with a `BOX x,y,w,h` column; `page.locator("#go")`; `highlighted`; `viewport is now 900x600`; `localStorage['token'] = 'abc'`; `abc`; `go`; `saved …/shot.png`; `tracing run <id> → …/run.zip`; `clicked with the right button`; a `tracing run <id> stopped: 1 action(s), 0 failure(s)` block naming both files; `saved …/report2.html`; `session stopped`.

Then confirm the artefacts:

```bash
uv run python -c "import pathlib,zipfile,json; z=zipfile.ZipFile('run.zip'); ev=[json.loads(l) for l in z.read('events.jsonl').decode().splitlines() if l.strip()]; print('actions:', [e['action'] for e in ev]); print('report bytes:', pathlib.Path('report.html').stat().st_size)"
```

Expected: `actions: ['click']` (non-empty — this is the D11 regression, which before this plan printed `actions: []`), and a report of tens of kilobytes.

- [ ] **Step 5: Confirm the deprecated names still work**

```bash
uv run visus session start --headless "data:text/html,<title>x</title>"
uv run visus session-screenshot -o legacy.png 2>warn.txt
uv run visus session-pdf -o legacy.pdf 2>>warn.txt
uv run visus session stop
uv run visus console --help
```

Expected: `legacy.png` and `legacy.pdf` exist; `warn.txt` contains both `warning: \`visus session-screenshot\` is deprecated` and `warning: \`visus session-pdf\` is deprecated` — i.e. **nothing** went to stdout. `visus console --help` prints `DEPRECATED alias for \`visus repl\`` (Typer's `--help` short-circuits the body, so the stderr notice only appears on a real invocation).

Then delete `warn.txt`.

- [ ] **Step 6: Commit any residual fixes**

If step 1-5 revealed a gap, fix it and commit with a `fix(cli): ...` message. If everything passed, there is nothing to commit — do not create an empty commit.

Finally, remove the scratch artefacts this verification wrote:

```bash
uv run python -c "import pathlib; [pathlib.Path(f).unlink(missing_ok=True) for f in ('shot.png','run.zip','report.html','report2.html','legacy.png','legacy.pdf','capture.json','warn.txt')]"
```
