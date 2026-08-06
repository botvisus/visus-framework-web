# Tier 2d — New Engineering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the four `visus` capabilities that need genuinely new engineering rather than a CLI wrapper over an existing library call — named sessions with fleet management, real network mocking, a Python escape hatch against the live session, and attach/detach to a browser visus did not launch — plus the drop / file-chooser / emulation / config-file gaps that ride on the same machinery.

**Architecture:** Session state moves from the single `.visus/session.json` to `.visus/sessions/<name>.json`, with a mirror under `~/.visus/sessions/` so a daemon abandoned in another project is visible and killable. Request interception is a new engine-side module (`backends/selenium/cdp_fetch.py`) that opens its own DevTools WebSocket to the tab's target, runs `Fetch.enable` and answers `Fetch.requestPaused` — the only gap with no `eval` workaround — behind a hidden-engine-clean `page.route()`. `run-code` and `attach` extend the daemon's lifecycle: the first executes Python with `page`/`context`/`browser`/`expect` bound to the live objects behind an explicit opt-in, the second launches with Selenium's `debuggerAddress` and adds a release path that ends the WebDriver session without ever telling the browser to close.

**Tech Stack:** Python 3.10+, Typer, Rich, Selenium 4.38, pytest + pytest-xdist, hatchling, mypy --strict, ruff

## Global Constraints

- Gates that must pass before any commit: `uv run ruff check src tests`, `uv run mypy` (strict), `uv run pytest -q` (≥90% coverage on `visus.web`).
- **THE HIDDEN-ENGINE RULE (inviolable):** no `selenium.*` type may appear in any public signature/return/exception/docstring. Selenium imports are allowed ONLY in `backends/browsers/*.py`, `backends/selenium/*.py`, `backends/selenium_backend.py`.
- Test convention: **real browser, no fakes**, `@pytest.mark.browser`, fixtures in `tests/fixtures/*.html` served by the session-scoped `base_url` fixture (`tests/conftest.py:38-48`).
- Test doubles isolate a unit ONLY when its real behaviour is also covered by an integration test. No `skip` / `xfail` / mock-to-pass.
- Ruff: line-length 100, select `["E","F","I","UP","B"]`. mypy: `strict = true`, `python_version = "3.10"`.
- Commits: small, TDD (failing test → minimal impl → green → commit), semantic messages `label(scope): description`. Labels: `fix`, `feat`, `chore`, `docs`, `test`, `devops`.
- **Never** add `Co-Authored-By` lines to commits.
- Single-test runs use `--no-cov` (the 90% gate only makes sense on a full run).
- Every new CLI command gets its REPL twin (`console.py` dispatch + `_HELP`) and a `README.md` command-table row in the same task.

## Prerequisites

Four plan files must land before this one.

**PLAN 1 — `2026-08-06-tier1-skill-distribution.md`** creates the project's first `@app.callback()` in `main.py` (there is none today: `main.py:14-17` builds the `Typer` with only `help` / `no_args_is_help`). Consumed here:

- `main._root(ctx: typer.Context, ...) -> None` — Task 1 and Task 14 add parameters to it.
- `visus.web.cli.skill_check.check_installed_skills(cwd: Path | None = None) -> None` — kept in the callback body verbatim.

**PLAN 3 — `2026-08-06-tier2a-daemon-correctness.md`** must land first so named sessions are not built on the orphaned-lock bug (B2) or the missing WebDriver mutex (B3). Consumed here:

| Symbol | Where this plan uses it |
|---|---|
| `session_server._claim_lock(sf: Path) -> Path` | unchanged — `<name>.json.lock` falls out of `sf.with_name(sf.name + ".lock")` |
| `session_server._read_lock_pid(lock: Path) -> int` | Task 3 (`kill-all` reads a lock's owner) |
| `session_server._write_private(path: Path, text: str) -> None` | Task 1 (the per-name session file stays owner-only) |
| `session_server._prune(threads) -> list[threading.Thread]`, `SHUTDOWN_GRACE_SECONDS` | Task 1 rewrites `serve()`'s tail and must preserve both |
| `SessionHandler._lock: threading.RLock` | Tasks 8/10 add ops whose bodies run inside `handle()`'s `with self._lock:` |
| `SessionHandler.bind_stop(stop: threading.Event) -> None`, `SessionHandler._stop` | Task 10 (`_op_detach` sets the stop event, exactly as `_op_tab_close` does) |
| `SessionHandler._invalidate_fields() -> None` | Tasks 8/10/11 (every op that can move the page calls it) |
| `SessionHandler.last_op_at() -> float`, `serve(..., idle_timeout=)` | Task 1 keeps both when it adds `name=` |
| `session_client._probe_pid(pid: int) -> bool` (uncached), `_pid_alive` (memoised) | Tasks 2/3 (liveness in `list`/`kill-all` must be uncached) |
| `session_client._cleanup(sf: Path) -> None` (removes json **and** lock) | Tasks 1/3 |
| `session_client._terminate(pid: int) -> None` | Task 3 (`kill-all` iterates over it) |
| `session_client.kill(*, start_dir=None) -> str` | Task 1 adds `name=`; Task 3's `kill_all` reuses its parts |
| `session_client._find_lock_file(start_dir) -> Path \| None` | Task 1 makes it name-aware |
| `session_client.socket_timeout_for(args) -> float`, `DEFAULT_SOCKET_TIMEOUT` | Task 1 threads `name=` through `send` without disturbing it |
| `session_client._log_tail(base: Path, *, lines: int = 20) -> str` | unchanged |

**PLAN 4 — `2026-08-06-tier2c-agent-driving-loop.md`** owns `cli/output.py`, the global flags and the daemon envelope. Consumed here:

- `output.set_mode(*, as_json=False, raw=False)`, `output.mode() -> Mode`, `output.emit(value, *, table=None)`, `output.emit_error(message, *, code=1) -> NoReturn`, `output.emit_envelope(env, *, table=None)`, `output.set_output_dir(path)`, `output.resolve_out(path)`, `output.snapshot_sink()`.
- `session_client.send_envelope(op, args=None, *, start_dir=None) -> dict[str, Any]` — Task 1 adds `name=` to it and to `send()`.
- `main._send(op, args=None) -> Any` and `main._send_env(op, args=None) -> dict[str, Any]`.
- `session_server._MUTATING_OPS: frozenset[str]` — Tasks 6/8/11/12 add their ops to the existing frozenset.
- `session_server._post_state() -> dict[str, Any]`.
- `console.render_value(result) -> str` (produced by PLAN 3, rendered by PLAN 4).

**PLAN 5 — `2026-08-06-tier2b-cli-surface-parity.md`** owns the raw launch passthrough. Its Task 7 produces exactly these, which Task 13 builds the higher-level profile UX **on top of** rather than duplicating:

- `SessionHandler(..., user_data_dir: str | None = None, remote_url: str | None = None, slow_mo: int = 0)` and the `launch(...)` call inside `_ensure()` that forwards all three.
- `session_client.start_daemon(engine, headless, url, *, user_data_dir=None, remote_url=None, slow_mo=0, cwd=None, timeout=20.0, idle_timeout=None)`.
- env vars `VISUS_WEB_USER_DATA_DIR`, `VISUS_WEB_REMOTE_URL`, `VISUS_WEB_SLOW_MO`.
- `main.session_start(url, engine, headless, user_data_dir, remote_url, slow_mo, idle_timeout)` — Task 13 **extends** this signature; it never re-declares `--user-data-dir`'s behaviour.

PLAN 5 also produces `session_server._op_type` / `_op_key_down` / `_op_key_up` and `console.dispatch`'s table-driven target parsing; this plan's REPL additions slot into that same dispatch.

### Ordering inside this plan (hard constraint)

1. Tasks 1–3: named sessions. Every later task's CLI surface resolves a session name, and `session list` is the only way to see what the later tasks created.
2. Tasks 4–6: request mocking, engine → API → CLI.
3. Tasks 7–8: `run-code`, gate first then the op.
4. Tasks 9–10: attach/detach, engine → CLI.
5. Tasks 11–14: drop, file chooser, emulation, config file.
6. Task 15: full-suite verification.

### One inherited claim this plan corrects

`visus open` (`main.py:147-153`) does **not** deadlock an agent. Its `input()` at `:153` runs with no guard, and under a closed stdin `input()` raises `EOFError` — the process exits non-zero rather than hanging. Task 13 leaves `open` alone for that reason; the session flags land on `session start`, which is the command an agent actually uses.

---

## File Structure

**Created**

| Path | Single responsibility |
|---|---|
| `src/visus/web/api/route.py` | `RouteRule` (the CONVENTIONS-pinned dataclass), glob→regex compilation, header redaction for listing. No engine, no I/O. |
| `src/visus/web/api/devices.py` | The named device table behind `--device` / `--mobile` and `visus devices`. |
| `src/visus/web/backends/selenium/cdp_fetch.py` | The only new engine module: locate a tab's DevTools WebSocket, run `Fetch.enable`, answer `Fetch.requestPaused` with fulfill/fail/continue. |
| `src/visus/web/cli/config.py` | `.visus/cli.json` discovery, parsing, and the "an explicit flag always wins" merge helper. |
| `tests/test_cli_sessions_named.py` | Named-session paths, the global registry, `list` / `close-all` / `kill-all` / `delete-data`. |
| `tests/test_route.py` | `RouteRule` unit tests + real-browser fulfil/abort/unroute. |
| `tests/test_cli_route.py` | `visus route` / `unroute` / `route-list` argument plumbing and REPL twins. |
| `tests/test_cli_run_code.py` | The default-OFF gate first, then the opt-in execution path. |
| `tests/test_cli_attach.py` | `debugger_address` option building, `Browser.detach`, `session attach` / `detach`. |
| `tests/test_cli_drop_upload.py` | `visus drop` and the target-free `visus upload`. |
| `tests/test_cli_emulation.py` | `--persistent` / `--profile` / `--device` / `--mobile` / `--browser` and `visus devices`. |
| `tests/test_cli_config.py` | Config discovery, parsing, precedence, and error messages. |
| `tests/fixtures/route_fetch.html` | A page that fetches `/api/items` and renders what came back. |
| `tests/fixtures/dropzone.html` | A dropzone with no `<input type=file>`. |
| `tests/fixtures/upload_single.html` | One hidden `<input type=file>` behind a styled button. |

**Modified**

| Path | What changes |
|---|---|
| `src/visus/web/cli/session_server.py` | `sessions_dir` / `session_file(cwd, name)` / registry write; `serve(..., name=)`; `_op_route` / `_op_unroute` / `_op_route_list` / `_op_run_code` / `_op_detach` / `_op_drop`; targetless `_op_upload`; `allow_run_code`, `debugger_address`, `device` on the handler; `release()` / `detach()` / `detached()`. |
| `src/visus/web/cli/session_client.py` | Session-name resolution and validation; every discovery/transport function gains `name=`; `list_sessions`, `close_all`, `kill_all`, `delete_data`, `profile_dir`; `start_daemon` gains `name`, `allow_run_code`, `debugger_address`, `device`. |
| `src/visus/web/cli/main.py` | `--session` / `-S` and `--config` on the root callback; `session list` / `close-all` / `kill-all` / `delete-data` / `attach` / `detach`; `route` / `unroute` / `route-list`; `run-code`; `drop`; targetless `upload`; `session start --persistent/--profile/--device/--mobile/--browser`; `devices`. |
| `src/visus/web/cli/console.py` | REPL twins for `route` / `unroute` / `routes` / `run-code` / `drop` / `upload`, plus their `_HELP` lines. |
| `src/visus/web/api/page.py` | `Page.route` / `Page.unroute` / `Page.routes`. |
| `src/visus/web/async_api/__init__.py` | `AsyncPage.route` / `unroute` / `routes` mirrors. |
| `src/visus/web/backends/base.py` | `PageDelegate.route_add` / `route_remove` / `route_list`; `BrowserDelegate.detach`; `Backend.launch(..., debugger_address=)`. |
| `src/visus/web/backends/selenium/driver_delegate.py` | Route storage + interceptor lifecycle on `SeleniumPageDelegate` (including teardown in `close()`). |
| `src/visus/web/backends/selenium_backend.py` | `debugger_address` through `_spawn_driver` / `launch`; `SeleniumBrowserDelegate.detach()`. |
| `src/visus/web/backends/browsers/chrome.py`, `edge.py`, `firefox.py`, `edge_ie.py` | `build_options(..., debugger_address=None)`. |
| `src/visus/web/__init__.py` | `launch(..., debugger_address=None)`. |
| `src/visus/web/api/browser.py` | `Browser.detach()`. |
| `pyproject.toml` | `websocket-client` dependency + its mypy override. |
| `README.md` | Session/Actions/DevTools command-table rows, the env-var table, and a config-file section. |
| `tests/test_cli_session.py` | Session-file paths become `.visus/sessions/default.json`. |
| `tests/test_e2e_cli_session.py` | Same, at `:48`. |
| `tests/test_backend_protocols.py` | `_FakePage` gains the route methods; `_FakeBrowser` gains `detach`. |

---

### Task 1: Named session state — `.visus/sessions/<name>.json` and `--session` / `-S`

`session_client.start_daemon` refuses a second session outright (`:143-147`, "a session is already running (pid ..., port ...)"), and discovery walks UP the tree (`:58-66`) so a `start` inside a subfolder of a project that already has a daemon binds to the parent's without saying so. One name per project directory is the whole model. This task replaces it with a namespace.

`-s` is **already** `--selector` in 29 places (`main.py:307`, `:320`, `:341`, …), so the flag is `--session` / `-S` (capital S) and the env var is `VISUS_WEB_SESSION`, per CONVENTIONS.

The upward walk is kept — it is what lets a command in `repo/src/` reach the session started in `repo/` — but two things change so it can never be silent: the "already running" error now prints the **resolved file path** it found, and `visus session list` (Task 2) shows where every session lives.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:601-604` (`session_file`), `:674-735` (`serve`), `:738-773` (`main`)
- Modify: `src/visus/web/cli/session_client.py:8-17` (imports), `:58-66` (`_find_session_file`), `:69-89` (`find_session`), `:113-126` (`send`/`send_envelope`), `:129-194` (`start_daemon`), `:197-214` (`stop`), `:217-231` (`status`), and `kill` / `_find_lock_file` (PLAN 3 Task 5)
- Modify: `src/visus/web/cli/main.py` — the `@app.callback()` PLAN 1 created and PLAN 4 extended
- Modify: `tests/test_cli_session.py:775`, `:824`, `:915`, `:1129-1131`, `:1149`
- Modify: `tests/test_e2e_cli_session.py:48`
- Test: `tests/test_cli_sessions_named.py`

**Interfaces:**
- Consumes: `session_server._write_private`, `_claim_lock`, `_prune`, `SHUTDOWN_GRACE_SECONDS` (PLAN 3); `session_client._cleanup`, `_probe_pid` (PLAN 3); `output.set_mode` / `set_output_dir` / `set_snapshot_sink` (PLAN 4); `skill_check.check_installed_skills` (PLAN 1)
- Produces:
  ```python
  session_server.sessions_dir(cwd: str | Path | None = None) -> Path
  session_server.session_file(cwd: str | Path | None = None, name: str | None = None) -> Path
  session_server.serve(handler, *, token, cwd=None, host="127.0.0.1",
                       idle_timeout=None, name=None) -> None
  session_client.DEFAULT_SESSION_NAME: str
  session_client.validate_session_name(name: str) -> str
  session_client.set_session_name(name: str | None) -> None
  session_client.session_name(name: str | None = None) -> str
  session_client.find_session(start_dir=None, name=None) -> dict[str, Any] | None
  session_client.send(op, args=None, *, start_dir=None, name=None, timeout=None) -> Any
  session_client.send_envelope(op, args=None, *, start_dir=None, name=None) -> dict[str, Any]
  session_client.start_daemon(..., name: str | None = None) -> dict[str, Any]
  session_client.stop(*, start_dir=None, name=None) -> str
  session_client.status(*, start_dir=None, name=None) -> dict[str, Any] | None
  session_client.kill(*, start_dir=None, name=None) -> str
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_sessions_named.py`:

```python
"""Named sessions, the cross-project registry, and fleet management.

Every test is isolated: session state under ``tmp_path``, the global registry
under ``VISUS_WEB_HOME``. Nothing ever writes into the developer's real
``~/.visus`` or into the repo root.

The shared fakes are imported as ``from test_cli_session import ...`` (no
``tests.`` prefix): ``tests/`` has no ``__init__.py``, so pytest's default
prepend import mode puts ``tests/`` itself on ``sys.path`` and every test module
is a top-level module. The same spelling is used throughout this plan.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the global session registry at tmp_path and clear any pinned name."""
    monkeypatch.setenv("VISUS_WEB_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("VISUS_WEB_SESSION", raising=False)
    session_client.set_session_name(None)


def test_session_file_defaults_to_the_default_name(tmp_path: Path) -> None:
    sf = session_server.session_file(tmp_path)
    assert sf == tmp_path / ".visus" / "sessions" / "default.json"
    assert session_server.sessions_dir(tmp_path) == tmp_path / ".visus" / "sessions"


def test_session_file_is_namespaced(tmp_path: Path) -> None:
    assert (
        session_server.session_file(tmp_path, "auth")
        == tmp_path / ".visus" / "sessions" / "auth.json"
    )


def test_lock_name_follows_the_session_name(tmp_path: Path) -> None:
    """PLAN 3's _claim_lock is unchanged — the lock name falls out of the path."""
    sf = session_server.session_file(tmp_path, "auth")
    sf.parent.mkdir(parents=True, exist_ok=True)
    lock = session_server._claim_lock(sf)
    assert lock.name == "auth.json.lock"
    lock.unlink()


@pytest.mark.parametrize(
    "bad", ["", "../escape", "a/b", "a\\b", ".hidden", "x" * 65, "with space", "sess:1"]
)
def test_invalid_session_names_are_refused(bad: str) -> None:
    with pytest.raises(session_client.SessionError, match="invalid session name"):
        session_client.validate_session_name(bad)


@pytest.mark.parametrize("good", ["default", "auth", "a", "site-1", "v1.2_x", "A9"])
def test_valid_session_names_are_accepted(good: str) -> None:
    assert session_client.validate_session_name(good) == good


def test_session_name_resolution_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """explicit argument > `-S` (set_session_name) > VISUS_WEB_SESSION > "default"."""
    assert session_client.session_name() == "default"

    monkeypatch.setenv("VISUS_WEB_SESSION", "from-env")
    assert session_client.session_name() == "from-env"

    session_client.set_session_name("from-flag")
    assert session_client.session_name() == "from-flag"
    assert session_client.session_name("explicit") == "explicit"

    session_client.set_session_name(None)
    assert session_client.session_name() == "from-env"


def test_find_session_is_namespaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two names in one directory are two independent sessions."""
    import socket as _socket

    srv = _socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        sessions = tmp_path / ".visus" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "auth.json").write_text(
            json.dumps({"pid": 1, "port": port, "token": "t-auth"}), encoding="utf-8"
        )
        monkeypatch.setattr(session_client, "_pid_alive", lambda pid: True)
        assert session_client.find_session(tmp_path, "auth")["token"] == "t-auth"
        assert session_client.find_session(tmp_path, "public") is None
        assert session_client.find_session(tmp_path) is None  # "default" is a third name
    finally:
        srv.close()


def test_start_daemon_refusal_names_the_file_it_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old message never said WHERE — so a parent-directory session looked silent."""
    sf = tmp_path / ".visus" / "sessions" / "default.json"
    monkeypatch.setattr(
        session_client,
        "find_session",
        lambda base, name=None: {"pid": 7, "port": 8, "token": "t", "_file": str(sf)},
    )
    with pytest.raises(session_client.SessionError) as excinfo:
        session_client.start_daemon("chrome", True, None, cwd=tmp_path)
    message = str(excinfo.value)
    assert "already running" in message
    assert str(sf) in message, message
    assert "--session" in message, message


def test_start_daemon_exports_the_session_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, *a: Any, **kw: Any) -> None:
            captured["env"] = kw["env"]

    monkeypatch.setattr(session_client, "find_session", lambda base, name=None: None)
    monkeypatch.setattr(session_client.subprocess, "Popen", _FakePopen)
    with pytest.raises(session_client.SessionError):
        session_client.start_daemon("chrome", True, None, cwd=tmp_path, timeout=0.2, name="auth")
    assert captured["env"]["VISUS_WEB_SESSION"] == "auth"


def test_serve_writes_the_named_session_file(tmp_path: Path) -> None:
    import threading as _threading
    import time as _time

    from test_cli_session import _FakePage, _handler_with_fake_page

    handler = _handler_with_fake_page(_FakePage())
    t = _threading.Thread(
        target=session_server.serve,
        kwargs={"handler": handler, "token": "tok", "cwd": tmp_path, "name": "auth"},
        daemon=True,
    )
    t.start()
    sf = session_server.session_file(tmp_path, "auth")
    for _ in range(200):
        if sf.is_file():
            break
        _time.sleep(0.02)
    try:
        assert sf.is_file()
        info = json.loads(sf.read_text(encoding="utf-8"))
        assert info["name"] == "auth"
        assert Path(info["cwd"]) == tmp_path.resolve()
        port = int(info["port"])
    finally:
        from test_cli_session import _shutdown_thread

        _shutdown_thread(t, port, "tok")
    assert not sf.is_file()
    assert not sf.with_name("auth.json.lock").exists()


def test_daemon_main_reads_the_session_name_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served: dict[str, Any] = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VISUS_WEB_SESSION", "auth")
    monkeypatch.setattr(session_server, "SessionHandler", lambda **kw: object())
    monkeypatch.setattr(
        session_server, "serve", lambda handler, **kw: served.update(kw)
    )
    session_server.main(["chrome", "1", ""])
    assert served["name"] == "auth"


def test_cli_root_accepts_the_session_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []
    monkeypatch.setattr(session_client, "set_session_name", seen.append)
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: "Dashboard")
    r = runner.invoke(app, ["-S", "auth", "title"])
    assert r.exit_code == 0, r.output
    assert seen == ["auth"]


def test_cli_session_flag_is_capital_s_only() -> None:
    """`-s` must stay `--selector`: 29 commands already bind it."""
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "-S" in r.output and "--session" in r.output
    r2 = runner.invoke(app, ["click", "--help"])
    assert r2.exit_code == 0
    assert "-s" in r2.output and "--selector" in r2.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_sessions_named.py -v --no-cov`
Expected: FAIL — `AttributeError: module 'visus.web.cli.session_server' has no attribute 'sessions_dir'`, and `test_session_file_defaults_to_the_default_name` fails on `assert sf == .../sessions/default.json` because `session_file` still returns `.visus/session.json`.

- [ ] **Step 3: Write the session-name resolution in the client**

In `src/visus/web/cli/session_client.py`, add `import re` to the import block (alphabetical for ruff's `I` rule: `json`, `os`, `re`, `signal`, `socket`, `subprocess`, `sys`, `time`).

Add immediately below `class SessionError`:

```python
DEFAULT_SESSION_NAME = "default"

# The name becomes a FILE name under .visus/sessions/, so path separators, `..`
# and a leading dot are all refused rather than escaped.
_SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

_session_name: str | None = None


def validate_session_name(name: str) -> str:
    """Return *name* when it is a safe session name, else raise :class:`SessionError`."""
    if not _SESSION_NAME_RE.match(name or ""):
        raise SessionError(
            f"invalid session name {name!r} — start with a letter or digit and use only "
            "letters, digits, '.', '_' or '-' (max 64 chars); the name becomes a file "
            "name under .visus/sessions/"
        )
    return name


def set_session_name(name: str | None) -> None:
    """Pin the session name for this process (the CLI's ``--session`` / ``-S``)."""
    global _session_name
    _session_name = validate_session_name(name) if name else None


def session_name(name: str | None = None) -> str:
    """Resolve the session name: explicit arg > ``-S`` > ``VISUS_WEB_SESSION`` > default."""
    if name:
        return validate_session_name(name)
    if _session_name:
        return _session_name
    env = os.environ.get("VISUS_WEB_SESSION")
    if env:
        return validate_session_name(env)
    return DEFAULT_SESSION_NAME
```

Replace `_find_session_file` (`:58-66`) with:

```python
def _find_session_file(
    start_dir: str | Path | None = None, name: str | None = None
) -> Path | None:
    """Search upward from *start_dir* for ``.visus/sessions/<name>.json`` (git-style).

    The upward walk is deliberate: a command run in ``repo/src`` must reach the
    session started in ``repo``. It is also why every "already running" message
    prints the file it resolved — the same walk used to bind a subfolder to its
    parent's daemon without ever saying so.
    """
    cur = Path(start_dir) if start_dir is not None else Path.cwd()
    cur = cur.resolve()
    filename = f"{session_name(name)}.json"
    for d in [cur, *cur.parents]:
        candidate = d / ".visus" / "sessions" / filename
        if candidate.is_file():
            return candidate
    return None
```

Replace `find_session` (`:69-89`) with:

```python
def find_session(
    start_dir: str | Path | None = None, name: str | None = None
) -> dict[str, Any] | None:
    """Return the live session dict for *name*, or ``None``. Cleans stale files.

    A session is live when its pid is alive AND its socket accepts. A session
    file that fails either check is treated as stale and deleted.
    """
    sf = _find_session_file(start_dir, name)
    if sf is None:
        return None
    try:
        info: dict[str, Any] = json.loads(sf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _cleanup(sf)
        return None
    pid = int(info.get("pid", -1))
    port = int(info.get("port", -1))
    if not _pid_alive(pid) or not _socket_open(port):
        _cleanup(sf)
        return None
    info["_file"] = str(sf)
    return info
```

Replace `_find_lock_file` (PLAN 3 Task 5) with:

```python
def _find_lock_file(
    start_dir: str | Path | None = None, name: str | None = None
) -> Path | None:
    """Search upward for ``.visus/sessions/<name>.json.lock`` (git-style).

    A wedged project has the LOCK but no session file, so the lock needs its own
    discovery walk — :func:`_find_session_file` would return ``None``.
    """
    cur = Path(start_dir) if start_dir is not None else Path.cwd()
    cur = cur.resolve()
    filename = f"{session_name(name)}.json.lock"
    for d in [cur, *cur.parents]:
        candidate = d / ".visus" / "sessions" / filename
        if candidate.is_file():
            return candidate
    return None
```

Thread `name` through the transport. Replace `send_envelope` and `send` (PLAN 4 Task 5's versions) with:

```python
def send_envelope(
    op: str,
    args: dict[str, Any] | None = None,
    *,
    start_dir: str | Path | None = None,
    name: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Send an op to the named session and return the daemon's FULL reply envelope."""
    info = find_session(start_dir, name)
    if info is None:
        raise SessionError(
            f"no live session {session_name(name)!r} — run `visus session start` first "
            "(`visus session list` shows every session)"
        )
    resp = _send_raw(
        int(info["port"]),
        {"token": info["token"], "op": op, "args": args or {}},
        timeout=socket_timeout_for(args) if timeout is None else timeout,
    )
    if not resp.get("ok"):
        raise SessionError(str(resp.get("error", "unknown error")))
    return resp


def send(
    op: str,
    args: dict[str, Any] | None = None,
    *,
    start_dir: str | Path | None = None,
    name: str | None = None,
    timeout: float | None = None,
) -> Any:
    """Send an op to the named session and return its ``result`` (raises on failure)."""
    return send_envelope(
        op, args, start_dir=start_dir, name=name, timeout=timeout
    ).get("result")
```

In `start_daemon`, replace the signature's tail and the guard + env block:

```python
def start_daemon(
    engine: str = "chrome",
    headless: bool = False,
    url: str | None = None,
    *,
    name: str | None = None,
    user_data_dir: str | None = None,
    remote_url: str | None = None,
    slow_mo: int = 0,
    cwd: str | Path | None = None,
    timeout: float = 20.0,
    idle_timeout: float | None = None,
) -> dict[str, Any]:
    """Spawn a detached daemon for session *name* and block until its socket accepts.

    Sessions are namespaced: ``.visus/sessions/<name>.json``. Discovery walks
    upward, so a second session in the same tree needs its own ``--session`` name.

    Returns the session dict. Raises :class:`SessionError` if a live session of the
    same name is already present or the daemon does not come up in time.
    """
    resolved = session_name(name)
    base = Path(cwd) if cwd is not None else Path.cwd()
    existing = find_session(base, resolved)
    if existing is not None:
        raise SessionError(
            f"session {resolved!r} is already running "
            f"(pid {existing['pid']}, port {existing['port']}, "
            f"state {existing.get('_file', '?')}) — stop it, or start another one "
            "with `--session <name>`"
        )

    env = dict(os.environ)
    env["VISUS_WEB_ENGINE"] = engine
    env["VISUS_WEB_HEADLESS"] = "1" if headless else "0"
    env["VISUS_WEB_SESSION"] = resolved
    if url:
        env["VISUS_WEB_URL"] = url
```

(The rest of the env block from PLAN 5 Task 7 — `VISUS_WEB_USER_DATA_DIR`, `VISUS_WEB_REMOTE_URL`, `VISUS_WEB_SLOW_MO` — and PLAN 3 Task 14's `VISUS_WEB_IDLE_TIMEOUT` are unchanged and stay exactly where they are.)

Replace the poll loop's session-file line (`sf = base / ".visus" / "session.json"`) with:

```python
    sf = base / ".visus" / "sessions" / f"{resolved}.json"
```

Replace `stop` (`:197-214`) and `status` (PLAN 3 Task 17's version) with:

```python
def stop(*, start_dir: str | Path | None = None, name: str | None = None) -> str:
    """Shut down the named session's daemon. Returns a status message."""
    info = find_session(start_dir, name)
    if info is None:
        return f"no session {session_name(name)!r} running"
    try:
        _send_raw(int(info["port"]), {"token": info["token"], "op": "shutdown", "args": {}})
    except (OSError, SessionError):
        pass
    # Wait briefly for the session file to be removed by the daemon.
    sf = Path(info["_file"])
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not sf.is_file():
            break
        time.sleep(0.1)
    _cleanup(sf)
    return "session stopped"


def status(
    *, start_dir: str | Path | None = None, name: str | None = None
) -> dict[str, Any] | None:
    """Return the named session's status dict, or ``None`` when it is not running.

    Sends on the connection info from the SINGLE ``find_session`` call above —
    routing through :func:`send` would re-run discovery and pay a second liveness
    probe (on Windows: a second ``tasklist`` with a 5 s timeout).
    """
    info = find_session(start_dir, name)
    if info is None:
        return None
    resp = _send_raw(int(info["port"]), {"token": info["token"], "op": "status", "args": {}})
    if not resp.get("ok"):
        raise SessionError(str(resp.get("error", "unknown error")))
    result = resp.get("result")
    merged: dict[str, Any] = {
        "name": session_name(name),
        "pid": info["pid"],
        "port": info["port"],
        "engine": info.get("engine"),
        "headless": info.get("headless"),
    }
    if isinstance(result, dict):
        merged.update(result)
    return merged
```

In `kill` (PLAN 3 Task 5), change the signature and its two discovery calls:

```python
def kill(*, start_dir: str | Path | None = None, name: str | None = None) -> str:
```

```python
    sf = _find_session_file(start_dir, name)
```

```python
    lock = _find_lock_file(start_dir, name)
```

- [ ] **Step 4: Write the server-side path + registry-ready session payload**

In `src/visus/web/cli/session_server.py`, replace `session_file` (`:601-604`) with:

```python
def sessions_dir(cwd: str | Path | None = None) -> Path:
    """Directory holding this project's named session files."""
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".visus" / "sessions"


def session_file(cwd: str | Path | None = None, name: str | None = None) -> Path:
    """Path to ``.visus/sessions/<name>.json`` under *cwd* (default: process cwd).

    ``.visus/`` is already the daemon's directory, so the namespace lives inside
    it. The ownership lock is ``<name>.json.lock``, which :func:`_claim_lock`
    derives from this path without any change.
    """
    return sessions_dir(cwd) / f"{name or 'default'}.json"
```

Change `serve()`'s signature (PLAN 3 Task 14's version) to add `name`, and its first line:

```python
def serve(
    handler: SessionHandler,
    *,
    token: str,
    cwd: str | Path | None = None,
    host: str = "127.0.0.1",
    idle_timeout: float | None = None,
    name: str | None = None,
) -> None:
    """Bind a JSON-lines TCP server, write the session file, serve until shutdown.

    *idle_timeout* (seconds, ``None`` = never) reaps a session nobody is using.
    *name* selects the ``.visus/sessions/<name>.json`` state file, so several
    daemons can serve the same project directory at once.
    """
    resolved_name = name or "default"
    sf = session_file(cwd, resolved_name)
```

Replace the JSON payload built at `:697-707` (PLAN 5 Task 7 already added the three launch keys; keep them) with:

```python
    payload = json.dumps(
        {
            "name": resolved_name,
            "cwd": str((Path(cwd) if cwd is not None else Path.cwd()).resolve()),
            "pid": os.getpid(),
            "port": port,
            "token": token,
            "engine": handler._engine,
            "headless": handler._headless,
            "url": handler._url,
            "user_data_dir": handler._user_data_dir,
            "remote_url": handler._remote_url,
            "slow_mo": handler._slow_mo,
            "started_at": time.time(),
        }
    )
```

In `main()`, read the name from env right after the `token` line and pass it to `serve`:

```python
    name = os.environ.get("VISUS_WEB_SESSION") or "default"
```

```python
        serve(handler, token=token, idle_timeout=_idle_timeout_from_env(), name=name)
```

and include it in the startup log line:

```python
    _log(
        f"daemon starting session={name!r} engine={engine} headless={headless} "
        f"url={url!r} user_data_dir={user_data_dir!r} remote_url={remote_url!r} "
        f"slow_mo={slow_mo} pid={os.getpid()}"
    )
```

- [ ] **Step 5: Add `--session` / `-S` to the root callback**

In `src/visus/web/cli/main.py`, add the parameter to the `@app.callback()` that PLAN 4 Task 2 produced — inserted after `output_dir`, with the body gaining one line:

```python
    session: str = typer.Option(
        None,
        "--session",
        "-S",
        envvar="VISUS_WEB_SESSION",
        help="Session name (default: 'default'). `-s` is --selector, so this is -S.",
    ),
```

```python
    from visus.web.cli import session_client

    session_client.set_session_name(session)
```

placed immediately before the existing `output.set_mode(...)` calls, so a bad name fails before anything is printed.

- [ ] **Step 6: Repair the tests that hard-code the old path**

In `tests/test_cli_session.py`:

- `_write_session` (`:772-777`) becomes:

```python
def _write_session(dir_: Path, info: dict[str, Any], name: str = "default") -> Path:
    sessions = dir_ / ".visus" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    sf = sessions / f"{name}.json"
    sf.write_text(json.dumps(info), encoding="utf-8")
    return sf
```

- `test_find_session_cleans_corrupt_file` (`:821-827`): replace the two body lines that build the path with

```python
    visus = tmp_path / ".visus" / "sessions"
    visus.mkdir(parents=True)
    sf = visus / "default.json"
```

- `test_start_daemon_retries_through_partial_session_file` (`:913-915`): replace with

```python
    visus = tmp_path / ".visus" / "sessions"
    visus.mkdir(parents=True, exist_ok=True)
    sf = visus / "default.json"
```

and its `monkeypatch.setattr(session_client, "find_session", lambda d=None: None)` (`:905`) with

```python
    monkeypatch.setattr(session_client, "find_session", lambda d=None, name=None: None)
```

- Apply the same two-parameter lambda to every other `find_session` monkeypatch in the file (`:891`, and PLAN 3's `test_kill_*` / `test_stop_*` helpers): the signature is now `find_session(start_dir=None, name=None)`.
- `test_serve_writes_session_file_atomically` (`:1128-1131`) becomes:

```python
        visus = tmp_path / ".visus" / "sessions"
        leftovers = list(visus.glob("default.json.*.tmp"))
        assert leftovers == []
        assert (visus / "default.json").is_file()
```

- `test_serve_second_daemon_aborts_via_lock` (`:1149`) becomes:

```python
    assert not (tmp_path / ".visus" / "sessions" / "default.json.lock").exists()
```

In `tests/test_e2e_cli_session.py:48`:

```python
    sf = tmp_path / ".visus" / "sessions" / "default.json"
```

and PLAN 3's `test_start_recovers_after_the_daemon_is_hard_killed` lock path:

```python
    lock = tmp_path / ".visus" / "sessions" / "default.json.lock"
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_sessions_named.py -v --no-cov`
Expected: PASS (16 passed)

Run: `uv run pytest tests/test_cli_session.py -q --no-cov`
Expected: PASS (no failures)

- [ ] **Step 8: Run the cross-process e2e**

Run: `uv run pytest tests/test_e2e_cli_session.py -v --no-cov`
Expected: PASS

- [ ] **Step 9: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 10: Commit**

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/session_client.py \
        src/visus/web/cli/main.py tests/test_cli_sessions_named.py \
        tests/test_cli_session.py tests/test_e2e_cli_session.py
git commit -m "feat(cli): namespace session state under .visus/sessions/<name>.json"
```

---

### Task 2: The cross-project registry and `visus session list`

A daemon started in `~/projects/a` is invisible from `~/projects/b`: discovery only walks *up*, so a sibling directory's headed browser can neither be listed nor stopped from the CLI. This task mirrors every live session into `~/.visus/sessions/` (overridable with `VISUS_WEB_HOME`, which every test in this plan sets) and adds the command that reads both sources.

The registry entry deliberately carries **no token** — the shared secret stays in the owner-only `.visus/sessions/<name>.json` that PLAN 3 Task 16 writes with `_write_private`. The registry records the *path* of that file instead, so `close-all` (Task 3) can read the token when the caller is entitled to it and fall back to a kill when it is not.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:15-34` (imports), `:674-735` (`serve`)
- Modify: `src/visus/web/cli/session_client.py` — append `list_sessions`
- Modify: `src/visus/web/cli/main.py` — `visus session list`
- Modify: `README.md` (Session & lifecycle table, env-var table)
- Test: `tests/test_cli_sessions_named.py`

**Interfaces:**
- Consumes: `session_server.session_file` / `sessions_dir` (Task 1); `session_client._probe_pid`, `_socket_open` (PLAN 3); `output.emit` (PLAN 4)
- Produces:
  ```python
  session_server.visus_home() -> Path
  session_server.registry_dir() -> Path
  session_server.registry_file(cwd: str | Path, name: str) -> Path
  session_server._register(sf: Path, *, name: str, cwd: Path, pid: int, port: int,
                           engine: str, headless: bool, url: str | None) -> Path | None
  session_client.list_sessions(start_dir: str | Path | None = None) -> list[dict[str, Any]]
  ```
  Each `list_sessions` entry: `{"name", "cwd", "file", "pid", "port", "engine", "headless", "url", "live", "scope"}` where `scope` is `"local"` (found by the upward walk from `start_dir`) or `"other"` (registry only). **Never** contains `token`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_sessions_named.py`:

```python
def _registry_entry(tmp_path: Path, name: str, cwd: Path, port: int, pid: int) -> Path:
    """Write a registry mirror by hand, exactly as serve() would."""
    reg = session_server.registry_file(cwd, name)
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(
        json.dumps(
            {
                "name": name,
                "cwd": str(cwd),
                "file": str(session_server.session_file(cwd, name)),
                "pid": pid,
                "port": port,
                "engine": "chrome",
                "headless": True,
                "url": "http://x",
            }
        ),
        encoding="utf-8",
    )
    return reg


def test_registry_paths_are_keyed_by_cwd_and_name(tmp_path: Path) -> None:
    a = session_server.registry_file(tmp_path / "proj-a", "default")
    b = session_server.registry_file(tmp_path / "proj-b", "default")
    c = session_server.registry_file(tmp_path / "proj-a", "auth")
    assert a.parent == session_server.registry_dir()
    assert a != b, "two projects must not share a registry entry"
    assert a != c, "two names in one project must not share a registry entry"
    assert a.name.endswith("-default.json") and c.name.endswith("-auth.json")


def test_registry_dir_honours_visus_web_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tests (and CI) must never write into the developer's real ~/.visus."""
    monkeypatch.setenv("VISUS_WEB_HOME", str(tmp_path / "custom"))
    assert session_server.registry_dir() == tmp_path / "custom" / "sessions"


def test_registry_never_records_the_token(tmp_path: Path) -> None:
    import threading as _threading
    import time as _time

    from test_cli_session import _FakePage, _handler_with_fake_page, _shutdown_thread

    handler = _handler_with_fake_page(_FakePage())
    t = _threading.Thread(
        target=session_server.serve,
        kwargs={"handler": handler, "token": "super-secret", "cwd": tmp_path},
        daemon=True,
    )
    t.start()
    sf = session_server.session_file(tmp_path)
    for _ in range(200):
        if sf.is_file():
            break
        _time.sleep(0.02)
    port = int(json.loads(sf.read_text(encoding="utf-8"))["port"])
    reg = session_server.registry_file(tmp_path, "default")
    try:
        assert reg.is_file(), "serve() did not mirror the session into the registry"
        entry = json.loads(reg.read_text(encoding="utf-8"))
        assert "token" not in entry
        assert entry["file"] == str(sf)
        assert entry["port"] == port
    finally:
        _shutdown_thread(t, port, "super-secret")
    assert not reg.exists(), "the registry entry outlived the daemon"


def test_list_sessions_merges_local_and_other_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket as _socket

    srv = _socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        here = tmp_path / "here"
        elsewhere = tmp_path / "elsewhere"
        sessions = here / ".visus" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "default.json").write_text(
            json.dumps(
                {
                    "name": "default",
                    "cwd": str(here),
                    "pid": 11,
                    "port": port,
                    "token": "t",
                    "engine": "chrome",
                    "headless": False,
                    "url": "http://here",
                }
            ),
            encoding="utf-8",
        )
        _registry_entry(tmp_path, "default", here, port, 11)
        _registry_entry(tmp_path, "scrape", elsewhere, port, 22)
        monkeypatch.setattr(session_client, "_probe_pid", lambda pid: True)

        rows = session_client.list_sessions(here)
        by_key = {(r["name"], r["scope"]): r for r in rows}
        assert ("default", "local") in by_key
        assert ("scrape", "other") in by_key
        assert by_key[("default", "local")]["live"] is True
        assert by_key[("default", "local")]["url"] == "http://here"
        assert Path(by_key[("scrape", "other")]["cwd"]) == elsewhere
        assert all("token" not in r for r in rows), "list_sessions leaked a token"
    finally:
        srv.close()


def test_list_sessions_marks_a_dead_entry_not_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registry_entry(tmp_path, "ghost", tmp_path / "gone", 1, 999999)
    monkeypatch.setattr(session_client, "_probe_pid", lambda pid: False)
    rows = session_client.list_sessions(tmp_path)
    assert [(r["name"], r["live"]) for r in rows] == [("ghost", False)]


def test_cli_session_list_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client,
        "list_sessions",
        lambda start_dir=None: [
            {
                "name": "auth",
                "cwd": "/p/a",
                "file": "/p/a/.visus/sessions/auth.json",
                "pid": 4,
                "port": 5,
                "engine": "chrome",
                "headless": False,
                "url": "http://x",
                "live": True,
                "scope": "local",
            }
        ],
    )
    r = runner.invoke(app, ["--json", "session", "list"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)[0]["name"] == "auth"


def test_cli_session_list_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "list_sessions", lambda start_dir=None: [])
    r = runner.invoke(app, ["session", "list"])
    assert r.exit_code == 0
    assert "no sessions" in r.output


def test_cli_session_list_table_shows_scope_and_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        session_client,
        "list_sessions",
        lambda start_dir=None: [
            {
                "name": "auth",
                "cwd": "/p/a",
                "file": "/p/a/.visus/sessions/auth.json",
                "pid": 4,
                "port": 5,
                "engine": "chrome",
                "headless": False,
                "url": "http://x",
                "live": True,
                "scope": "local",
            },
            {
                "name": "ghost",
                "cwd": "/p/b",
                "file": "/p/b/.visus/sessions/ghost.json",
                "pid": 9,
                "port": 0,
                "engine": "chrome",
                "headless": True,
                "url": None,
                "live": False,
                "scope": "other",
            },
        ],
    )
    r = runner.invoke(app, ["session", "list"])
    assert r.exit_code == 0, r.output
    for token in ("auth", "ghost", "local", "other", "live", "dead"):
        assert token in r.output, f"{token!r} missing from the session table"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_sessions_named.py -k "registry or list_sessions or session_list" -v --no-cov`
Expected: FAIL — `AttributeError: module 'visus.web.cli.session_server' has no attribute 'registry_file'`

- [ ] **Step 3: Write the registry in the server**

In `src/visus/web/cli/session_server.py`, add `import hashlib` to the import block (alphabetical: `hashlib`, `json`, `os`, `secrets`, `socket`, `sys`, `threading`, `time`).

Add immediately below `session_file`:

```python
def visus_home() -> Path:
    """The per-user visus directory — ``VISUS_WEB_HOME`` when set, else ``~/.visus``.

    The override exists so tests and CI never touch a real home directory; the
    registry it holds is the ONLY visus state outside the project tree.
    """
    override = os.environ.get("VISUS_WEB_HOME")
    return Path(override) if override else Path.home() / ".visus"


def registry_dir() -> Path:
    """Directory of the cross-project session registry."""
    return visus_home() / "sessions"


def registry_file(cwd: str | Path, name: str) -> Path:
    """Registry path for session *name* under *cwd*.

    Keyed by a hash of the ABSOLUTE cwd plus the session name: a daemon started in
    another project is otherwise invisible (discovery only walks upward) and so
    can be neither listed nor killed from the CLI.
    """
    resolved = str(Path(cwd).resolve())
    digest = hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]
    return registry_dir() / f"{digest}-{name}.json"


def _register(
    sf: Path,
    *,
    name: str,
    cwd: Path,
    pid: int,
    port: int,
    engine: str,
    headless: bool,
    url: str | None,
) -> Path | None:
    """Mirror a live session into the registry. Returns the entry path, or ``None``.

    Deliberately token-free: the shared secret stays in the owner-only session
    file, and the entry records that file's PATH so a caller who can read it can
    still shut the daemon down politely. Never raises — a read-only or missing
    home must not stop a daemon from serving.
    """
    try:
        entry = registry_file(cwd, name)
        entry.parent.mkdir(parents=True, exist_ok=True)
        entry.write_text(
            json.dumps(
                {
                    "name": name,
                    "cwd": str(cwd),
                    "file": str(sf),
                    "pid": pid,
                    "port": port,
                    "engine": engine,
                    "headless": headless,
                    "url": url,
                    "started_at": time.time(),
                }
            ),
            encoding="utf-8",
        )
        return entry
    except OSError:
        return None
```

In `serve()`, immediately after the `os.replace(tmp, sf)` line that publishes the session file, add:

```python
    base_dir = (Path(cwd) if cwd is not None else Path.cwd()).resolve()
    registry_entry = _register(
        sf,
        name=resolved_name,
        cwd=base_dir,
        pid=os.getpid(),
        port=port,
        engine=handler._engine,
        headless=handler._headless,
        url=handler._url,
    )
```

and in `serve()`'s `finally`, after the existing `lock.unlink()` block, add:

```python
        if registry_entry is not None:
            try:
                registry_entry.unlink()
            except OSError:
                pass
```

- [ ] **Step 4: Write `list_sessions` in the client**

In `src/visus/web/cli/session_client.py`, append:

```python
def _find_sessions_dir(start_dir: str | Path | None = None) -> Path | None:
    """Search upward for a ``.visus/sessions`` directory (git-style). First hit wins."""
    cur = Path(start_dir) if start_dir is not None else Path.cwd()
    cur = cur.resolve()
    for d in [cur, *cur.parents]:
        candidate = d / ".visus" / "sessions"
        if candidate.is_dir():
            return candidate
    return None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _entry(info: dict[str, Any], *, sf: Path, scope: str) -> dict[str, Any]:
    """Shape one session record for :func:`list_sessions` — never carries the token."""
    pid = int(info.get("pid", -1) or -1)
    port = int(info.get("port", -1) or -1)
    return {
        "name": str(info.get("name") or sf.stem),
        "cwd": str(info.get("cwd") or sf.parent.parent.parent),
        "file": str(info.get("file") or sf),
        "pid": pid,
        "port": port,
        "engine": info.get("engine"),
        "headless": info.get("headless"),
        "url": info.get("url"),
        "live": bool(pid > 0 and _probe_pid(pid) and _socket_open(port)),
        "scope": scope,
    }


def list_sessions(start_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """Every session visus knows about: this project's, plus every other project's.

    Two sources are merged on ``(cwd, name)``: the project's own
    ``.visus/sessions/*.json`` (found with the same upward walk commands use) and
    the cross-project registry under ``~/.visus/sessions``. Local records win —
    they are the authoritative file the daemon writes. Liveness is probed with
    the UNCACHED :func:`_probe_pid`, because a stale "alive" here would hide a
    dead daemon from ``kill-all``.
    """
    from visus.web.cli import session_server

    merged: dict[tuple[str, str], dict[str, Any]] = {}

    local_dir = _find_sessions_dir(start_dir)
    if local_dir is not None:
        for sf in sorted(local_dir.glob("*.json")):
            info = _read_json(sf)
            if info is None:
                continue
            row = _entry(info, sf=sf, scope="local")
            merged[(str(Path(row["cwd"]).resolve()), row["name"])] = row

    try:
        registry = sorted(session_server.registry_dir().glob("*.json"))
    except OSError:
        registry = []
    for entry_file in registry:
        info = _read_json(entry_file)
        if info is None:
            continue
        row = _entry(info, sf=entry_file, scope="other")
        key = (str(Path(row["cwd"]).resolve()), row["name"])
        if key not in merged:
            merged[key] = row

    return sorted(
        merged.values(), key=lambda r: (r["scope"] != "local", r["name"], r["cwd"])
    )
```

- [ ] **Step 5: Add `visus session list`**

In `src/visus/web/cli/main.py`, add after `session_status`:

```python
@session_app.command("list")
def session_list() -> None:
    """List every session — this project's and any left running in other projects."""
    from visus.web.cli import output, session_client

    rows = session_client.list_sessions()
    if not rows:
        output.emit([], table="no sessions")
        return
    from rich import box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=box.ASCII, header_style="bold", pad_edge=False)
    for column in ("NAME", "SCOPE", "STATE", "PID", "PORT", "ENGINE", "URL", "DIR"):
        table.add_column(column, overflow="fold", no_wrap=column in ("NAME", "STATE"))
    for row in rows:
        table.add_row(
            str(row["name"]),
            str(row["scope"]),
            "live" if row["live"] else "dead",
            str(row["pid"]),
            str(row["port"]),
            str(row.get("engine") or ""),
            str(row.get("url") or ""),
            str(row["cwd"]),
        )
    console_obj = Console()
    with console_obj.capture() as cap:
        console_obj.print(table)
    output.emit(rows, table=cap.get().rstrip("\n"))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_sessions_named.py -k "registry or list_sessions or session_list" -v --no-cov`
Expected: PASS (7 passed)

- [ ] **Step 7: Update the README**

In `README.md`, in the **Session & lifecycle** table, add after the `visus session status` row:

```markdown
| `visus session list [--json]` | List every session — this project's and any daemon left running in another project. |
```

and add to the environment-variable table, after `VISUS_WEB_URL`:

```markdown
| `VISUS_WEB_SESSION` | CLI session | `default` | Session name (same as `--session` / `-S`). |
| `VISUS_WEB_HOME` | CLI session | `~/.visus` | Where the cross-project session registry lives. |
```

- [ ] **Step 8: Run the gates and commit**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/session_client.py \
        src/visus/web/cli/main.py tests/test_cli_sessions_named.py README.md
git commit -m "feat(cli): register sessions globally and add a session list command"
```

---

### Task 3: `visus session close-all`, `kill-all`, `delete-data`

`session list` (Task 2) makes an abandoned daemon *visible*; these three make it actionable. `close-all` shuts sessions down politely (it needs the token, which lives only in the owner-only session file). `kill-all` is the escape hatch that needs no token at all. `delete-data` removes a persistent profile directory — and refuses to touch a directory the user chose themselves, because a convenience command must never `rmtree` an arbitrary path.

This task also sweeps the pre-namespace `.visus/session.json` left by a daemon started before Task 1: it is discoverable by neither the new client nor `session stop`, so `kill-all` is the only thing that can reach it.

**Files:**
- Modify: `src/visus/web/cli/session_client.py` — append `profile_dir`, `_legacy_paths`, `close_all`, `kill_all`, `delete_data`
- Modify: `src/visus/web/cli/main.py` — three `session_app` commands
- Modify: `README.md` (Session & lifecycle table)
- Test: `tests/test_cli_sessions_named.py`

**Interfaces:**
- Consumes: `session_client.list_sessions` (Task 2); `_send_raw`, `_cleanup`, `_terminate`, `_probe_pid`, `_read_json` (PLAN 3 + Task 2); `session_server.registry_file`, `session_server._read_lock_pid` (Task 2 + PLAN 3); `output.emit` (PLAN 4)
- Produces:
  ```python
  session_client.profile_dir(cwd: str | Path | None = None, name: str | None = None) -> Path
  session_client.close_all(*, start_dir=None) -> str
  session_client.kill_all(*, start_dir=None) -> str
  session_client.delete_data(*, start_dir=None, name=None) -> str
  ```
  `profile_dir` is also what Task 13's `--persistent` writes into, so the two agree by construction.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_sessions_named.py`:

```python
def test_profile_dir_is_inside_the_project(tmp_path: Path) -> None:
    assert (
        session_client.profile_dir(tmp_path, "auth")
        == tmp_path / ".visus" / "profiles" / "auth"
    )


def test_close_all_shuts_down_every_live_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[int, str, str]] = []

    rows = [
        {
            "name": "auth",
            "cwd": str(tmp_path / "a"),
            "file": str(tmp_path / "a" / ".visus" / "sessions" / "auth.json"),
            "pid": 1,
            "port": 5001,
            "live": True,
            "scope": "local",
        },
        {
            "name": "ghost",
            "cwd": str(tmp_path / "b"),
            "file": str(tmp_path / "b" / ".visus" / "sessions" / "ghost.json"),
            "pid": 2,
            "port": 5002,
            "live": False,
            "scope": "other",
        },
    ]
    sf = Path(rows[0]["file"])
    sf.parent.mkdir(parents=True)
    sf.write_text(json.dumps({"pid": 1, "port": 5001, "token": "tok-a"}), encoding="utf-8")

    monkeypatch.setattr(session_client, "list_sessions", lambda start_dir=None: rows)
    monkeypatch.setattr(
        session_client,
        "_send_raw",
        lambda port, payload, **kw: sent.append((port, payload["token"], payload["op"]))
        or {"ok": True, "result": "shutdown"},
    )
    msg = session_client.close_all(start_dir=tmp_path)
    assert sent == [(5001, "tok-a", "shutdown")], sent
    assert "closed 1" in msg
    assert "ghost" not in msg  # a dead session is not "closed"


def test_close_all_reports_a_session_it_cannot_authenticate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No readable session file means no token — say so, don't pretend it closed."""
    rows = [
        {
            "name": "locked",
            "cwd": str(tmp_path / "x"),
            "file": str(tmp_path / "x" / ".visus" / "sessions" / "locked.json"),
            "pid": 3,
            "port": 5003,
            "live": True,
            "scope": "other",
        }
    ]
    monkeypatch.setattr(session_client, "list_sessions", lambda start_dir=None: rows)
    msg = session_client.close_all(start_dir=tmp_path)
    assert "locked" in msg and "kill-all" in msg


def test_close_all_with_nothing_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(session_client, "list_sessions", lambda start_dir=None: [])
    assert session_client.close_all(start_dir=tmp_path) == "no live sessions"


def test_kill_all_terminates_and_removes_every_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[int] = []
    proj = tmp_path / "proj"
    sessions = proj / ".visus" / "sessions"
    sessions.mkdir(parents=True)
    sf = sessions / "auth.json"
    sf.write_text(json.dumps({"pid": 42, "port": 1, "token": "t"}), encoding="utf-8")
    lock = sessions / "auth.json.lock"
    lock.write_text("42", encoding="utf-8")
    reg = session_server.registry_file(proj, "auth")
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(
        json.dumps({"name": "auth", "cwd": str(proj), "file": str(sf), "pid": 42, "port": 1}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        session_client,
        "list_sessions",
        lambda start_dir=None: [
            {
                "name": "auth",
                "cwd": str(proj),
                "file": str(sf),
                "pid": 42,
                "port": 1,
                "live": True,
                "scope": "local",
            }
        ],
    )
    monkeypatch.setattr(session_client, "_probe_pid", lambda pid: True)
    monkeypatch.setattr(session_client, "_terminate", killed.append)

    msg = session_client.kill_all(start_dir=tmp_path)
    assert killed == [42]
    assert not sf.exists() and not lock.exists() and not reg.exists()
    assert "auth" in msg and "42" in msg


def test_kill_all_sweeps_a_pre_namespace_session_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A daemon started before named sessions writes .visus/session.json.

    Neither the new client nor `session stop` can find it, so kill-all is the
    only command that can reach it.
    """
    killed: list[int] = []
    visus = tmp_path / ".visus"
    visus.mkdir(parents=True)
    legacy = visus / "session.json"
    legacy.write_text(json.dumps({"pid": 77, "port": 1, "token": "t"}), encoding="utf-8")
    (visus / "session.json.lock").write_text("77", encoding="utf-8")

    monkeypatch.setattr(session_client, "list_sessions", lambda start_dir=None: [])
    monkeypatch.setattr(session_client, "_probe_pid", lambda pid: True)
    monkeypatch.setattr(session_client, "_terminate", killed.append)

    msg = session_client.kill_all(start_dir=tmp_path)
    assert killed == [77]
    assert not legacy.exists()
    assert not (visus / "session.json.lock").exists()
    assert "session.json" in msg


def test_kill_all_with_nothing_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(session_client, "list_sessions", lambda start_dir=None: [])
    assert session_client.kill_all(start_dir=tmp_path) == "no session state to remove"


def test_delete_data_removes_the_managed_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = session_client.profile_dir(tmp_path, "auth")
    profile.mkdir(parents=True)
    (profile / "Cookies").write_text("x", encoding="utf-8")
    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None, name=None: None)
    msg = session_client.delete_data(start_dir=tmp_path, name="auth")
    assert not profile.exists()
    assert str(profile) in msg


def test_delete_data_refuses_while_the_session_is_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = session_client.profile_dir(tmp_path, "auth")
    profile.mkdir(parents=True)
    monkeypatch.setattr(
        session_client,
        "find_session",
        lambda start_dir=None, name=None: {"pid": 9, "port": 8, "token": "t"},
    )
    with pytest.raises(session_client.SessionError, match="still running"):
        session_client.delete_data(start_dir=tmp_path, name="auth")
    assert profile.exists(), "a live session's profile must not be deleted"


def test_delete_data_never_touches_a_user_chosen_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--profile <dir> points at a directory the USER owns; never rmtree it."""
    outside = tmp_path / "my-chrome-profile"
    outside.mkdir()
    sessions = tmp_path / ".visus" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "auth.json").write_text(
        json.dumps({"pid": 1, "port": 1, "user_data_dir": str(outside)}), encoding="utf-8"
    )
    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None, name=None: None)
    msg = session_client.delete_data(start_dir=tmp_path, name="auth")
    assert outside.is_dir(), "delete-data deleted a directory it does not manage"
    assert str(outside) in msg and "not managed by visus" in msg


def test_delete_data_with_nothing_to_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None, name=None: None)
    msg = session_client.delete_data(start_dir=tmp_path, name="auth")
    assert "no profile data" in msg


def test_cli_fleet_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "close_all", lambda: "closed 2 session(s)")
    monkeypatch.setattr(session_client, "kill_all", lambda: "killed pid 1")
    monkeypatch.setattr(session_client, "delete_data", lambda name=None: f"deleted {name}")

    assert "closed 2" in runner.invoke(app, ["session", "close-all"]).output
    assert "killed pid 1" in runner.invoke(app, ["session", "kill-all"]).output
    r = runner.invoke(app, ["-S", "auth", "session", "delete-data"])
    assert r.exit_code == 0 and "deleted auth" in r.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_sessions_named.py -k "profile_dir or close_all or kill_all or delete_data or fleet" -v --no-cov`
Expected: FAIL — `AttributeError: module 'visus.web.cli.session_client' has no attribute 'profile_dir'`

- [ ] **Step 3: Write the fleet functions**

In `src/visus/web/cli/session_client.py`, add `import shutil` to the import block (alphabetical: `json`, `os`, `re`, `shutil`, `signal`, `socket`, `subprocess`, `sys`, `time`) and append:

```python
def profile_dir(
    cwd: str | Path | None = None, name: str | None = None
) -> Path:
    """The persistent profile ``--persistent`` creates for session *name*.

    Inside the project (``.visus/profiles/<name>``) so it is git-ignored with the
    rest of ``.visus/`` and so :func:`delete_data` has exactly one directory it is
    entitled to remove.
    """
    base = Path(cwd) if cwd is not None else Path.cwd()
    return base / ".visus" / "profiles" / session_name(name)


def _legacy_paths(start_dir: str | Path | None = None) -> list[Path]:
    """Pre-namespace ``.visus/session.json`` (+ lock), searched upward.

    A daemon started before sessions were namespaced writes that path. The new
    client cannot discover it and ``session stop`` cannot reach it, so
    :func:`kill_all` is the only command that can clean it up.
    """
    cur = Path(start_dir) if start_dir is not None else Path.cwd()
    cur = cur.resolve()
    found: list[Path] = []
    for d in [cur, *cur.parents]:
        for candidate in (d / ".visus" / "session.json", d / ".visus" / "session.json.lock"):
            if candidate.is_file():
                found.append(candidate)
    return found


def close_all(*, start_dir: str | Path | None = None) -> str:
    """Politely shut down every live session. Returns a status message.

    Shutdown needs the session token, which lives only in the owner-only session
    file — so a session whose file this user cannot read is reported rather than
    silently skipped, with the command that CAN stop it.
    """
    closed: list[str] = []
    unreachable: list[str] = []
    for row in list_sessions(start_dir):
        if not row.get("live"):
            continue
        info = _read_json(Path(str(row.get("file") or "")))
        token = None if info is None else info.get("token")
        if not isinstance(token, str):
            unreachable.append(str(row["name"]))
            continue
        try:
            _send_raw(int(row["port"]), {"token": token, "op": "shutdown", "args": {}})
        except (OSError, SessionError, json.JSONDecodeError):
            unreachable.append(str(row["name"]))
            continue
        closed.append(str(row["name"]))
    if not closed and not unreachable:
        return "no live sessions"
    parts = [f"closed {len(closed)} session(s): {', '.join(closed)}"] if closed else []
    if unreachable:
        parts.append(
            f"could not reach {', '.join(unreachable)} "
            "(session file unreadable) — use `visus session kill-all`"
        )
    return "; ".join(parts)


def kill_all(*, start_dir: str | Path | None = None) -> str:
    """Force-clear every session: terminate live daemons and delete all state.

    The no-token escape hatch behind :func:`close_all`. Sweeps three places: each
    project session file (+ its lock), the cross-project registry entry, and any
    pre-namespace ``.visus/session.json`` nothing else can reach.
    """
    from visus.web.cli import session_server

    killed: list[int] = []
    removed: list[str] = []

    for row in list_sessions(start_dir):
        pid = int(row.get("pid", -1) or -1)
        if pid > 0 and _probe_pid(pid):
            _terminate(pid)
            killed.append(pid)
        sf = Path(str(row.get("file") or ""))
        if sf.is_file():
            _cleanup(sf)  # removes the session file AND the lock beside it
            removed.append(sf.name)
        try:
            entry = session_server.registry_file(str(row["cwd"]), str(row["name"]))
            if entry.is_file():
                entry.unlink()
                removed.append(entry.name)
        except OSError:
            pass

    for legacy in _legacy_paths(start_dir):
        if legacy.name == "session.json":
            info = _read_json(legacy)
            pid = -1 if info is None else int(info.get("pid", -1) or -1)
        else:
            pid = session_server._read_lock_pid(legacy)
        if pid > 0 and pid not in killed and _probe_pid(pid):
            _terminate(pid)
            killed.append(pid)
        try:
            legacy.unlink()
            removed.append(legacy.name)
        except OSError:
            pass

    if not killed and not removed:
        return "no session state to remove"
    parts: list[str] = []
    if killed:
        parts.append("killed pid " + ", ".join(str(p) for p in killed))
    if removed:
        parts.append("removed " + ", ".join(removed))
    return "; ".join(parts)


def delete_data(
    *, start_dir: str | Path | None = None, name: str | None = None
) -> str:
    """Delete session *name*'s persistent browser profile. Returns a message.

    Only the directory visus itself creates (:func:`profile_dir`) is removed. A
    profile the user pointed at with ``--profile`` / ``--user-data-dir`` is
    reported but never deleted: it is their directory, it may hold their real
    Chrome data, and an rmtree there is unrecoverable.
    """
    resolved = session_name(name)
    if find_session(start_dir, resolved) is not None:
        raise SessionError(
            f"session {resolved!r} is still running — stop it first "
            "(`visus session stop`), then delete its data"
        )

    managed = profile_dir(start_dir, resolved)
    notes: list[str] = []
    if managed.is_dir():
        shutil.rmtree(managed, ignore_errors=True)
        notes.append(f"deleted {managed}")

    sf = _find_session_file(start_dir, resolved)
    info = None if sf is None else _read_json(sf)
    external = None if info is None else info.get("user_data_dir")
    if isinstance(external, str) and external and Path(external) != managed:
        notes.append(f"left {external} alone (not managed by visus — delete it yourself)")

    if not notes:
        return f"no profile data for session {resolved!r}"
    return "; ".join(notes)
```

- [ ] **Step 4: Add the three commands**

In `src/visus/web/cli/main.py`, add after `session_list`:

```python
@session_app.command("close-all")
def session_close_all() -> None:
    """Shut down every live session, in this project and in any other."""
    from visus.web.cli import output, session_client

    output.emit(session_client.close_all())


@session_app.command("kill-all")
def session_kill_all() -> None:
    """Force-kill every session daemon and delete all session state.

    The escape hatch when `close-all` cannot authenticate: it needs no token and
    also sweeps state left by a visus older than named sessions.
    """
    from visus.web.cli import output, session_client

    output.emit(session_client.kill_all())


@session_app.command("delete-data")
def session_delete_data() -> None:
    """Delete this session's persistent browser profile (`--persistent`)."""
    from visus.web.cli import output, session_client

    try:
        output.emit(session_client.delete_data())
    except session_client.SessionError as exc:
        output.emit_error(str(exc))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_sessions_named.py -v --no-cov`
Expected: PASS (35 passed)

- [ ] **Step 6: Update the README**

In `README.md`, in the **Session & lifecycle** table, add after the `visus session list` row:

```markdown
| `visus session close-all` | Shut down every live session (this project's and other projects'). |
| `visus session kill-all` | Force-kill every session daemon and delete all session state. |
| `visus session delete-data` | Delete this session's persistent profile (`--persistent` only). |
```

- [ ] **Step 7: Run the gates and commit**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

```bash
git add src/visus/web/cli/session_client.py src/visus/web/cli/main.py \
        tests/test_cli_sessions_named.py README.md
git commit -m "feat(cli): add session close-all, kill-all and delete-data"
```

---

### Task 4: `RouteRule` and glob matching (`api/route.py`)

A grep for `\broute\b|fulfill|Fetch.enable|requestPaused|intercept|abort` across `src/` returns four irrelevant hits (`actionability.py:84`, `session_server.py:685`/`:767`, `network.py:58`). Nothing exists. The two closest primitives are one-directional: `page.block_urls` (`api/page.py:355-357`) drops requests and `page.set_offline` (`:363-365`) drops all of them. **This is the only gap with no `eval` workaround** — an interception handler installed from page JS races the page's own scripts and cannot see document navigations at all.

The value type comes first because both the engine (Task 5) and the CLI (Task 6) match against it, and it is the one piece testable without a browser.

`RouteRule`'s fields are pinned by CONVENTIONS.md and must not be renamed or reordered.

**Files:**
- Create: `src/visus/web/api/route.py`
- Test: `tests/test_route.py`

**Interfaces:**
- Consumes: `visus.web.network.scrub_headers(h: dict) -> dict` (`network.py:45-53`) — the same redaction the network capture already applies
- Produces:
  ```python
  @dataclass(frozen=True)
  class RouteRule:
      pattern: str; status: int | None; body: str | None
      content_type: str | None; headers: dict[str, str]; abort: bool
      def to_dict(self) -> dict[str, object]: ...
      @classmethod
      def from_dict(cls, data: dict[str, object]) -> RouteRule: ...
      def matches(self, url: str) -> bool: ...
      def redacted(self) -> RouteRule: ...
  def compile_pattern(pattern: str) -> re.Pattern[str]: ...
  def cdp_url_pattern(pattern: str) -> str: ...
  ```

- [ ] **Step 1: Write the failing test**

Create `tests/test_route.py`:

```python
"""Route rules: glob semantics, redaction, and (below) real interception."""

from __future__ import annotations

import pytest

from visus.web.api.route import RouteRule, cdp_url_pattern, compile_pattern


@pytest.mark.parametrize(
    ("pattern", "url", "expected"),
    [
        ("**/api/users", "https://x.test/api/users", True),
        ("**/api/users", "https://x.test/v1/api/users", True),
        ("**/api/users", "https://x.test/api/users/1", False),
        ("**/api/*/details", "https://x.test/api/7/details", True),
        ("**/api/*/details", "https://x.test/api/7/8/details", False),
        ("**/*.{png,jpg}", "https://x.test/a/b/logo.png", True),
        ("**/*.{png,jpg}", "https://x.test/a/b/logo.gif", False),
        ("https://x.test/exact", "https://x.test/exact", True),
        ("https://x.test/exact", "https://y.test/exact", False),
        ("**/search?q=*", "https://x.test/search?q=cats", True),
        ("**/search?q=*", "https://x.test/searchXq=cats", False),
        ("**", "https://anything.test/at/all", True),
    ],
)
def test_glob_matching(pattern: str, url: str, expected: bool) -> None:
    assert RouteRule(pattern, None, None, None, {}, False).matches(url) is expected


def test_question_mark_is_literal_not_a_wildcard() -> None:
    """URLs use `?` for the query string; treating it as a wildcard would be a trap."""
    assert compile_pattern("a?b").match("a?b") is not None
    assert compile_pattern("a?b").match("axb") is None


def test_regex_metacharacters_in_a_pattern_are_literal() -> None:
    rule = RouteRule("**/price(usd).json", None, None, None, {}, False)
    assert rule.matches("https://x.test/price(usd).json") is True
    assert rule.matches("https://x.test/priceXusd.json") is False


def test_round_trip_through_dict() -> None:
    rule = RouteRule(
        pattern="**/api/*",
        status=503,
        body='{"error":"down"}',
        content_type="application/json",
        headers={"X-Mock": "1"},
        abort=False,
    )
    assert RouteRule.from_dict(rule.to_dict()) == rule


def test_from_dict_tolerates_a_minimal_payload() -> None:
    rule = RouteRule.from_dict({"pattern": "**/x"})
    assert rule == RouteRule("**/x", None, None, None, {}, False)


def test_redacted_scrubs_secret_headers_but_keeps_the_rule() -> None:
    rule = RouteRule(
        pattern="**/api/*",
        status=200,
        body="{}",
        content_type="application/json",
        headers={"Authorization": "Bearer abc", "X-Trace": "keep"},
        abort=False,
    )
    safe = rule.redacted()
    assert safe.headers == {"Authorization": "REDACTED", "X-Trace": "keep"}
    assert safe.pattern == rule.pattern and safe.status == 200
    assert rule.headers["Authorization"] == "Bearer abc", "redacted() mutated the original"


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("**/api/users", "*/api/users"),
        ("**/*.{png,jpg}", "*/*.*"),
        ("https://x.test/exact", "*https://x.test/exact"),
        ("**", "*"),
    ],
)
def test_cdp_url_pattern_is_a_superset(pattern: str, expected: str) -> None:
    """CDP only knows `*`; it pre-filters, Python decides. So it must never be narrower."""
    assert cdp_url_pattern(pattern) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_route.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'visus.web.api.route'`

- [ ] **Step 3: Write the implementation**

Create `src/visus/web/api/route.py`:

```python
"""Request-interception rules.

A :class:`RouteRule` is a pure value: a URL glob plus what to answer with. The
engine (``backends/selenium/cdp_fetch.py``) turns it into CDP ``Fetch`` commands,
the CLI turns it into a ``visus route`` invocation, and neither leaks into this
module — nothing here touches a browser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from visus.web.network import scrub_headers


def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Compile a Playwright-style URL glob into a full-match regex.

    ``**`` matches anything including ``/``; ``*`` matches anything except ``/``;
    ``{a,b}`` is an alternation. ``?`` is **literal** — URLs use it to start the
    query string, so treating it as a wildcard would silently widen every pattern
    that names a query parameter. Everything else is escaped.
    """
    out: list[str] = ["^"]
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern.startswith("**", i):
                out.append(".*")
                i += 2
            else:
                out.append("[^/]*")
                i += 1
            continue
        if ch == "{":
            end = pattern.find("}", i)
            if end != -1:
                alts = pattern[i + 1 : end].split(",")
                out.append("(?:" + "|".join(re.escape(a) for a in alts) + ")")
                i = end + 1
                continue
        out.append(re.escape(ch))
        i += 1
    out.append("$")
    return re.compile("".join(out))


def cdp_url_pattern(pattern: str) -> str:
    """A permissive CDP ``urlPattern`` for *pattern*.

    CDP's ``Fetch.enable`` only understands ``*``, and it merely decides which
    requests get PAUSED — :meth:`RouteRule.matches` still makes the real decision
    in Python. So this only has to be a SUPERSET: every construct CDP cannot
    express collapses to ``*``, and a pattern that does not already start with a
    wildcard gets one so it can match a full absolute URL.
    """
    collapsed = re.sub(r"\{[^}]*\}", "*", pattern)
    while "**" in collapsed:
        collapsed = collapsed.replace("**", "*")
    if not collapsed.startswith("*"):
        collapsed = "*" + collapsed
    return collapsed


@dataclass(frozen=True)
class RouteRule:
    """One interception rule: what to match, and what to answer with.

    ``abort=True`` fails the request outright (the network-error path). Otherwise
    the request is fulfilled locally with *status* / *body* / *content_type* /
    *headers* and never reaches the network.
    """

    pattern: str
    status: int | None
    body: str | None
    content_type: str | None
    headers: dict[str, str]
    abort: bool

    def to_dict(self) -> dict[str, object]:
        """The transport shape: what crosses the delegate boundary and the socket."""
        return {
            "pattern": self.pattern,
            "status": self.status,
            "body": self.body,
            "content_type": self.content_type,
            "headers": dict(self.headers),
            "abort": self.abort,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> RouteRule:
        """Rebuild a rule from :meth:`to_dict` (or from a partial CLI payload)."""
        status = data.get("status")
        headers = data.get("headers")
        return cls(
            pattern=str(data.get("pattern", "")),
            status=None if status is None else int(status),  # type: ignore[arg-type]
            body=None if data.get("body") is None else str(data.get("body")),
            content_type=(
                None if data.get("content_type") is None else str(data.get("content_type"))
            ),
            headers={str(k): str(v) for k, v in dict(headers or {}).items()},  # type: ignore[arg-type]
            abort=bool(data.get("abort", False)),
        )

    def matches(self, url: str) -> bool:
        """Whether *url* is covered by this rule's glob."""
        return compile_pattern(self.pattern).match(url) is not None

    def redacted(self) -> RouteRule:
        """A copy whose secret headers are ``"REDACTED"`` — safe to print or log.

        Reuses the network capture's redaction list so `visus route-list` cannot
        become the one command that prints an ``Authorization`` header back out.
        """
        return replace(self, headers={str(k): str(v) for k, v in scrub_headers(self.headers).items()})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_route.py -v --no-cov`
Expected: PASS (21 passed)

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/api/route.py tests/test_route.py
git commit -m "feat(api): add RouteRule with Playwright-style URL glob matching"
```

---

### Task 5: The CDP `Fetch` interceptor and `page.route()`

`execute_cdp_cmd` (which `NetworkCapture` uses at `network.py:189-204`) is a *command* channel — chromedriver's `send_command_and_get_result` returns one result and delivers no events, and its performance log only carries `Network.*` / `Page.*`. `Fetch.requestPaused` therefore needs a DevTools connection of its own. Chrome has allowed multiple DevTools clients per target since M63, so a second client can enable `Fetch` and answer pauses without disturbing the one chromedriver holds.

The whole websocket lives in `backends/selenium/cdp_fetch.py`; `api/route.py` and `Page` never see it. **Chrome and Edge only** — Firefox exposes no CDP endpoint, and the error says so and names the alternative rather than misbehaving quietly.

**Files:**
- Create: `src/visus/web/backends/selenium/cdp_fetch.py`
- Modify: `src/visus/web/backends/base.py:97-100` (network-controls block of `PageDelegate`)
- Modify: `src/visus/web/backends/selenium/driver_delegate.py:1-34` (imports), `:81-107` (`__init__`), `:195-203` (`close`), `:934-955` (network-controls block)
- Modify: `src/visus/web/api/page.py:353-365` (network-controls block)
- Modify: `src/visus/web/async_api/__init__.py:645-654` (network-controls block)
- Modify: `pyproject.toml:18` (dependencies), `:96-102` (mypy overrides)
- Modify: `tests/test_backend_protocols.py:121-123`
- Create: `tests/fixtures/route_fetch.html`
- Test: `tests/test_route.py`

**Interfaces:**
- Consumes: `RouteRule`, `cdp_url_pattern` (Task 4); `errors.VisusWebError` (`errors.py:5-6`)
- Produces:
  ```python
  # backends/selenium/cdp_fetch.py
  def devtools_ws_url(driver: WebDriver, handle: str) -> str: ...
  class FetchInterceptor:
      def __init__(self, ws_url: str, *, timeout: float = 10.0) -> None: ...
      def start(self) -> None: ...
      def stop(self) -> None: ...
      def set_rules(self, rules: list[dict[str, object]]) -> None: ...

  # backends/base.py — PageDelegate
  def route_add(self, rule: dict[str, object]) -> None: ...
  def route_remove(self, pattern: str | None) -> int: ...
  def route_list(self) -> list[dict[str, object]]: ...

  # api/page.py — Page
  def route(self, pattern: str, *, status=None, body=None, content_type=None,
            headers=None, abort=False) -> RouteRule: ...
  def unroute(self, pattern: str | None = None) -> int: ...
  def routes(self) -> list[RouteRule]: ...
  ```

- [ ] **Step 1: Write the fixture page**

Create `tests/fixtures/route_fetch.html` with exactly this content:

```html
<!doctype html>
<html>
  <head><title>route fixture</title></head>
  <body>
    <!-- Each button issues ONE request and writes the outcome into #out, so a
         test can tell "fulfilled by the mock" from "hit the real server" from
         "aborted" by reading text — no CDP inspection needed. -->
    <button id="go">Load items</button>
    <button id="img">Load image</button>
    <pre id="out">idle</pre>
    <img id="pic" alt="" width="8" height="8" />
    <script>
      var out = document.getElementById('out');
      document.getElementById('go').addEventListener('click', function () {
        out.textContent = 'loading';
        fetch('/api/items')
          .then(function (r) {
            return r.text().then(function (body) {
              out.textContent = 'status=' + r.status + ' body=' + body;
            });
          })
          .catch(function (e) { out.textContent = 'failed:' + e.message; });
      });
      document.getElementById('img').addEventListener('click', function () {
        var pic = document.getElementById('pic');
        pic.onload = function () { out.textContent = 'image-ok'; };
        pic.onerror = function () { out.textContent = 'image-blocked'; };
        pic.src = '/pixel.png?t=' + Date.now();
      });
    </script>
  </body>
</html>
```

Note: the fixture server (`tests/conftest.py:14-31`) has no `/api/items` and no `/pixel.png`, so an un-mocked fetch returns 404 and an un-mocked image errors — which is exactly what makes "the mock answered" unambiguous.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_route.py`:

```python
from pathlib import Path

from visus.web import errors, launch
from visus.web.api.route import RouteRule as _RouteRule  # noqa: F401  (re-export check)


@pytest.mark.browser
def test_route_fulfills_a_request_without_hitting_the_network(base_url: str) -> None:
    """The gap with no eval workaround: an answer the page never made a request for."""
    with launch(headless=True) as browser:
        page = browser.new_page()
        page.goto(f"{base_url}/route_fetch.html")
        page.route(
            "**/api/items",
            status=201,
            body='[{"id":1,"name":"Alice"}]',
            content_type="application/json",
            headers={"X-Mock": "yes"},
        )
        page.locator("#go").click()
        from visus.web import expect

        expect(page.locator("#out")).to_have_text("status=201", timeout=10000)
        text = page.locator("#out").text_content() or ""
        assert '"name":"Alice"' in text, text
        assert "404" not in text, "the request reached the real fixture server"


@pytest.mark.browser
def test_route_abort_fails_a_subresource(base_url: str) -> None:
    with launch(headless=True) as browser:
        page = browser.new_page()
        page.goto(f"{base_url}/route_fetch.html")
        page.route("**/pixel.png*", abort=True)
        page.locator("#img").click()
        from visus.web import expect

        expect(page.locator("#out")).to_have_text("image-blocked", timeout=10000)


@pytest.mark.browser
def test_unmatched_requests_still_reach_the_server(base_url: str) -> None:
    """Fetch.enable pauses traffic — anything unmatched MUST be continued."""
    with launch(headless=True) as browser:
        page = browser.new_page()
        page.goto(f"{base_url}/route_fetch.html")
        page.route("**/never-matches", status=500, body="nope")
        page.locator("#go").click()
        from visus.web import expect

        expect(page.locator("#out")).to_have_text("status=404", timeout=10000)


@pytest.mark.browser
def test_routes_lists_and_unroute_removes(base_url: str) -> None:
    with launch(headless=True) as browser:
        page = browser.new_page()
        page.goto(f"{base_url}/route_fetch.html")
        page.route("**/api/items", status=201, body="[]", content_type="application/json")
        page.route("**/pixel.png*", abort=True)
        listed = page.routes()
        assert [r.pattern for r in listed] == ["**/api/items", "**/pixel.png*"]
        assert listed[1].abort is True

        assert page.unroute("**/pixel.png*") == 1
        assert [r.pattern for r in page.routes()] == ["**/api/items"]
        assert page.unroute() == 1
        assert page.routes() == []

        # Interception is fully off again: the real 404 comes back.
        page.locator("#go").click()
        from visus.web import expect

        expect(page.locator("#out")).to_have_text("status=404", timeout=10000)


@pytest.mark.browser
def test_re_routing_the_same_pattern_replaces_it(base_url: str) -> None:
    with launch(headless=True) as browser:
        page = browser.new_page()
        page.goto(f"{base_url}/route_fetch.html")
        page.route("**/api/items", status=200, body="first")
        page.route("**/api/items", status=200, body="second")
        assert len(page.routes()) == 1
        page.locator("#go").click()
        from visus.web import expect

        expect(page.locator("#out")).to_have_text("body=second", timeout=10000)


def test_route_is_refused_without_a_devtools_endpoint() -> None:
    """A non-Chromium (or grid) session has no debuggerAddress — say what to do.

    Asserted against the resolver directly rather than by launching Firefox: the
    guard is a capability check, and Firefox is not installed on every machine
    that runs this suite.
    """
    from visus.web.backends.selenium.cdp_fetch import devtools_ws_url

    class _NoCdpDriver:
        capabilities: dict[str, object] = {"browserName": "firefox"}

    with pytest.raises(errors.VisusWebError) as excinfo:
        devtools_ws_url(_NoCdpDriver(), "CDwindow-1")  # type: ignore[arg-type]
    message = str(excinfo.value)
    assert "chrome" in message and "edge" in message
    assert "add_init_script" in message


def test_page_route_signature_is_engine_free() -> None:
    """THE HIDDEN-ENGINE RULE: no selenium type in the public route surface."""
    import inspect

    from visus.web.api.page import Page

    for name in ("route", "unroute", "routes"):
        source = inspect.getsource(getattr(Page, name))
        assert "selenium" not in source, f"Page.{name} mentions selenium"
        signature = str(inspect.signature(getattr(Page, name)))
        assert "selenium" not in signature and "WebDriver" not in signature
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_route.py -k "devtools_ws_url or engine_free" -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'visus.web.backends.selenium.cdp_fetch'`

- [ ] **Step 4: Declare the websocket dependency**

In `pyproject.toml`, replace `:18` with:

```toml
# websocket-client drives the DevTools connection request interception needs:
# chromedriver's execute_cdp_cmd is command-only and delivers no CDP events, so
# Fetch.requestPaused has to arrive over a socket of our own. It is already a
# hard dependency of selenium>=4.28; declared explicitly so it is never a
# transitive accident.
dependencies = ["selenium>=4.38,<5", "websocket-client>=1.8,<2"]
```

and add after the `mcp.*` override (`:100-102`):

```toml
[[tool.mypy.overrides]]
module = ["websocket.*"]
ignore_missing_imports = true
```

- [ ] **Step 5: Write the interceptor**

Create `src/visus/web/backends/selenium/cdp_fetch.py`:

```python
"""CDP ``Fetch`` request interception over a dedicated DevTools WebSocket.

Selenium's ``execute_cdp_cmd`` is a command channel: chromedriver returns one
result per call and never delivers events, and its performance log only carries
``Network.*``/``Page.*``. ``Fetch.requestPaused`` therefore cannot be observed
through it. Chrome has supported several concurrent DevTools clients per target
since M63, so this module opens its own connection to the tab's target, enables
``Fetch`` on it, and answers each pause — leaving chromedriver's own session
untouched.

Everything selenium- and protocol-shaped stays here. The public surface
(:class:`visus.web.api.route.RouteRule`, ``Page.route``) never sees it.
"""

from __future__ import annotations

import base64
import json
import threading
import urllib.request
from typing import Any

from selenium.webdriver.remote.webdriver import WebDriver

from visus.web import errors
from visus.web.api.route import RouteRule, cdp_url_pattern

_NO_CDP = (
    "request interception requires a Chromium engine (chrome/edge) driven locally — "
    "this session exposes no DevTools address. Firefox has no CDP Fetch domain: stub "
    "the API from the page instead with page.add_init_script(...), which runs before "
    "the app boots."
)


def devtools_ws_url(driver: WebDriver, handle: str) -> str:
    """The DevTools WebSocket URL for the tab behind *handle*.

    Chromedriver's window handles are ``CDwindow-<targetId>``, and the browser's
    ``/json/list`` endpoint keys page targets by that same id — so the right tab
    is addressed even when several are open.
    """
    capabilities: dict[str, Any] = dict(getattr(driver, "capabilities", None) or {})
    address = ""
    for key in ("goog:chromeOptions", "ms:edgeOptions"):
        options = capabilities.get(key)
        if isinstance(options, dict) and options.get("debuggerAddress"):
            address = str(options["debuggerAddress"])
            break
    if not address:
        raise errors.VisusWebError(_NO_CDP)

    try:
        with urllib.request.urlopen(f"http://{address}/json/list", timeout=10) as resp:
            targets: list[dict[str, Any]] = json.loads(resp.read().decode("utf-8"))
    except OSError as exc:
        raise errors.VisusWebError(
            f"could not reach the DevTools endpoint at {address}: {exc}"
        ) from exc

    target_id = handle.split("CDwindow-", 1)[-1]
    pages = [
        t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
    ]
    for target in pages:
        if target.get("id") == target_id:
            return str(target["webSocketDebuggerUrl"])
    if pages:
        return str(pages[0]["webSocketDebuggerUrl"])
    raise errors.VisusWebError("no DevTools page target is available for this tab")


class FetchInterceptor:
    """Owns one DevTools connection and answers ``Fetch.requestPaused``.

    ``Fetch.enable`` pauses every matching request until somebody answers it, so
    a dead pump would hang the page. Two guarantees follow: any request that
    matches no rule is immediately continued, and the pump disables ``Fetch``
    on its way out however it exits.
    """

    def __init__(self, ws_url: str, *, timeout: float = 10.0) -> None:
        self._ws_url = ws_url
        self._timeout = timeout
        self._ws: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._send_lock = threading.Lock()
        self._rules_lock = threading.Lock()
        self._rules: list[RouteRule] = []
        self._msg_id = 0

    # --- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Connect and enable ``Fetch``, then start the pump thread."""
        if self._thread is not None:
            return
        import websocket  # imported here so the module loads without the extra present

        try:
            self._ws = websocket.create_connection(self._ws_url, timeout=self._timeout)
        except Exception as exc:  # noqa: BLE001 — any transport failure is one error
            raise errors.VisusWebError(
                f"could not open a DevTools connection for request interception: {exc}"
            ) from exc
        self._await(self._send("Fetch.enable", {"patterns": self._patterns()}))
        self._ws.settimeout(0.5)
        self._stop.clear()
        self._thread = threading.Thread(target=self._pump, name="visus-route", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Disable ``Fetch``, close the socket, and join the pump."""
        self._stop.set()
        try:
            if self._ws is not None:
                self._send("Fetch.disable", {})
        except Exception:  # noqa: BLE001 — a dead socket is already disabled
            pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)
        try:
            if self._ws is not None:
                self._ws.close()
        except Exception:  # noqa: BLE001
            pass
        self._ws = None

    def set_rules(self, rules: list[dict[str, object]]) -> None:
        """Replace the rule list and re-arm the CDP pause patterns."""
        with self._rules_lock:
            self._rules = [RouteRule.from_dict(r) for r in rules]
        if self._ws is not None:
            self._send("Fetch.enable", {"patterns": self._patterns()})

    # --- protocol --------------------------------------------------------
    def _patterns(self) -> list[dict[str, str]]:
        with self._rules_lock:
            return [{"urlPattern": cdp_url_pattern(r.pattern)} for r in self._rules]

    def _send(self, method: str, params: dict[str, Any] | None = None) -> int:
        with self._send_lock:
            self._msg_id += 1
            message_id = self._msg_id
            self._ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
            return message_id

    def _await(self, message_id: int) -> None:
        """Read until the reply to *message_id* arrives (startup only, pre-pump).

        Bounded by the connection's own timeout: a DevTools endpoint that answers
        nothing raises rather than blocking the caller forever.
        """
        while True:
            raw = self._ws.recv()
            if not raw:
                raise errors.VisusWebError("DevTools closed the connection during Fetch.enable")
            try:
                message: dict[str, Any] = json.loads(raw)
            except ValueError:
                continue
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise errors.VisusWebError(f"Fetch.enable failed: {message['error']}")
            return

    def _pump(self) -> None:
        import websocket

        try:
            while not self._stop.is_set():
                try:
                    raw = self._ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                except Exception:  # noqa: BLE001 — socket gone: leave the loop
                    break
                if not raw:
                    continue
                try:
                    message: dict[str, Any] = json.loads(raw)
                except ValueError:
                    continue
                if message.get("method") == "Fetch.requestPaused":
                    self._answer(dict(message.get("params") or {}))
        finally:
            # Never leave requests paused with nobody listening.
            try:
                if self._ws is not None and not self._stop.is_set():
                    self._send("Fetch.disable", {})
            except Exception:  # noqa: BLE001
                pass

    def _match(self, url: str) -> RouteRule | None:
        with self._rules_lock:
            for rule in self._rules:
                if rule.matches(url):
                    return rule
        return None

    def _answer(self, params: dict[str, Any]) -> None:
        request_id = params.get("requestId")
        if not request_id:
            return
        url = str((params.get("request") or {}).get("url", ""))
        rule = self._match(url)
        try:
            if rule is None:
                self._send("Fetch.continueRequest", {"requestId": request_id})
                return
            if rule.abort:
                self._send(
                    "Fetch.failRequest", {"requestId": request_id, "errorReason": "Failed"}
                )
                return
            headers = [{"name": k, "value": v} for k, v in rule.headers.items()]
            if rule.content_type:
                headers.append({"name": "Content-Type", "value": rule.content_type})
            body = rule.body or ""
            self._send(
                "Fetch.fulfillRequest",
                {
                    "requestId": request_id,
                    "responseCode": int(rule.status or 200),
                    "responseHeaders": headers,
                    "body": base64.b64encode(body.encode("utf-8")).decode("ascii"),
                },
            )
        except Exception:  # noqa: BLE001 — a send failure means the socket is gone
            self._stop.set()
```

- [ ] **Step 6: Wire the delegate**

In `src/visus/web/backends/base.py`, extend `PageDelegate`'s network-controls block (`:97-100`):

```python
    # --- network controls (Chromium CDP) ---
    def block_urls(self, patterns: list[str]) -> None: ...
    def set_extra_http_headers(self, headers: dict[str, str]) -> None: ...
    def set_offline(self, offline: bool) -> None: ...
    # --- request interception (Chromium CDP Fetch) ---
    def route_add(self, rule: dict[str, object]) -> None: ...
    def route_remove(self, pattern: str | None) -> int: ...
    def route_list(self) -> list[dict[str, object]]: ...
```

In `src/visus/web/backends/selenium/driver_delegate.py`, add to the `visus.web` import block (after `from visus.web.backends.selenium.actionability import run_action`):

```python
from visus.web.backends.selenium.cdp_fetch import FetchInterceptor, devtools_ws_url
```

Add to `SeleniumPageDelegate.__init__`, after `self._console_buffer: list[dict[str, object]] = []` (`:97`):

```python
        # Request interception is per-tab and lazy: no DevTools socket is opened
        # until the first route is added.
        self._routes: list[dict[str, object]] = []
        self._interceptor: FetchInterceptor | None = None
```

Replace `close()` (`:195-203`) with:

```python
    def close(self) -> None:
        if self._closed:
            return
        self._stop_interceptor()
        try:
            self._driver.switch_to.window(self._handle)
            self._driver.close()
        except WebDriverException:
            pass
        self._closed = True
```

Add these four methods immediately after `set_offline` (`:944-955`):

```python
    def _stop_interceptor(self) -> None:
        """Tear down the DevTools connection, if one was ever opened."""
        if self._interceptor is not None:
            self._interceptor.stop()
            self._interceptor = None

    def route_add(self, rule: dict[str, object]) -> None:
        """Install (or replace) one interception rule on this tab."""
        self._activate()
        if self._interceptor is None:
            self._interceptor = FetchInterceptor(devtools_ws_url(self._driver, self._handle))
            self._interceptor.start()
        pattern = rule.get("pattern")
        self._routes = [r for r in self._routes if r.get("pattern") != pattern]
        self._routes.append(dict(rule))
        self._interceptor.set_rules(list(self._routes))

    def route_remove(self, pattern: str | None) -> int:
        """Remove one rule (or every rule when *pattern* is ``None``). Returns the count."""
        before = len(self._routes)
        if pattern is None:
            self._routes = []
        else:
            self._routes = [r for r in self._routes if r.get("pattern") != pattern]
        removed = before - len(self._routes)
        if self._interceptor is not None:
            if self._routes:
                self._interceptor.set_rules(list(self._routes))
            else:
                # No rules left: drop the DevTools connection entirely so nothing
                # is paused and the tab is exactly as it was before any routing.
                self._stop_interceptor()
        return removed

    def route_list(self) -> list[dict[str, object]]:
        """The rules installed on this tab, in insertion order."""
        return [dict(r) for r in self._routes]
```

- [ ] **Step 7: Wire the public API**

In `src/visus/web/api/page.py`, add after `set_offline` (`:363-365`):

```python
    # --- request interception (Chromium CDP Fetch) ---

    def route(
        self,
        pattern: str,
        *,
        status: int | None = None,
        body: str | None = None,
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
        abort: bool = False,
    ) -> RouteRule:
        """Answer requests matching *pattern* locally instead of hitting the network.

        Chromium only (chrome/edge). *pattern* is a Playwright-style URL glob:
        ``**`` crosses ``/``, ``*`` does not, ``{a,b}`` is an alternation.
        ``abort=True`` fails the request instead of answering it. Adding a rule
        for a pattern that already has one replaces it::

            page.route("**/api/users", body='[]', content_type="application/json")
            page.route("**/*.{png,jpg}", abort=True)
        """
        rule = RouteRule(
            pattern=pattern,
            status=status,
            body=body,
            content_type=content_type,
            headers=dict(headers or {}),
            abort=abort,
        )
        self._delegate.route_add(rule.to_dict())
        return rule

    def unroute(self, pattern: str | None = None) -> int:
        """Remove the rule for *pattern* (or every rule). Returns how many went."""
        return self._delegate.route_remove(pattern)

    def routes(self) -> list[RouteRule]:
        """The interception rules installed on this page, in insertion order."""
        return [RouteRule.from_dict(r) for r in self._delegate.route_list()]
```

and add the import next to the other `visus.web.api` imports at the top of the file:

```python
from visus.web.api.route import RouteRule
```

In `src/visus/web/async_api/__init__.py`, add after `set_offline` (`:652-653`):

```python
    # --- request interception (Chromium CDP Fetch) ---

    async def route(
        self,
        pattern: str,
        *,
        status: int | None = None,
        body: str | None = None,
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
        abort: bool = False,
    ) -> RouteRule:
        """Async mirror of :meth:`visus.web.Page.route`."""
        return await asyncio.to_thread(
            lambda: self._p.route(
                pattern,
                status=status,
                body=body,
                content_type=content_type,
                headers=headers,
                abort=abort,
            )
        )

    async def unroute(self, pattern: str | None = None) -> int:
        """Async mirror of :meth:`visus.web.Page.unroute`."""
        return await asyncio.to_thread(lambda: self._p.unroute(pattern))

    async def routes(self) -> list[RouteRule]:
        """Async mirror of :meth:`visus.web.Page.routes`."""
        return await asyncio.to_thread(self._p.routes)
```

with `from visus.web.api.route import RouteRule` added to its import block.

In `tests/test_backend_protocols.py`, add to `_FakePage` after `def set_offline(self, offline): ...` (`:123`):

```python
    def route_add(self, rule): ...

    def route_remove(self, pattern):
        return 0

    def route_list(self):
        return []
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_route.py -m "not browser" -v --no-cov`
Expected: PASS (23 passed)

Run: `uv run pytest tests/test_route.py -m browser -v --no-cov`
Expected: PASS (5 passed)

Run: `uv run pytest tests/test_backend_protocols.py tests/test_async_api_unit.py -q --no-cov`
Expected: PASS

- [ ] **Step 9: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml src/visus/web/backends/selenium/cdp_fetch.py \
        src/visus/web/backends/base.py src/visus/web/backends/selenium/driver_delegate.py \
        src/visus/web/api/page.py src/visus/web/async_api/__init__.py \
        tests/test_route.py tests/test_backend_protocols.py tests/fixtures/route_fetch.html
git commit -m "feat(api): intercept requests with page.route over the CDP Fetch domain"
```

---

### Task 6: `visus route`, `visus unroute`, `visus route-list`

Three daemon ops over the `Page` methods Task 5 produced, plus the CLI, REPL and README rows. This is the surface an agent uses to make a flow deterministic — a 500, a timeout-shaped abort, an empty list — without touching the app.

`route-list` prints the **redacted** rule (`RouteRule.redacted()`, Task 4) so an `Authorization` header handed to a mock never comes back out of the CLI.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:485-489` (below `_op_eval`), and PLAN 4's `_MUTATING_OPS`
- Modify: `src/visus/web/cli/main.py` — three commands after `eval_js` (`:812-830`)
- Modify: `src/visus/web/cli/console.py:19-53` (`_HELP`), `:181-190` (dispatch, next to `eval`)
- Modify: `README.md` (a new **Network mocking** table)
- Test: `tests/test_cli_route.py`

**Interfaces:**
- Consumes: `Page.route` / `unroute` / `routes`, `RouteRule` (Tasks 4-5); `main._send`, `output.emit`, `output.emit_error` (PLAN 4); `SessionHandler.page()` (`session_server.py:121-128`)
- Produces: ops `route`, `unroute`, `route_list`; commands `visus route` / `visus unroute` / `visus route-list`; REPL `route` / `unroute` / `routes`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_route.py`:

```python
"""`visus route` / `unroute` / `route-list`: payload plumbing and REPL twins.

The daemon ops are driven against a fake page that records the calls; their real
behaviour against a live browser is covered by tests/test_route.py.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.api.route import RouteRule
from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


class _RoutingPage:
    """A page that records route calls and answers `routes()` from its own store."""

    def __init__(self) -> None:
        self.rules: list[RouteRule] = []
        self.url = "http://x.test/"

    def route(
        self,
        pattern: str,
        *,
        status: int | None = None,
        body: str | None = None,
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
        abort: bool = False,
    ) -> RouteRule:
        rule = RouteRule(pattern, status, body, content_type, dict(headers or {}), abort)
        self.rules = [r for r in self.rules if r.pattern != pattern]
        self.rules.append(rule)
        return rule

    def unroute(self, pattern: str | None = None) -> int:
        before = len(self.rules)
        self.rules = [] if pattern is None else [r for r in self.rules if r.pattern != pattern]
        return before - len(self.rules)

    def routes(self) -> list[RouteRule]:
        return list(self.rules)


def _handler_with_routing_page() -> session_server.SessionHandler:
    from test_cli_session import _FakeBrowser

    h = session_server.SessionHandler(engine="chrome", headless=True)
    h._browser = _FakeBrowser()  # type: ignore[assignment]
    h._page = _RoutingPage()  # type: ignore[assignment]
    return h


def test_op_route_returns_the_installed_rule() -> None:
    h = _handler_with_routing_page()
    resp = h.handle(
        "route",
        {
            "pattern": "**/api/*",
            "status": 503,
            "body": '{"error":"down"}',
            "content_type": "application/json",
            "headers": {"X-Mock": "1"},
        },
    )
    assert resp["ok"] is True
    rule = resp["result"]["route"]
    assert rule["pattern"] == "**/api/*" and rule["status"] == 503
    assert rule["headers"] == {"X-Mock": "1"}
    assert rule["abort"] is False


def test_op_route_list_redacts_secret_headers() -> None:
    h = _handler_with_routing_page()
    h.handle("route", {"pattern": "**/a", "headers": {"Authorization": "Bearer s3cret"}})
    listed = h.handle("route_list", {})["result"]["routes"]
    assert listed[0]["headers"] == {"Authorization": "REDACTED"}


def test_op_unroute_counts_removals() -> None:
    h = _handler_with_routing_page()
    h.handle("route", {"pattern": "**/a"})
    h.handle("route", {"pattern": "**/b", "abort": True})
    assert h.handle("unroute", {"pattern": "**/a"})["result"] == {"removed": 1}
    assert h.handle("unroute", {})["result"] == {"removed": 1}
    assert h.handle("route_list", {})["result"] == {"routes": []}


def test_op_route_requires_a_pattern() -> None:
    h = _handler_with_routing_page()
    resp = h.handle("route", {})
    assert resp["ok"] is False and "pattern" in resp["error"]


def test_cli_route_builds_the_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(op=op, args=args)
        or {"route": {"pattern": "**/api/*", "status": 404, "abort": False}},
    )
    r = runner.invoke(
        app,
        [
            "route", "**/api/*",
            "--status", "404",
            "--body", '{"x":1}',
            "--content-type", "application/json",
            "--header", "X-A: 1",
            "--header", "X-B: 2",
        ],
    )
    assert r.exit_code == 0, r.output
    assert captured["op"] == "route"
    assert captured["args"] == {
        "pattern": "**/api/*",
        "status": 404,
        "body": '{"x":1}',
        "content_type": "application/json",
        "headers": {"X-A": "1", "X-B": "2"},
        "abort": False,
    }


def test_cli_route_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(args=args)
        or {"route": {"pattern": "**/*.png", "abort": True}},
    )
    r = runner.invoke(app, ["route", "**/*.png", "--abort"])
    assert r.exit_code == 0, r.output
    assert captured["args"]["abort"] is True


def test_cli_route_body_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    payload = tmp_path / "items.json"
    payload.write_text('[{"id":1}]', encoding="utf-8")
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(args=args) or {"route": {}},
    )
    r = runner.invoke(app, ["route", "**/api/*", "--body-file", str(payload)])
    assert r.exit_code == 0, r.output
    assert captured["args"]["body"] == '[{"id":1}]'


def test_cli_route_rejects_a_malformed_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: {"route": {}})
    r = runner.invoke(app, ["route", "**/api/*", "--header", "no-colon-here"])
    assert r.exit_code == 1
    assert "K: V" in r.output or "K: V" in (r.stderr or "")


def test_cli_route_rejects_abort_with_a_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """--abort fails the request; a body would silently be thrown away."""
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: {"route": {}})
    r = runner.invoke(app, ["route", "**/api/*", "--abort", "--body", "x"])
    assert r.exit_code == 1


def test_cli_route_list_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: {
            "routes": [
                {
                    "pattern": "**/api/*",
                    "status": 503,
                    "body": "{}",
                    "content_type": "application/json",
                    "headers": {},
                    "abort": False,
                }
            ]
        },
    )
    r = runner.invoke(app, ["--json", "route-list"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)[0]["pattern"] == "**/api/*"


def test_cli_route_list_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: {"routes": []})
    r = runner.invoke(app, ["route-list"])
    assert r.exit_code == 0 and "no routes" in r.output


def test_cli_unroute(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(op=op, args=args) or {"removed": 2},
    )
    assert "2" in runner.invoke(app, ["unroute"]).output
    assert captured["args"] == {"pattern": None}
    runner.invoke(app, ["unroute", "**/api/*"])
    assert captured["args"] == {"pattern": "**/api/*"}


def test_repl_route_twins() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "route_list":
            return {"routes": [{"pattern": "**/a", "status": 500, "abort": False}]}
        if op == "unroute":
            return {"removed": 1}
        return {"route": {"pattern": args.get("pattern"), "status": 500, "abort": False}}

    assert "**/a" in console.dispatch("route **/a 500", send)
    assert calls[0] == ("route", {"pattern": "**/a", "status": 500})
    assert "**/a" in console.dispatch("routes", send)
    assert "1" in console.dispatch("unroute **/a", send)
    assert calls[-1] == ("unroute", {"pattern": "**/a"})


def test_repl_help_lists_the_route_commands() -> None:
    out = console.dispatch("help", lambda op, args: None)
    for line in ("route ", "unroute", "routes"):
        assert line in out, f"{line!r} missing from the REPL help"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_route.py -v --no-cov`
Expected: FAIL — `test_op_route_returns_the_installed_rule` fails with `assert resp["ok"] is True` because `handle` answers `{"ok": False, "error": "ValueError: unknown op 'route'"}`.

- [ ] **Step 3: Write the daemon ops**

In `src/visus/web/cli/session_server.py`, add after `_op_eval` (`:486-489`):

```python
    # --- request interception (Chromium) ---------------------------------
    def _op_route(self, args: dict[str, Any]) -> dict[str, Any]:
        """Install one interception rule on the session's page."""
        pattern = args.get("pattern")
        if not pattern:
            raise ValueError("route: provide a URL pattern, e.g. '**/api/*'")
        headers = args.get("headers") or {}
        rule = self.page().route(
            str(pattern),
            status=None if args.get("status") is None else int(args["status"]),
            body=None if args.get("body") is None else str(args["body"]),
            content_type=(
                None if args.get("content_type") is None else str(args["content_type"])
            ),
            headers={str(k): str(v) for k, v in dict(headers).items()},
            abort=bool(args.get("abort", False)),
        )
        return {"route": rule.redacted().to_dict()}

    def _op_unroute(self, args: dict[str, Any]) -> dict[str, Any]:
        """Remove one rule (or every rule when no pattern is given)."""
        pattern = args.get("pattern")
        return {"removed": self.page().unroute(None if pattern is None else str(pattern))}

    def _op_route_list(self, args: dict[str, Any]) -> dict[str, Any]:
        """The installed rules, with secret headers redacted before they leave."""
        return {"routes": [r.redacted().to_dict() for r in self.page().routes()]}
```

In PLAN 4's `_MUTATING_OPS` frozenset, add `"route"` and `"unroute"` — installing or removing a rule changes what the page will do next, so the agent should get the `### Page` footer:

```python
    "add_cookies", "clear_cookies", "eval", "route", "unroute",
```

- [ ] **Step 4: Write the CLI commands**

In `src/visus/web/cli/main.py`, add after `eval_js` (`:812-830`):

```python
# ---------------------------------------------------------------------------
# Network mocking (Chromium)
# ---------------------------------------------------------------------------

# Module-level singleton defaults (B008: a call cannot be an inline default).
_ROUTE_HEADER_OPT = typer.Option(
    None, "--header", "-H", help="Response header 'K: V' (repeatable)."
)


def _parse_headers(raw: list[str] | None) -> dict[str, str]:
    """Parse repeated ``--header 'K: V'`` values into a dict."""
    from visus.web.cli import output

    headers: dict[str, str] = {}
    for item in raw or []:
        key, sep, value = item.partition(":")
        if not sep or not key.strip():
            output.emit_error(f"bad --header {item!r} — use the form 'K: V'")
        headers[key.strip()] = value.strip()
    return headers


@app.command()
def route(
    pattern: str = typer.Argument(..., help="URL glob, e.g. '**/api/users' or '**/*.png'."),
    status: int = typer.Option(None, "--status", help="Response status for the mock."),
    body: str = typer.Option(None, "--body", help="Response body text."),
    body_file: str = typer.Option(None, "--body-file", help="Read the body from a file."),
    content_type: str = typer.Option(
        None, "--content-type", help="Response Content-Type, e.g. application/json."
    ),
    header: list[str] = _ROUTE_HEADER_OPT,
    abort: bool = typer.Option(False, "--abort", help="Fail the request instead of mocking it."),
) -> None:
    """Mock or block requests matching a URL glob (Chromium only).

    `**` crosses `/`, `*` does not, `{a,b}` is an alternation, and `?` is literal.
    Re-routing the same pattern replaces the rule.
    """
    from visus.web.cli import output

    if abort and (status is not None or body is not None or body_file is not None):
        output.emit_error("--abort fails the request — it cannot also carry a status or body")
    if body is not None and body_file is not None:
        output.emit_error("pass --body or --body-file, not both")
    payload_body = body
    if body_file is not None:
        # Read on the CLIENT side so the path resolves against the user's cwd.
        payload_body = Path(body_file).read_text(encoding="utf-8")
    args: dict[str, Any] = {
        "pattern": pattern,
        "status": status,
        "body": payload_body,
        "content_type": content_type,
        "headers": _parse_headers(header),
        "abort": abort,
    }
    result = _send("route", args)
    rule = result.get("route", {})
    verb = "aborting" if rule.get("abort") else f"mocking with {rule.get('status') or 200}"
    output.emit(rule, table=f"routed {rule.get('pattern', pattern)} — {verb}")


@app.command()
def unroute(
    pattern: str = typer.Argument(None, help="Pattern to remove (omit = remove every rule)."),
) -> None:
    """Remove an interception rule, or all of them."""
    from visus.web.cli import output

    result = _send("unroute", {"pattern": pattern})
    removed = result.get("removed", 0)
    output.emit(removed, table=f"removed {removed} route(s)")


@app.command("route-list")
def route_list() -> None:
    """List the interception rules installed on the session's page."""
    from visus.web.cli import output

    rules = _send("route_list", {}).get("routes", [])
    if not rules:
        output.emit([], table="no routes")
        return
    from rich import box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=box.ASCII, header_style="bold", pad_edge=False)
    for column in ("PATTERN", "ACTION", "STATUS", "CONTENT-TYPE", "BODY"):
        table.add_column(column, overflow="fold", no_wrap=column == "ACTION")
    for rule in rules:
        body_text = str(rule.get("body") or "")
        table.add_row(
            str(rule.get("pattern", "")),
            "abort" if rule.get("abort") else "fulfill",
            str(rule.get("status") or ""),
            str(rule.get("content_type") or ""),
            body_text if len(body_text) <= 120 else body_text[:117] + "...",
        )
    console_obj = Console()
    with console_obj.capture() as cap:
        console_obj.print(table)
    output.emit(rules, table=cap.get().rstrip("\n"))
```

- [ ] **Step 5: Write the REPL twins**

In `src/visus/web/cli/console.py`, add these branches immediately after the `eval` branch (`:181-182`):

```python
        if cmd == "route":
            args = {"pattern": rest[0]}
            if len(rest) > 1:
                args["status"] = int(rest[1])
            if len(rest) > 2:
                args["body"] = " ".join(rest[2:])
            r = send("route", args)
            rule = r.get("route", {})
            verb = "aborting" if rule.get("abort") else f"mocking with {rule.get('status') or 200}"
            return f"routed {rule.get('pattern', rest[0])} — {verb}"
        if cmd == "unroute":
            r = send("unroute", {"pattern": rest[0] if rest else None})
            return f"removed {r.get('removed', 0)} route(s)"
        if cmd == "routes":
            items = send("route_list", {}).get("routes", [])
            if not items:
                return "(no routes)"
            return "\n".join(
                f"{r.get('pattern', ''):32} "
                f"{'abort' if r.get('abort') else 'fulfill'} {r.get('status') or ''}"
                for r in items
            )
```

and add these `_HELP` lines immediately after the `eval expr` line (`:44`):

```
  route pat [st] [body] mock requests matching pat (Chromium only)
  unroute [pat]        remove one route (omit pat = all)
  routes               list the installed routes
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_route.py -v --no-cov`
Expected: PASS (15 passed)

- [ ] **Step 7: Update the README**

In `README.md`, add a new table immediately after the **Dialogs / cookies / JS** table:

```markdown
### Network mocking *(Chromium only)*

| Command | What it does |
|---|---|
| `visus route <PATTERN> --status <N> --body <T> --body-file <F> --content-type <CT> --header 'K: V' --abort` | Answer matching requests locally, or fail them with `--abort`. |
| `visus unroute [PATTERN]` | Remove one rule, or every rule. |
| `visus route-list [--json]` | List the installed rules (secret headers are redacted). |

Patterns are Playwright-style globs: `**` crosses `/`, `*` does not, `{png,jpg}` is an
alternation, and `?` is literal (URLs use it for the query string). Interception runs on the
CDP `Fetch` domain, so it needs **chrome** or **edge**; on Firefox, stub the API from the page
with `page.add_init_script(...)` instead. `--header` sets *response* headers on the mock — the
real request never leaves the browser, so there is nothing to strip from it.
```

- [ ] **Step 8: Run the gates and commit**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py \
        src/visus/web/cli/console.py tests/test_cli_route.py README.md
git commit -m "feat(cli): add route, unroute and route-list for network mocking"
```

---

### Task 7: The `run-code` opt-in gate (default OFF)

`visus eval` runs JavaScript **in the page** (`main.py:812-830` → `session_server.py:486-489`); `visus run` is `runpy.run_path(script, run_name="__main__")` (`main.py:156-159`) — a separate process with its own browser and no connection to the daemon at all. Neither can touch the live `page` / `context` / `browser`, so the command list is a hard ceiling: `playwright-cli`'s `references/running-code.md` is 241 lines of recipes (geolocation, permissions, media emulation, waits, frames, downloads, clipboard) and two other reference files route their advanced cases through it.

Executing arbitrary Python inside the user's live browser session is a genuine capability change, so the gate lands **before** the capability and the default-OFF path is what gets tested first. A session started without `--allow-run-code` refuses with a message naming the flag; nothing else about it changes.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:84-101` (`__init__`), `:571-589` (`_op_status`), `:697-710` (session payload), `:738-773` (`main`)
- Modify: `src/visus/web/cli/session_client.py` — `start_daemon`'s env block
- Modify: `src/visus/web/cli/main.py` — `session start --allow-run-code`
- Modify: `README.md` (Session table row, env-var table)
- Test: `tests/test_cli_run_code.py`

**Interfaces:**
- Consumes: `SessionHandler.__init__(..., user_data_dir, remote_url, slow_mo)` (PLAN 5 Task 7); `session_client.start_daemon(...)` (PLAN 5 Task 7 + Task 1); `output.emit` / `emit_error` (PLAN 4)
- Produces: `SessionHandler(..., allow_run_code: bool = False)`, `SessionHandler._allow_run_code`, `start_daemon(..., allow_run_code: bool = False)`, env `VISUS_WEB_ALLOW_RUN_CODE`, flag `visus session start --allow-run-code`, `_op_status` key `"allow_run_code"`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_run_code.py`:

```python
"""`visus run-code`: the opt-in gate first, then the execution path.

The gate is the reason this file exists — arbitrary Python against a live browser
session is only safe because the DEFAULT refuses it, so that is what is asserted
before anything can run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


def test_run_code_is_disabled_by_default() -> None:
    """A session started the ordinary way must refuse to execute Python."""
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    assert h._allow_run_code is False
    resp = h.handle("run_code", {"code": "page.title()"})
    assert resp["ok"] is False
    assert "disabled" in resp["error"]
    assert "--allow-run-code" in resp["error"]


def test_run_code_gate_is_not_bypassable_by_an_empty_payload() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    for args in ({}, {"code": ""}, {"code": "   "}):
        resp = h.handle("run_code", args)
        assert resp["ok"] is False and "disabled" in resp["error"], args


def test_status_reports_the_gate() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    off = _handler_with_fake_page(_FakePage())
    assert off.handle("status", {})["result"]["allow_run_code"] is False

    on = _handler_with_fake_page(_FakePage())
    on._allow_run_code = True
    assert on.handle("status", {})["result"]["allow_run_code"] is True


def test_handler_accepts_the_flag() -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True, allow_run_code=True)
    assert h._allow_run_code is True


def test_daemon_main_reads_the_gate_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: dict[str, Any] = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VISUS_WEB_ALLOW_RUN_CODE", "1")
    monkeypatch.setattr(session_server, "SessionHandler", lambda **kw: built.update(kw))
    monkeypatch.setattr(session_server, "serve", lambda handler, **kw: None)
    session_server.main(["chrome", "1", ""])
    assert built["allow_run_code"] is True


def test_daemon_main_gate_defaults_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: dict[str, Any] = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VISUS_WEB_ALLOW_RUN_CODE", raising=False)
    monkeypatch.setattr(session_server, "SessionHandler", lambda **kw: built.update(kw))
    monkeypatch.setattr(session_server, "serve", lambda handler, **kw: None)
    session_server.main(["chrome", "1", ""])
    assert built["allow_run_code"] is False


def test_start_daemon_exports_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, *a: Any, **kw: Any) -> None:
            captured["env"] = kw["env"]

    monkeypatch.setattr(session_client, "find_session", lambda base, name=None: None)
    monkeypatch.setattr(session_client.subprocess, "Popen", _FakePopen)
    with pytest.raises(session_client.SessionError):
        session_client.start_daemon(
            "chrome", True, None, cwd=tmp_path, timeout=0.2, allow_run_code=True
        )
    assert captured["env"]["VISUS_WEB_ALLOW_RUN_CODE"] == "1"


def test_start_daemon_omits_the_gate_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, *a: Any, **kw: Any) -> None:
            captured["env"] = kw["env"]

    monkeypatch.setattr(session_client, "find_session", lambda base, name=None: None)
    monkeypatch.setattr(session_client.subprocess, "Popen", _FakePopen)
    monkeypatch.delenv("VISUS_WEB_ALLOW_RUN_CODE", raising=False)
    with pytest.raises(session_client.SessionError):
        session_client.start_daemon("chrome", True, None, cwd=tmp_path, timeout=0.2)
    assert "VISUS_WEB_ALLOW_RUN_CODE" not in captured["env"]


def test_cli_session_start_passes_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_start(engine: str, headless: bool, url: str | None, **kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"pid": 1, "port": 2}

    monkeypatch.setattr(session_client, "start_daemon", fake_start)
    assert runner.invoke(app, ["session", "start"]).exit_code == 0
    assert captured["allow_run_code"] is False
    assert runner.invoke(app, ["session", "start", "--allow-run-code"]).exit_code == 0
    assert captured["allow_run_code"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_run_code.py -v --no-cov`
Expected: FAIL — `AttributeError: 'SessionHandler' object has no attribute '_allow_run_code'`

- [ ] **Step 3: Write the gate**

In `src/visus/web/cli/session_server.py`, add the parameter to `SessionHandler.__init__` (PLAN 5 Task 7's version) — after `slow_mo: int = 0`:

```python
        allow_run_code: bool = False,
```

and the attribute, after `self._slow_mo = slow_mo`:

```python
        # Arbitrary Python against the LIVE browser is opt-in per session: the
        # daemon holds cookies, logins and a token that authorises file writes,
        # so `run-code` stays off unless the user asked for it at start time.
        self._allow_run_code = allow_run_code
```

In `_op_status`, add to the `info` dict right after `"headless": self._headless,`:

```python
            "allow_run_code": self._allow_run_code,
```

In `serve()`'s session payload, add after `"slow_mo": handler._slow_mo,`:

```python
            "allow_run_code": handler._allow_run_code,
```

In `main()`, read it from env next to the other launch options:

```python
    allow_run_code = os.environ.get("VISUS_WEB_ALLOW_RUN_CODE", "0") not in (
        "0", "", "false", "False", "no"
    )
```

and pass it into the handler construction:

```python
        allow_run_code=allow_run_code,
```

and include it in the startup log line so a session's capabilities are on the record:

```python
        f"slow_mo={slow_mo} allow_run_code={allow_run_code} pid={os.getpid()}"
```

In `src/visus/web/cli/session_client.py`, add `allow_run_code: bool = False` to `start_daemon`'s keyword-only block (after `slow_mo: int = 0`) and this to its env block:

```python
    if allow_run_code:
        env["VISUS_WEB_ALLOW_RUN_CODE"] = "1"
```

In `src/visus/web/cli/main.py`, add the flag to `session_start` (PLAN 5 Task 7's version), after `slow_mo`:

```python
    allow_run_code: bool = typer.Option(
        False,
        "--allow-run-code",
        help="Allow `visus run-code` to execute Python against this live session.",
    ),
```

and pass it through in the `start_daemon(...)` call:

```python
            allow_run_code=allow_run_code,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_run_code.py -v --no-cov`
Expected: PASS (9 passed)

- [ ] **Step 5: Update the README**

In `README.md`, replace the `visus session start` row (as PLAN 5 Task 7 left it) with:

```markdown
| `visus session start [URL] --engine <e> --headless --user-data-dir <dir> --remote-url <url> --slow-mo <ms> --allow-run-code` | Start the persistent browser daemon (headed by default); optionally on a persistent profile, a Selenium Grid, slowed down, or with `run-code` enabled. |
```

and add one env-var row after `VISUS_WEB_SLOW_MO`:

```markdown
| `VISUS_WEB_ALLOW_RUN_CODE` | CLI session | off | `"1"` lets `visus run-code` execute Python in the live session. |
```

- [ ] **Step 6: Run the gates and commit**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/session_client.py \
        src/visus/web/cli/main.py tests/test_cli_run_code.py README.md
git commit -m "feat(cli): gate run-code behind session start --allow-run-code"
```

---

### Task 8: `_op_run_code` and `visus run-code`

With the gate in place (Task 7), this is the escape hatch itself: Python executed with `page`, `context`, `browser` and `expect` bound to the **live** objects. `expect` is already imported in the daemon at `session_server.py:28`, so assertions work with no extra wiring.

Return-value convention: a single expression is evaluated and returned; anything longer is executed and whatever it assigned to `result` is returned. The value is coerced to something `json.dumps` can encode before it goes back over the socket — a `Locator` or a `Page` would otherwise crash the reply.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:485-489` (below the route ops from Task 6), plus PLAN 4's `_MUTATING_OPS`
- Modify: `src/visus/web/cli/main.py` — `visus run-code` next to `eval_js`
- Modify: `src/visus/web/cli/console.py:19-53` (`_HELP`), dispatch
- Modify: `README.md` (Dialogs / cookies / JS table)
- Test: `tests/test_cli_run_code.py`

**Interfaces:**
- Consumes: `SessionHandler._allow_run_code` (Task 7); `expect` (`session_server.py:28`); `SessionHandler.page()` / `context()` (`:121-128`, `:170-182`); `SessionHandler._invalidate_fields` (PLAN 3); `main._send`, `output.emit` (PLAN 4)
- Produces: `session_server._jsonable(value: Any, *, depth: int = 0) -> Any`; op `run_code`; command `visus run-code`; REPL `run-code`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_run_code.py`:

```python
def _enabled_handler() -> session_server.SessionHandler:
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    h._allow_run_code = True
    return h


def test_run_code_evaluates_a_single_expression() -> None:
    h = _enabled_handler()
    assert h.handle("run_code", {"code": "page.title()"})["result"] == {
        "result": "FakeTitle"
    }


def test_run_code_runs_a_script_and_returns_result() -> None:
    h = _enabled_handler()
    code = "\n".join(
        [
            "titles = [page.title() for _ in range(2)]",
            "result = {'titles': titles, 'url': page.url}",
        ]
    )
    resp = h.handle("run_code", {"code": code})
    assert resp["ok"] is True
    assert resp["result"]["result"] == {"titles": ["FakeTitle", "FakeTitle"], "url": "about:blank"}


def test_run_code_binds_every_documented_name() -> None:
    h = _enabled_handler()
    resp = h.handle(
        "run_code",
        {"code": "result = sorted(n for n in ('page','context','browser','expect'))"},
    )
    assert resp["ok"] is True
    code = "result = [type(page).__name__, browser is not None, callable(expect)]"
    got = h.handle("run_code", {"code": code})["result"]["result"]
    assert got[1] is True and got[2] is True


def test_run_code_reports_an_exception_without_killing_the_daemon() -> None:
    h = _enabled_handler()
    resp = h.handle("run_code", {"code": "raise ValueError('boom')"})
    assert resp["ok"] is False
    assert "ValueError: boom" in resp["error"]
    # The handler is still usable.
    assert h.handle("title", {})["result"] == "FakeTitle"


def test_run_code_reports_a_syntax_error_clearly() -> None:
    h = _enabled_handler()
    resp = h.handle("run_code", {"code": "def ("})
    assert resp["ok"] is False and "SyntaxError" in resp["error"]


def test_run_code_rejects_empty_code_once_enabled() -> None:
    h = _enabled_handler()
    resp = h.handle("run_code", {"code": "   "})
    assert resp["ok"] is False and "no code" in resp["error"]


def test_run_code_invalidates_cached_field_indexes() -> None:
    """Arbitrary code may navigate — a cached index must not survive it."""
    h = _enabled_handler()
    h.handle("list_fields", {})
    assert h._fields
    h.handle("run_code", {"code": "result = 1"})
    assert h._fields == [] and h._fields_url is None


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("None", None),
        ("42", 42),
        ("3.5", 3.5),
        ("True", True),
        ("'hi'", "hi"),
        ("[1, 'a', None]", [1, "a", None]),
        ("(1, 2)", [1, 2]),
        ("{'k': [1, {'n': 2}]}", {"k": [1, {"n": 2}]}),
        ("{1: 'a'}", {"1": "a"}),
    ],
)
def test_run_code_return_values_are_json_safe(expression: str, expected: Any) -> None:
    h = _enabled_handler()
    value = h.handle("run_code", {"code": f"result = {expression}"})["result"]["result"]
    assert value == expected
    json.dumps(value)  # the reply must survive the socket


def test_run_code_falls_back_to_repr_for_a_live_object() -> None:
    h = _enabled_handler()
    value = h.handle("run_code", {"code": "result = page"})["result"]["result"]
    assert isinstance(value, str) and "FakePage" in value
    json.dumps(value)


def test_cli_run_code_sends_the_code(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(op=op, args=args) or {"result": "ok"},
    )
    r = runner.invoke(app, ["run-code", "page.title()"])
    assert r.exit_code == 0, r.output
    assert captured == {"op": "run_code", "args": {"code": "page.title()"}}
    assert "ok" in r.output


def test_cli_run_code_reads_a_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = tmp_path / "snippet.py"
    script.write_text("result = page.url\n", encoding="utf-8")
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(args=args) or {"result": "http://x"},
    )
    r = runner.invoke(app, ["run-code", "--file", str(script)])
    assert r.exit_code == 0, r.output
    assert captured["args"]["code"] == "result = page.url\n"


def test_cli_run_code_needs_code_or_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: {"result": None})
    r = runner.invoke(app, ["run-code"])
    assert r.exit_code == 1


def test_cli_run_code_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client, "send", lambda op, args=None, **kw: {"result": {"a": 1}}
    )
    r = runner.invoke(app, ["--json", "run-code", "result = {'a': 1}"])
    assert r.exit_code == 0
    assert json.loads(r.output) == {"a": 1}


def test_repl_run_code_twin() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return {"result": "Dashboard"}

    assert console.dispatch("run-code page.title()", send) == "Dashboard"
    assert calls == [("run_code", {"code": "page.title()"})]


def test_repl_help_lists_run_code() -> None:
    assert "run-code" in console.dispatch("help", lambda op, args: None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_run_code.py -k "evaluates or script or binds or exception or syntax or empty_code or invalidates or json_safe or repr or cli_run_code or repl" -v --no-cov`
Expected: FAIL — `assert resp["ok"] is False` inverted, reported as `{"ok": False, "error": "PermissionError: run-code is disabled..."}`; and `test_cli_run_code_sends_the_code` fails with exit code 2 (`No such command 'run-code'`).

- [ ] **Step 3: Write the op**

In `src/visus/web/cli/session_server.py`, add this module-level helper immediately above `class SessionHandler`:

```python
def _jsonable(value: Any, *, depth: int = 0) -> Any:
    """Coerce a ``run_code`` return value into something ``json.dumps`` accepts.

    A snippet can legitimately return a ``Page``, a ``Locator`` or any other live
    object; those have no JSON form, and an unencodable reply would break the
    socket protocol rather than the snippet. Anything unknown becomes its
    ``repr`` — informative, and always encodable.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if depth >= 6:  # guards a self-referential structure
        return repr(value)
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v, depth=depth + 1) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v, depth=depth + 1) for k, v in value.items()}
    return repr(value)
```

Add the op after `_op_route_list` (Task 6):

```python
    # --- arbitrary python against the live session (opt-in) ---------------
    def _op_run_code(self, args: dict[str, Any]) -> dict[str, Any]:
        """Execute Python with ``page``/``context``/``browser``/``expect`` bound live.

        The escape hatch that turns the command list into a floor instead of a
        ceiling. A single expression is evaluated and returned; a longer snippet is
        executed and whatever it assigned to ``result`` is returned.

        Refused unless the session was started with ``--allow-run-code``: this runs
        anything the caller sends inside a browser holding the user's logins.
        """
        if not self._allow_run_code:
            raise PermissionError(
                "run-code is disabled for this session — it executes arbitrary Python "
                "in your live browser. Restart with "
                "`visus session start --allow-run-code` to enable it."
            )
        code = str(args.get("code") or "")
        if not code.strip():
            raise ValueError("run-code: no code given")
        self._ensure()
        namespace: dict[str, Any] = {
            "page": self.page(),
            "context": self.context(),
            "browser": self._browser,
            "expect": expect,
            "result": None,
        }
        try:
            expression = compile(code, "<visus run-code>", "eval")
        except SyntaxError:
            exec(compile(code, "<visus run-code>", "exec"), namespace, namespace)
            value = namespace.get("result")
        else:
            value = eval(expression, namespace, namespace)
        # The snippet may have navigated, so cached indexes are void either way.
        self._invalidate_fields()
        return {"result": _jsonable(value)}
```

In PLAN 4's `_MUTATING_OPS`, add `"run_code"`:

```python
    "add_cookies", "clear_cookies", "eval", "route", "unroute", "run_code",
```

- [ ] **Step 4: Write the CLI command**

In `src/visus/web/cli/main.py`, add after `eval_js` (`:812-830`):

```python
@app.command("run-code")
def run_code(
    code: str = typer.Argument(
        None, help="Python to run, e.g. 'page.title()' or 'result = page.url'."
    ),
    file: str = typer.Option(None, "--file", "-f", help="Read the code from a file instead."),
) -> None:
    """Run Python against the LIVE session (`page`, `context`, `browser`, `expect`).

    Requires `visus session start --allow-run-code`. A single expression is
    returned directly; a longer snippet returns whatever it assigns to `result`::

        visus run-code "page.set_geolocation(51.5074, -0.1278)"
        visus run-code --file ./snippet.py
    """
    from visus.web.cli import output

    if file is not None:
        # Read on the CLIENT side so the path resolves against the user's cwd.
        source = Path(file).read_text(encoding="utf-8")
    elif code is not None:
        source = code
    else:
        output.emit_error("no code — pass it as an argument or use --file <path>")
    output.emit(_send("run_code", {"code": source}).get("result"))
```

- [ ] **Step 5: Write the REPL twin**

In `src/visus/web/cli/console.py`, add this branch immediately after the `eval` branch:

```python
        if cmd == "run-code":
            return str(send("run_code", {"code": " ".join(rest)}).get("result"))
```

and this `_HELP` line immediately after the `eval expr` line:

```
  run-code code...     run Python against the live session (needs --allow-run-code)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_run_code.py -v --no-cov`
Expected: PASS (33 passed)

- [ ] **Step 7: Verify the gate still holds with the op present**

Run: `uv run pytest tests/test_cli_run_code.py -k "disabled_by_default or not_bypassable or status_reports" -v --no-cov`
Expected: PASS (3 passed) — the default-OFF path is unchanged by the new op.

- [ ] **Step 8: Update the README**

In `README.md`, in the **Dialogs / cookies / JS** table, add after the `visus eval` row:

```markdown
| `visus run-code "<python>"` / `--file <f>` | Run Python against the live session (`page`, `context`, `browser`, `expect`). Needs `session start --allow-run-code`. |
```

and add this note under the same table:

```markdown
`visus eval` runs **JavaScript in the page**; `visus run-code` runs **Python against the live
session objects**, and `visus run <script.py>` runs a script in a *separate* process with its own
browser. `run-code` is the only one that can reach the daemon's page — which is why it is off
until you start the session with `--allow-run-code`.
```

- [ ] **Step 9: Run the gates and commit**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py \
        src/visus/web/cli/console.py tests/test_cli_run_code.py README.md
git commit -m "feat(cli): add run-code to execute Python against the live session"
```

---

### Task 9: `launch(..., debugger_address=)` and `Browser.detach()`

`_ensure` calls `launch(...)` unconditionally (`session_server.py:106`), so every session has to be a browser visus itself started — never the user's already-logged-in Chrome, never a container exposing CDP. Selenium supports attaching through Chromium's `debuggerAddress` experimental option; this task adds it at the engine layer, together with the release path `detach` needs.

`Browser.detach()` deliberately does **not** call `driver.quit()`. Whether ChromeDriver closes a browser it merely attached to has varied across versions, and closing the user's own window is unrecoverable — so the driver *process* is stopped instead, which ends the WebDriver session without ever sending a close command to the browser.

**Files:**
- Modify: `src/visus/web/__init__.py:59-90` (`launch`)
- Modify: `src/visus/web/backends/base.py:137-141` (`BrowserDelegate`), `:152-161` (`Backend`)
- Modify: `src/visus/web/backends/selenium_backend.py:46-91` (`_spawn_driver`), `:154-170` (`dispose`), `:173-193` (`SeleniumBackend.launch`)
- Modify: `src/visus/web/backends/browsers/chrome.py:10-36`, `edge.py:10-36`, `firefox.py:12-21`, `edge_ie.py:25-33`
- Modify: `src/visus/web/api/browser.py:35-36` (`close`)
- Modify: `tests/test_backend_protocols.py:182-189` (`_FakeBrowser`)
- Modify: `tests/test_browsers_chrome.py`, `tests/test_browsers_edge.py`, `tests/test_browsers_firefox.py`, `tests/test_browsers_edge_ie.py`
- Test: `tests/test_cli_attach.py`

**Interfaces:**
- Consumes: `errors.UnsupportedEngineError` (`errors.py:9-10`); `Engine.CHROME` / `Engine.EDGE` (`engine.py:9-12`)
- Produces:
  ```python
  visus.web.launch(engine=Engine.CHROME, *, headless=False, slow_mo=0,
                   user_data_dir=None, remote_url=None,
                   debugger_address: str | None = None) -> Browser
  Browser.detach() -> None
  BrowserDelegate.detach() -> None
  SeleniumBrowserDelegate.detach() -> None
  chrome.build_options(*, headless, download_dir, user_data_dir,
                       debugger_address: str | None = None) -> Options   # same for edge/firefox/edge_ie
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_attach.py`:

```python
"""Attaching to a browser visus did not launch, and releasing it again."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web import errors, launch
from visus.web.backends.browsers import chrome, edge, edge_ie, firefox
from visus.web.cli import session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


def test_chrome_options_attach_and_drop_launch_arguments(tmp_path: Path) -> None:
    """Chrome ignores launch flags when attaching, and chromedriver rejects some."""
    opts = chrome.build_options(
        headless=True,
        download_dir=str(tmp_path),
        user_data_dir=str(tmp_path / "p"),
        debugger_address="127.0.0.1:9222",
    )
    assert opts.experimental_options["debuggerAddress"] == "127.0.0.1:9222"
    assert opts.arguments == []
    assert "prefs" not in opts.experimental_options


def test_edge_options_attach(tmp_path: Path) -> None:
    opts = edge.build_options(
        headless=False,
        download_dir=str(tmp_path),
        user_data_dir=str(tmp_path / "p"),
        debugger_address="localhost:9333",
    )
    assert opts.experimental_options["debuggerAddress"] == "localhost:9333"
    assert opts.arguments == []


def test_chrome_options_unchanged_without_a_debugger_address(tmp_path: Path) -> None:
    opts = chrome.build_options(
        headless=True, download_dir=str(tmp_path), user_data_dir=str(tmp_path / "p")
    )
    assert "--headless=new" in opts.arguments
    assert any(a.startswith("--user-data-dir=") for a in opts.arguments)
    assert "debuggerAddress" not in opts.experimental_options


@pytest.mark.parametrize("module", [firefox, edge_ie])
def test_non_chromium_option_builders_refuse_to_attach(module: Any, tmp_path: Path) -> None:
    with pytest.raises(errors.UnsupportedEngineError, match="chrome or edge"):
        module.build_options(
            headless=True,
            download_dir=str(tmp_path),
            user_data_dir=str(tmp_path / "p"),
            debugger_address="127.0.0.1:9222",
        )


def test_launch_refuses_a_debugger_address_on_a_non_chromium_engine() -> None:
    """Fail before spawning anything, with the engine named."""
    with pytest.raises(errors.UnsupportedEngineError, match="chrome or edge"):
        launch("firefox", debugger_address="127.0.0.1:9222")


class _FakeService:
    def __init__(self) -> None:
        self.stopped = 0

    def stop(self) -> None:
        self.stopped += 1


class _FakeDriver:
    def __init__(self) -> None:
        self.quit_calls = 0
        self.service = _FakeService()

    @property
    def current_window_handle(self) -> str:
        return "CDwindow-1"

    def quit(self) -> None:
        self.quit_calls += 1


def _delegate(tmp_path: Path, driver: _FakeDriver) -> Any:
    from visus.web.backends.base import BrowserConfig
    from visus.web.backends.selenium_backend import SeleniumBrowserDelegate
    from visus.web.engine import Engine

    config = BrowserConfig(
        engine=Engine.CHROME,
        options_factory=lambda **k: None,
        service_factory=lambda: None,
        driver_factory=lambda **k: driver,
    )
    profile = tmp_path / "profile"
    downloads = tmp_path / "downloads"
    profile.mkdir()
    downloads.mkdir()
    return SeleniumBrowserDelegate(
        driver,
        str(profile),
        str(downloads),
        config=config,
        headless=True,
    )


def test_detach_stops_the_driver_process_and_never_quits(tmp_path: Path) -> None:
    """quit() may close a browser visus only attached to — stop the driver instead."""
    driver = _FakeDriver()
    delegate = _delegate(tmp_path, driver)
    delegate.detach()
    assert driver.quit_calls == 0, "detach() closed the user's browser"
    assert driver.service.stopped == 1
    assert not (tmp_path / "downloads").exists()


def test_detach_is_idempotent_and_disables_dispose(tmp_path: Path) -> None:
    driver = _FakeDriver()
    delegate = _delegate(tmp_path, driver)
    delegate.detach()
    delegate.detach()
    delegate.dispose()
    assert driver.quit_calls == 0
    assert driver.service.stopped == 1


def test_dispose_still_quits_a_browser_visus_launched(tmp_path: Path) -> None:
    driver = _FakeDriver()
    delegate = _delegate(tmp_path, driver)
    delegate.dispose()
    assert driver.quit_calls == 1


def test_browser_detach_delegates(tmp_path: Path) -> None:
    from visus.web.api.browser import Browser
    from visus.web.config import Defaults

    calls: list[str] = []

    class _Delegate:
        def new_context(self) -> Any: ...

        def contexts(self) -> list[Any]:
            return []

        def dispose(self) -> None:
            calls.append("dispose")

        def detach(self) -> None:
            calls.append("detach")

    Browser(_Delegate(), Defaults()).detach()  # type: ignore[arg-type]
    assert calls == ["detach"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_attach.py -v --no-cov`
Expected: FAIL — `TypeError: build_options() got an unexpected keyword argument 'debugger_address'`

- [ ] **Step 3: Write the option builders**

In `src/visus/web/backends/browsers/chrome.py`, replace `build_options` (`:10-36`) with:

```python
def build_options(
    *,
    headless: bool,
    download_dir: str,
    user_data_dir: str,
    debugger_address: str | None = None,
) -> Options:
    opts = Options()
    if debugger_address:
        # Attaching to a browser somebody else launched: Chrome ignores every
        # launch argument in this mode (profile, headless, download prefs), and
        # chromedriver rejects a session that mixes them with debuggerAddress.
        # Log capture is also a launch-time capability, so an attached session
        # has no performance/console history — page.network_requests() and
        # page.console_messages() simply stay empty.
        opts.add_experimental_option("debuggerAddress", debugger_address)
        return opts
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument(f"--user-data-dir={user_data_dir}")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-gpu")
    opts.add_experimental_option(
        "prefs",
        {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
        },
    )
    # Performance log feeds page.network_requests(); browser log feeds
    # page.console_messages(). Negligible overhead when never drained.
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    # perfLoggingPrefs enables CDP Network.* events (requestWillBeSent/
    # responseReceived/loadingFinished) so NetworkCapture(use_cdp=True) captures
    # JSONP <script>, sendBeacon, images and document navigations beyond the
    # fetch/XHR JS hook. Must be set at session creation — cannot be turned on later.
    opts.add_experimental_option(
        "perfLoggingPrefs",
        {"enableNetwork": True, "enablePage": False},
    )
    return opts
```

In `src/visus/web/backends/browsers/edge.py`, apply the identical change: the same signature, and the same early-return block at the top of the body (keeping Edge's existing `ms:loggingPrefs` capability in the non-attach path untouched).

In `src/visus/web/backends/browsers/firefox.py`, replace `build_options`'s signature and add the guard as its first statement:

```python
def build_options(
    *,
    headless: bool,
    download_dir: str,
    user_data_dir: str,
    debugger_address: str | None = None,
) -> Options:
    if debugger_address:
        raise UnsupportedEngineError(
            "attaching to a running browser needs chrome or edge — Firefox exposes no "
            "Chrome DevTools Protocol endpoint"
        )
```

with `from visus.web.errors import UnsupportedEngineError` added to its imports.

In `src/visus/web/backends/browsers/edge_ie.py`, apply the same signature and guard, with the message ending `— IE mode is driven by IEDriverServer, which cannot attach`.

- [ ] **Step 4: Write the backend plumbing**

In `src/visus/web/backends/selenium_backend.py`, replace `_spawn_driver`'s signature, docstring and the `options_factory` call (`:46-71`):

```python
def _spawn_driver(
    config: BrowserConfig,
    *,
    headless: bool,
    user_data_dir: str | None = None,
    remote_url: str | None = None,
    debugger_address: str | None = None,
) -> tuple[WebDriver, str, str, bool]:
    """Create a driver with a profile + download dir.

    The profile is a fresh temp dir unless *user_data_dir* names a persistent
    profile to reuse (created if missing, never deleted). With *remote_url*, the
    session is opened on a Selenium Grid / Remote WebDriver instead of spawning
    a local driver (download capture and profile paths are then remote-side).
    With *debugger_address*, the driver ATTACHES to a browser somebody else
    launched: the temp profile is created but never used by that browser, and is
    still removed on dispose.

    Returns (driver, profile_dir, download_dir, owns_profile).
    """
    owns_profile = user_data_dir is None
    if user_data_dir is not None:
        os.makedirs(user_data_dir, exist_ok=True)
        profile_dir = user_data_dir
    else:
        profile_dir = tempfile.mkdtemp(prefix="visus-web-")
    download_dir = tempfile.mkdtemp(prefix="visus-dl-")
    options = config.options_factory(
        headless=headless,
        download_dir=download_dir,
        user_data_dir=profile_dir,
        debugger_address=debugger_address,
    )
```

Replace `SeleniumBackend.launch` (`:173-193`) with:

```python
class SeleniumBackend:
    def launch(
        self,
        config: BrowserConfig,
        *,
        headless: bool,
        user_data_dir: str | None = None,
        remote_url: str | None = None,
        debugger_address: str | None = None,
    ) -> SeleniumBrowserDelegate:
        driver, profile_dir, download_dir, owns_profile = _spawn_driver(
            config,
            headless=headless,
            user_data_dir=user_data_dir,
            remote_url=remote_url,
            debugger_address=debugger_address,
        )
        return SeleniumBrowserDelegate(
            driver,
            profile_dir,
            download_dir,
            config=config,
            headless=headless,
            owns_profile=owns_profile,
            remote_url=remote_url,
            attached=debugger_address is not None,
        )
```

In `SeleniumBrowserDelegate.__init__`, add `attached: bool = False` to the keyword-only parameters and `self._attached = attached` beside the other assignments. Add this method immediately after `dispose()`:

```python
    def detach(self) -> None:
        """End the WebDriver session WITHOUT closing the browser.

        ``driver.quit()`` is deliberately not called: whether ChromeDriver closes a
        browser it merely ATTACHED to has varied between versions, and closing the
        user's own window is unrecoverable. Stopping the local driver PROCESS ends
        the session just as surely and never sends a close command to the browser.
        Temp dirs this delegate owns are still cleaned; a user-supplied persistent
        profile is never touched.
        """
        if self._disposed:
            return
        self._disposed = True
        atexit.unregister(self._atexit_cleanup)
        for ctx in list(self._contexts):
            if ctx.owns_driver:
                ctx.close()
        service = getattr(self._driver, "service", None)
        stop = getattr(service, "stop", None)
        if callable(stop):
            try:
                stop()
            except Exception:
                pass
        if self._owns_profile:
            shutil.rmtree(self._profile_dir, ignore_errors=True)
        shutil.rmtree(self._download_dir, ignore_errors=True)
```

In `src/visus/web/backends/base.py`, extend the two protocols:

```python
@runtime_checkable
class BrowserDelegate(Protocol):
    def new_context(self) -> ContextDelegate: ...
    def contexts(self) -> list[ContextDelegate]: ...
    def dispose(self) -> None: ...
    def detach(self) -> None: ...
```

```python
@runtime_checkable
class Backend(Protocol):
    def launch(
        self,
        config: BrowserConfig,
        *,
        headless: bool,
        user_data_dir: str | None = None,
        remote_url: str | None = None,
        debugger_address: str | None = None,
    ) -> BrowserDelegate: ...
```

In `src/visus/web/api/browser.py`, add after `close()` (`:35-36`):

```python
    def detach(self) -> None:
        """Release the browser without closing it (attached sessions).

        Use instead of :meth:`close` when visus did not launch this browser: the
        WebDriver session ends, the browser window stays exactly as the user left
        it.
        """
        self._delegate.detach()
```

In `src/visus/web/__init__.py`, replace `launch` (`:59-90`) with:

```python
def launch(
    engine: Engine | str = Engine.CHROME,
    *,
    headless: bool = False,
    slow_mo: int = 0,
    user_data_dir: str | None = None,
    remote_url: str | None = None,
    debugger_address: str | None = None,
) -> Browser:
    """Launch a browser and return a Browser handle.

    *slow_mo* delays every action/navigation by the given milliseconds — handy
    to watch a script drive the page in real time.

    *user_data_dir* reuses (or creates) a persistent browser profile instead of
    a throwaway temp profile — cookies, localStorage and logins survive across
    runs. The directory is never deleted by visus.

    *remote_url* opens the session on a Selenium Grid / Remote WebDriver
    (e.g. ``"http://grid:4444/wd/hub"``) instead of spawning a local browser.

    *debugger_address* (``"host:port"``, chrome/edge only) ATTACHES to a browser
    that is already running with remote debugging enabled instead of launching
    one — the user's own logged-in window, or a container exposing CDP. Release
    it with :meth:`Browser.detach`; :meth:`Browser.close` would end the browser
    along with the session.

    Usage:
        with launch(headless=True) as browser:
            page = browser.new_page()
            page.goto("https://example.com")
    """
    resolved = Engine.from_str(engine)
    if debugger_address is not None and resolved not in (Engine.CHROME, Engine.EDGE):
        raise errors.UnsupportedEngineError(
            f"attaching to a running browser needs chrome or edge, not {resolved.value!r}"
        )
    config = get_browser_config(resolved)
    backend = SeleniumBackend()
    delegate = backend.launch(
        config,
        headless=headless,
        user_data_dir=user_data_dir,
        remote_url=remote_url,
        debugger_address=debugger_address,
    )
    return Browser(delegate, Defaults(slow_mo_ms=slow_mo))
```

- [ ] **Step 5: Repair the protocol fake and the option-builder tests**

In `tests/test_backend_protocols.py`, add to `_FakeBrowser` (`:182-189`):

```python
    def detach(self): ...
```

In `tests/test_browsers_chrome.py`, `tests/test_browsers_edge.py`, `tests/test_browsers_firefox.py` and `tests/test_browsers_edge_ie.py`, no call sites change — every existing call passes `headless` / `download_dir` / `user_data_dir` by keyword and `debugger_address` defaults to `None`. Run them to confirm rather than editing them.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_attach.py -v --no-cov`
Expected: PASS (11 passed)

Run: `uv run pytest tests/test_browsers_chrome.py tests/test_browsers_edge.py tests/test_browsers_firefox.py tests/test_browsers_edge_ie.py tests/test_backend_protocols.py tests/test_selenium_backend_protocol.py -q --no-cov`
Expected: PASS

- [ ] **Step 7: Prove a real launch is unaffected**

Run: `uv run pytest tests/test_e2e_launch.py -v --no-cov`
Expected: PASS — the default path still spawns a browser with its own profile.

- [ ] **Step 8: Run the gates and commit**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

```bash
git add src/visus/web/__init__.py src/visus/web/api/browser.py src/visus/web/backends/base.py \
        src/visus/web/backends/selenium_backend.py src/visus/web/backends/browsers/chrome.py \
        src/visus/web/backends/browsers/edge.py src/visus/web/backends/browsers/firefox.py \
        src/visus/web/backends/browsers/edge_ie.py tests/test_cli_attach.py \
        tests/test_backend_protocols.py
git commit -m "feat(api): attach to a running Chromium via debugger_address and detach cleanly"
```

---

### Task 10: `visus session attach --cdp` and `visus session detach`

`session stop` always closes the browser (`session_server.py:591-593` → `serve()`'s `finally` at `:726-727`). For a session visus launched that is right; for one it *attached to* it destroys the user's window. This task adds both halves: a start path that attaches, and a stop path that releases.

Following the brief, `detach` sets a flag that makes `serve()`'s `finally` skip `handler.close()` — it calls `handler.release()` instead, which goes through `Browser.detach()` (Task 9) rather than leaving an orphaned driver process behind.

Unlike playwright-cli, `attach` does **not** rename the session after the channel: the name comes from `--session` / `-S` / `VISUS_WEB_SESSION` exactly as it does for `start`, so one rule covers every command. The README row says so.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:84-119` (`__init__` / `_ensure`), `:162-168` (`close`), `:571-593` (`_op_status`, new `_op_detach`), `:674-735` (`serve`'s `finally`), `:738-773` (`main`)
- Modify: `src/visus/web/cli/session_client.py` — `start_daemon`'s env block
- Modify: `src/visus/web/cli/main.py` — `session attach`, `session detach`
- Modify: `src/visus/web/cli/console.py` — no REPL twin (see below)
- Modify: `README.md` (Session & lifecycle table, env-var table)
- Test: `tests/test_cli_attach.py`

**Interfaces:**
- Consumes: `launch(..., debugger_address=)`, `Browser.detach()` (Task 9); `SessionHandler.bind_stop` / `_stop` (PLAN 3 Task 7); `SessionHandler._invalidate_fields` (PLAN 3 Task 1); `session_client.session_name` (Task 1); `output.emit` / `emit_error` (PLAN 4)
- Produces: `SessionHandler(..., debugger_address: str | None = None)`, `SessionHandler.detach()` / `detached()` / `release()`, op `detach`, env `VISUS_WEB_DEBUGGER_ADDRESS`, commands `visus session attach --cdp <host:port>` and `visus session detach`, `_op_status` key `"attached"`

`session attach` / `detach` get **no REPL twin**: the REPL runs *inside* a session, and both commands are session-lifecycle operations that would terminate the REPL's own connection. `visus session start`/`stop` have no REPL twin for the same reason.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_attach.py`:

```python
def test_handler_forwards_the_debugger_address(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class _Page:
        def goto(self, url: str) -> None: ...

    class _Browser:
        def new_page(self) -> _Page:
            return _Page()

        def close(self) -> None: ...

        def detach(self) -> None: ...

    def fake_launch(engine: Any, **kwargs: Any) -> _Browser:
        seen.update(kwargs)
        return _Browser()

    monkeypatch.setattr(session_server, "launch", fake_launch)
    h = session_server.SessionHandler(
        engine="chrome", headless=False, debugger_address="127.0.0.1:9222"
    )
    h._ensure()
    assert seen["debugger_address"] == "127.0.0.1:9222"
    assert h._attached is True


def test_handler_is_not_attached_by_default() -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True)
    assert h._attached is False
    assert h.detached() is False


def test_status_reports_attached() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    h._attached = True
    assert h.handle("status", {})["result"]["attached"] is True


def test_op_detach_refuses_on_a_launched_session() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    resp = h.handle("detach", {})
    assert resp["ok"] is False
    assert "session attach" in resp["error"] and "session stop" in resp["error"]
    assert h.detached() is False


def test_op_detach_flags_the_session_and_sets_the_stop_event() -> None:
    import threading as _threading

    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    h._attached = True
    stop = _threading.Event()
    h.bind_stop(stop)
    resp = h.handle("detach", {})
    assert resp["ok"] is True
    assert "stays open" in resp["result"]
    assert h.detached() is True
    assert stop.is_set()


def test_release_detaches_the_browser_instead_of_closing_it() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    calls: list[str] = []

    class _Browser:
        @property
        def contexts(self) -> list[Any]:
            return []

        def close(self) -> None:
            calls.append("close")

        def detach(self) -> None:
            calls.append("detach")

    h = _handler_with_fake_page(_FakePage())
    h._browser = _Browser()  # type: ignore[assignment]
    h.release()
    assert calls == ["detach"]
    assert h._browser is None and h._page is None
    assert h._fields == [] and h._fields_url is None


def test_serve_releases_instead_of_closing_a_detached_session(tmp_path: Path) -> None:
    """The brief's contract: serve()'s finally must SKIP handler.close()."""
    import json as _json
    import socket as _socket
    import threading as _threading
    import time as _time

    from test_cli_session import _FakePage, _handler_with_fake_page

    calls: list[str] = []
    handler = _handler_with_fake_page(_FakePage())
    handler._attached = True

    class _Browser:
        @property
        def contexts(self) -> list[Any]:
            return []

        def close(self) -> None:
            calls.append("close")

        def detach(self) -> None:
            calls.append("detach")

    handler._browser = _Browser()  # type: ignore[assignment]

    t = _threading.Thread(
        target=session_server.serve,
        kwargs={"handler": handler, "token": "tok", "cwd": tmp_path},
        daemon=True,
    )
    t.start()
    sf = session_server.session_file(tmp_path)
    for _ in range(200):
        if sf.is_file():
            break
        _time.sleep(0.02)
    port = int(_json.loads(sf.read_text(encoding="utf-8"))["port"])

    with _socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        f = sock.makefile("rwb")
        f.write((_json.dumps({"token": "tok", "op": "detach"}) + "\n").encode("utf-8"))
        f.flush()
        assert _json.loads(f.readline().decode("utf-8"))["ok"] is True

    t.join(timeout=20)
    assert not t.is_alive(), "detach did not stop the daemon"
    assert calls == ["detach"], f"the browser was closed on detach: {calls}"
    assert not sf.is_file()


def test_daemon_main_reads_the_debugger_address_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: dict[str, Any] = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VISUS_WEB_DEBUGGER_ADDRESS", "127.0.0.1:9222")
    monkeypatch.setattr(session_server, "SessionHandler", lambda **kw: built.update(kw))
    monkeypatch.setattr(session_server, "serve", lambda handler, **kw: None)
    session_server.main(["chrome", "0", ""])
    assert built["debugger_address"] == "127.0.0.1:9222"


def test_start_daemon_exports_the_debugger_address(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, *a: Any, **kw: Any) -> None:
            captured["env"] = kw["env"]

    monkeypatch.setattr(session_client, "find_session", lambda base, name=None: None)
    monkeypatch.setattr(session_client.subprocess, "Popen", _FakePopen)
    with pytest.raises(session_client.SessionError):
        session_client.start_daemon(
            "chrome", False, None, cwd=tmp_path, timeout=0.2, debugger_address="h:9222"
        )
    assert captured["env"]["VISUS_WEB_DEBUGGER_ADDRESS"] == "h:9222"


def test_cli_session_attach(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_start(engine: str, headless: bool, url: str | None, **kwargs: Any) -> dict[str, Any]:
        captured.update(engine=engine, headless=headless, url=url, **kwargs)
        return {"pid": 3, "port": 4}

    monkeypatch.setattr(session_client, "start_daemon", fake_start)
    r = runner.invoke(app, ["session", "attach", "--cdp", "127.0.0.1:9222"])
    assert r.exit_code == 0, r.output
    assert captured["debugger_address"] == "127.0.0.1:9222"
    assert captured["headless"] is False
    assert "attached" in r.output


def test_cli_session_attach_accepts_a_url_form(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--cdp http://localhost:9222` is what a container prints — accept it."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(kw) or {"pid": 1, "port": 2},
    )
    r = runner.invoke(app, ["session", "attach", "--cdp", "http://localhost:9222"])
    assert r.exit_code == 0, r.output
    assert captured["debugger_address"] == "localhost:9222"


def test_cli_session_attach_refuses_a_non_chromium_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_client, "start_daemon", lambda *a, **kw: {"pid": 1, "port": 2})
    r = runner.invoke(
        app, ["session", "attach", "--cdp", "127.0.0.1:9222", "--engine", "firefox"]
    )
    assert r.exit_code == 1


def test_cli_session_detach(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(op=op) or "detached — the browser stays open",
    )
    r = runner.invoke(app, ["session", "detach"])
    assert r.exit_code == 0, r.output
    assert captured["op"] == "detach"
    assert "stays open" in r.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_attach.py -k "debugger or attached or detach or release or serve_releases" -v --no-cov`
Expected: FAIL — `TypeError: SessionHandler.__init__() got an unexpected keyword argument 'debugger_address'`

- [ ] **Step 3: Write the handler side**

In `src/visus/web/cli/session_server.py`, add to `SessionHandler.__init__` — the parameter after `allow_run_code: bool = False`:

```python
        debugger_address: str | None = None,
```

and the attributes after `self._allow_run_code = allow_run_code`:

```python
        self._debugger_address = debugger_address
        # True when the browser belongs to somebody else: closing it would destroy
        # the user's own window, so only `detach` may end such a session.
        self._attached = debugger_address is not None
        self._detached = False
```

In `_ensure()`, add `debugger_address=self._debugger_address,` to the `launch(...)` call PLAN 5 Task 7 produced.

Replace `close()` (PLAN 3 Task 1's version) and add the release path immediately after it:

```python
    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        self._browser = None
        self._context = None
        self._page = None
        self._invalidate_fields()

    def detach(self) -> None:
        """Mark this session for release — ``serve()`` must not close the browser."""
        self._detached = True

    def detached(self) -> bool:
        """True once :meth:`detach` was called (read by ``serve()``'s teardown)."""
        return self._detached

    def release(self) -> None:
        """Drop the browser WITHOUT closing it (see :meth:`visus.web.Browser.detach`)."""
        if self._browser is not None:
            self._browser.detach()
        self._browser = None
        self._context = None
        self._page = None
        self._invalidate_fields()
```

Add to `_op_status`'s `info` dict, after `"allow_run_code": self._allow_run_code,`:

```python
            "attached": self._attached,
```

Add the op immediately before `_op_shutdown` (`:591-593`):

```python
    def _op_detach(self, args: dict[str, Any]) -> str:
        """End the session while leaving an ATTACHED browser exactly as it is."""
        if not self._attached:
            raise RuntimeError(
                "detach only works on a session created by `visus session attach` — "
                "use `visus session stop` to close a browser visus launched"
            )
        self.detach()
        if self._stop is not None:
            self._stop.set()
        return "detached — the browser stays open"
```

In `serve()`'s `finally` (PLAN 3 Task 9's version), replace the bare `handler.close()` with:

```python
        if handler.detached():
            # An attached browser belongs to the user: end the WebDriver session,
            # never the window.
            handler.release()
        else:
            handler.close()
```

In `main()`, read the address from env beside the other launch options and pass it to the handler:

```python
    debugger_address = os.environ.get("VISUS_WEB_DEBUGGER_ADDRESS") or None
```

```python
        debugger_address=debugger_address,
```

In `src/visus/web/cli/session_client.py`, add `debugger_address: str | None = None` to `start_daemon`'s keyword-only block and to its env block:

```python
    if debugger_address:
        env["VISUS_WEB_DEBUGGER_ADDRESS"] = debugger_address
```

- [ ] **Step 4: Write the CLI commands**

In `src/visus/web/cli/main.py`, add after `session_stop` (`:255-261`):

```python
def _cdp_address(raw: str) -> str:
    """Normalise ``--cdp`` to ``host:port``.

    A container or `chrome://inspect` prints ``http://localhost:9222``; Selenium's
    ``debuggerAddress`` wants the bare authority, so both forms are accepted.
    """
    value = raw.strip()
    for prefix in ("http://", "https://", "ws://", "wss://"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    return value.rstrip("/")


@session_app.command("attach")
def session_attach(
    cdp: str = typer.Option(
        ..., "--cdp", help="DevTools address, e.g. 127.0.0.1:9222 or http://localhost:9222."
    ),
    url: str = typer.Argument(None, help="Optional URL to navigate the attached tab to."),
    engine: str = typer.Option("chrome", "--engine", "-e", help="chrome | edge."),
) -> None:
    """Attach the session to a browser that is ALREADY running (chrome/edge).

    Start the target browser with remote debugging enabled — in Chrome/Edge,
    visit `chrome://inspect/#remote-debugging` and tick "Allow remote debugging
    for this browser instance", or launch it with `--remote-debugging-port=9222`.

    The session name comes from `--session` / `-S` / `VISUS_WEB_SESSION`, exactly
    as it does for `session start`. End it with `visus session detach` — a plain
    `stop` would close a window that is not yours to close.
    """
    from visus.web.cli import output, session_client

    if engine not in ("chrome", "edge"):
        output.emit_error(
            f"attaching needs chrome or edge, not {engine!r} — no other engine "
            "exposes the Chrome DevTools Protocol"
        )
    try:
        info = session_client.start_daemon(
            engine, False, url, debugger_address=_cdp_address(cdp)
        )
    except session_client.SessionError as exc:
        output.emit_error(str(exc))
    output.emit(
        info,
        table=(
            f"attached to {_cdp_address(cdp)} "
            f"(pid {info['pid']}, port {info['port']}, engine {engine})"
        ),
    )


@session_app.command("detach")
def session_detach() -> None:
    """End an attached session, leaving the browser open (`attach` sessions only)."""
    from visus.web.cli import output

    output.emit(_send("detach", {}))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_attach.py -v --no-cov`
Expected: PASS (24 passed)

Run: `uv run pytest tests/test_cli_session.py tests/test_cli_sessions_named.py -q --no-cov`
Expected: PASS — `serve()`'s teardown is unchanged for every non-detached session.

- [ ] **Step 6: Update the README**

In `README.md`, in the **Session & lifecycle** table, add after the `visus session stop` row:

```markdown
| `visus session attach --cdp <host:port> [URL] --engine <chrome\|edge>` | Attach to a browser that is already running (your logged-in Chrome, or a container exposing CDP). |
| `visus session detach` | End an attached session and leave the browser open (`attach` sessions only). |
```

and one env-var row after `VISUS_WEB_ALLOW_RUN_CODE`:

```markdown
| `VISUS_WEB_DEBUGGER_ADDRESS` | CLI session | — | Attach to this DevTools address instead of launching a browser. |
```

Add this note under the same table:

```markdown
An attached session has no performance/console log history: those are enabled when a browser is
*launched*, which visus did not do. `visus requests` and `visus logs` therefore stay empty on an
attached session — everything else works normally. Unlike `playwright-cli`, `attach` does not
rename the session after the browser channel; the name always comes from `--session` / `-S`.
```

- [ ] **Step 7: Run the gates and commit**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/session_client.py \
        src/visus/web/cli/main.py tests/test_cli_attach.py README.md
git commit -m "feat(cli): add session attach --cdp and session detach"
```

---

### Task 11: `visus drop` — drag a file or payload onto a dropzone

`visus drag` (`main.py:626-648`) moves one element onto another; `visus upload` (`:656-672`) sets files on an `<input type=file>`. Neither reaches the third case: a dropzone with **no** `<input type=file>`, which expects a `DragEvent` carrying a `DataTransfer` from outside the page. Those components are currently unautomatable.

The file is read on the CLIENT (so the path resolves against the user's cwd, matching `session-screenshot` at `main.py:440-442` and `upload` at `:670-671`), base64-encoded, and rebuilt as a real `File` inside the page.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:351-368` (beside `_op_drag` / `_op_upload`), plus PLAN 4's `_MUTATING_OPS`
- Modify: `src/visus/web/cli/main.py:626-648` (after `drag`)
- Modify: `src/visus/web/cli/console.py:19-53` (`_HELP`), dispatch
- Modify: `README.md` (Actions table)
- Create: `tests/fixtures/dropzone.html`
- Test: `tests/test_cli_drop_upload.py`

**Interfaces:**
- Consumes: `SessionHandler._target(args)` (`session_server.py:205-221`); `Locator.evaluate(expression, arg)` (`api/locator.py:439-440`, which passes `(el, arg)` — see `driver_delegate.py:533-544`); `main._target_args` (`main.py:222-235`); `output.emit` / `emit_error` (PLAN 4)
- Produces: `session_server._DROP_JS`, op `drop`, command `visus drop`, REPL `drop`

- [ ] **Step 1: Write the fixture page**

Create `tests/fixtures/dropzone.html` with exactly this content:

```html
<!doctype html>
<html>
  <head><title>dropzone fixture</title></head>
  <body>
    <!-- Deliberately NO <input type=file>: this is the component `upload`
         cannot reach, and the only way in is a DragEvent carrying a
         DataTransfer built outside the page. -->
    <div id="zone" style="width:220px;height:120px;border:2px dashed #888">Drop here</div>
    <pre id="out">idle</pre>
    <script>
      var zone = document.getElementById('zone');
      var out = document.getElementById('out');
      function swallow(e) { e.preventDefault(); e.stopPropagation(); }
      zone.addEventListener('dragenter', swallow);
      zone.addEventListener('dragover', swallow);
      zone.addEventListener('drop', function (e) {
        swallow(e);
        var dt = e.dataTransfer;
        var files = Array.prototype.map.call(dt.files, function (f) {
          return f.name + ':' + f.size + ':' + f.type;
        });
        out.textContent = JSON.stringify({ files: files, text: dt.getData('text/plain') });
      });
    </script>
  </body>
</html>
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_cli_drop_upload.py`:

```python
"""`visus drop` and the target-free `visus upload`.

Both close a gap that only shows up against a real DOM, so each has a browser
test; the argument plumbing is asserted separately with a recording fake.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web import expect, launch
from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


@pytest.mark.browser
def test_drop_delivers_a_file_to_a_zone_with_no_file_input(
    base_url: str, tmp_path: Path
) -> None:
    payload = tmp_path / "report.csv"
    payload.write_text("a,b\n1,2\n", encoding="utf-8")

    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/dropzone.html"
    )
    try:
        import base64 as _base64

        resp = h.handle(
            "drop",
            {
                "selector": "#zone",
                "file": {
                    "name": "report.csv",
                    "type": "text/csv",
                    "b64": _base64.b64encode(payload.read_bytes()).decode("ascii"),
                },
            },
        )
        assert resp["ok"] is True, resp
        assert resp["result"]["dropped"]["files"] == 1

        out = json.loads(h.handle("get_text", {"selector": "#out"})["result"]["value"])
        assert out["files"] == ["report.csv:8:text/csv"], out
    finally:
        h.close()


@pytest.mark.browser
def test_drop_delivers_plain_text(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/dropzone.html"
    )
    try:
        resp = h.handle("drop", {"selector": "#zone", "data": "hello dropzone"})
        assert resp["ok"] is True, resp
        out = json.loads(h.handle("get_text", {"selector": "#out"})["result"]["value"])
        assert out["text"] == "hello dropzone"
        assert out["files"] == []
    finally:
        h.close()


def test_op_drop_requires_a_payload() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    resp = h.handle("drop", {"selector": "#zone"})
    assert resp["ok"] is False
    assert "--path" in resp["error"] and "--data" in resp["error"]


def test_cli_drop_reads_the_file_client_side(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import base64 as _base64

    payload = tmp_path / "logo.png"
    payload.write_bytes(b"\x89PNG\r\n\x1a\n")
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(op=op, args=args)
        or {"dropped": {"files": 1, "types": ["Files"]}},
    )
    r = runner.invoke(app, ["drop", "--selector", "#zone", "--path", str(payload)])
    assert r.exit_code == 0, r.output
    assert captured["op"] == "drop"
    assert captured["args"]["file"]["name"] == "logo.png"
    assert captured["args"]["file"]["type"] == "image/png"
    assert _base64.b64decode(captured["args"]["file"]["b64"]) == b"\x89PNG\r\n\x1a\n"


def test_cli_drop_sends_data_and_type(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(args=args) or {"dropped": {"files": 0}},
    )
    r = runner.invoke(
        app,
        ["drop", "3", "--data", '{"id":1}', "--data-type", "application/json"],
    )
    assert r.exit_code == 0, r.output
    assert captured["args"]["index"] == 3
    assert captured["args"]["data"] == '{"id":1}'
    assert captured["args"]["data_type"] == "application/json"


def test_cli_drop_needs_a_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: {"dropped": {}})
    r = runner.invoke(app, ["drop", "--selector", "#zone"])
    assert r.exit_code == 1


def test_cli_drop_rejects_both_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: {"dropped": {}})
    r = runner.invoke(app, ["drop", "--selector", "#z", "--path", "a", "--data", "b"])
    assert r.exit_code == 1


def test_repl_drop_twin() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return {"dropped": {"files": 0, "types": ["text/plain"]}}

    out = console.dispatch("drop 2 hello there", send)
    assert calls == [("drop", {"index": 2, "data": "hello there"})]
    assert "dropped" in out


def test_repl_help_lists_drop() -> None:
    assert "drop" in console.dispatch("help", lambda op, args: None)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_drop_upload.py -m "not browser" -v --no-cov`
Expected: FAIL — `test_op_drop_requires_a_payload` fails because `handle` answers `{"ok": False, "error": "ValueError: unknown op 'drop'"}` with the wrong message, and `test_cli_drop_reads_the_file_client_side` exits 2 (`No such command 'drop'`).

- [ ] **Step 4: Write the op**

In `src/visus/web/cli/session_server.py`, add this module-level constant immediately above `class SessionHandler` (beside `_jsonable` from Task 8):

```python
# Locator.evaluate calls the expression as (element, arg) — see
# SeleniumPageDelegate.locator_evaluate. A DataTransfer is built here rather
# than in Python because a File object cannot cross the WebDriver boundary.
_DROP_JS = r"""(el, a) => {
  const dt = new DataTransfer();
  if (a.file) {
    const bin = atob(a.file.b64);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    dt.items.add(new File([arr], a.file.name,
                          {type: a.file.type || 'application/octet-stream'}));
  }
  if (a.data !== null && a.data !== undefined) {
    dt.setData(a.dataType || 'text/plain', a.data);
  }
  const init = {bubbles: true, cancelable: true, composed: true, dataTransfer: dt};
  for (const type of ['dragenter', 'dragover', 'drop']) {
    el.dispatchEvent(new DragEvent(type, init));
  }
  return {files: dt.files.length, types: Array.from(dt.types)};
}"""
```

Add the op immediately after `_op_drag` (`:351-363`):

```python
    def _op_drop(self, args: dict[str, Any]) -> dict[str, Any]:
        """Drop a file or a data payload onto the target from OUTSIDE the page.

        The case neither ``drag`` nor ``upload`` covers: a dropzone with no
        ``<input type=file>`` only reacts to a ``DragEvent`` carrying a
        ``DataTransfer``, which nothing on the page can produce.
        """
        file = args.get("file")
        data = args.get("data")
        if file is None and data is None:
            raise ValueError("drop: provide a payload — --path <file> or --data <text>")
        payload = {
            "file": file,
            "data": data,
            "dataType": args.get("data_type") or "text/plain",
        }
        result = self._target(args).evaluate(_DROP_JS, payload)
        return {"dropped": result}
```

In PLAN 4's `_MUTATING_OPS`, add `"drop"` next to `"drag"`:

```python
    "hover", "focus", "clear_input", "drag", "drop", "upload", "goto", "back",
```

- [ ] **Step 5: Write the CLI command**

In `src/visus/web/cli/main.py`, add after `drag` (`:626-648`):

```python
@app.command()
def drop(
    index: int = typer.Argument(None, help="Dropzone field index from the last list-fields."),
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
    path: str = typer.Option(None, "--path", help="File to drop onto the target."),
    data: str = typer.Option(None, "--data", help="Text payload to drop instead of a file."),
    data_type: str = typer.Option(
        "text/plain", "--data-type", help="MIME type for --data (default text/plain)."
    ),
) -> None:
    """Drop a file or a payload onto an element from outside the page.

    For dropzones with no `<input type=file>`, which `visus upload` cannot reach::

        visus drop --selector "#zone" --path ./report.csv
        visus drop 4 --data '{"id":1}' --data-type application/json
    """
    import base64
    import mimetypes

    from visus.web.cli import output

    if path is None and data is None:
        output.emit_error("nothing to drop — pass --path <file> or --data <text>")
    if path is not None and data is not None:
        output.emit_error("pass --path or --data, not both")
    args = _target_args(index, selector, role, name, text)
    if path is not None:
        # Read on the CLIENT side so the path resolves against the user's cwd.
        source = Path(path)
        args["file"] = {
            "name": source.name,
            "type": mimetypes.guess_type(source.name)[0] or "application/octet-stream",
            "b64": base64.b64encode(source.read_bytes()).decode("ascii"),
        }
    else:
        args["data"] = data
        args["data_type"] = data_type
    result = _send("drop", args).get("dropped", {})
    output.emit(
        result,
        table=f"dropped {result.get('files', 0)} file(s), types {result.get('types', [])}",
    )
```

- [ ] **Step 6: Write the REPL twin**

In `src/visus/web/cli/console.py`, add this branch immediately after the `clear-input` branch (`:137-138`):

```python
        if cmd == "drop":
            r = send("drop", {**_idx(rest[0]), "data": " ".join(rest[1:])})
            dropped = r.get("dropped", {})
            return f"dropped {dropped.get('files', 0)} file(s), types {dropped.get('types', [])}"
```

and this `_HELP` line after the `clear-input N` line (`:30`):

```
  drop N text...       drop a text payload onto field N (files: use `visus drop --path`)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_drop_upload.py -m "not browser" -v --no-cov`
Expected: PASS (7 passed)

Run: `uv run pytest tests/test_cli_drop_upload.py -m browser -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 8: Update the README**

In `README.md`, in the **Actions** table, add after the `visus drag` row:

```markdown
| `visus drop [idx] [target] --path <f>` / `--data <t> --data-type <ct>` | Drop a file or payload onto an element from outside the page (dropzones with no file input). |
```

- [ ] **Step 9: Run the gates and commit**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py \
        src/visus/web/cli/console.py tests/test_cli_drop_upload.py \
        tests/fixtures/dropzone.html README.md
git commit -m "feat(cli): add drop for dropzones with no file input"
```

---

### Task 12: Target-free `visus upload` — the file-chooser gap

A grep for `file_chooser` in `src/` returns 0, and `_op_upload` (`session_server.py:365-368`) always goes through `_target(args)`, which exits with "provide an index, or --selector / --role / --text" when nothing is given (`main.py:232-234`). `playwright-cli upload <file>` needs no target at all.

Rather than intercepting the OS chooser dialog, `visus upload <paths…>` with no target finds the page's `<input type=file>` and sets the files on it directly. That covers the common shape — a styled button proxying for a hidden input — *better* than chooser interception does, because it never has to open a dialog. When the page has zero or several file inputs the error says exactly which command disambiguates.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:365-368` (`_op_upload`)
- Modify: `src/visus/web/cli/main.py:656-672` (`upload`)
- Modify: `src/visus/web/cli/console.py:19-53` (`_HELP`), dispatch
- Modify: `README.md` (Actions table)
- Create: `tests/fixtures/upload_single.html`
- Test: `tests/test_cli_drop_upload.py`

**Interfaces:**
- Consumes: `SessionHandler._has_target(args)` (`session_server.py:198-203`); `Page.locator(selector, *, deep=False)` (`api/page.py:194`); `Locator.count()` / `first()` (`api/locator.py:195`, `:158`); `errors.ElementNotFoundError` / `errors.StrictModeViolation` (`errors.py:27-31`)
- Produces: `SessionHandler._only_file_input() -> Locator`; `visus upload <paths…>` with no target; REPL `upload`

- [ ] **Step 1: Write the fixture page**

Create `tests/fixtures/upload_single.html` with exactly this content:

```html
<!doctype html>
<html>
  <head><title>upload fixture</title></head>
  <body>
    <!-- The common real-world shape: a styled button whose click() proxies to a
         hidden input. Targeting the INPUT works without ever opening the OS
         file chooser the button would normally raise. -->
    <button id="pick" onclick="document.getElementById('hidden_file').click()">
      Choose a file
    </button>
    <input id="hidden_file" type="file" style="display:none" />
    <pre id="out">idle</pre>
    <script>
      document.getElementById('hidden_file').addEventListener('change', function (e) {
        var names = Array.prototype.map.call(e.target.files, function (f) { return f.name; });
        document.getElementById('out').textContent = names.join(',');
      });
    </script>
  </body>
</html>
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_cli_drop_upload.py`:

```python
@pytest.mark.browser
def test_upload_without_a_target_finds_the_only_file_input(
    base_url: str, tmp_path: Path
) -> None:
    """`visus upload <file>` must work on a page whose input is hidden behind a button."""
    payload = tmp_path / "avatar.png"
    payload.write_bytes(b"\x89PNG\r\n\x1a\n")

    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/upload_single.html"
    )
    try:
        resp = h.handle("upload", {"paths": [str(payload)]})
        assert resp["ok"] is True, resp
        assert h.handle("get_text", {"selector": "#out"})["result"]["value"] == "avatar.png"
    finally:
        h.close()


@pytest.mark.browser
def test_upload_without_a_target_says_what_to_do_when_there_is_none(
    base_url: str, tmp_path: Path
) -> None:
    payload = tmp_path / "x.txt"
    payload.write_text("x", encoding="utf-8")
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/dropzone.html"
    )
    try:
        resp = h.handle("upload", {"paths": [str(payload)]})
        assert resp["ok"] is False
        assert "no <input type=file>" in resp["error"]
        assert "visus drop" in resp["error"]
    finally:
        h.close()


@pytest.mark.browser
def test_upload_without_a_target_refuses_an_ambiguous_page(
    base_url: str, tmp_path: Path
) -> None:
    payload = tmp_path / "x.txt"
    payload.write_text("x", encoding="utf-8")
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/upload_single.html"
    )
    try:
        h.handle(
            "eval",
            {
                "expression": (
                    "() => { const i = document.createElement('input');"
                    " i.type = 'file'; i.id = 'second'; document.body.appendChild(i);"
                    " return true; }"
                )
            },
        )
        resp = h.handle("upload", {"paths": [str(payload)]})
        assert resp["ok"] is False
        assert "2 file inputs" in resp["error"]
        assert "list-fields" in resp["error"]
    finally:
        h.close()


def test_op_upload_still_honours_an_explicit_target() -> None:
    """The targeted path is unchanged — the fake records the set_input_files call."""
    from test_cli_session import _FakePage, _handler_with_fake_page

    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("list_fields", {})
    resp = h.handle("upload", {"index": 0, "paths": ["/tmp/a.png"]})
    assert resp["ok"] is True and resp["result"] == "set 1 file(s)"
    # _FakeLocator.set_input_files records "upload:<label>:<paths>".
    assert any(entry.startswith("upload:") for entry in page.log), page.log


def test_op_upload_requires_paths() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    resp = h.handle("upload", {})
    assert resp["ok"] is False and "at least one file path" in resp["error"]


def test_cli_upload_without_a_target_sends_only_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = tmp_path / "a.png"
    payload.write_bytes(b"x")
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(op=op, args=args) or "set 1 file(s)",
    )
    r = runner.invoke(app, ["upload", str(payload)])
    assert r.exit_code == 0, r.output
    assert captured["op"] == "upload"
    assert list(captured["args"]) == ["paths"]
    assert captured["args"]["paths"] == [str(payload.resolve())]


def test_cli_upload_with_an_index_still_targets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = tmp_path / "a.png"
    payload.write_bytes(b"x")
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(args=args) or "set 1 file(s)",
    )
    r = runner.invoke(app, ["upload", "4", str(payload)])
    assert r.exit_code == 0, r.output
    assert captured["args"]["index"] == 4
    assert captured["args"]["paths"] == [str(payload.resolve())]


def test_cli_upload_still_needs_a_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: "")
    assert runner.invoke(app, ["upload"]).exit_code == 1


def test_repl_upload_twin() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return "set 1 file(s)"

    assert "set 1 file(s)" in console.dispatch("upload ./a.png", send)
    assert calls[0][0] == "upload"
    assert calls[0][1]["paths"][0].endswith("a.png")
    assert "index" not in calls[0][1]

    console.dispatch("upload 3 ./a.png", send)
    assert calls[1][1]["index"] == 3
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_drop_upload.py -k "upload" -m "not browser" -v --no-cov`
Expected: FAIL — `test_cli_upload_without_a_target_sends_only_paths` exits 1 with "error: provide an index, or --selector / --role / --text".

- [ ] **Step 4: Write the op**

In `src/visus/web/cli/session_server.py`, replace `_op_upload` (`:365-368`) with:

```python
    def _only_file_input(self) -> Locator:
        """The page's single ``<input type=file>`` — the target-free ``visus upload``.

        No OS file-chooser interception is needed: a button that "opens the file
        chooser" is proxying for an input, and setting files on that input is both
        simpler and more reliable than driving a native dialog. Hidden inputs count
        — sites routinely hide them behind a styled button.
        """
        loc = self.page().locator('input[type="file"]', deep=True)
        found = loc.count()
        if found == 0:
            raise errors.ElementNotFoundError(
                "no <input type=file> on this page — open the form that reveals one, "
                "or use `visus drop --path <file>` for a dropzone that has none"
            )
        if found > 1:
            raise errors.StrictModeViolation(
                f"{found} file inputs on this page — name one explicitly: run "
                "`visus list-fields` and pass its index, e.g. `visus upload 4 a.png`"
            )
        return loc.first()

    def _op_upload(self, args: dict[str, Any]) -> str:
        """Set file(s) on a file input — the target is optional."""
        paths = args.get("paths") or []
        if not paths:
            raise ValueError("upload: provide at least one file path")
        target = self._target(args) if self._has_target(args) else self._only_file_input()
        target.set_input_files(paths)
        return f"set {len(paths)} file(s)"
```

- [ ] **Step 5: Write the CLI command**

In `src/visus/web/cli/main.py`, replace `upload` (`:656-672`) with:

```python
@app.command()
def upload(
    index: int = typer.Argument(None, help="File-input field index (omit = find it for me)."),
    paths: list[str] = _UPLOAD_PATHS_ARG,
    selector: str = typer.Option(None, "--selector", "-s"),
    role: str = typer.Option(None, "--role"),
    name: str = typer.Option(None, "--name"),
    text: str = typer.Option(None, "--text"),
) -> None:
    """Set file(s) on a file input.

    With no target visus finds the page's single `<input type=file>` — including
    one hidden behind a styled "Choose a file" button, which is the shape a file
    chooser normally hides::

        visus upload ./avatar.png
        visus upload 4 a.png b.png
    """
    from visus.web.cli import output

    if not paths:
        output.emit_error("provide at least one file path to upload")
    args: dict[str, Any] = {}
    if index is not None or selector or role or text:
        args = _target_args(index, selector, role, name, text)
    # Resolve paths against the CLIENT's cwd so the daemon receives absolute paths.
    args["paths"] = [str(Path(p).resolve()) for p in paths]
    output.emit(_send("upload", args))
```

- [ ] **Step 6: Write the REPL twin**

In `src/visus/web/cli/console.py`, add this branch immediately after the `drop` branch (Task 11):

```python
        if cmd == "upload":
            from pathlib import Path as _Path

            head, *files = rest
            if head.isdigit():
                args = {"index": int(head)}
            else:
                args = {}
                files = [head, *files]
            # Resolve against the CLIENT's cwd, not the daemon's (see main.upload).
            args["paths"] = [str(_Path(p).resolve()) for p in files]
            return str(send("upload", args))
```

and this `_HELP` line after the `drop N text...` line:

```
  upload [N] paths...  set file(s) on a file input (omit N to find the only one)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_drop_upload.py -m "not browser" -v --no-cov`
Expected: PASS (13 passed)

Run: `uv run pytest tests/test_cli_drop_upload.py -m browser -v --no-cov`
Expected: PASS (5 passed)

Run: `uv run pytest tests/test_cli_session.py -k upload -v --no-cov`
Expected: PASS — the existing targeted-upload tests are unaffected.

- [ ] **Step 8: Update the README**

In `README.md`, in the **Actions** table, replace the `visus upload` row with:

```markdown
| `visus upload [idx] <paths…>` | Set file(s) on a file input. With no index visus finds the page's only `<input type=file>` — including one hidden behind a "Choose a file" button. |
```

- [ ] **Step 9: Run the gates and commit**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py \
        src/visus/web/cli/console.py tests/test_cli_drop_upload.py \
        tests/fixtures/upload_single.html README.md
git commit -m "feat(cli): upload without a target by finding the page's file input"
```

---

### Task 13: `session start --persistent / --profile / --device / --mobile / --browser`

PLAN 5 Task 7 already threads the raw `--user-data-dir` / `--remote-url` / `--slow-mo` through to `launch()`. This task builds the higher-level UX **on top of** it and adds nothing to the transport that PLAN 5 did not already put there:

- `--persistent` fills `user_data_dir` with `session_client.profile_dir(...)` (Task 3), so `visus session delete-data` and `--persistent` agree on one directory by construction.
- `--profile <dir>` is a second spelling of `--user-data-dir` — one option, two declarations, so muscle memory from `playwright-cli` transfers with no second code path.
- `--browser` is a second spelling of `--engine`, for the same reason.
- `--device <name>` / `--mobile` apply `Page.set_device_metrics` (`api/page.py:442-455`) as soon as the page exists, **before** the initial `goto`, so the first load already sees the mobile viewport.

`--device` names come from a small explicit table, and `visus devices` prints it — an unknown name should never be a shrug.

**Files:**
- Create: `src/visus/web/api/devices.py`
- Modify: `src/visus/web/cli/session_server.py:84-119` (`__init__` / `_ensure`), `:571-589` (`_op_status`), `:697-710` (session payload), `:738-773` (`main`)
- Modify: `src/visus/web/cli/session_client.py` — `start_daemon`'s env block
- Modify: `src/visus/web/cli/main.py` — `session start`, new `devices`
- Modify: `README.md` (Session table, Tooling table, env-var table)
- Test: `tests/test_cli_emulation.py`

**Interfaces:**
- Consumes: `SessionHandler(..., user_data_dir, remote_url, slow_mo)` and `start_daemon(..., user_data_dir=...)` (PLAN 5 Task 7); `session_client.profile_dir` (Task 3); `Page.set_device_metrics` (`api/page.py:442`); `config.is_default` is **not** used here — Task 14 adds config merging on top
- Produces:
  ```python
  @dataclass(frozen=True)
  class Device:
      name: str; width: int; height: int; device_scale_factor: float; mobile: bool
  visus.web.api.devices.DEVICES: dict[str, Device]
  visus.web.api.devices.DEFAULT_MOBILE: str
  visus.web.api.devices.get_device(name: str) -> Device
  SessionHandler(..., device: str | None = None)
  session_client.start_daemon(..., device: str | None = None)
  env VISUS_WEB_DEVICE
  visus session start --persistent --profile <dir> --device <name> --mobile --browser <e>
  visus devices
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_emulation.py`:

```python
"""Profile and device emulation on `session start`, and `visus devices`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.api.devices import DEFAULT_MOBILE, DEVICES, get_device
from visus.web.cli import session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


def test_device_table_is_non_empty_and_well_formed() -> None:
    assert DEVICES, "the device table must not be empty"
    for key, device in DEVICES.items():
        assert key == key.lower(), f"{key!r} must be lower-case for lookup"
        assert device.width > 0 and device.height > 0
        assert device.device_scale_factor > 0
        assert isinstance(device.mobile, bool)


def test_get_device_is_case_and_space_insensitive() -> None:
    assert get_device("iPhone 15").mobile is True
    assert get_device("  iphone 15 ") == get_device("iPhone 15")


def test_default_mobile_device_exists_and_is_mobile() -> None:
    assert get_device(DEFAULT_MOBILE).mobile is True


def test_unknown_device_lists_the_known_ones() -> None:
    with pytest.raises(ValueError) as excinfo:
        get_device("Nokia 3310")
    message = str(excinfo.value)
    assert "Nokia 3310" in message
    assert get_device(DEFAULT_MOBILE).name in message


def test_handler_applies_device_metrics_before_the_initial_goto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first load must already see the mobile viewport."""
    order: list[str] = []

    class _Page:
        def set_device_metrics(
            self, width: int, height: int, *, device_scale_factor: float, mobile: bool
        ) -> None:
            order.append(f"metrics:{width}x{height}@{device_scale_factor}:{mobile}")

        def goto(self, url: str) -> None:
            order.append(f"goto:{url}")

    class _Browser:
        def new_page(self) -> _Page:
            return _Page()

        def close(self) -> None: ...

    monkeypatch.setattr(session_server, "launch", lambda engine, **kw: _Browser())
    device = get_device("iPhone 15")
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url="http://x", device="iPhone 15"
    )
    h._ensure()
    assert order == [
        f"metrics:{device.width}x{device.height}@{device.device_scale_factor}:True",
        "goto:http://x",
    ]


def test_handler_without_a_device_never_touches_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _Page:
        def set_device_metrics(self, *a: Any, **kw: Any) -> None:
            calls.append("metrics")

        def goto(self, url: str) -> None: ...

    class _Browser:
        def new_page(self) -> _Page:
            return _Page()

        def close(self) -> None: ...

    monkeypatch.setattr(session_server, "launch", lambda engine, **kw: _Browser())
    session_server.SessionHandler(engine="chrome", headless=True, url="http://x")._ensure()
    assert calls == []


def test_status_reports_the_device() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    h._device = "iPhone 15"
    assert h.handle("status", {})["result"]["device"] == "iPhone 15"


def test_daemon_main_reads_the_device_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: dict[str, Any] = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VISUS_WEB_DEVICE", "Pixel 7")
    monkeypatch.setattr(session_server, "SessionHandler", lambda **kw: built.update(kw))
    monkeypatch.setattr(session_server, "serve", lambda handler, **kw: None)
    session_server.main(["chrome", "1", ""])
    assert built["device"] == "Pixel 7"


def test_cli_persistent_uses_the_managed_profile_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(kw) or {"pid": 1, "port": 2},
    )
    r = runner.invoke(app, ["-S", "auth", "session", "start", "--persistent"])
    assert r.exit_code == 0, r.output
    assert Path(captured["user_data_dir"]) == session_client.profile_dir(tmp_path, "auth")


def test_cli_profile_is_a_spelling_of_user_data_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(kw) or {"pid": 1, "port": 2},
    )
    assert runner.invoke(app, ["session", "start", "--profile", "/p/x"]).exit_code == 0
    assert captured["user_data_dir"] == "/p/x"
    assert runner.invoke(app, ["session", "start", "--user-data-dir", "/p/y"]).exit_code == 0
    assert captured["user_data_dir"] == "/p/y"


def test_cli_persistent_and_profile_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "start_daemon", lambda *a, **kw: {"pid": 1, "port": 2})
    r = runner.invoke(app, ["session", "start", "--persistent", "--profile", "/p/x"])
    assert r.exit_code == 1


def test_cli_browser_is_a_spelling_of_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(engine=e) or {"pid": 1, "port": 2},
    )
    assert runner.invoke(app, ["session", "start", "--browser", "edge"]).exit_code == 0
    assert captured["engine"] == "edge"


def test_cli_mobile_selects_the_default_device(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(kw) or {"pid": 1, "port": 2},
    )
    assert runner.invoke(app, ["session", "start", "--mobile"]).exit_code == 0
    assert captured["device"] == DEFAULT_MOBILE


def test_cli_device_wins_over_mobile(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(kw) or {"pid": 1, "port": 2},
    )
    r = runner.invoke(app, ["session", "start", "--mobile", "--device", "Pixel 7"])
    assert r.exit_code == 0, r.output
    assert captured["device"] == "Pixel 7"


def test_cli_rejects_an_unknown_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "start_daemon", lambda *a, **kw: {"pid": 1, "port": 2})
    r = runner.invoke(app, ["session", "start", "--device", "Nokia 3310"])
    assert r.exit_code == 1


def test_cli_rejects_a_device_on_a_non_chromium_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """set_device_metrics is a CDP call — fail at start, not on the first action."""
    monkeypatch.setattr(session_client, "start_daemon", lambda *a, **kw: {"pid": 1, "port": 2})
    r = runner.invoke(app, ["session", "start", "--engine", "firefox", "--mobile"])
    assert r.exit_code == 1


def test_cli_devices_lists_the_table() -> None:
    r = runner.invoke(app, ["devices"])
    assert r.exit_code == 0, r.output
    for device in DEVICES.values():
        assert device.name in r.output


def test_cli_devices_json() -> None:
    r = runner.invoke(app, ["--json", "devices"])
    assert r.exit_code == 0, r.output
    names = {row["name"] for row in json.loads(r.output)}
    assert {d.name for d in DEVICES.values()} == names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_emulation.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'visus.web.api.devices'`

- [ ] **Step 3: Write the device table**

Create `src/visus/web/api/devices.py`:

```python
"""Named device presets for viewport emulation.

Deliberately small and explicit rather than a vendored descriptor dump: every
entry is a viewport plus a pixel ratio plus the mobile flag, which is exactly
what :meth:`visus.web.Page.set_device_metrics` takes. The user agent is NOT
changed — emulation here is layout-level, and saying so beats implying more.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Device:
    """One viewport preset: CSS pixel size, device pixel ratio, and the mobile flag."""

    name: str
    width: int
    height: int
    device_scale_factor: float
    mobile: bool


DEVICES: dict[str, Device] = {
    "iphone 15": Device("iPhone 15", 393, 852, 3.0, True),
    "iphone se": Device("iPhone SE", 375, 667, 2.0, True),
    "pixel 7": Device("Pixel 7", 412, 915, 2.625, True),
    "galaxy s21": Device("Galaxy S21", 360, 800, 3.0, True),
    "ipad mini": Device("iPad Mini", 768, 1024, 2.0, True),
    "desktop": Device("Desktop", 1280, 800, 1.0, False),
}

DEFAULT_MOBILE = "iphone 15"


def get_device(name: str) -> Device:
    """Look up a device preset by name (case- and space-insensitive)."""
    device = DEVICES.get(name.strip().lower())
    if device is None:
        known = ", ".join(sorted(d.name for d in DEVICES.values()))
        raise ValueError(f"unknown device {name!r} — known devices: {known}")
    return device
```

- [ ] **Step 4: Apply the device in the daemon**

In `src/visus/web/cli/session_server.py`, add `device: str | None = None,` to `SessionHandler.__init__`'s keyword-only block (after `debugger_address`) and `self._device = device` beside the other assignments.

In `_ensure()`, insert the metrics call between `new_page()` and the initial `goto` so the FIRST load already sees the emulated viewport:

```python
                self._page = self._browser.new_page()
                if self._device:
                    from visus.web.api.devices import get_device

                    preset = get_device(self._device)
                    self._page.set_device_metrics(
                        preset.width,
                        preset.height,
                        device_scale_factor=preset.device_scale_factor,
                        mobile=preset.mobile,
                    )
                if self._url:
                    self._page.goto(self._url)
```

Add to `_op_status`'s `info` dict, after `"attached": self._attached,`:

```python
            "device": self._device,
```

Add to `serve()`'s session payload, after `"slow_mo": handler._slow_mo,`:

```python
            "device": handler._device,
```

In `main()`, read it from env and pass it through:

```python
    device = os.environ.get("VISUS_WEB_DEVICE") or None
```

```python
        device=device,
```

In `src/visus/web/cli/session_client.py`, add `device: str | None = None` to `start_daemon`'s keyword-only block and to its env block:

```python
    if device:
        env["VISUS_WEB_DEVICE"] = device
```

- [ ] **Step 5: Extend `session start` and add `visus devices`**

In `src/visus/web/cli/main.py`, extend `session_start` (as PLAN 5 Task 7 and Task 7 of this plan left it). Replace the `engine` parameter and add four more, keeping every existing parameter untouched:

```python
    engine: str = typer.Option(
        "chrome", "--engine", "-e", "--browser", help="chrome | edge | firefox | edge_ie."
    ),
```

```python
    persistent: bool = typer.Option(
        False,
        "--persistent",
        help="Keep the profile in .visus/profiles/<session> so logins survive runs.",
    ),
    profile: str = typer.Option(
        None, "--profile", help="Alias of --user-data-dir: a profile directory you own."
    ),
    device: str = typer.Option(
        None, "--device", help="Emulate a device viewport (see `visus devices`)."
    ),
    mobile: bool = _MOBILE_OPT,
```

where `_MOBILE_OPT` is declared next to the other module-level singleton defaults in `main.py`
(B008 forbids a call as an inline default, and the help text has to name the real preset):

```python
_MOBILE_OPT = typer.Option(
    False, "--mobile", help="Shorthand for --device 'iPhone 15' (see `visus devices`)."
)
```

Add this resolution block at the top of `session_start`'s body, before the `start_daemon` call:

```python
    from visus.web.api.devices import DEFAULT_MOBILE, get_device
    from visus.web.cli import output, session_client

    chosen = [flag for flag, on in (("--persistent", persistent), ("--profile", profile)) if on]
    if user_data_dir and chosen:
        output.emit_error(f"pass --user-data-dir or {chosen[0]}, not both")
    if persistent and profile:
        output.emit_error("pass --persistent or --profile, not both")
    if persistent:
        # The same directory `visus session delete-data` is entitled to remove.
        user_data_dir = str(session_client.profile_dir())
    elif profile:
        user_data_dir = profile

    if mobile and not device:
        device = DEFAULT_MOBILE
    if device:
        try:
            get_device(device)  # fail here, not on the daemon's first action
        except ValueError as exc:
            output.emit_error(str(exc))
        if engine not in ("chrome", "edge"):
            output.emit_error(
                f"device emulation is a CDP feature — it needs chrome or edge, not {engine!r}"
            )
```

and `device=device,` added to the `start_daemon(...)` call.

Add the discovery command next to `version` (`:20-25`):

```python
@app.command()
def devices() -> None:
    """List the device presets `session start --device` accepts."""
    from visus.web.api.devices import DEVICES
    from visus.web.cli import output

    rows = [
        {
            "name": d.name,
            "width": d.width,
            "height": d.height,
            "device_scale_factor": d.device_scale_factor,
            "mobile": d.mobile,
        }
        for d in DEVICES.values()
    ]
    from rich import box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=box.ASCII, header_style="bold", pad_edge=False)
    for column in ("NAME", "WIDTH", "HEIGHT", "DPR", "MOBILE"):
        table.add_column(column, no_wrap=True)
    for row in rows:
        table.add_row(
            str(row["name"]),
            str(row["width"]),
            str(row["height"]),
            str(row["device_scale_factor"]),
            "yes" if row["mobile"] else "no",
        )
    console_obj = Console()
    with console_obj.capture() as cap:
        console_obj.print(table)
    output.emit(rows, table=cap.get().rstrip("\n"))
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_emulation.py -v --no-cov`
Expected: PASS (18 passed)

Run: `uv run pytest tests/test_cli_session.py tests/test_cli_sessions_named.py -k "session_start or start_daemon" -v --no-cov`
Expected: PASS — every pre-existing `session start` invocation still works, because all four new options default to inert values.

- [ ] **Step 7: Update the README**

In `README.md`, replace the `visus session start` row with:

```markdown
| `visus session start [URL] --engine/--browser <e> --headless --persistent --profile <dir> --user-data-dir <dir> --remote-url <url> --slow-mo <ms> --device <d> --mobile --allow-run-code` | Start the persistent browser daemon (headed by default). |
```

Add a row to the **Tooling** table:

```markdown
| `visus devices [--json]` | List the device presets `--device` accepts. |
```

Add one env-var row after `VISUS_WEB_SLOW_MO`:

```markdown
| `VISUS_WEB_DEVICE` | CLI session | — | Device preset emulated at session start (see `visus devices`). |
```

Add this note under the Session table:

```markdown
`--persistent` stores the profile in `.visus/profiles/<session>` (git-ignored, and the only
directory `visus session delete-data` will remove). `--profile <dir>` points at a directory you
own — visus never deletes it. `--device` / `--mobile` emulate the **viewport** (size, pixel
ratio, the mobile flag) via CDP, so they need chrome or edge; the user-agent string is not
changed.
```

- [ ] **Step 8: Run the gates and commit**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

```bash
git add src/visus/web/api/devices.py src/visus/web/cli/session_server.py \
        src/visus/web/cli/session_client.py src/visus/web/cli/main.py \
        tests/test_cli_emulation.py README.md
git commit -m "feat(cli): add --persistent/--profile/--device/--mobile/--browser to session start"
```

---

### Task 14: `--config` — a project config file

`session_server.main` reads exactly four things from the environment — engine, headless, url, token (`session_server.py:743-750`) — and everything else has to be repeated on every `session start`. `playwright-cli` documents a full config schema (`README.md:385-518`: `browser.browserName`, `browser.isolated`, `browser.userDataDir`, `outputDir`, `outputMode`, timeouts, …) loaded from `.playwright/cli.config.json` by default.

This task adds the same idea, scoped to what this CLI actually has: `.visus/cli.json`, discovered with the same upward walk sessions use, overridable with `--config <path>`, and always **losing** to an explicitly-passed flag. An unknown key is an error naming the key — a silent typo in a config file is the classic way this feature goes wrong.

**Files:**
- Create: `src/visus/web/cli/config.py`
- Modify: `src/visus/web/cli/main.py` — the root callback, and `session_start`'s merge
- Modify: `README.md` (new config section, env-var table)
- Test: `tests/test_cli_config.py`

**Interfaces:**
- Consumes: `session_client.set_session_name` (Task 1); `session_client.profile_dir` (Task 3); `output.set_output_dir`, `output.set_mode`, `output.emit_error` (PLAN 4); `skill_check.check_installed_skills` (PLAN 1)
- Produces:
  ```python
  class ConfigError(RuntimeError): ...
  CONFIG_RELPATH: Path                      # .visus/cli.json
  @dataclass(frozen=True)
  class CliConfig:
      path: Path | None; session: str | None; engine: str | None
      headless: bool | None; url: str | None; device: str | None
      persistent: bool | None; user_data_dir: str | None
      remote_url: str | None; slow_mo: int | None; idle_timeout: float | None
      allow_run_code: bool | None; output_dir: str | None
  def find_config(start_dir: str | Path | None = None) -> Path | None: ...
  def load_config(path: Path) -> CliConfig: ...
  def set_active(cfg: CliConfig) -> None: ...
  def active() -> CliConfig: ...
  def is_default(ctx: typer.Context, name: str) -> bool: ...
  ```

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_config.py`:

```python
"""`.visus/cli.json` discovery, parsing, precedence and error messages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import config as cliconfig
from visus.web.cli import session_client
from visus.web.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_active() -> Any:
    cliconfig.set_active(cliconfig.CliConfig())
    session_client.set_session_name(None)
    yield
    cliconfig.set_active(cliconfig.CliConfig())
    session_client.set_session_name(None)


def _write_config(dir_: Path, data: dict[str, Any]) -> Path:
    visus = dir_ / ".visus"
    visus.mkdir(parents=True, exist_ok=True)
    path = visus / "cli.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_find_config_walks_upward(tmp_path: Path) -> None:
    path = _write_config(tmp_path, {"engine": "edge"})
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert cliconfig.find_config(deep) == path


def test_find_config_returns_none_when_absent(tmp_path: Path) -> None:
    assert cliconfig.find_config(tmp_path) is None


def test_load_config_maps_every_key(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        {
            "session": "auth",
            "engine": "edge",
            "headless": True,
            "url": "https://example.com",
            "device": "Pixel 7",
            "persistent": True,
            "remoteUrl": "http://grid:4444/wd/hub",
            "slowMo": 120,
            "idleTimeout": 600,
            "allowRunCode": True,
            "outputDir": "artifacts",
        },
    )
    cfg = cliconfig.load_config(path)
    assert cfg.session == "auth"
    assert cfg.engine == "edge"
    assert cfg.headless is True
    assert cfg.url == "https://example.com"
    assert cfg.device == "Pixel 7"
    assert cfg.persistent is True
    assert cfg.remote_url == "http://grid:4444/wd/hub"
    assert cfg.slow_mo == 120
    assert cfg.idle_timeout == 600.0
    assert cfg.allow_run_code is True
    assert Path(cfg.output_dir or "") == (tmp_path / "artifacts")
    assert cfg.path == path


def test_relative_paths_resolve_against_the_config_file(tmp_path: Path) -> None:
    """A config in repo/.visus must not mean "relative to wherever you ran the command"."""
    path = _write_config(tmp_path, {"userDataDir": "./profiles/main"})
    cfg = cliconfig.load_config(path)
    assert Path(cfg.user_data_dir or "") == (tmp_path / "profiles" / "main")


def test_absolute_paths_are_left_alone(tmp_path: Path) -> None:
    absolute = str((tmp_path / "elsewhere").resolve())
    path = _write_config(tmp_path, {"userDataDir": absolute})
    assert cliconfig.load_config(path).user_data_dir == absolute


def test_unknown_key_is_an_error_that_names_it(tmp_path: Path) -> None:
    path = _write_config(tmp_path, {"engien": "edge"})
    with pytest.raises(cliconfig.ConfigError) as excinfo:
        cliconfig.load_config(path)
    message = str(excinfo.value)
    assert "engien" in message
    assert "engine" in message  # the valid keys are listed


def test_malformed_json_is_an_error_that_names_the_file(tmp_path: Path) -> None:
    visus = tmp_path / ".visus"
    visus.mkdir(parents=True)
    path = visus / "cli.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(cliconfig.ConfigError, match="cli.json"):
        cliconfig.load_config(path)


def test_non_object_config_is_an_error(tmp_path: Path) -> None:
    visus = tmp_path / ".visus"
    visus.mkdir(parents=True)
    path = visus / "cli.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(cliconfig.ConfigError, match="JSON object"):
        cliconfig.load_config(path)


def test_wrong_value_type_is_an_error(tmp_path: Path) -> None:
    path = _write_config(tmp_path, {"slowMo": "fast"})
    with pytest.raises(cliconfig.ConfigError, match="slowMo"):
        cliconfig.load_config(path)


def test_cli_loads_the_config_from_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"session": "auth", "engine": "edge"})
    captured: dict[str, Any] = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(engine=e, headless=h, **kw)
        or {"pid": 1, "port": 2},
    )
    r = runner.invoke(app, ["session", "start"])
    assert r.exit_code == 0, r.output
    assert captured["engine"] == "edge"
    assert session_client.session_name() == "auth"


def test_an_explicit_flag_always_beats_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"engine": "edge", "headless": True})
    captured: dict[str, Any] = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(engine=e, headless=h) or {"pid": 1, "port": 2},
    )
    r = runner.invoke(app, ["session", "start", "--engine", "chrome"])
    assert r.exit_code == 0, r.output
    assert captured["engine"] == "chrome"
    assert captured["headless"] is True  # not passed, so the config still applies


def test_explicit_session_flag_beats_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"session": "auth"})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: "T")
    assert runner.invoke(app, ["-S", "public", "title"]).exit_code == 0
    assert session_client.session_name() == "public"


def test_explicit_config_path_wins_over_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"engine": "edge"})
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"engine": "firefox"}), encoding="utf-8")
    captured: dict[str, Any] = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(engine=e) or {"pid": 1, "port": 2},
    )
    r = runner.invoke(app, ["--config", str(other), "session", "start"])
    assert r.exit_code == 0, r.output
    assert captured["engine"] == "firefox"


def test_missing_explicit_config_is_an_error(tmp_path: Path) -> None:
    r = runner.invoke(app, ["--config", str(tmp_path / "nope.json"), "version"])
    assert r.exit_code == 1


def test_a_broken_discovered_config_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo in a config nobody asked for must not be swallowed either."""
    _write_config(tmp_path, {"engien": "edge"})
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 1


def test_config_persistent_uses_the_managed_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"persistent": True, "session": "auth"})
    captured: dict[str, Any] = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(kw) or {"pid": 1, "port": 2},
    )
    r = runner.invoke(app, ["session", "start"])
    assert r.exit_code == 0, r.output
    assert Path(captured["user_data_dir"]) == session_client.profile_dir(tmp_path, "auth")


def test_config_output_dir_reaches_the_output_funnel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from visus.web.cli import output

    _write_config(tmp_path, {"outputDir": "artifacts"})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: "T")
    assert runner.invoke(app, ["title"]).exit_code == 0
    assert Path(output.resolve_out("shot.png")).parent == (tmp_path / "artifacts")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_config.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'visus.web.cli.config'`

- [ ] **Step 3: Write the config module**

Create `src/visus/web/cli/config.py`:

```python
"""Project config file for the `visus` CLI (``.visus/cli.json``).

Discovered with the same upward walk sessions use, so a config in the repo root
applies to a command run in ``repo/src``. Every value is a DEFAULT: an option the
user actually typed always wins, which is what :func:`is_default` decides.

Unknown keys are an error rather than a shrug — a typo in a config file is the
classic way this feature silently does nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

CONFIG_RELPATH = Path(".visus") / "cli.json"


class ConfigError(RuntimeError):
    """Raised when a config file is missing, malformed, or has an unknown key."""


@dataclass(frozen=True)
class CliConfig:
    """Defaults read from ``.visus/cli.json``. ``None`` means "not configured"."""

    path: Path | None = None
    session: str | None = None
    engine: str | None = None
    headless: bool | None = None
    url: str | None = None
    device: str | None = None
    persistent: bool | None = None
    user_data_dir: str | None = None
    remote_url: str | None = None
    slow_mo: int | None = None
    idle_timeout: float | None = None
    allow_run_code: bool | None = None
    output_dir: str | None = None


# JSON key -> (dataclass field, python type, is it a path?)
_SCHEMA: dict[str, tuple[str, type, bool]] = {
    "session": ("session", str, False),
    "engine": ("engine", str, False),
    "headless": ("headless", bool, False),
    "url": ("url", str, False),
    "device": ("device", str, False),
    "persistent": ("persistent", bool, False),
    "userDataDir": ("user_data_dir", str, True),
    "remoteUrl": ("remote_url", str, False),
    "slowMo": ("slow_mo", int, False),
    "idleTimeout": ("idle_timeout", float, False),
    "allowRunCode": ("allow_run_code", bool, False),
    "outputDir": ("output_dir", str, True),
}

_active = CliConfig()


def set_active(cfg: CliConfig) -> None:
    """Install the config the root callback resolved for this invocation."""
    global _active
    _active = cfg


def active() -> CliConfig:
    """The config in force for this invocation (empty when none was found)."""
    return _active


def find_config(start_dir: str | Path | None = None) -> Path | None:
    """Search upward from *start_dir* for ``.visus/cli.json`` (git-style)."""
    cur = Path(start_dir) if start_dir is not None else Path.cwd()
    cur = cur.resolve()
    for d in [cur, *cur.parents]:
        candidate = d / CONFIG_RELPATH
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path) -> CliConfig:
    """Parse *path* into a :class:`CliConfig`, or raise :class:`ConfigError`.

    Relative ``userDataDir`` / ``outputDir`` values resolve against the config
    file's own directory, never the caller's cwd — a config in ``repo/.visus``
    must mean the same thing from every subdirectory.
    """
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a JSON object, not {type(raw).__name__}")

    values: dict[str, Any] = {"path": path}
    base = path.parent
    for key, value in raw.items():
        entry = _SCHEMA.get(str(key))
        if entry is None:
            known = ", ".join(sorted(_SCHEMA))
            raise ConfigError(f"unknown key {key!r} in {path} — valid keys: {known}")
        field, expected, is_path = entry
        if expected is bool:
            if not isinstance(value, bool):
                raise ConfigError(f"{key!r} in {path} must be true or false")
        elif expected is float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{key!r} in {path} must be a number")
            value = float(value)
        elif expected is int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ConfigError(f"{key!r} in {path} must be a whole number")
        elif not isinstance(value, str):
            raise ConfigError(f"{key!r} in {path} must be a string")
        if is_path and isinstance(value, str) and value:
            candidate = Path(value)
            value = str(candidate if candidate.is_absolute() else (base / candidate).resolve())
        values[field] = value
    return CliConfig(**values)


def resolve(explicit: str | None, start_dir: str | Path | None = None) -> CliConfig:
    """Load the config named by ``--config``, else the discovered one, else empty."""
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        return load_config(path)
    found = find_config(start_dir)
    return CliConfig() if found is None else load_config(found)


def is_default(ctx: typer.Context, name: str) -> bool:
    """True when *name* was NOT supplied on the command line.

    Click records where each parameter's value came from; anything other than
    ``DEFAULT`` means the user (or an env var) asked for it, and the config must
    step aside.
    """
    source = ctx.get_parameter_source(name)
    return source is None or getattr(source, "name", "") == "DEFAULT"
```

- [ ] **Step 4: Wire the root callback and `session start`**

In `src/visus/web/cli/main.py`, add `--config` to the root callback — the parameter after `session` (Task 1):

```python
    config: str = typer.Option(
        None,
        "--config",
        envvar="VISUS_WEB_CONFIG",
        help="Config file (default: the nearest .visus/cli.json).",
    ),
```

and replace the callback body's opening lines with:

```python
    from visus.web.cli import config as cliconfig
    from visus.web.cli import output, session_client

    try:
        cfg = cliconfig.resolve(config)
    except cliconfig.ConfigError as exc:
        output.emit_error(str(exc))
    cliconfig.set_active(cfg)

    session_client.set_session_name(session or cfg.session)
    output.set_mode(as_json=as_json, raw=raw)
    output.set_output_dir(output_dir if output_dir is not None else cfg.output_dir)
    output.set_snapshot_sink(snapshot_sink)
    if ctx.invoked_subcommand not in ("install", "install-skills"):
        check_installed_skills()
```

In `session_start`, add `ctx: typer.Context,` as the **first** parameter and this merge immediately after the imports at the top of its body, before the `--persistent` / `--profile` resolution added in Task 13:

```python
    cfg = cliconfig.active()
    if cliconfig.is_default(ctx, "engine") and cfg.engine:
        engine = cfg.engine
    if cliconfig.is_default(ctx, "headless") and cfg.headless is not None:
        headless = cfg.headless
    if cliconfig.is_default(ctx, "url") and cfg.url:
        url = cfg.url
    if cliconfig.is_default(ctx, "device") and cfg.device:
        device = cfg.device
    if cliconfig.is_default(ctx, "persistent") and cfg.persistent is not None:
        persistent = cfg.persistent
    if cliconfig.is_default(ctx, "user_data_dir") and cfg.user_data_dir:
        user_data_dir = cfg.user_data_dir
    if cliconfig.is_default(ctx, "remote_url") and cfg.remote_url:
        remote_url = cfg.remote_url
    if cliconfig.is_default(ctx, "slow_mo") and cfg.slow_mo is not None:
        slow_mo = cfg.slow_mo
    if cliconfig.is_default(ctx, "idle_timeout") and cfg.idle_timeout is not None:
        idle_timeout = cfg.idle_timeout
    if cliconfig.is_default(ctx, "allow_run_code") and cfg.allow_run_code is not None:
        allow_run_code = cfg.allow_run_code
```

with `from visus.web.cli import config as cliconfig` added to `session_start`'s local import line.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_config.py -v --no-cov`
Expected: PASS (18 passed)

Run: `uv run pytest tests/test_cli_emulation.py tests/test_cli_sessions_named.py -q --no-cov`
Expected: PASS — with no config file present, `active()` is empty and every merge is a no-op.

- [ ] **Step 6: Update the README**

In `README.md`, add this section immediately after the **Full command reference** `</details>` block:

````markdown
### Config file

Put shared defaults in `.visus/cli.json` (discovered from the current directory upward, like
`.git`), or point at one with `visus --config <path>`. Every value is a **default** — an option
you actually type always wins.

```json
{
  "session": "default",
  "engine": "chrome",
  "headless": false,
  "url": "https://app.example.com",
  "device": "iPhone 15",
  "persistent": true,
  "userDataDir": "./profiles/main",
  "remoteUrl": "http://grid:4444/wd/hub",
  "slowMo": 0,
  "idleTimeout": 600,
  "allowRunCode": false,
  "outputDir": "artifacts"
}
```

Relative `userDataDir` / `outputDir` values resolve against the config file's own directory, so a
config in the repo root means the same thing from every subdirectory. An unknown key is an error
naming the key — a typo never silently does nothing.
````

and one env-var row:

```markdown
| `VISUS_WEB_CONFIG` | CLI | — | Config file path (same as `--config`). |
```

- [ ] **Step 7: Run the gates and commit**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

```bash
git add src/visus/web/cli/config.py src/visus/web/cli/main.py \
        tests/test_cli_config.py README.md
git commit -m "feat(cli): load defaults from .visus/cli.json via --config"
```

---

### Task 15: Full-suite verification

Every previous task ran a narrow selection. This one proves the whole thing holds together, and repairs anything the new surfaces broke — in particular the coverage gate, which is the only check that sees the new modules as a whole.

**Files:**
- Modify: whichever file a failure points at
- Test: the whole suite

**Interfaces:**
- Consumes: everything above
- Produces: nothing new

- [ ] **Step 1: Run the non-browser suite**

Run: `uv run pytest -m "not browser" -q --no-cov`
Expected: PASS, no errors, no warnings-as-errors.

- [ ] **Step 2: Run the browser suite**

Run: `uv run pytest -m browser -q --no-cov`
Expected: PASS. If `tests/test_route.py`'s browser tests are flaky, the cause is almost always the interception pump: check that `FetchInterceptor.stop()` ran (a leftover `Fetch.enable` with no listener hangs the *next* test's page load), and that `SeleniumPageDelegate.close()` calls `_stop_interceptor()`.

- [ ] **Step 3: Run the full suite with the coverage gate**

Run: `uv run pytest -q`
Expected: PASS with `Required test coverage of 90% reached`.

If coverage regressed, the likely gaps are the branches this plan added that no test reaches yet — check the `term-missing` report for `cli/config.py`, `cli/session_client.py` (`close_all`'s unreachable branch, `kill_all`'s legacy sweep) and `backends/selenium/cdp_fetch.py` (`_pump`'s error exits). Add a test for each missing branch; do **not** lower the gate.

- [ ] **Step 4: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 5: Verify the CLI/REPL/README triangle is complete**

Run: `uv run python -c "from visus.web.cli.main import app; print(sorted(c.name for c in app.registered_commands))"`

Confirm every command this plan added appears: `devices`, `drop`, `route`, `route-list`, `run-code`, `unroute`. Then confirm each has a REPL twin and a README row by adding this test to `tests/test_cli_route.py` (it is a real regression test, not a one-off check — the CLI/REPL/README triangle is exactly what let the drift in `A6` accumulate):

```python
def test_every_command_this_plan_added_has_a_repl_twin_and_a_readme_row() -> None:
    from pathlib import Path as _Path

    readme = _Path("README.md").read_text(encoding="utf-8")
    repl_source = _Path("src/visus/web/cli/console.py").read_text(encoding="utf-8")

    for name in ("devices", "drop", "route", "route-list", "run-code", "unroute", "upload"):
        assert f"visus {name}" in readme, f"`visus {name}` has no README row"

    # Session-lifecycle commands intentionally have NO repl twin: the REPL runs
    # inside a session, and each of these either ends it or reports on others.
    for name in ("session list", "session close-all", "session kill-all",
                 "session delete-data", "session attach", "session detach"):
        assert f"visus {name}" in readme, f"`visus {name}` has no README row"

    for repl in ("drop", "route", "unroute", "routes", "run-code", "upload"):
        assert f'cmd == "{repl}"' in repl_source, f"{repl!r} missing from console.dispatch"
        assert repl in console._HELP, f"{repl!r} missing from the REPL help text"
```

Run: `uv run pytest tests/test_cli_route.py::test_every_command_this_plan_added_has_a_repl_twin_and_a_readme_row -v --no-cov`
Expected: PASS

Session-lifecycle commands (`session list` / `close-all` / `kill-all` / `delete-data` / `attach` / `detach`) intentionally have no REPL twin — the REPL runs *inside* a session, and each of those either ends it or reports on others. `visus session start`/`stop` set that precedent.

- [ ] **Step 6: Commit any repairs**

```bash
git add -A
git commit -m "test(cli): close the coverage gaps left by the new engineering surfaces"
```

---

## What this plan deliberately does not do

- **`attach --extension`** (`references/session-management.md:144-148`). It needs a Playwright-specific browser extension that does not exist for visus; `--cdp` covers the same "drive the browser I am already logged into" need with nothing to install.
- **Auto-naming an attached session after the browser channel** (`session-management.md:132`). One name-resolution rule (`--session` / `-S` / `VISUS_WEB_SESSION` / `default`) covers every command; a per-command exception would be a second rule to learn. The README row says so explicitly.
- **`route --remove-header`** (`request-mocking.md:18`). It strips headers from the *outgoing* request; a fulfilled request never leaves the browser, so there is nothing to strip. Stripping headers on a *continued* request is a different feature (`Fetch.continueRequest` with `headers`) and belongs with response modification (`route.fetch()`-style), which needs a second Fetch stage — out of scope here.
- **Conditional / delayed / response-modifying routes** (`request-mocking.md:37-87`). `playwright-cli` routes exactly those through `run-code`, and so does this plan: Task 8 gives an agent `page` and `context` live, which is the same escape hatch.
- **Performance/console capture on an attached session.** Both are enabled at browser launch; visus did not launch that browser. Documented in Task 10's README note rather than faked.
- **`--user-agent` with `--device`.** `Page.set_device_metrics` (`api/page.py:442-455`) emulates the viewport only. Claiming device emulation while leaving the UA string untouched would be worse than saying which half is covered.

