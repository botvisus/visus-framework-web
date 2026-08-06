# Tier 2a — Daemon Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every correctness, concurrency and lifecycle bug in the `visus` session daemon before any new command surface is built on top of it.

**Architecture:** The daemon is a JSON-lines TCP server on `127.0.0.1` (`src/visus/web/cli/session_server.py`) holding one live `Browser`/`Context`/`Page`; a thin client (`src/visus/web/cli/session_client.py`) discovers `.visus/session.json` git-style, checks liveness and sends ops; `src/visus/web/cli/main.py` (Typer) and `src/visus/web/cli/console.py` (REPL) are two frontends over that client. Every fix in this plan lands in those four files — no new modules, no public API surface outside the CLI package.

**Tech Stack:** Python 3.10+, Typer, Rich, Selenium 4.38, pytest + pytest-xdist, hatchling, mypy --strict, ruff

## Global Constraints

- Gates before any commit: `uv run ruff check src tests`, `uv run mypy` (strict), `uv run pytest -q` (≥90% coverage on `visus.web`).
- **THE HIDDEN-ENGINE RULE (inviolable):** no `selenium.*` type may appear in any public signature/return/exception/docstring. Selenium imports allowed ONLY in `backends/browsers/*.py`, `backends/selenium/*.py`, `backends/selenium_backend.py`.
- Test convention: **real browser, no fakes**, `@pytest.mark.browser`, fixtures in `tests/fixtures/*.html` served by the session-scoped `base_url` fixture. Test doubles isolate a unit ONLY when its real behaviour is also covered by an integration test. No `skip`/`xfail`/mock-to-pass.
- Ruff: line-length 100, select `["E","F","I","UP","B"]`.
- mypy: `strict = true`, `python_version = "3.10"`.
- Commits: small, TDD (failing test → minimal impl → green → commit), semantic messages `label(scope): description`. Labels: `fix`, `feat`, `chore`, `docs`, `test`, `devops`.
- **Never** add `Co-Authored-By` lines to commits.
- Single-test runs use `--no-cov` (the 90% gate only makes sense on a full run).

## Prerequisites

**None.** This plan is self-contained and must land FIRST among the Tier 2 plans — it is the foundation the agent-driving loop (PLAN 4), the CLI surface parity work (PLAN 5) and the new engineering (PLAN 6) all build on.

Symbols this plan **produces** that other plans consume:

| Symbol | Consumer |
|---|---|
| `session_server.StaleFieldIndexError` | PLAN 4 (renders it), PLAN 5 |
| `SessionHandler._fields_url: str \| None` | PLAN 4 |
| `SessionHandler._invalidate_fields() -> None` | PLAN 4, PLAN 5, PLAN 6 (every new navigating op must call it) |
| `SessionHandler.fields_stale() -> bool` | PLAN 4 — `_post_state()`'s `"fields_stale"` key MUST call this, not re-derive staleness |
| `SessionHandler.bind_stop(stop: threading.Event) -> None` | PLAN 6 (named sessions re-implement `serve()`) |
| `_op_get_text` / `_op_get_attribute` returning `{"value": str \| None, "present": bool}` | PLAN 4 (renders `--json` / `--raw`) |
| `session_client.socket_timeout_for(args) -> float` | PLAN 6 |
| `session_client.kill(*, start_dir=None) -> str` | PLAN 6 (`session kill-all` iterates over it) |
| `console.render_value(result) -> str` | PLAN 4 |

Symbols this plan **consumes**: none from other plans.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/visus/web/cli/session_server.py` | MODIFIED — field-cache staleness contract, lock reclamation, per-handler mutex, honest last-tab close, read-only observation ops, graceful shutdown, idle reaper, rotating log, constant-time token check, owner-only session file |
| `src/visus/web/cli/session_client.py` | MODIFIED — lock cleanup, `kill()`, daemon-log tail on start timeout, op-derived socket timeout, single liveness probe for `status()`, memoised pid probe |
| `src/visus/web/cli/main.py` | MODIFIED — `visus session kill`, `--idle-timeout` on `session start`, honest `tab-close` message, null-vs-empty rendering, non-`SessionError` failures mapped to a clean exit |
| `src/visus/web/cli/console.py` | MODIFIED — `render_value()` helper, REPL `screenshot` path resolved against the client cwd, honest last-tab message |
| `tests/fixtures/stale_a.html` | NEW — page A of the stale-index pair (Task 1) |
| `tests/fixtures/stale_b.html` | NEW — page B of the stale-index pair (Task 1) |
| `tests/fixtures/nullvsempty.html` | NEW — empty-vs-absent text and attribute cases (Task 12) |
| `tests/test_cli_session.py` | MODIFIED — most new tests land here, alongside the existing fakes and `_serve_in_thread` helper |
| `tests/test_e2e_cli_session.py` | MODIFIED — cross-process hard-kill recovery, get-text payload shape |

---

### Task 1: Field-cache staleness contract (`StaleFieldIndexError` + URL stamp)

The critical bug: `_resolve_field` (`session_server.py:185-196`) only bounds-checks `self._fields`, then re-resolves the stored selector against whatever page is loaded now. The selector generator (`backends/selenium/js/bundle.js:520-584`) falls through to generic selectors like `button.btn.primary`, `input[type="email"]` and bare tags, each of which matches *something* on a different page — so `visus click 3` returns `"clicked"` while having clicked the wrong element, silently.

This task adds the URL stamp that catches **JS-driven** navigation (link clicks, form submits, SPA routing). Task 2 adds the belt-and-braces clear for the explicit navigation ops.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:84-101` (`__init__`), `:162-168` (`close`), `:185-196` (`_resolve_field`), `:235-243` (`_op_list_fields`)
- Create: `tests/fixtures/stale_a.html`
- Create: `tests/fixtures/stale_b.html`
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces: `class StaleFieldIndexError(RuntimeError)`, `SessionHandler._fields_url: str | None`, `SessionHandler._invalidate_fields() -> None`, `SessionHandler.fields_stale() -> bool`
- Consumes: nothing

- [ ] **Step 1: Write the two fixture pages**

Create `tests/fixtures/stale_a.html` with exactly this content:

```html
<!doctype html>
<html>
  <head><title>stale A</title></head>
  <body>
    <h1 id="amarker">Page A</h1>

    <!-- Three leading inputs so the nameless button below lands at field INDEX 3. -->
    <input id="a_one" placeholder="one" />
    <input id="a_two" placeholder="two" />
    <input id="a_three" placeholder="three" />

    <!-- No id / name / test hook / aria-label AND no accessible name (empty
         content), so bundle.js bestLocator falls all the way through to the
         minimal-CSS tier and emits the GENERIC selector `button.btn.primary`.
         The same generic selector also matches a DIFFERENT button on page B —
         which is exactly how a stale index used to click the wrong element. -->
    <button class="btn primary" style="width:120px;height:32px;"
            onclick="document.body.dataset.clicked='A'"></button>

    <!-- Navigating by CLICKING this link is a JS/DOM navigation: it never goes
         through the daemon's `goto` op, so only the URL stamp can catch it. -->
    <a id="tob" href="stale_b.html">Go to B</a>
  </body>
</html>
```

Create `tests/fixtures/stale_b.html` with exactly this content:

```html
<!doctype html>
<html>
  <head><title>stale B</title></head>
  <body>
    <h1 id="bmarker">Page B</h1>

    <!-- Only ONE leading input, so `button.btn.primary` sits at field index 1
         here and at index 3 on page A: the same cached index means two
         different buttons. -->
    <input id="b_first" placeholder="first" />

    <!-- Same generic fallback selector as page A's button, different action. -->
    <button class="btn primary" style="width:120px;height:32px;"
            onclick="document.body.dataset.clicked='B'"></button>

    <a id="toa" href="stale_a.html">Back to A</a>
  </body>
</html>
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_cli_session.py`:

```python
@pytest.mark.browser
def test_index_targeting_refuses_after_a_js_driven_navigation(base_url: str) -> None:
    """A cached index must never re-resolve against a page it was not captured on.

    The two fixtures share the generic fallback selector `button.btn.primary`, so
    before this fix `click <index>` returned "clicked" having hit page B's button.
    """
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/stale_a.html"
    )
    try:
        fields = h.handle("list_fields", {"highlight": False})["result"]["fields"]
        by_locator = {f["locator"]: f["index"] for f in fields}
        assert "button.btn.primary" in by_locator, by_locator
        btn_idx = by_locator["button.btn.primary"]
        link_idx = by_locator["#tob"]

        # Navigate by CLICKING the link: a JS/DOM navigation that never reaches
        # the `goto` op, so only the URL stamp can catch it.
        assert h.handle("click", {"index": link_idx})["ok"] is True
        assert h.handle(
            "wait", {"selector": "#bmarker", "state": "visible", "timeout": 5000}
        )["result"] == "element is visible"

        resp = h.handle("click", {"index": btn_idx})
        assert resp["ok"] is False
        assert "StaleFieldIndexError" in resp["error"]
        assert "run list-fields again" in resp["error"]

        # Proof the risk was real: the stale selector DOES match an element here,
        # and it was not clicked.
        assert h.handle("count", {"selector": "button.btn.primary"})["result"] == 1
        clicked = h.handle(
            "eval", {"expression": "() => document.body.dataset.clicked || ''"}
        )["result"]["result"]
        assert clicked == "", f"a stale index clicked the wrong element: {clicked!r}"

        # A fresh list_fields re-stamps and the SAME selector is a different index.
        fresh = h.handle("list_fields", {"highlight": False})["result"]["fields"]
        fresh_by_locator = {f["locator"]: f["index"] for f in fresh}
        assert fresh_by_locator["button.btn.primary"] != btn_idx
        assert h.handle(
            "click", {"index": fresh_by_locator["button.btn.primary"]}
        )["ok"] is True
        assert h.handle(
            "eval", {"expression": "() => document.body.dataset.clicked || ''"}
        )["result"]["result"] == "B"
    finally:
        h.close()


def test_fields_stale_predicate() -> None:
    """fields_stale() is the single source of truth PLAN 4's page footer reads."""
    h = session_server.SessionHandler(engine="chrome", headless=True)
    assert h.fields_stale() is True  # no browser, no cache

    page = _FakePage()
    h = _handler_with_fake_page(page)
    assert h.fields_stale() is True  # browser up, but nothing cached yet
    h.handle("list_fields", {})
    assert h.fields_stale() is False
    assert h._fields_url == page.url
    page.url = "http://elsewhere.test/"
    assert h.fields_stale() is True


def test_invalidate_fields_drops_cache_and_stamp() -> None:
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("list_fields", {})
    assert h._fields and h._fields_url is not None
    h._invalidate_fields()
    assert h._fields == [] and h._fields_url is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "js_driven_navigation or fields_stale_predicate or invalidate_fields" -v --no-cov`
Expected: FAIL — `AttributeError: 'SessionHandler' object has no attribute 'fields_stale'` and, for the browser test, `assert False` on `resp["ok"] is False` (the stale click currently succeeds).

- [ ] **Step 4: Write the implementation**

In `src/visus/web/cli/session_server.py`, add the exception class immediately after `make_locator` (before `class SessionHandler`):

```python
class StaleFieldIndexError(RuntimeError):
    """Raised when a cached field index no longer belongs to the current page.

    Index targeting re-resolves a stored selector against whatever page is loaded
    now. Generated selectors intentionally fall back to generic forms
    (``button[type="submit"]``, ``input[type="email"]``, ``.btn.primary``, a bare
    tag), each of which matches *something* on a different page — so without this
    guard a stale index clicks the wrong element and reports success.
    """
```

In `SessionHandler.__init__`, after `self._fields: list[Field] = []` (`:99`), add:

```python
        self._fields_url: str | None = None
```

Replace `close()` (`:162-168`) with:

```python
    def close(self) -> None:
        if self._browser is not None:
            self._browser.close()
        self._browser = None
        self._context = None
        self._page = None
        self._invalidate_fields()
```

Add these two methods immediately after `close()`:

```python
    def _invalidate_fields(self) -> None:
        """Drop the cached field list and its page stamp — index targeting is void."""
        self._fields = []
        self._fields_url = None

    def fields_stale(self) -> bool:
        """True when cached field indexes no longer address the current page.

        The single source of truth for staleness: never raises, so a status/footer
        caller can read it unconditionally.
        """
        if self._browser is None or not self._fields or self._fields_url is None:
            return True
        try:
            return self.page().url != self._fields_url
        except Exception:  # noqa: BLE001 — an unreadable page is a stale page
            return True
```

Replace `_resolve_field` (`:185-196`) with:

```python
    def _resolve_field(self, index: int) -> Locator:
        """Re-resolve a cached field for an action via the foundation contract."""
        if index < 0 or index >= len(self._fields):
            raise IndexError(
                f"field index {index} out of range "
                f"(have {len(self._fields)}; run list_fields first)"
            )
        if self._fields_url is not None:
            current = self.page().url
            if current != self._fields_url:
                raise StaleFieldIndexError(
                    f"field indexes were captured on {self._fields_url}, "
                    f"page is now {current} — run list-fields again"
                )
        field = self._fields[index]
        root: Any = self.page()
        for sel in field.frame:
            root = root.frame_locator(sel)
        return cast(Locator, root.locator(field.locator, deep=field.deep))
```

Replace `_op_list_fields` (`:235-243`) with:

```python
    def _op_list_fields(self, args: dict[str, Any]) -> dict[str, Any]:
        kinds = args.get("kinds")
        include_hidden = bool(args.get("include_hidden", False))
        highlight = bool(args.get("highlight", True))
        page = self.page()
        fields = page.list_fields(
            kinds=kinds, include_hidden=include_hidden, highlight=highlight
        )
        self._fields = list(fields)
        # Stamp the page identity so a later index op can tell the page moved.
        self._fields_url = page.url
        return {"fields": [f.to_dict() for f in fields]}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "js_driven_navigation or fields_stale_predicate or invalidate_fields" -v --no-cov`
Expected: PASS (3 passed)

- [ ] **Step 6: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 7: Commit**

```bash
git add src/visus/web/cli/session_server.py tests/fixtures/stale_a.html tests/fixtures/stale_b.html tests/test_cli_session.py
git commit -m "fix(cli): reject stale field indexes after a page change"
```

---

### Task 2: Navigation ops invalidate the field cache

`_op_goto` (`:275-279`), `_op_back` (`:301-304`), `_op_forward` (`:306-309`) and `_op_reload` (`:311-314`) never touch `self._fields`, unlike the explicit clears at `:410` (`tab_new`), `:443` (`tab_close`) and `:563` (`tab`). Task 1's URL stamp already turns this into a clean error, but the *right* behaviour for an explicit navigation is to drop the cache outright: the user gets `run list_fields first` (an obviously-actionable message) instead of a staleness complaint.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:275-279`, `:301-314`, `:398-421` (`_op_tab_new`), `:423-456` (`_op_tab_close`), `:547-569` (`_op_tab`)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Consumes: `SessionHandler._invalidate_fields() -> None` (Task 1)
- Produces: nothing new

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_session.py`:

```python
def test_navigation_ops_invalidate_the_field_cache() -> None:
    """goto/back/forward/reload drop cached indexes — like tab/tab_new/tab_close."""
    for op, args in (
        ("goto", {"url": "http://elsewhere.test/"}),
        ("back", {}),
        ("forward", {}),
        ("reload", {}),
    ):
        page = _FakePage()
        h = _handler_with_fake_page(page)
        h.handle("list_fields", {})
        assert h._fields, op
        assert h.handle(op, args)["ok"] is True, op
        assert h._fields == [], f"{op} left the field cache in place"
        assert h._fields_url is None, f"{op} left the page stamp in place"
        resp = h.handle("click", {"index": 0})
        assert resp["ok"] is False, op
        assert "run list_fields first" in resp["error"], op


def test_tab_ops_also_drop_the_page_stamp() -> None:
    """The pre-existing `self._fields = []` sites must clear the stamp too."""
    page = _FakePage()
    h = _handler_with_fake_page(page)
    h.handle("list_fields", {})
    h._invalidate_fields()
    assert h._fields_url is None
    # tab ops need a real driver, so assert the source contract instead: every
    # site that empties the cache goes through _invalidate_fields(), so the only
    # remaining literal is the one inside _invalidate_fields itself.
    src = Path(session_server.__file__).read_text(encoding="utf-8")
    assert src.count("self._fields = []") == 1, (
        "clear the cache via self._invalidate_fields(); the only literal "
        "`self._fields = []` belongs inside _invalidate_fields itself"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "navigation_ops_invalidate or tab_ops_also_drop" -v --no-cov`
Expected: FAIL — `AssertionError: goto left the field cache in place`, and `AssertionError: clear the cache with self._invalidate_fields(), never 'self._fields = []'`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/session_server.py`, replace `_op_goto` (`:275-279`) with:

```python
    def _op_goto(self, args: dict[str, Any]) -> str:
        url = args["url"]
        page = self.page()
        page.goto(url)
        self._invalidate_fields()  # cached indexes belonged to the previous page
        return page.url
```

Replace the three navigation ops (`:301-314`) with:

```python
    # --- navigation ------------------------------------------------------
    def _op_back(self, args: dict[str, Any]) -> str:
        page = self.page()
        page.go_back()
        self._invalidate_fields()  # cached indexes belonged to the previous page
        return page.url

    def _op_forward(self, args: dict[str, Any]) -> str:
        page = self.page()
        page.go_forward()
        self._invalidate_fields()  # cached indexes belonged to the previous page
        return page.url

    def _op_reload(self, args: dict[str, Any]) -> str:
        page = self.page()
        page.reload()
        self._invalidate_fields()  # a reload rebuilds the DOM from scratch
        return page.url
```

In `_op_tab_new`, replace the line `self._fields = []` (`:410`) with:

```python
        self._invalidate_fields()
```

In `_op_tab_close`, replace the line `self._fields = []` (`:443`) with:

```python
        self._invalidate_fields()
```

In `_op_tab`, replace the line `self._fields = []  # cached field indices belonged to the previous tab` (`:563`) with:

```python
        self._invalidate_fields()  # cached indexes belonged to the previous tab
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "navigation_ops_invalidate or tab_ops_also_drop" -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the affected browser tests**

Run: `uv run pytest tests/test_cli_session.py -m browser -k "real_back_forward_reload or real_tab_new_and_close or manual_tab_switch" -v --no-cov`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/session_server.py tests/test_cli_session.py
git commit -m "fix(cli): drop cached field indexes on goto/back/forward/reload"
```

---

### Task 3: Reclaim a session lock whose owner process is dead

`_claim_lock` (`:654-671`) writes `os.getpid()` at `:668` and **nothing in the repo ever reads it back**. The unlink happens only in `serve()`'s `finally` (`:733`), which never runs on `kill -9` or a reboot. The next `visus session start` spawns a daemon that hits `SessionLockedError`, logs into `.visus/daemon.log` and exits silently; the user waits 20 s and gets "daemon did not come up within 20s".

**Files:**
- Modify: `src/visus/web/cli/session_server.py:15-34` (imports), `:654-671` (`_claim_lock`)
- Test: `tests/test_cli_session.py`, `tests/test_e2e_cli_session.py`

**Interfaces:**
- Produces: `session_server._read_lock_pid(lock: Path) -> int`
- Consumes: `session_client._pid_alive(pid: int) -> bool` (existing, `session_client.py:24-46`)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_session.py`:

```python
def _exited_pid() -> int:
    """A pid that genuinely belonged to a process which has now exited."""
    import subprocess
    import sys as _sys

    proc = subprocess.Popen([_sys.executable, "-c", ""])
    proc.wait(timeout=30)
    return proc.pid


def test_claim_lock_reclaims_a_lock_whose_owner_is_dead(tmp_path: Path) -> None:
    """A `kill -9`'d daemon leaves its lock behind; the next daemon must reclaim it."""
    import os as _os

    sf = session_server.session_file(tmp_path)
    sf.parent.mkdir(parents=True, exist_ok=True)
    lock = sf.with_name(sf.name + ".lock")
    lock.write_text(str(_exited_pid()), encoding="utf-8")

    claimed = session_server._claim_lock(sf)
    assert claimed == lock
    assert lock.read_text(encoding="utf-8") == str(_os.getpid())


def test_claim_lock_refuses_while_the_owner_is_alive(tmp_path: Path) -> None:
    """A live owner still wins: the TOCTOU guard must not become a no-op."""
    import os as _os

    sf = session_server.session_file(tmp_path)
    sf.parent.mkdir(parents=True, exist_ok=True)
    lock = sf.with_name(sf.name + ".lock")
    lock.write_text(str(_os.getpid()), encoding="utf-8")  # THIS process is alive

    with pytest.raises(session_server.SessionLockedError, match="already holds"):
        session_server._claim_lock(sf)
    assert lock.read_text(encoding="utf-8") == str(_os.getpid())  # untouched


def test_claim_lock_reclaims_an_unreadable_lock(tmp_path: Path) -> None:
    """An empty/garbage lock carries no owner, so it is orphaned by definition."""
    import os as _os

    sf = session_server.session_file(tmp_path)
    sf.parent.mkdir(parents=True, exist_ok=True)
    lock = sf.with_name(sf.name + ".lock")
    lock.write_text("", encoding="utf-8")

    session_server._claim_lock(sf)
    assert lock.read_text(encoding="utf-8") == str(_os.getpid())
```

Append to `tests/test_e2e_cli_session.py` (add `import subprocess`, `import signal` and `import sys` to its imports):

```python
def _hard_kill(pid: int) -> None:
    """SIGKILL / `taskkill /F` — no cleanup handler runs, exactly like a crash."""
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=15
        )
    else:
        os.kill(pid, signal.SIGKILL)


@pytest.mark.browser
def test_start_recovers_after_the_daemon_is_hard_killed(tmp_path: Path) -> None:
    """A hard-killed daemon leaves session.json AND session.json.lock behind.

    The next `session start` must come up anyway instead of wedging until the
    20 s timeout with a message that never mentions the lock.
    """
    first = session_client.start_daemon("chrome", headless=True, url=_PAGE, cwd=tmp_path)
    first_pid = int(first["pid"])
    lock = tmp_path / ".visus" / "session.json.lock"
    assert lock.is_file(), "the daemon should hold a lock while serving"

    _hard_kill(first_pid)
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline and _pid_alive(first_pid):
        time.sleep(0.2)
    assert not _pid_alive(first_pid)
    assert lock.is_file(), "the orphaned lock is the precondition of this test"

    second = session_client.start_daemon(
        "chrome", headless=True, url=_PAGE, cwd=tmp_path, timeout=30.0
    )
    try:
        assert int(second["pid"]) != first_pid
        assert session_client.send("url", start_dir=tmp_path)
    finally:
        session_client.stop(start_dir=tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k claim_lock -v --no-cov`
Expected: FAIL — `test_claim_lock_reclaims_a_lock_whose_owner_is_dead` raises `SessionLockedError: another daemon already holds ...`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/session_server.py`, add to the `visus.web` import block (after `from visus.web.backends.selenium.driver_delegate import SeleniumPageDelegate`, `:34`):

```python
from visus.web.cli import session_client
```

Replace `_claim_lock` (`:654-671`) with:

```python
def _read_lock_pid(lock: Path) -> int:
    """The pid recorded in *lock*, or ``-1`` when it is missing/empty/garbage."""
    try:
        return int(lock.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return -1


def _claim_lock(sf: Path) -> Path:
    """Atomically claim ownership for this daemon (O_CREAT|O_EXCL lock file).

    Closes the TOCTOU between ``find_session() is None`` and ``Popen`` in the
    client: two concurrent daemons cannot both claim the lock, so the loser
    exits immediately (before serving / launching a browser) instead of running
    forever untracked with a live driver.

    A lock left behind by a daemon that was killed (``kill -9``, reboot, power
    cut) would otherwise wedge every future ``visus session start`` forever, so
    the pid written into the lock is read back: when its owner is gone the lock
    is removed and claimed on ONE retry. A live rival that grabs it in between
    wins that retry, which keeps the mutual-exclusion guarantee intact.
    """
    lock = sf.with_name(sf.name + ".lock")
    for attempt in (0, 1):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            owner = _read_lock_pid(lock)
            if attempt == 0 and not session_client._pid_alive(owner):
                try:
                    lock.unlink()
                except OSError:
                    pass
                continue
            raise SessionLockedError(
                f"another daemon already holds {lock} (owner pid {owner})"
            ) from exc
        try:
            os.write(fd, str(os.getpid()).encode("utf-8"))
        finally:
            os.close(fd)
        return lock
    raise SessionLockedError(f"another daemon already holds {lock}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "claim_lock or second_daemon_aborts" -v --no-cov`
Expected: PASS (4 passed)

Run: `uv run pytest tests/test_e2e_cli_session.py::test_start_recovers_after_the_daemon_is_hard_killed -v --no-cov`
Expected: PASS

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/session_server.py tests/test_cli_session.py tests/test_e2e_cli_session.py
git commit -m "fix(cli): reclaim an orphaned session lock when its owner is dead"
```

---

### Task 4: Stale-file cleanup removes the lock as well

`find_session` (`session_client.py:69-89`) deletes a stale `session.json` via `_cleanup` (`:92-96`) but leaves the `.lock`. Same for `stop()` (`:197-214`): it swallows shutdown failures at `:202-205`, waits 10 s, then `_cleanup`s only the json — so `visus session stop` against a wedged daemon prints "session stopped" and leaves the lock behind.

Fixing `_cleanup` fixes both paths at once.

**Files:**
- Modify: `src/visus/web/cli/session_client.py:92-96`
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces: `session_client._cleanup(sf: Path) -> None` (unchanged signature, widened behaviour)
- Consumes: nothing

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_session.py`:

```python
def test_cleanup_removes_the_lock_beside_the_session_file(tmp_path: Path) -> None:
    sf = _write_session(tmp_path, {"pid": 1, "port": 2, "token": "t"})
    lock = sf.with_name(sf.name + ".lock")
    lock.write_text("999999", encoding="utf-8")
    session_client._cleanup(sf)
    assert not sf.exists()
    assert not lock.exists(), "the orphaned lock survived cleanup"


def test_find_session_stale_cleanup_removes_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sf = _write_session(tmp_path, {"pid": 999999, "port": 1, "token": "t"})
    lock = sf.with_name(sf.name + ".lock")
    lock.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(session_client, "_pid_alive", lambda pid: False)
    assert session_client.find_session(tmp_path) is None
    assert not sf.exists() and not lock.exists()


def test_stop_on_a_wedged_daemon_removes_the_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`visus session stop` must not print success while leaving the lock."""
    sf = _write_session(tmp_path, {"pid": 1, "port": 9, "token": "t"})
    lock = sf.with_name(sf.name + ".lock")
    lock.write_text("1", encoding="utf-8")
    info = {"pid": 1, "port": 9, "token": "t", "_file": str(sf)}
    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None: info)
    monkeypatch.setattr(
        session_client,
        "_send_raw",
        lambda *a, **kw: (_ for _ in ()).throw(OSError("connection refused")),
    )
    assert session_client.stop(start_dir=tmp_path) == "session stopped"
    assert not sf.exists() and not lock.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "cleanup_removes_the_lock or stale_cleanup_removes_the_lock or wedged_daemon_removes" -v --no-cov`
Expected: FAIL — `AssertionError: the orphaned lock survived cleanup`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/session_client.py`, replace `_cleanup` (`:92-96`) with:

```python
def _cleanup(sf: Path) -> None:
    """Remove a dead session's state: the session file AND its ownership lock.

    Deleting only ``session.json`` leaves ``session.json.lock`` behind, and the
    daemon claims that lock BEFORE binding — so the next ``session start`` aborts
    on a lock nobody owns and the user only sees a 20 s timeout.
    """
    for path in (sf, sf.with_name(sf.name + ".lock")):
        try:
            path.unlink()
        except OSError:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "cleanup or find_session or stop" -v --no-cov`
Expected: PASS (all selected tests pass, including the pre-existing `test_find_session_cleans_*` and `test_stop_swallows_send_failure_on_dead_socket`)

- [ ] **Step 5: Commit**

```bash
git add src/visus/web/cli/session_client.py tests/test_cli_session.py
git commit -m "fix(cli): remove the session lock together with a stale session file"
```

---

### Task 5: `visus session kill` — force-clear wedged session state

There is no escape hatch today: if a lock or session file survives in a state neither `start` nor `stop` resolves, the CLI is unusable in that directory tree.

**Files:**
- Modify: `src/visus/web/cli/session_client.py:8-17` (imports), append `_find_lock_file`, `_terminate`, `kill`
- Modify: `src/visus/web/cli/main.py:255-261` (next to `session_stop`)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces: `session_client.kill(*, start_dir: str | Path | None = None) -> str`, `session_client._find_lock_file(start_dir) -> Path | None`, `session_client._terminate(pid: int) -> None`; CLI command `visus session kill`
- Consumes: `session_client._cleanup` (Task 4), `session_client._pid_alive` (existing)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_session.py`:

```python
def test_kill_removes_json_and_lock_and_reports(tmp_path: Path) -> None:
    sf = _write_session(tmp_path, {"pid": _exited_pid(), "port": 2, "token": "t"})
    lock = sf.with_name(sf.name + ".lock")
    lock.write_text("999999", encoding="utf-8")
    msg = session_client.kill(start_dir=tmp_path)
    assert not sf.exists() and not lock.exists()
    assert "session.json" in msg and "session.json.lock" in msg


def test_kill_removes_an_orphaned_lock_with_no_session_file(tmp_path: Path) -> None:
    """The wedge case: the json was cleaned, the lock was not."""
    visus = tmp_path / ".visus"
    visus.mkdir(parents=True)
    lock = visus / "session.json.lock"
    lock.write_text(str(_exited_pid()), encoding="utf-8")
    msg = session_client.kill(start_dir=tmp_path)
    assert not lock.exists()
    assert "session.json.lock" in msg


def test_kill_with_nothing_to_remove(tmp_path: Path) -> None:
    assert session_client.kill(start_dir=tmp_path) == "no session state to remove"


def test_kill_terminates_a_live_daemon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[int] = []
    sf = _write_session(tmp_path, {"pid": 4242, "port": 2, "token": "t"})
    sf.with_name(sf.name + ".lock").write_text("4242", encoding="utf-8")
    monkeypatch.setattr(session_client, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(session_client, "_terminate", killed.append)
    msg = session_client.kill(start_dir=tmp_path)
    assert killed == [4242]
    assert "killed daemon pid 4242" in msg


def test_cli_session_kill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "kill", lambda: "removed session.json")
    r = runner.invoke(app, ["session", "kill"])
    assert r.exit_code == 0 and "removed session.json" in r.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "kill" -v --no-cov`
Expected: FAIL — `AttributeError: module 'visus.web.cli.session_client' has no attribute 'kill'`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/session_client.py`, add `import signal` to the import block (between `import os` and `import socket`, keeping alphabetical order for ruff's `I` rule: `json`, `os`, `signal`, `socket`, `subprocess`, `sys`, `time`).

Append at the end of the module:

```python
def _find_lock_file(start_dir: str | Path | None = None) -> Path | None:
    """Search upward from *start_dir* for ``.visus/session.json.lock`` (git-style).

    A wedged project has the LOCK but no session file, so the lock needs its own
    discovery walk — :func:`_find_session_file` would return ``None``.
    """
    cur = Path(start_dir) if start_dir is not None else Path.cwd()
    cur = cur.resolve()
    for d in [cur, *cur.parents]:
        candidate = d / ".visus" / "session.json.lock"
        if candidate.is_file():
            return candidate
    return None


def _terminate(pid: int) -> None:
    """Best-effort terminate of a daemon process (``taskkill`` / ``SIGTERM``)."""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10
            )
        except Exception:
            pass
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def kill(*, start_dir: str | Path | None = None) -> str:
    """Force-clear this project's session state. Returns a status message.

    The escape hatch for a wedged daemon: ``stop()`` needs a reachable socket and
    ``start()`` refuses while a lock exists, so neither can recover a process that
    was killed mid-flight. ``kill`` terminates the recorded pid when it is still
    alive and deletes ``session.json`` and ``session.json.lock`` unconditionally.
    """
    removed: list[str] = []
    pid = -1

    sf = _find_session_file(start_dir)
    if sf is not None:
        try:
            info: dict[str, Any] = json.loads(sf.read_text(encoding="utf-8"))
            pid = int(info.get("pid", -1))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pid = -1
        lock_beside = sf.with_name(sf.name + ".lock")
        had_lock = lock_beside.is_file()
        _cleanup(sf)  # removes the session file AND the lock beside it
        removed.append(sf.name)
        if had_lock:
            removed.append(lock_beside.name)

    lock = _find_lock_file(start_dir)
    if lock is not None:
        if pid <= 0:
            try:
                pid = int(lock.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                pid = -1
        try:
            lock.unlink()
            removed.append(lock.name)
        except OSError:
            pass

    if pid > 0 and _pid_alive(pid):
        _terminate(pid)
        return f"killed daemon pid {pid}; removed {', '.join(removed) or 'nothing'}"
    if not removed:
        return "no session state to remove"
    return f"removed {', '.join(removed)}"
```

In `src/visus/web/cli/main.py`, add the command immediately after `session_stop` (`:255-261`):

```python
@session_app.command("kill")
def session_kill() -> None:
    """Force-clear a wedged session: terminate the daemon and delete its state.

    Use when `visus session start` reports a timeout or `visus session stop`
    cannot reach the daemon — those paths cannot recover a process that was
    killed mid-flight and left `.visus/session.json.lock` behind.
    """
    from visus.web.cli import session_client

    typer.echo(session_client.kill())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "kill" -v --no-cov`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/session_client.py src/visus/web/cli/main.py tests/test_cli_session.py
git commit -m "feat(cli): add `visus session kill` to force-clear wedged session state"
```

---

### Task 6: Start timeout reports the daemon log tail

`start_daemon`'s timeout message (`session_client.py:191-194`) says "daemon did not come up within 20s (see .../daemon.log)". The actual cause — `daemon aborting: another daemon already holds ...`, a driver failure, a bad URL — is sitting in that file and nobody reads it.

**Files:**
- Modify: `src/visus/web/cli/session_client.py:191-194`
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces: `session_client._log_tail(base: Path, *, lines: int = 20) -> str`
- Consumes: nothing

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_session.py`:

```python
def test_start_daemon_timeout_reports_the_real_daemon_log(tmp_path: Path) -> None:
    """A wedged start must show WHY, not just "did not come up within Ns".

    Fully real: the lock is held by THIS (live) process, so a genuinely spawned
    daemon aborts on the lock and writes its reason to .visus/daemon.log before
    exiting — no browser is ever launched on that path.
    """
    import os as _os

    visus = tmp_path / ".visus"
    visus.mkdir(parents=True)
    (visus / "session.json.lock").write_text(str(_os.getpid()), encoding="utf-8")

    with pytest.raises(session_client.SessionError) as excinfo:
        session_client.start_daemon("chrome", True, None, cwd=tmp_path, timeout=8.0)

    message = str(excinfo.value)
    assert "did not come up within 8s" in message
    assert "daemon aborting" in message, message
    assert "already holds" in message, message


def test_log_tail_of_a_missing_log_is_empty(tmp_path: Path) -> None:
    assert session_client._log_tail(tmp_path) == ""


def test_log_tail_returns_only_the_last_lines(tmp_path: Path) -> None:
    visus = tmp_path / ".visus"
    visus.mkdir(parents=True)
    (visus / "daemon.log").write_text(
        "\n".join(f"line {i}" for i in range(50)), encoding="utf-8"
    )
    tail = session_client._log_tail(tmp_path, lines=3)
    assert tail == "line 47\nline 48\nline 49"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "log_tail or timeout_reports_the_real" -v --no-cov`
Expected: FAIL — `AttributeError: module 'visus.web.cli.session_client' has no attribute '_log_tail'`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/session_client.py`, add above `start_daemon` (before `:129`):

```python
def _log_tail(base: Path, *, lines: int = 20) -> str:
    """The last *lines* of ``<base>/.visus/daemon.log``, or ``""`` when unreadable."""
    log = base / ".visus" / "daemon.log"
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])
```

Replace the closing `raise SessionError(...)` of `start_daemon` (`:191-194`) with:

```python
    log_path = base / ".visus" / "daemon.log"
    tail = _log_tail(base)
    if tail:
        detail = f"\n--- last lines of {log_path} ---\n{tail}"
    else:
        detail = f" (no output in {log_path})"
    raise SessionError(f"daemon did not come up within {timeout:.0f}s{detail}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "log_tail or timeout_reports_the_real" -v --no-cov`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/visus/web/cli/session_client.py tests/test_cli_session.py
git commit -m "fix(cli): show the daemon log tail when a session fails to start"
```

---

### Task 7: Closing the last tab genuinely stops the daemon

`_op_tab_close` (`:444-446`) calls `self.close()` without ever setting the server's stop event (`stop` lives in `serve()`'s frame at `:712` and is unreachable from the handler). `close()` (`:162-168`) nils the browser but the socket stays bound and `session.json` stays on disk, so `main.py:743-745`'s "closed the last tab — session stopped" is a lie: the next op hits `_ensure()` (`:104-119`), launches a **new** browser and re-`goto`s `self._url` — an agent that had logged in silently finds itself logged out on the landing page. Meanwhile `_op_status` (`:571-572`) reports `running: False` while `session.json` still advertises a live pid/port that `find_session` accepts.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:84-101` (`__init__`), `:423-456` (`_op_tab_close`), `:674-735` (`serve`)
- Modify: `src/visus/web/cli/main.py:737-746` (`tab_close`)
- Modify: `src/visus/web/cli/console.py:206-210` (`tab-close` branch)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces: `SessionHandler.bind_stop(stop: threading.Event) -> None`; `tab_close` result gains `"session_stopped": bool`
- Consumes: nothing

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_session.py`:

```python
@pytest.mark.browser
def test_closing_the_last_tab_really_stops_the_daemon(tmp_path: Path) -> None:
    """The socket must close and session.json must go — otherwise the next op
    launches a BRAND-NEW browser and the login is silently gone."""
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url="data:text/html,<title>only</title>"
    )
    token = "tok"
    t, port = _serve_in_thread(h, token, tmp_path)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=30) as sock:
            f = sock.makefile("rwb")
            payload = {"token": token, "op": "tab_close", "args": {}}
            f.write((json.dumps(payload) + "\n").encode("utf-8"))
            f.flush()
            resp = json.loads(f.readline().decode("utf-8"))
        assert resp["ok"] is True
        assert resp["result"] == {"closed": 0, "remaining": 0, "session_stopped": True}
        t.join(timeout=20)
        assert not t.is_alive(), "the daemon kept serving after the last tab closed"
        assert not session_server.session_file(tmp_path).is_file()
        assert not (tmp_path / ".visus" / "session.json.lock").exists()
    finally:
        if t.is_alive():
            _shutdown_thread(t, port, token)
        h.close()


def test_bind_stop_is_optional() -> None:
    """An unbound handler (unit tests, embedders) reports session_stopped=False."""
    import threading as _threading

    h = session_server.SessionHandler(engine="chrome", headless=True)
    assert h._stop is None
    ev = _threading.Event()
    h.bind_stop(ev)
    assert h._stop is ev


def test_cli_tab_close_last_tab_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: {"closed": 0, "remaining": 0, "session_stopped": True},
    )
    r = runner.invoke(app, ["tab-close"])
    assert r.exit_code == 0 and "session stopped" in r.output


def test_cli_tab_close_last_tab_message_when_session_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Never claim the session stopped when it did not."""
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: {"closed": 0, "remaining": 0, "session_stopped": False},
    )
    r = runner.invoke(app, ["tab-close"])
    assert r.exit_code == 0
    assert "browser is closed" in r.output and "session stopped" not in r.output


def test_dispatch_tab_close_last_tab_messages() -> None:
    def send_stopped(op: str, args: dict[str, Any]) -> Any:
        return {"closed": 0, "remaining": 0, "session_stopped": True}

    def send_alive(op: str, args: dict[str, Any]) -> Any:
        return {"closed": 0, "remaining": 0, "session_stopped": False}

    assert "session stopped" in console.dispatch("tab-close", send_stopped)
    out = console.dispatch("tab-close", send_alive)
    assert "browser is closed" in out and "session stopped" not in out
```

**Delete** the pre-existing `test_cli_tab_close_last_tab_message` at `tests/test_cli_session.py:1514-1519` — the version above replaces it (same name, new payload).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "last_tab or bind_stop" -v --no-cov`
Expected: FAIL — `AttributeError: 'SessionHandler' object has no attribute 'bind_stop'`, and the browser test times out on `t.join(timeout=20)` with `AssertionError: the daemon kept serving after the last tab closed`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/session_server.py`, add to `SessionHandler.__init__` after `self._active_handle: str | None = None` (`:101`):

```python
        self._stop: threading.Event | None = None
```

Add this method immediately after `__init__` (before `# --- lifecycle ---`):

```python
    def bind_stop(self, stop: threading.Event) -> None:
        """Give the handler the server's stop event so an op can end the daemon.

        Closing the LAST tab has to actually stop the daemon: ``close()`` alone
        leaves the socket bound and ``session.json`` on disk, and the next op
        would silently launch a brand-new browser at the original URL — losing
        whatever session state (logins, cookies in memory) the user built up.
        """
        self._stop = stop
```

Replace `_op_tab_close` (`:423-456`) with:

```python
    def _op_tab_close(self, args: dict[str, Any]) -> dict[str, Any]:
        """Close a tab by index (default: the active one), resetting the active handle.

        Closing the last tab ends the whole session: the browser is gone, so the
        daemon stops rather than pretending it can still serve.
        """
        self._ensure()
        driver = self._driver()
        if driver is None:
            raise RuntimeError("no live browser")
        handles = list(driver.window_handles)
        idx = args.get("index")
        if idx is None:
            target = self._active_handle if self._active_handle in handles else handles[-1]
            i = handles.index(target)
        else:
            i = int(idx)
            if i < 0 or i >= len(handles):
                raise IndexError(f"tab index {i} out of range (have {len(handles)} tabs)")
            target = handles[i]
        driver.switch_to.window(target)
        driver.close()
        try:
            remaining = list(driver.window_handles)
        except Exception:  # noqa: BLE001 — the driver is gone once the last window closes
            remaining = []
        self._known_handles = remaining
        self._invalidate_fields()
        if not remaining:
            self.close()
            stopped = self._stop is not None
            if self._stop is not None:
                self._stop.set()
            return {"closed": i, "remaining": 0, "session_stopped": stopped}
        self._active_handle = remaining[min(i, len(remaining) - 1)]
        try:
            driver.switch_to.window(self._active_handle)
        except Exception:  # noqa: BLE001
            pass
        return {
            "closed": i,
            "remaining": len(remaining),
            "active": remaining.index(self._active_handle),
        }
```

In `serve()`, immediately after `stop = threading.Event()` (`:712`), add:

```python
    handler.bind_stop(stop)
```

In `src/visus/web/cli/main.py`, replace `tab_close` (`:737-746`) with:

```python
@app.command("tab-close")
def tab_close(
    index: int = typer.Argument(None, help="Tab index to close (omit = the active tab)."),
) -> None:
    """Close a tab/window by index (or the active one if omitted)."""
    result = _send("tab_close", {"index": index})
    if result.get("remaining", 0) == 0:
        if result.get("session_stopped"):
            typer.echo("closed the last tab — session stopped")
        else:
            typer.echo("closed the last tab — the browser is closed")
        return
    typer.echo(f"closed tab {result['closed']} ({result['remaining']} remaining)")
```

In `src/visus/web/cli/console.py`, replace the `tab-close` branch (`:206-210`) with:

```python
        if cmd == "tab-close":
            r = send("tab_close", {"index": int(rest[0]) if rest else None})
            if r.get("remaining", 0) == 0:
                if r.get("session_stopped"):
                    return "closed the last tab — session stopped"
                return "closed the last tab — the browser is closed"
            return f"closed tab {r['closed']} ({r['remaining']} remaining)"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "last_tab or bind_stop or dispatch_tab_new_and_close or real_tab_new_and_close" -v --no-cov`
Expected: PASS (7 passed)

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py src/visus/web/cli/console.py tests/test_cli_session.py
git commit -m "fix(cli): stop the daemon when the last tab is closed"
```

---

### Task 8: Serialise every op behind a per-handler mutex

`serve()` spawns `threading.Thread(target=_handle_conn, ...)` per accepted connection (`:720-724`), all closing over the **same** `SessionHandler`. A grep for `Lock(|RLock` in `src/visus/web/cli/` finds only `threading.Event` at `:712` — there is no mutex anywhere. Shared mutable state lives at `:100-101` (`_known_handles`/`_active_handle`), `:151-160` (`_resolve_active`), `:523-545` (`_op_tabs` switches window on every handle in a loop and then restores) and `:547-569` (`_op_tab`). Two concurrent commands can land on the wrong tab or interleave WebDriver HTTP exchanges.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:84-101` (`__init__`), `:224-233` (`handle`)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces: `SessionHandler._lock: threading.RLock` (re-entrant so an op may call `handle` indirectly without deadlocking)
- Consumes: nothing

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_session.py`:

```python
def test_handle_serialises_concurrent_ops() -> None:
    """One handler, many connection threads: op bodies must never overlap.

    `serve()` runs one thread per connection over a SHARED handler, and the ops
    mutate `_known_handles`/`_active_handle` and switch the driver's window.
    """
    import threading as _threading
    import time as _time

    counter_lock = _threading.Lock()
    inside = {"now": 0, "max": 0}

    class _SlowPage(_FakePage):
        def title(self) -> str:
            with counter_lock:
                inside["now"] += 1
                inside["max"] = max(inside["max"], inside["now"])
            _time.sleep(0.05)
            with counter_lock:
                inside["now"] -= 1
            return "FakeTitle"

    h = _handler_with_fake_page(_SlowPage())
    results: list[dict[str, Any]] = []
    results_lock = _threading.Lock()

    def drive() -> None:
        resp = h.handle("title", {})
        with results_lock:
            results.append(resp)

    threads = [_threading.Thread(target=drive) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=20)

    assert len(results) == 8
    assert all(r["ok"] is True and r["result"] == "FakeTitle" for r in results)
    assert inside["max"] == 1, f"{inside['max']} ops ran concurrently on one driver"


def test_handle_lock_is_reentrant() -> None:
    """RLock, not Lock: an op that dispatches another op must not deadlock."""
    page = _FakePage()
    h = _handler_with_fake_page(page)
    with h._lock:
        assert h.handle("title", {})["result"] == "FakeTitle"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "serialises_concurrent_ops or lock_is_reentrant" -v --no-cov`
Expected: FAIL — `AssertionError: 8 ops ran concurrently on one driver` (or a number > 1), and `AttributeError: 'SessionHandler' object has no attribute '_lock'`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/session_server.py`, add to `SessionHandler.__init__` after `self._stop: threading.Event | None = None`:

```python
        # One WebDriver, one thread per connection in serve(): every op body runs
        # under this mutex. RLock (not Lock) so an op may re-enter handle().
        self._lock = threading.RLock()
```

Replace `handle` (`:224-233`) with:

```python
    def handle(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Dispatch one op. Returns ``{ok:True,result:...}`` or ``{ok:False,error:str}``.

        The whole body runs under ``self._lock``: ``serve()`` runs one thread per
        connection over a SHARED handler, and a WebDriver plus the tab bookkeeping
        in ``_known_handles``/``_active_handle`` are not safe to interleave.
        """
        args = args or {}
        with self._lock:
            try:
                method = getattr(self, f"_op_{op}", None)
                if method is None:
                    raise ValueError(f"unknown op {op!r}")
                return {"ok": True, "result": method(args)}
            except Exception as exc:  # noqa: BLE001 — daemon must never crash a client
                return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "serialises_concurrent_ops or lock_is_reentrant" -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/visus/web/cli/session_server.py tests/test_cli_session.py
git commit -m "fix(cli): serialise daemon ops behind a per-handler mutex"
```

---

### Task 9: Graceful shutdown — name, prune and join the worker threads

`serve()`'s `finally` (`:725-735`) closes the socket and the handler immediately after the accept loop exits. The `threads` list (`:713`/`:724`) is never joined and every worker is `daemon=True`, so a concurrent op runs against a driver being torn down underneath it. This fires on the ordinary `visus session stop` path, not only under user parallelism. The same list also grows forever — roughly two dead entries per command, because `find_session` opens an extra liveness connection (`session_client.py:49-56`).

**Files:**
- Modify: `src/visus/web/cli/session_server.py:674-735` (`serve`)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces: `session_server.SHUTDOWN_GRACE_SECONDS: float`, `session_server._prune(threads: list[threading.Thread]) -> list[threading.Thread]`, worker threads named `"visus-session-conn"`
- Consumes: nothing

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_session.py`:

```python
def test_prune_drops_finished_threads() -> None:
    import threading as _threading

    done = _threading.Thread(target=lambda: None)
    done.start()
    done.join(timeout=10)
    running_gate = _threading.Event()
    running = _threading.Thread(target=running_gate.wait, daemon=True)
    running.start()
    try:
        assert session_server._prune([done, running]) == [running]
    finally:
        running_gate.set()
        running.join(timeout=10)


def test_serve_joins_worker_threads_before_tearing_down(tmp_path: Path) -> None:
    """No worker may outlive serve(): a live op must not meet a closing driver."""
    import threading as _threading

    baseline = {
        t.ident for t in _threading.enumerate() if t.name == "visus-session-conn"
    }
    handler = _handler_with_fake_page(_FakePage())
    token = "tok"
    t, port = _serve_in_thread(handler, token, tmp_path)
    for _ in range(12):
        with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
            f = sock.makefile("rwb")
            f.write((json.dumps({"token": token, "op": "status"}) + "\n").encode("utf-8"))
            f.flush()
            assert json.loads(f.readline().decode("utf-8"))["ok"] is True
    _shutdown_thread(t, port, token)
    assert not t.is_alive()
    leftovers = [
        x
        for x in _threading.enumerate()
        if x.name == "visus-session-conn" and x.ident not in baseline
    ]
    assert leftovers == [], f"worker threads outlived serve(): {leftovers}"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "prune_drops_finished or joins_worker_threads" -v --no-cov`
Expected: FAIL — `AttributeError: module 'visus.web.cli.session_server' has no attribute '_prune'`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/session_server.py`, add above `def serve(` (before `:674`):

```python
# How long serve() waits for in-flight ops before tearing the driver down. Kept
# under session_client.stop()'s 10 s wait so a normal stop still observes the
# session file disappear.
SHUTDOWN_GRACE_SECONDS = 8.0


def _prune(threads: list[threading.Thread]) -> list[threading.Thread]:
    """Drop finished workers so the list cannot grow without bound.

    Every command costs about two connections (``find_session`` probes liveness
    with its own connect), so an unpruned list leaks a Thread object per probe
    for the whole life of the daemon.
    """
    return [t for t in threads if t.is_alive()]
```

Replace the accept loop and `finally` of `serve()` (`:714-735`) with:

```python
    try:
        while not stop.is_set():
            threads = _prune(threads)
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            t = threading.Thread(
                target=_handle_conn,
                args=(conn, handler, token, stop),
                name="visus-session-conn",
                daemon=True,
            )
            t.start()
            threads.append(t)
    finally:
        srv.close()
        # Let in-flight ops finish BEFORE the driver is torn down: a concurrent
        # `wait`/`expect_text` can block for tens of seconds and would otherwise
        # run against a driver closing underneath it.
        deadline = time.monotonic() + SHUTDOWN_GRACE_SECONDS
        for worker in _prune(threads):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            worker.join(timeout=remaining)
        handler.close()
        try:
            sf.unlink()
        except OSError:
            pass
        try:
            lock.unlink()
        except OSError:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "prune_drops_finished or joins_worker_threads or serve_protocol or second_daemon_aborts or non_dict_request" -v --no-cov`
Expected: PASS (all selected tests pass)

- [ ] **Step 5: Commit**

```bash
git add src/visus/web/cli/session_server.py tests/test_cli_session.py
git commit -m "fix(cli): join in-flight daemon threads before closing the driver"
```

---

### Task 10: `status` and `tabs` become genuinely read-only

`_op_status` calls `_active_page()` (`:581`) → `_resolve_active()` (`:146`), which reassigns `self._known_handles` (`:155`) and `self._active_handle` (`:157`). A background popup gets adopted as the active tab merely because an agent polled status — a *read* changing where the next `click` lands. `_op_tabs` has the same defect via `:530`.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:133-160` (add read-only peers), `:523-545` (`_op_tabs`), `:571-589` (`_op_status`)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces: `SessionHandler._peek_active(handles: list[str]) -> str`, `SessionHandler._peek_page() -> Page`
- Consumes: nothing

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_session.py`:

```python
def test_peek_active_never_adopts_a_new_handle() -> None:
    """`_peek_active` observes; `_resolve_active` deliberately auto-follows."""
    h = session_server.SessionHandler(engine="chrome", headless=True)
    h._known_handles = ["A"]
    h._active_handle = "A"

    assert h._peek_active(["A", "B"]) == "A"
    assert h._known_handles == ["A"], "an observation mutated _known_handles"
    assert h._active_handle == "A", "an observation mutated _active_handle"

    # A closed active handle still falls back to the newest window.
    assert h._peek_active(["B", "C"]) == "C"
    assert h._active_handle == "A"

    # Contrast: the ACTION path adopts the new window on purpose.
    assert h._resolve_active(["A", "B"]) == "B"
    assert h._active_handle == "B"


@pytest.mark.browser
def test_status_and_tabs_do_not_adopt_a_background_window() -> None:
    """Polling status/tabs must not silently move the session to a popup."""
    h = session_server.SessionHandler(
        engine="chrome",
        headless=True,
        url="data:text/html,<title>first</title><button id=firstbtn>First</button>",
    )
    try:
        h.handle("list_fields", {"highlight": False})  # tab 0 becomes active
        driver = h._page._delegate._driver  # type: ignore[attr-defined]
        driver.switch_to.new_window("window")
        driver.get("data:text/html,<title>second</title><button id=b2>Second</button>")
        driver.switch_to.window(driver.window_handles[0])

        st = h.handle("status", {})["result"]
        assert st["title"] == "first", "status adopted the background window"
        assert st["windows"] == 2
        assert st["active_tab"] == 0

        tabs = h.handle("tabs", {})["result"]
        assert len(tabs["tabs"]) == 2
        assert tabs["active"] == 0, "tabs adopted the background window"
        assert tabs["tabs"][0]["active"] is True

        # Repeat polling is still stable.
        assert h.handle("status", {})["result"]["title"] == "first"
        assert h.handle("tabs", {})["result"]["active"] == 0
    finally:
        h.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "peek_active or do_not_adopt" -v --no-cov`
Expected: FAIL — `AttributeError: 'SessionHandler' object has no attribute '_peek_active'`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/session_server.py`, add these two methods immediately after `_resolve_active` (`:160`):

```python
    def _peek_active(self, handles: list[str]) -> str:
        """The active handle WITHOUT adopting new windows or mutating state.

        ``status``/``tabs`` are observations: polling them must never change where
        the next click lands. ``_resolve_active`` auto-follows a new window on
        purpose — that belongs to the ACTION path only.
        """
        active = self._active_handle
        if active is not None and active in handles:
            return active
        return handles[-1]

    def _peek_page(self) -> Page:
        """The active page WITHOUT auto-following newly-opened windows."""
        self._ensure()
        if self._page is None:
            raise RuntimeError("session page is not available")
        driver = self._driver()
        if driver is None:
            return self._page  # non-selenium page (tests) — no tab tracking
        try:
            handles = list(driver.window_handles)
        except Exception:  # noqa: BLE001
            return self._page
        if not handles:
            return self._page
        handle = self._peek_active(handles)
        if getattr(self._page._delegate, "_handle", None) == handle:
            return self._page
        return Page(SeleniumPageDelegate(driver, handle), self._page._defaults)
```

Replace the `active = self._resolve_active(handles)` line in `_op_tabs` (`:530`) with:

```python
        active = self._peek_active(handles)
```

Replace `_op_status` (`:571-589`) with:

```python
    def _op_status(self, args: dict[str, Any]) -> dict[str, Any]:
        """Report session state. READ-ONLY: never adopts a background window."""
        running = self._browser is not None
        info: dict[str, Any] = {
            "running": running,
            "engine": self._engine,
            "headless": self._headless,
            "fields_cached": len(self._fields),
        }
        if running:
            try:
                p = self._peek_page()
                info["url"] = p.url
                info["title"] = p.title()
                driver = self._driver()
                handles = (
                    list(driver.window_handles)
                    if driver is not None
                    else list(self._known_handles)
                )
                info["windows"] = len(handles)
                active = self._peek_active(handles) if handles else None
                if active is not None and active in handles:
                    info["active_tab"] = handles.index(active)
            except Exception:  # noqa: BLE001
                pass
        return info
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "peek_active or do_not_adopt or follows_focus or manual_tab_switch or goto_screenshot_clear_status or status_not_running" -v --no-cov`
Expected: PASS (all selected tests pass)

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/session_server.py tests/test_cli_session.py
git commit -m "fix(cli): make session status and tabs read-only observations"
```

---

### Task 11: Socket timeout derived from the op's own timeout

`session_client._send_raw` hardcodes `timeout: float = 60.0` (`:99`) and `send()` (`:123`) never passes one through. But `main.py:688` exposes an uncapped `--timeout` in milliseconds that `_op_wait` (`:371-383`) honours literally, so `visus wait 3 --timeout 90000` aborts the socket at 60 s while the daemon is still legitimately waiting. Worse, `main._send` (`:205-213`) only catches `session_client.SessionError`, so `socket.timeout` (an `OSError` subclass) and `json.JSONDecodeError` (`:109`) escape as raw tracebacks.

**Files:**
- Modify: `src/visus/web/cli/session_client.py:113-126` (`send`), add `socket_timeout_for`
- Modify: `src/visus/web/cli/main.py:205-213` (`_send`)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces: `session_client.DEFAULT_SOCKET_TIMEOUT: float`, `session_client.SOCKET_TIMEOUT_MARGIN: float`, `session_client.socket_timeout_for(args: dict[str, Any] | None) -> float`, `session_client.send(op, args=None, *, start_dir=None, timeout: float | None = None)`
- Consumes: nothing

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_session.py`:

```python
def test_socket_timeout_for_derives_from_the_op_timeout() -> None:
    assert session_client.socket_timeout_for(None) == 60.0
    assert session_client.socket_timeout_for({}) == 60.0
    assert session_client.socket_timeout_for({"timeout": 500}) == 60.0  # floored
    assert session_client.socket_timeout_for({"timeout": 120000}) == 130.0
    assert session_client.socket_timeout_for({"timeout": "nope"}) == 60.0
    assert session_client.socket_timeout_for({"timeout": None}) == 60.0


def test_send_honours_an_explicit_socket_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The timeout genuinely reaches the socket: a silent daemon must time out."""
    import threading as _threading

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    gate = _threading.Event()

    def _accept_and_stay_silent() -> None:
        conn, _ = srv.accept()
        try:
            gate.wait(timeout=10)
        finally:
            conn.close()

    th = _threading.Thread(target=_accept_and_stay_silent, daemon=True)
    th.start()
    _write_session(tmp_path, {"pid": 1, "port": port, "token": "t"})
    monkeypatch.setattr(session_client, "_pid_alive", lambda pid: True)
    try:
        with pytest.raises(TimeoutError):
            session_client.send(
                "wait", {"timeout": 5}, start_dir=tmp_path, timeout=0.3
            )
    finally:
        gate.set()
        th.join(timeout=10)
        srv.close()


def test_cli_send_maps_a_socket_timeout_to_a_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """socket.timeout is an OSError, not a SessionError — it used to traceback."""
    def boom(op: str, args: dict[str, Any] | None = None) -> Any:
        raise TimeoutError("timed out")

    monkeypatch.setattr(session_client, "send", boom)
    r = runner.invoke(app, ["click", "0"])
    assert r.exit_code == 1
    assert not isinstance(r.exception, TimeoutError), "the raw exception escaped"
    assert "error:" in r.output and "timed out" in r.output


def test_cli_send_maps_a_corrupt_response_to_a_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(op: str, args: dict[str, Any] | None = None) -> Any:
        raise json.JSONDecodeError("Expecting value", "{oops", 0)

    monkeypatch.setattr(session_client, "send", boom)
    r = runner.invoke(app, ["click", "0"])
    assert r.exit_code == 1
    assert not isinstance(r.exception, json.JSONDecodeError)
    assert "error:" in r.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "socket_timeout_for or honours_an_explicit_socket_timeout or maps_a_socket_timeout or maps_a_corrupt_response" -v --no-cov`
Expected: FAIL — `AttributeError: module 'visus.web.cli.session_client' has no attribute 'socket_timeout_for'`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/session_client.py`, add above `_send_raw` (before `:99`):

```python
# The client's socket deadline when an op carries no timeout of its own.
DEFAULT_SOCKET_TIMEOUT = 60.0
# Slack added on top of an op's own deadline, covering the daemon's reply hop.
SOCKET_TIMEOUT_MARGIN = 10.0


def socket_timeout_for(args: dict[str, Any] | None) -> float:
    """Socket deadline for one op: its own ``timeout`` (ms) plus slack.

    ``visus wait``/``visus expect-text`` expose an uncapped ``--timeout`` in
    milliseconds that the daemon honours literally, so a fixed 60 s socket
    deadline would abort a perfectly healthy long wait mid-flight.
    """
    ms = (args or {}).get("timeout")
    if ms is None:
        return DEFAULT_SOCKET_TIMEOUT
    try:
        seconds = float(ms) / 1000.0
    except (TypeError, ValueError):
        return DEFAULT_SOCKET_TIMEOUT
    return max(DEFAULT_SOCKET_TIMEOUT, seconds + SOCKET_TIMEOUT_MARGIN)
```

Change `_send_raw`'s default to reference the constant (`:99`):

```python
def _send_raw(
    port: int, payload: dict[str, Any], *, timeout: float = DEFAULT_SOCKET_TIMEOUT
) -> dict[str, Any]:
```

Replace `send` (`:113-126`) with:

```python
def send(
    op: str,
    args: dict[str, Any] | None = None,
    *,
    start_dir: str | Path | None = None,
    timeout: float | None = None,
) -> Any:
    """Send an op to the live daemon and return its ``result`` (raises on failure).

    The socket deadline defaults to :func:`socket_timeout_for` so a long
    ``--timeout`` on the op is not cut short by the transport.
    """
    info = find_session(start_dir)
    if info is None:
        raise SessionError("no live session — run `visus session start` first")
    resp = _send_raw(
        int(info["port"]),
        {"token": info["token"], "op": op, "args": args or {}},
        timeout=socket_timeout_for(args) if timeout is None else timeout,
    )
    if not resp.get("ok"):
        raise SessionError(str(resp.get("error", "unknown error")))
    return resp.get("result")
```

In `src/visus/web/cli/main.py`, replace `_send` (`:205-213`) with:

```python
def _send(op: str, args: dict[str, Any] | None = None) -> Any:
    """Send an op to the running daemon, mapping failures to a clean Exit(1).

    ``socket.timeout`` is an ``OSError`` and a truncated reply raises
    ``JSONDecodeError`` — neither is a ``SessionError``, and both used to reach
    the user as a raw traceback.
    """
    from visus.web.cli import session_client

    try:
        return session_client.send(op, args or {})
    except session_client.SessionError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc
    except _json.JSONDecodeError as exc:
        typer.echo(f"error: daemon sent a malformed response — {exc}")
        raise typer.Exit(1) from exc
    except OSError as exc:
        typer.echo(f"error: daemon communication failed — {type(exc).__name__}: {exc}")
        raise typer.Exit(1) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "socket_timeout_for or honours_an_explicit_socket_timeout or maps_a_socket_timeout or maps_a_corrupt_response or send_error_exits_1 or send_real_raises" -v --no-cov`
Expected: PASS (all selected tests pass)

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/session_client.py src/visus/web/cli/main.py tests/test_cli_session.py
git commit -m "fix(cli): derive the socket deadline from the op timeout and catch transport errors"
```

---

### Task 12: Distinguish a null value from an empty string

`_op_get_text` (`:272-273`) and `_op_get_attribute` (`:326-328`) return `str | None` straight into `typer.echo` (`main.py:419`, `:558`). `typer.echo(None)` and `typer.echo("")` both print an identical blank line, so "this element has no text node" and "this element's text is empty" are indistinguishable — as are "no such attribute" and "the attribute is `\"\"`".

This task makes the **daemon** carry the distinction explicitly. PLAN 4 owns the global `--json`/`--raw` machinery and will route the payload through its `emit()`; the text-mode renderer added here is the interim, and PLAN 4 replaces its call sites, not its shape.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:272-273`, `:326-328`
- Modify: `src/visus/web/cli/console.py` (add `render_value`), `:158-161` (`text`/`attr` branches)
- Modify: `src/visus/web/cli/main.py:410-419` (`get_text`), `:546-558` (`get_attribute`)
- Create: `tests/fixtures/nullvsempty.html`
- Test: `tests/test_cli_session.py`, `tests/test_e2e_cli_session.py`

**Interfaces:**
- Produces: `_op_get_text` / `_op_get_attribute` returning `{"value": str | None, "present": bool}`; `console.render_value(result: Any) -> str`
- Consumes: nothing

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/nullvsempty.html` with exactly this content:

```html
<!doctype html>
<html>
  <head><title>null vs empty</title></head>
  <body>
    <h1>Null vs empty</h1>

    <!-- Text content is genuinely the empty string: present, but empty. -->
    <span id="emptytext" style="display:inline-block;width:40px;height:12px;"></span>

    <!-- Text content is a real value. -->
    <span id="sometext">hello</span>

    <!-- `data-flag` is PRESENT with an empty value; `data-missing` is ABSENT.
         Both used to print an identical blank line on the client. -->
    <button id="btn" data-flag="" style="width:120px;height:32px;">Press</button>
  </body>
</html>
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_cli_session.py`:

```python
@pytest.mark.browser
def test_get_text_and_get_attribute_distinguish_null_from_empty(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/nullvsempty.html"
    )
    try:
        assert h.handle("get_text", {"selector": "#sometext"})["result"] == {
            "value": "hello",
            "present": True,
        }
        assert h.handle("get_text", {"selector": "#emptytext"})["result"] == {
            "value": "",
            "present": True,
        }
        flag = h.handle("get_attribute", {"selector": "#btn", "attr_name": "data-flag"})
        assert flag["result"] == {"value": "", "present": True}
        missing = h.handle(
            "get_attribute", {"selector": "#btn", "attr_name": "data-missing"}
        )
        assert missing["result"] == {"value": None, "present": False}
    finally:
        h.close()


def test_render_value_keeps_null_and_empty_apart() -> None:
    assert console.render_value({"value": "hi", "present": True}) == "hi"
    assert console.render_value({"value": "", "present": True}) == "(empty)"
    assert console.render_value({"value": None, "present": False}) == "(null)"
    # Anything that is not a {value, present} payload passes straight through.
    assert console.render_value("plain") == "plain"
    assert console.render_value(7) == "7"


def test_cli_get_text_and_get_attribute_render_the_distinction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payloads = iter(
        [
            {"value": "", "present": True},
            {"value": None, "present": False},
        ]
    )
    monkeypatch.setattr(session_client, "send", lambda op, args=None: next(payloads))
    assert "(empty)" in runner.invoke(app, ["get-text", "0"]).output
    assert "(null)" in runner.invoke(app, ["get-attribute", "href", "0"]).output


def test_dispatch_text_and_attr_render_the_distinction() -> None:
    def send(op: str, args: dict[str, Any]) -> Any:
        return {"value": None, "present": False}

    assert console.dispatch("text 0", send) == "(null)"
    assert console.dispatch("attr href 0", send) == "(null)"
```

Update the pre-existing assertions in `tests/test_cli_session.py` that pinned the old scalar shape:

- `test_handle_get_text_by_role` (`:294-299`): change the last assertion to
  `assert resp["result"] == {"value": "text-of:role(button,OK)", "present": True}`
- `test_handle_get_text_by_index_reresolves_via_frame_and_deep` (`:302-309`): change the last assertion to
  `assert resp["result"] == {"value": "text-of:frame(#f1)>loc(#b,deep=True)", "present": True}`
- `test_handle_get_attribute_and_count` (`:353-358`): change the first assertion to
  `assert resp["result"] == {"value": "attr:loc(#a,deep=False):href", "present": True}`
- `test_handle_real_get_attribute_and_count` (`:1800-1809`): change the `href` assertion to
  `assert href["ok"] is True and href["result"] == {"value": "https://example.com/", "present": True}`

Update `tests/test_e2e_cli_session.py` — replace lines 67-69 (`assert session_client.send("get_text", ...) is not None ...`) with:

```python
        text_payload = session_client.send(
            "get_text", {"selector": "#name"}, start_dir=tmp_path
        )
        transcript.append(f"get_text[#name] -> {text_payload}")
        # An <input> has no text node: the value is the empty string, not absent.
        assert text_payload["present"] is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "render_value or distinguish_null_from_empty or render_the_distinction" -v --no-cov`
Expected: FAIL — `AttributeError: module 'visus.web.cli.console' has no attribute 'render_value'`

- [ ] **Step 4: Write the implementation**

In `src/visus/web/cli/session_server.py`, replace `_op_get_text` (`:272-273`) with:

```python
    def _op_get_text(self, args: dict[str, Any]) -> dict[str, Any]:
        """Text content of the target, keeping "absent" distinct from "empty".

        ``typer.echo(None)`` and ``typer.echo("")`` print an identical blank line,
        so the two cases have to be separated here, in the payload.
        """
        value = self._target(args).first().text_content()
        return {"value": value, "present": value is not None}
```

Replace `_op_get_attribute` (`:326-328`) with:

```python
    def _op_get_attribute(self, args: dict[str, Any]) -> dict[str, Any]:
        """Attribute value of the target, keeping "absent" distinct from ``""``."""
        name = args.get("attr_name", "")
        value = self._target(args).first().get_attribute(name)
        return {"value": value, "present": value is not None}
```

In `src/visus/web/cli/console.py`, add `render_value` immediately after `format_fields` (after `:93`):

```python
def render_value(result: Any) -> str:
    """Render a ``{value, present}`` daemon payload, keeping ``None`` distinct from ``""``.

    An agent that reads a blank line cannot tell "this attribute does not exist"
    from "this attribute is the empty string", and the two lead to opposite next
    actions. Anything that is not such a payload passes straight through.
    """
    if not isinstance(result, dict) or "present" not in result:
        return str(result)
    if not result.get("present"):
        return "(null)"
    value = "" if result.get("value") is None else str(result["value"])
    return value if value != "" else "(empty)"
```

Replace the `text`/`attr` branches of `dispatch` (`:158-161`) with:

```python
        if cmd in ("text", "get-text"):
            return render_value(send("get_text", _idx(rest[0])))
        if cmd in ("attr", "get-attribute"):
            return render_value(
                send("get_attribute", {**_idx(rest[1]), "attr_name": rest[0]})
            )
```

In `src/visus/web/cli/main.py`, add this helper immediately after `_format_fields` (`:216-219`):

```python
def _render_value(result: Any) -> str:
    from visus.web.cli.console import render_value

    return render_value(result)
```

Replace the body line of `get_text` (`:419`) with:

```python
    typer.echo(_render_value(_send("get_text", _target_args(index, selector, role, name, text))))
```

Replace the last line of `get_attribute` (`:558`) with:

```python
    typer.echo(_render_value(_send("get_attribute", args)))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "render_value or distinguish_null_from_empty or render_the_distinction or get_text or get_attribute" -v --no-cov`
Expected: PASS (all selected tests pass)

Run: `uv run pytest tests/test_e2e_cli_session.py::test_cross_process_daemon_full_cycle -v --no-cov`
Expected: PASS

- [ ] **Step 6: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 7: Commit**

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/console.py src/visus/web/cli/main.py tests/fixtures/nullvsempty.html tests/test_cli_session.py tests/test_e2e_cli_session.py
git commit -m "fix(cli): keep a null value distinct from an empty string in get-text/get-attribute"
```

---

### Task 13: REPL `screenshot` resolves the path against the client cwd

`console.py:187` is `args = {"path": rest[0]} if rest else {}` — a raw string, resolved by the **daemon** against its own working directory. The non-interactive command already has the fix and the explanatory comment at `main.py:440-442`.

**Files:**
- Modify: `src/visus/web/cli/console.py:9-14` (imports), `:186-188`
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Consumes: nothing
- Produces: nothing

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_session.py`:

```python
def test_dispatch_screenshot_resolves_the_path_against_the_client_cwd() -> None:
    """The daemon's cwd is not the user's; a relative path must be resolved here."""
    calls, send = _recording_send()
    out = console.dispatch("screenshot shots/out.png", send)
    assert "saved" in out
    op, args = calls[-1]
    assert op == "screenshot"
    assert args == {"path": str(Path("shots/out.png").resolve())}
    assert Path(args["path"]).is_absolute()

    # No argument still means "let the daemon use its default name".
    console.dispatch("screenshot", send)
    assert calls[-1][1] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_session.py::test_dispatch_screenshot_resolves_the_path_against_the_client_cwd -v --no-cov`
Expected: FAIL — `AssertionError: assert {'path': 'shots/out.png'} == {'path': 'C:\\...\\shots\\out.png'}`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/console.py`, add `from pathlib import Path` to the import block (after `from collections.abc import Callable`, keeping ruff's `I` ordering: `collections.abc`, `pathlib`, `typing`).

Replace the `screenshot` branch (`:186-188`) with:

```python
        if cmd == "screenshot":
            # Resolve the path against the CLIENT's cwd (not the daemon's) so the
            # PNG lands where the user is, mirroring `visus session-screenshot`.
            args = {"path": str(Path(rest[0]).resolve())} if rest else {}
            return f"saved {send('screenshot', args)}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "dispatch_screenshot or dispatch_goto_text_screenshot" -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/visus/web/cli/console.py tests/test_cli_session.py
git commit -m "fix(cli): resolve the REPL screenshot path against the client cwd"
```

---

### Task 14: Opt-in idle timeout so abandoned daemons reap themselves

`serve()`'s accept loop (`:715`) runs forever and `started_at` is written at `:705` and never read by anything. An abandoned headed browser sits on the user's desktop until they find it by hand.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:84-101` (`__init__`), `:224-233` (`handle`), add `last_op_at`, `:674-735` (`serve`), `:738-773` (`main`)
- Modify: `src/visus/web/cli/session_client.py:129-194` (`start_daemon`)
- Modify: `src/visus/web/cli/main.py:238-252` (`session_start`)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces: `SessionHandler.last_op_at() -> float`, `serve(..., idle_timeout: float | None = None)`, `start_daemon(..., idle_timeout: float | None = None)`, env `VISUS_WEB_IDLE_TIMEOUT`, CLI flag `visus session start --idle-timeout`
- Consumes: nothing

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_session.py`:

```python
def test_serve_reaps_itself_after_the_idle_timeout(tmp_path: Path) -> None:
    import threading as _threading
    import time as _time

    handler = _handler_with_fake_page(_FakePage())
    t = _threading.Thread(
        target=session_server.serve,
        kwargs={
            "handler": handler,
            "token": "tok",
            "cwd": tmp_path,
            "idle_timeout": 0.5,
        },
        daemon=True,
    )
    t.start()
    sf = session_server.session_file(tmp_path)
    for _ in range(200):
        if sf.is_file():
            break
        _time.sleep(0.02)
    assert sf.is_file()

    t.join(timeout=20)
    assert not t.is_alive(), "the idle daemon never reaped itself"
    assert not sf.is_file()
    assert not sf.with_name(sf.name + ".lock").exists()


def test_activity_postpones_the_idle_timeout(tmp_path: Path) -> None:
    import threading as _threading
    import time as _time

    handler = _handler_with_fake_page(_FakePage())
    t = _threading.Thread(
        target=session_server.serve,
        kwargs={
            "handler": handler,
            "token": "tok",
            "cwd": tmp_path,
            "idle_timeout": 1.5,
        },
        daemon=True,
    )
    t.start()
    sf = session_server.session_file(tmp_path)
    for _ in range(200):
        if sf.is_file():
            break
        _time.sleep(0.02)
    port = int(json.loads(sf.read_text(encoding="utf-8"))["port"])

    deadline = _time.monotonic() + 3.0
    while _time.monotonic() < deadline:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            f = sock.makefile("rwb")
            f.write((json.dumps({"token": "tok", "op": "status"}) + "\n").encode("utf-8"))
            f.flush()
            assert json.loads(f.readline().decode("utf-8"))["ok"] is True
        _time.sleep(0.4)
    assert t.is_alive(), "an actively-used daemon reaped itself"
    _shutdown_thread(t, port, "tok")


def test_start_daemon_forwards_the_idle_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, *a: Any, **kw: Any) -> None:
            captured["env"] = kw["env"]

    monkeypatch.setattr(session_client, "find_session", lambda d=None: None)
    monkeypatch.setattr(session_client.subprocess, "Popen", _FakePopen)
    with pytest.raises(session_client.SessionError):
        session_client.start_daemon(
            "chrome", True, None, cwd=tmp_path, timeout=0.3, idle_timeout=900.0
        )
    assert captured["env"]["VISUS_WEB_IDLE_TIMEOUT"] == "900.0"


def test_cli_session_start_forwards_the_idle_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_start(engine: str, headless: bool, url: str | None, **kw: Any) -> Any:
        captured.update(kw)
        return {"pid": 1, "port": 2}

    monkeypatch.setattr(session_client, "start_daemon", fake_start)
    r = runner.invoke(app, ["session", "start", "--idle-timeout", "600"])
    assert r.exit_code == 0
    assert captured["idle_timeout"] == 600.0
    r2 = runner.invoke(app, ["session", "start"])
    assert r2.exit_code == 0 and captured["idle_timeout"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "idle_timeout" -v --no-cov`
Expected: FAIL — `TypeError: serve() got an unexpected keyword argument 'idle_timeout'`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/session_server.py`, add to `SessionHandler.__init__` after `self._lock = threading.RLock()`:

```python
        self._last_op_at = time.monotonic()
```

Add this accessor immediately after `bind_stop`:

```python
    def last_op_at(self) -> float:
        """``time.monotonic()`` of the most recently dispatched op (idle reaper).

        Read WITHOUT taking ``self._lock``: the reaper runs on the accept thread
        and must not queue behind an in-flight ``wait``. A float assignment is
        atomic, and a one-tick-stale read only postpones reaping by 0.5 s.
        """
        return self._last_op_at
```

In `handle`, add as the first statement inside `with self._lock:`:

```python
            self._last_op_at = time.monotonic()
```

Change the `serve` signature (`:674-680`) to:

```python
def serve(
    handler: SessionHandler,
    *,
    token: str,
    cwd: str | Path | None = None,
    host: str = "127.0.0.1",
    idle_timeout: float | None = None,
) -> None:
    """Bind a JSON-lines TCP server, write the session file, serve until shutdown.

    *idle_timeout* (seconds, ``None`` = never) reaps a session nobody is using:
    an abandoned headed browser otherwise sits on the desktop forever.
    """
```

Replace the `except TimeoutError: continue` branch in the accept loop with:

```python
            except TimeoutError:
                if idle_timeout is not None and (
                    time.monotonic() - handler.last_op_at() > idle_timeout
                ):
                    break
                continue
```

In `main()`, replace the `serve(handler, token=token)` call (`:763`) with:

```python
        serve(handler, token=token, idle_timeout=_idle_timeout_from_env())
```

and add this helper immediately above `def main(` (before `:738`):

```python
def _idle_timeout_from_env() -> float | None:
    """``VISUS_WEB_IDLE_TIMEOUT`` in seconds; ``0``/unset/garbage means never."""
    try:
        seconds = float(os.environ.get("VISUS_WEB_IDLE_TIMEOUT", "") or 0)
    except ValueError:
        return None
    return seconds if seconds > 0 else None
```

In `src/visus/web/cli/session_client.py`, change the `start_daemon` signature (`:129-136`) to:

```python
def start_daemon(
    engine: str = "chrome",
    headless: bool = False,
    url: str | None = None,
    *,
    cwd: str | Path | None = None,
    timeout: float = 20.0,
    idle_timeout: float | None = None,
) -> dict[str, Any]:
```

and add after `env["VISUS_WEB_URL"] = url` (`:153`):

```python
    if idle_timeout is not None:
        env["VISUS_WEB_IDLE_TIMEOUT"] = str(idle_timeout)
```

In `src/visus/web/cli/main.py`, replace `session_start` (`:238-252`) with:

```python
@session_app.command("start")
def session_start(
    url: str = typer.Argument(None, help="URL to open once the browser starts."),
    engine: str = typer.Option("chrome", "--engine", "-e"),
    headless: bool = typer.Option(False, "--headless", help="Run headless (default: headed)."),
    idle_timeout: float = typer.Option(
        None,
        "--idle-timeout",
        help="Stop the daemon after N seconds with no command (omit = never).",
    ),
) -> None:
    """Start a persistent browser session (detached daemon)."""
    from visus.web.cli import session_client

    try:
        info = session_client.start_daemon(
            engine, headless, url, idle_timeout=idle_timeout
        )
    except session_client.SessionError as exc:
        typer.echo(f"error: {exc}")
        raise typer.Exit(1) from exc
    typer.echo(f"session started (pid {info['pid']}, port {info['port']}, engine {engine})")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "idle_timeout or session_start" -v --no-cov`
Expected: PASS (all selected tests pass)

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/session_client.py src/visus/web/cli/main.py tests/test_cli_session.py
git commit -m "feat(cli): add an opt-in idle timeout that reaps an abandoned session"
```

---

### Task 15: Rotate `.visus/daemon.log`

`_log` (`session_server.py:756-758`) appends to `.visus/daemon.log` with no size cap, forever.

**Files:**
- Modify: `src/visus/web/cli/session_server.py:15-34` (imports), `:752-758` (log setup in `main`)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces: `session_server.LOG_MAX_BYTES: int`, `session_server.LOG_BACKUP_COUNT: int`, `session_server._make_logger(log_path, *, max_bytes=LOG_MAX_BYTES, backup_count=LOG_BACKUP_COUNT) -> logging.Logger`
- Consumes: nothing

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_session.py`:

```python
def test_daemon_log_rotates_instead_of_growing_forever(tmp_path: Path) -> None:
    log = tmp_path / "daemon.log"
    logger = session_server._make_logger(log, max_bytes=2048, backup_count=2)
    try:
        for i in range(400):
            logger.info("%s %d", "x" * 80, i)
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()

    assert log.is_file()
    assert log.stat().st_size <= 4096, "the active log grew past its cap"
    assert (tmp_path / "daemon.log.1").is_file(), "nothing rotated"
    assert (tmp_path / "daemon.log.2").is_file()
    assert not (tmp_path / "daemon.log.3").exists(), "backupCount was not honoured"


def test_make_logger_is_idempotent(tmp_path: Path) -> None:
    """Re-creating the logger must not stack handlers (double-written lines)."""
    log = tmp_path / "daemon.log"
    first = session_server._make_logger(log)
    second = session_server._make_logger(log)
    try:
        assert first is second
        assert len(second.handlers) == 1
        second.info("hello")
    finally:
        for handler in list(second.handlers):
            second.removeHandler(handler)
            handler.close()
    assert log.read_text(encoding="utf-8").count("hello") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "daemon_log_rotates or make_logger_is_idempotent" -v --no-cov`
Expected: FAIL — `AttributeError: module 'visus.web.cli.session_server' has no attribute '_make_logger'`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/session_server.py`, add to the stdlib import block (ruff `I` order: `json`, `logging`, `os`, `secrets`, `socket`, `sys`, `threading`, `time`) plus the handler import after it:

```python
import logging
...
from logging.handlers import RotatingFileHandler
```

Add above `def _idle_timeout_from_env()`:

```python
LOG_MAX_BYTES = 1_048_576
LOG_BACKUP_COUNT = 3


def _make_logger(
    log_path: Path,
    *,
    max_bytes: int = LOG_MAX_BYTES,
    backup_count: int = LOG_BACKUP_COUNT,
) -> logging.Logger:
    """The daemon's logger, writing to a size-capped rotating file.

    ``.visus/daemon.log`` used to be an unbounded append; a long-lived headed
    session logs on every start/abort/crash and nothing ever truncated it.
    Idempotent: re-creating the logger replaces its handler instead of stacking
    a second one (which would double every line).
    """
    logger = logging.getLogger("visus.web.cli.session_server")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        existing.close()
    handler = RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    return logger
```

In `main()`, replace the log setup (`:752-758`) with:

```python
    log_dir = Path.cwd() / ".visus"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = _make_logger(log_dir / "daemon.log")

    def _log(msg: str) -> None:
        logger.info(msg)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "daemon_log_rotates or make_logger_is_idempotent" -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/session_server.py tests/test_cli_session.py
git commit -m "chore(cli): rotate the daemon log instead of appending forever"
```

---

### Task 16: Harden the session token — constant-time compare, owner-only file

The token is written by `write_text` at `:709` with default permissions, and compared with `!=` at `:637-639`. The surface it guards includes `eval`, arbitrary-path writes (`:289`) and file exfiltration via `_op_upload` (`:365-368`).

**Files:**
- Modify: `src/visus/web/cli/session_server.py:634-639` (token check), `:695-710` (session-file write)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces: `session_server._write_private(path: Path, text: str) -> None`
- Consumes: nothing

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_session.py`:

```python
def test_write_private_creates_exclusively_and_owner_only(tmp_path: Path) -> None:
    import os as _os
    import stat as _stat

    target = tmp_path / "secret.json"
    session_server._write_private(target, '{"token": "abc"}')
    assert target.read_text(encoding="utf-8") == '{"token": "abc"}'

    # O_EXCL: never write THROUGH a file somebody else planted.
    with pytest.raises(FileExistsError):
        session_server._write_private(target, "second")
    assert target.read_text(encoding="utf-8") == '{"token": "abc"}'

    if hasattr(_os, "getuid"):  # POSIX enforces the mode bits
        assert _stat.S_IMODE(target.stat().st_mode) == 0o600


def test_token_check_is_type_safe_and_rejects_same_length_tokens(
    tmp_path: Path,
) -> None:
    """compare_digest raises TypeError on non-str input — that must never leak."""
    handler = _handler_with_fake_page(_FakePage())
    token = "0123456789abcdef"
    t, port = _serve_in_thread(handler, token, tmp_path)

    def rpc(payload: dict[str, Any]) -> dict[str, Any]:
        with socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
            f = sock.makefile("rwb")
            f.write((json.dumps(payload) + "\n").encode("utf-8"))
            f.flush()
            return json.loads(f.readline().decode("utf-8"))

    try:
        assert rpc({"token": token, "op": "status"})["ok"] is True
        for bad in ("fedcba9876543210", "", "café", None):
            resp = rpc({"token": bad, "op": "status"})
            assert resp["ok"] is False, bad
            assert resp["error"] == "unauthorized: bad token", (bad, resp)
        for bad_typed in (123, ["x"], {"a": 1}):
            resp = rpc({"token": bad_typed, "op": "status"})
            assert resp["ok"] is False, bad_typed
            assert resp["error"] == "unauthorized: bad token", (bad_typed, resp)
        assert rpc({"op": "status"})["error"] == "unauthorized: bad token"
    finally:
        _shutdown_thread(t, port, token)


def test_session_file_is_written_privately(tmp_path: Path) -> None:
    import os as _os
    import stat as _stat

    handler = _handler_with_fake_page(_FakePage())
    t, port = _serve_in_thread(handler, "tok", tmp_path)
    try:
        sf = session_server.session_file(tmp_path)
        assert json.loads(sf.read_text(encoding="utf-8"))["token"] == "tok"
        assert list((tmp_path / ".visus").glob("session.json.*.tmp")) == []
        if hasattr(_os, "getuid"):
            assert _stat.S_IMODE(sf.stat().st_mode) == 0o600
    finally:
        _shutdown_thread(t, port, "tok")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "write_private or token_check_is_type_safe or written_privately" -v --no-cov`
Expected: FAIL — `AttributeError: module 'visus.web.cli.session_server' has no attribute '_write_private'`, and for the token test `AssertionError: (123, {'ok': False, 'error': "TypeError: ..."})`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/session_server.py`, replace the token check in `_handle_conn` (`:637-639`) with:

```python
                tok = req.get("token")
                # Constant-time and type-safe: compare_digest raises TypeError on
                # a non-str/bytes argument, and a malicious client controls this
                # value entirely.
                if not isinstance(tok, str) or not secrets.compare_digest(
                    tok.encode("utf-8"), token.encode("utf-8")
                ):
                    _reply({"ok": False, "error": "unauthorized: bad token"})
                    continue
```

Add `_write_private` immediately above `def _read_lock_pid(` :

```python
def _write_private(path: Path, text: str) -> None:
    """Create *path* exclusively with owner-only permissions and write *text*.

    The session file carries the daemon's shared secret, and that token authorises
    ``eval``, screenshot writes to an arbitrary path and file upload — so it must
    not be world-readable. ``O_EXCL`` additionally refuses to write THROUGH a file
    somebody else planted. POSIX enforces the mode bits; on Windows the exclusive
    create still holds but ACLs are inherited from ``.visus/``.
    """
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, text.encode("utf-8"))
    finally:
        os.close(fd)
```

In `serve()`, replace the two lines that write the temp file (`:708-710`) with:

```python
    tmp = sf.with_name(f"{sf.name}.{os.getpid()}.tmp")
    try:
        tmp.unlink()  # a crashed predecessor may have left this behind
    except OSError:
        pass
    _write_private(tmp, payload)
    os.replace(tmp, sf)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "write_private or token_check_is_type_safe or written_privately or serve_protocol or writes_session_file_atomically" -v --no-cov`
Expected: PASS (all selected tests pass)

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/session_server.py tests/test_cli_session.py
git commit -m "fix(cli): compare the session token in constant time and keep the session file private"
```

---

### Task 17: One liveness probe per command

`session_client.status()` (`:217-231`) calls `find_session()` at `:219` and then `send()` at `:222`, which calls `find_session()` again — two liveness probes for one command. On Windows each probe shells out to `tasklist` with a 5 s timeout (`:28-39`), unmemoised.

**Files:**
- Modify: `src/visus/web/cli/session_client.py:24-46` (`_pid_alive`), `:217-231` (`status`), the `_pid_alive` call in `kill` (Task 5)
- Modify: `src/visus/web/cli/session_server.py` (`_claim_lock`'s liveness call, Task 3)
- Test: `tests/test_cli_session.py`

**Interfaces:**
- Produces: `session_client._probe_pid(pid: int) -> bool` (uncached), `session_client.PID_ALIVE_TTL: float`, `session_client._pid_alive` (now memoised)
- Consumes: nothing

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_session.py`:

```python
def test_status_costs_exactly_one_liveness_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`visus session status` used to probe twice; on Windows that is 2x tasklist."""
    probes: list[int] = []
    real_probe = session_client._probe_pid

    def spy(pid: int) -> bool:
        probes.append(pid)
        return real_probe(pid)

    handler = _handler_with_fake_page(_FakePage())
    t, port = _serve_in_thread(handler, "tok", tmp_path)
    try:
        # Rewrite the session file with THIS process's pid so the probe is real.
        import os as _os

        sf = session_server.session_file(tmp_path)
        info = json.loads(sf.read_text(encoding="utf-8"))
        info["pid"] = _os.getpid()
        sf.write_text(json.dumps(info), encoding="utf-8")

        session_client._pid_alive_cache.clear()
        monkeypatch.setattr(session_client, "_probe_pid", spy)
        result = session_client.status(start_dir=tmp_path)
        assert result is not None and result["running"] is True
        assert len(probes) == 1, f"{len(probes)} liveness probes for one status"
    finally:
        monkeypatch.undo()
        _shutdown_thread(t, port, "tok")


def test_pid_alive_is_memoised_within_its_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        session_client, "_probe_pid", lambda pid: calls.append(pid) or True
    )
    session_client._pid_alive_cache.clear()
    assert session_client._pid_alive(4242) is True
    assert session_client._pid_alive(4242) is True
    assert session_client._pid_alive(4242) is True
    assert calls == [4242], "the probe was not memoised"


def test_pid_alive_memo_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        session_client, "_probe_pid", lambda pid: calls.append(pid) or True
    )
    monkeypatch.setattr(session_client, "PID_ALIVE_TTL", 0.0)
    session_client._pid_alive_cache.clear()
    session_client._pid_alive(4242)
    session_client._pid_alive(4242)
    assert calls == [4242, 4242], "a zero TTL must not memoise"
```

Update the pre-existing `test_pid_alive_windows_tasklist_branch` (`tests/test_cli_session.py:967-996`): the memo would make its three consecutive `_pid_alive(12345)` calls return the same answer. Change all three call sites from `session_client._pid_alive(12345)` to `session_client._probe_pid(12345)`. The docstring becomes:

```python
    """Exercise the win32 tasklist parse (uncached probe): present -> True,
    absent/raising -> False."""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_session.py -k "one_liveness_probe or memoised_within_its_ttl or memo_expires" -v --no-cov`
Expected: FAIL — `AttributeError: module 'visus.web.cli.session_client' has no attribute '_probe_pid'`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/cli/session_client.py`, replace `_pid_alive` (`:24-46`) with:

```python
# How long a liveness answer may be reused. Short enough that a dying daemon is
# noticed almost immediately, long enough to collapse the repeat probes a single
# CLI invocation makes.
PID_ALIVE_TTL = 1.0
_pid_alive_cache: dict[int, tuple[float, bool]] = {}


def _probe_pid(pid: int) -> bool:
    """Ask the OS whether a process with *pid* exists (uncached)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # tasklist is the dependency-free way to probe a pid on Windows.
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        except Exception:
            return False
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _pid_alive(pid: int) -> bool:
    """True if a process with *pid* exists, memoised for :data:`PID_ALIVE_TTL`.

    On Windows every probe spawns ``tasklist`` with a 5 s timeout, and a single
    command probes the same pid more than once (discovery, then the op). The memo
    removes the duplicate cost without ever hiding a death for longer than the TTL.
    Liveness-critical callers use :func:`_probe_pid` directly.
    """
    now = time.monotonic()
    hit = _pid_alive_cache.get(pid)
    if hit is not None and now - hit[0] < PID_ALIVE_TTL:
        return hit[1]
    alive = _probe_pid(pid)
    _pid_alive_cache[pid] = (now, alive)
    return alive
```

Replace `status` (`:217-231`) with:

```python
def status(*, start_dir: str | Path | None = None) -> dict[str, Any] | None:
    """Return the live daemon's status dict, or ``None`` if no session is running.

    Sends on the connection info from the SINGLE ``find_session`` call above —
    routing through :func:`send` would re-run discovery and pay a second liveness
    probe (on Windows: a second ``tasklist`` with a 5 s timeout).
    """
    info = find_session(start_dir)
    if info is None:
        return None
    resp = _send_raw(int(info["port"]), {"token": info["token"], "op": "status", "args": {}})
    if not resp.get("ok"):
        raise SessionError(str(resp.get("error", "unknown error")))
    result = resp.get("result")
    merged: dict[str, Any] = {
        "pid": info["pid"],
        "port": info["port"],
        "engine": info.get("engine"),
        "headless": info.get("headless"),
    }
    if isinstance(result, dict):
        merged.update(result)
    return merged
```

In `kill()` (Task 5), change `if pid > 0 and _pid_alive(pid):` to:

```python
    if pid > 0 and _probe_pid(pid):
```

In `src/visus/web/cli/session_server.py`'s `_claim_lock` (Task 3), change
`if attempt == 0 and not session_client._pid_alive(owner):` to:

```python
            if attempt == 0 and not session_client._probe_pid(owner):
```

(Both are liveness-critical: a memoised "alive" must never keep a dead daemon's lock or state around.)

Because `kill()` now probes through `_probe_pid`, update the test written in Task 5,
`test_kill_terminates_a_live_daemon`: replace

```python
    monkeypatch.setattr(session_client, "_pid_alive", lambda pid: True)
```

with

```python
    monkeypatch.setattr(session_client, "_probe_pid", lambda pid: True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_session.py -k "liveness_probe or memoised or memo_expires or pid_alive or claim_lock or kill or status" -v --no-cov`
Expected: PASS (all selected tests pass)

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/session_client.py src/visus/web/cli/session_server.py tests/test_cli_session.py
git commit -m "perf(cli): probe daemon liveness once per command"
```

---

### Task 18: Full-suite verification

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

- [ ] **Step 2: Drive the fixed daemon by hand once**

Run these in order from the repo root and confirm each printed line:

```bash
uv run visus session start --headless "http://127.0.0.1:8000/does-not-matter"
```
Expected: `session started (pid <N>, port <N>, engine chrome)`

```bash
uv run visus goto "data:text/html,<title>one</title><button class='btn primary' style='width:120px;height:32px' onclick=\"document.body.dataset.clicked='A'\"></button>"
uv run visus list-fields --no-highlight
uv run visus goto "data:text/html,<title>two</title><input id=x>"
uv run visus click 0
```
Expected: the last command prints `error: IndexError: field index 0 out of range (have 0; run list_fields first)` and exits 1 — **not** `clicked`.

```bash
uv run visus session status
uv run visus session stop
uv run visus session kill
```
Expected: a status block, then `session stopped`, then `no session state to remove`.

- [ ] **Step 3: Commit any residual fixes**

If step 1 or 2 revealed a gap, fix it and commit with a `fix(cli): ...` message. If everything passed, there is nothing to commit — do not create an empty commit.
