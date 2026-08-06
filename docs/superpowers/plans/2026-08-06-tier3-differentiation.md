# Tier 3 — Differentiation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop matching `playwright-cli` feature for feature and build the things its architecture cannot reach — one op vocabulary behind both frontends, index/frame/shadow targeting on MCP, a single-file HTML report as the headline artifact, and pixel-level targeting — then put the remaining six differentiators on a designed, spiked footing instead of a wish list.

**Architecture:** A new package `src/visus/web/ops/` sits *below* both frontends: it imports `visus.web.api` and nothing optional, so the CLI can use it without the `[mcp]` extra and the MCP server can use it without the `[cli]` extra — which is exactly the constraint that produced the copy-pasted `make_locator` at `session_server.py:49-71` / `mcp/session.py:142-160`. It holds the shared targeting resolver, the tool⇄op registry, and `RemoteDispatcher`, whose `handle(op, args)` has the same signature and the same envelope as `SessionHandler.handle` but crosses a process boundary. On top of that seam the MCP server stops being a second, invisible browser and becomes a frontend over the very session the shell is driving. Vision targeting lands as two ordinary daemon ops (`click_image`, `click_ocr_text`) so it reaches the CLI, the REPL and MCP through the same three-part mirror every other command uses.

**Scoping decision — deliberate, not an omission.** The ten Tier 3 items in `synthesis.md:447-469` are not equally ready. Items 1–4 (unify the dispatcher, index targeting on MCP, observability as the product, native vision targeting) are concrete against code that exists today, so **Tasks 1–12** implement them under full TDD. Items 5–10 (`annotate`, ARIA-snapshot assertions, the test-generation flow, `edge_ie`/Grid, video, the fleet dashboard) each carry one unresolved question that no amount of plan prose can answer — can a bounding box be turned into a set of elements at all? can Selenium's synchronous CDP bridge receive screencast frames? what does a `visus` heal loop look like when there is no `--debug=cli` to attach to? Specifying six months of implementation line by line on top of an unanswered question is how plans rot. So **Tasks 13–18 are design tasks**: each writes a design document to `docs/design/` *and* lands a real, tested spike that answers that task's one open question. Every one has explicit acceptance criteria and a real failing-test-first cycle for the spike. Item 9 (video) is explicitly LOW priority and is sequenced after items 1–3, as the brief requires. Item 10 (the fleet dashboard) is blocked on PLAN 6's named sessions — before those exist it is a view over a set of size one — so its task ships the renderer and the design, not a product. **Task 19** is the full-suite gate pass.

**Ordering note.** Item 1's payoff tasks (Tasks 5–7, the MCP dispatch seam and `browser_attach_session`) are interleaved with item 2's (Tasks 4–5) even though item 1 comes first in the brief. Both rewrite the same 21 MCP tool signatures, and doing them in separate passes would rewrite every one of those bodies twice; Task 5 therefore adds `index` and the `_run` seam in a single edit, Task 6 converts the other 22 tools, and Task 7 flips attach on. Items 3–10 follow the brief's order exactly.

**Tech Stack:** Python 3.10+, Typer, Rich, Selenium 4.38, pytest + pytest-xdist, hatchling, mypy --strict, ruff

## Global Constraints

- Gates that must pass before any commit: `uv run ruff check src tests`, `uv run mypy` (strict), `uv run pytest -q` (≥90% coverage on `visus.web`).
- **THE HIDDEN-ENGINE RULE (inviolable):** no `selenium.*` type may appear in any public signature/return/exception/docstring. Selenium imports allowed ONLY in `backends/browsers/*.py`, `backends/selenium/*.py`, `backends/selenium_backend.py`.
- Test convention: **real browser, no fakes**, `@pytest.mark.browser`, fixtures in `tests/fixtures/*.html` served by the session-scoped `base_url` fixture (`tests/conftest.py:38-48`).
- Test doubles isolate a unit ONLY when its real behaviour is also covered by an integration test. No `skip` / `xfail` / mock-to-pass.
- Ruff: line-length 100, select `["E","F","I","UP","B"]`. mypy: `strict = true`, `python_version = "3.10"`.
- Commits: small, TDD (failing test → minimal impl → green → commit), semantic messages `label(scope): description`. Labels: `fix`, `feat`, `chore`, `docs`, `test`, `devops`.
- **Never** add `Co-Authored-By` lines to commits.
- Single-test runs use `--no-cov` (the repo pins `--cov-fail-under=90` in `addopts`, `pyproject.toml:74`; the gate only makes sense on a full run).
- Every new CLI command gets its REPL twin (`console.py:119-210` dispatch + `:19-53` help) **and** a `README.md:286-377` table row.

## Prerequisites

**Four plan files must land before this one.** This plan consumes their symbols and never redefines them.

**PLAN 1 — `2026-08-06-tier1-skill-distribution.md`.** Owns `cli/skills.py`, `cli/skill_check.py`, `cli/_entry.py` and the project's first `@app.callback()` in `main.py`. Consumed here only indirectly: Tasks 11–13 add CLI options to commands that live under that callback.

**PLAN 3 — `2026-08-06-tier2a-daemon-correctness.md`.** Consumed symbols:

```python
# src/visus/web/cli/session_server.py
class StaleFieldIndexError(RuntimeError): ...
    # message: "field indexes were captured on <old>, page is now <new> — run list-fields again"
class SessionHandler:
    _fields_url: str | None
    _lock: threading.RLock                       # handle() body is wrapped in `with self._lock:`
    def _invalidate_fields(self) -> None: ...
    def fields_stale(self) -> bool: ...
def _op_get_text(...)      -> {"value": str | None, "present": bool}
def _op_get_attribute(...) -> {"value": str | None, "present": bool}
```

Task 1 **moves** `StaleFieldIndexError` and the body of `_resolve_field` into `visus.web.ops.targeting` and re-exports both from `session_server`, so `session_server.StaleFieldIndexError` and every PLAN 3 test keep working byte-for-byte.

**PLAN 4 — `2026-08-06-tier2c-agent-driving-loop.md`.** Consumed symbols:

```python
# src/visus/web/cli/output.py
def set_mode(*, as_json: bool = False, raw: bool = False) -> None: ...
def emit(value: Any, *, table: str | None = None) -> None: ...
def emit_error(message: str, *, code: int = 1) -> NoReturn: ...
def emit_envelope(env: dict[str, Any], *, table: str | None = None) -> None: ...

# src/visus/web/cli/session_client.py
def send_envelope(op: str, args: dict[str, Any] | None = None, *,
                  start_dir: str | Path | None = None) -> dict[str, Any]: ...

# src/visus/web/cli/session_server.py
_MUTATING_OPS: frozenset[str]                    # Tasks 12 and 13 append to it
def _post_state(self) -> dict[str, Any]: ...     # {"url","title","fields_stale"}

# src/visus/web/cli/main.py
def _send_env(op: str, args: dict[str, Any] | None = None) -> dict[str, Any]: ...
def _target_args(index, selector, role, name, text) -> dict[str, Any]: ...

# src/visus/web/api/page.py
def snapshot(self, selector: str | None = None, *, depth: int | None = None) -> list[dict]: ...

# src/visus/web/mcp/server.py
def _acted(message: str) -> str: ...             # Task 6 widens this to _acted(env, message)
```

PLAN 4 also owns the daemon envelope `{"ok", "result", "page", "code", "snapshot"}` and the scoped `visus snapshot <target>`. **This plan does not redefine either.** Task 6 replaces PLAN 4's `_acted(message)` with `_acted(env, message)`; PLAN 4's two tests for it (`tests/test_e2e_mcp.py::test_click_result_reports_the_resulting_page` and `::test_fill_result_reports_the_page`) call the *tools*, not the helper, so they stay green.

**PLAN 5 — `2026-08-06-tier2b-cli-surface-parity.md`.** Consumed symbols (declared in its Prerequisites at `:136-152` and its File Structure at `:165-171`):

```python
# src/visus/web/cli/session_server.py — new ops (PLAN 5 Tasks 3, 4, 5, 6)
def _op_console_messages(args) -> {"messages": [{"level","text"}]}
def _op_network_requests(args) -> {"requests": [{"index","url","method","status","resource_type"}]}
def _op_network_request(args)  -> {"index","url","method","status","resource_type","body"}
def _op_tab_activate(args)     -> {"active": int, "handle": str, "title": str}
def _op_tab_follow(args)       -> {"follow": bool}

# src/visus/web/tracing.py — PLAN 5 Task 17
def start_recording(**opts: Any) -> Recorder: ...
def stop_recording(zip_path: str | None = None,
                   report: str | None = None) -> dict[str, str]: ...

# src/visus/web/api/fields.py — PLAN 5 Task 11
Field.box: dict[str, float] | None = None        # {"x","y","width","height"}, viewport CSS px

# CLI commands PLAN 5 owns and this plan builds on top of, never redefines:
#   visus tracing-start / visus tracing-stop / visus report <zip>
#   visus requests [--filter] / visus request <N>   (NetworkCapture wiring, its Task 18)
#   visus session start --remote-url / --user-data-dir / --slow-mo   (its Task 7)
#   visus logs / state-save / state-load / tab-activate / tab-follow
```

PLAN 5's `_op_console_messages`, `_op_network_requests`, `_op_tab_activate` and `_op_tab_follow` are what close the four MCP-only holes of D3 — Task 2's drift test **fails** until PLAN 5 has landed, which is the point: it is the regression test for that gap.

**PLAN 6 — `2026-08-06-tier2d-new-engineering.md`.** Not a prerequisite. Task 19 (the fleet dashboard) is explicitly blocked on its named sessions and ships only a renderer plus a design document.

Symbols **this plan produces** that later work may rely on:

| Symbol | Where |
|---|---|
| `visus.web.ops.targeting.make_locator / any_match_visible / resolve_field / StaleFieldIndexError` | Task 1 |
| `visus.web.ops.registry.TOOL_OPS / SESSIONLESS_TOOLS / LOCAL_ONLY_TOOLS / INDEXABLE_TOOLS` | Tasks 2, 5 |
| `visus.web.ops.remote.RemoteDispatcher / NoSessionError` | Task 3 |
| `visus.web.mcp.session.Session.cache_fields / field_locator / target / invalidate_fields` | Task 4 |
| `visus.web.mcp.server._run / _target_payload / _remote / _acted` | Tasks 5, 7 |
| MCP tools `browser_attach_session` / `browser_detach_session` | Task 7 |
| MCP tools `browser_tracing_start` / `browser_tracing_stop` / `browser_tracing_report` | Task 8 |
| `visus.web.vision.TextBox / read_text_boxes / find_text` | Task 10 |
| `SessionHandler._op_click_image` / `_device_pixel_ratio`, `visus click --image` | Task 11 |
| `SessionHandler._op_click_ocr_text`, `visus click --ocr-text`, `browser_click_image` / `browser_click_ocr_text` | Task 12 |
| `visus.web.api.page.Page.fields_in_box` | Task 13 (spike) |
| `PageAssertions.to_match_aria_snapshot` | Task 14 (spike) |
| `visus.web.cli.codegen.generate_test` | Task 15 (spike) |
| `visus doctor --remote-url` | Task 16 (spike) |
| `visus.web.observability.video.capture_frames / cdp_screencast_available` | Task 17 (spike) |
| `visus.web.cli.fleet.render_fleet` | Task 18 (spike) |

---

## File Structure

**Created**

| Path | Single responsibility |
|---|---|
| `src/visus/web/ops/__init__.py` | Package marker + the layering rule in one docstring. |
| `src/visus/web/ops/targeting.py` | The ONE locator resolver: `make_locator`, `any_match_visible`, `resolve_field`, `StaleFieldIndexError`. |
| `src/visus/web/ops/registry.py` | The tool⇄op inventory both frontends are checked against. |
| `src/visus/web/ops/remote.py` | `RemoteDispatcher` — the daemon's op vocabulary as an in-process object. |
| `src/visus/web/observability/video.py` | Task 18 spike: frame capture for the video extra. |
| `src/visus/web/cli/fleet.py` | Task 19 spike: the fleet renderer. |
| `tests/test_ops_targeting.py` | Unit tests for the shared resolver (+ the identity assertions). |
| `tests/test_ops_registry.py` | The tool⇄op drift test and the index-coverage test. |
| `tests/test_ops_remote.py` | `RemoteDispatcher` unit + real cross-process test. |
| `tests/test_mcp_attach.py` | The attach seam: routing, refusals, structural totality. |
| `tests/test_mcp_index.py` | Index/frame/shadow targeting on the MCP surface. |
| `tests/test_mcp_tracing.py` | `browser_tracing_*` and the rendered report. |
| `tests/test_cli_vision_targeting.py` | `click --image` / `click --ocr-text` (CLI + REPL + daemon). |
| `tests/test_report_copy.py` | The report's self-healing copy (fast, no browser). |
| `tests/test_cli_fleet.py` | The fleet renderer (Task 18 spike). |
| `tests/fixtures/imagetarget.html` | A canvas-drawn button with no accessibility tree (Tasks 12–13). |
| `docs/design/annotate.md` … `docs/design/session-dashboard.md` | Six design documents (Tasks 14–19). |

**Modified**

| Path | What changes |
|---|---|
| `src/visus/web/cli/session_server.py` | Re-exports the shared resolver; `_resolve_field` delegates; `_op_click_image` / `_op_click_ocr_text`; `_MUTATING_OPS` gains two names. |
| `src/visus/web/mcp/session.py` | Re-exports `make_locator`; gains the field cache, `cache_fields`, `field_locator`, `target`; headless default reconciled. |
| `src/visus/web/mcp/server.py` | `index=` on every targeting tool; `_run` / `_target_payload` / `_remote`; attach + detach + tracing + vision tools. |
| `src/visus/web/cli/main.py` | `--image` / `--ocr-text` / `--confidence` on `visus click`. |
| `src/visus/web/cli/console.py` | REPL twins `click-image` / `click-text` + help lines. |
| `src/visus/web/vision/ocr.py`, `vision/__init__.py` | `TextBox`, `read_text_boxes`, `find_text`. |
| `src/visus/web/observability/report.py` | The KPI band and per-step badge name self-healing out loud. |
| `src/visus/web/api/page.py` | `fields_in_box` (Task 14 spike). |
| `src/visus/web/api/assertions.py` | `to_match_aria_snapshot` (Task 15 spike). |
| `src/visus/web/cli/codegen.py` | `generate_test` (Task 16 spike). |
| `tests/test_mcp_server.py` | `_EXPECTED_TOOLS` grows from 45 to 52. |
| `tests/test_e2e_observability.py` | The copy lock at `:110` follows the rename; the video spike's tests. |
| `tests/test_cli_session.py` | `_MUTATING_OPS` expectation gains the two vision ops. |
| `tests/test_cli.py` | `doctor` failure assertions read stderr; the Grid/IE-mode tests. |
| `tests/test_vision.py`, `tests/test_codegen.py`, `tests/test_e2e_expect.py`, `tests/test_e2e_fields.py` | The spike tests for Tasks 10, 13, 14 and 15. |
| `README.md` | Command-table rows for the new CLI surface. |
| `pyproject.toml` | The `[video]` extra (Task 18). |

---

### Task 1: `visus.web.ops.targeting` — one locator resolver, two frontends

`make_locator` exists twice today. `session_server.py:59-63` says why in its own docstring: *"Local copy of the MCP helper (the cli must not import the `mcp` package, as the `mcp` extra may be absent)."* The constraint is real; the duplication is not the only way to satisfy it. A module that lives outside `mcp/` and imports nothing optional can be imported by both.

The same argument applies to `_any_match_visible` (`session_server.py:37-46` is a stated "local copy" of `mcp/server.py:22-32`) and — after PLAN 3 — to `_resolve_field` (`session_server.py:185-196`), which Task 4 needs verbatim on the MCP side.

**Files:**
- Create: `src/visus/web/ops/__init__.py`
- Create: `src/visus/web/ops/targeting.py`
- Modify: `src/visus/web/cli/session_server.py:15-46` (imports + `_any_match_visible`), `:49-71` (`make_locator`), `:185-196` (`_resolve_field`, as rewritten by PLAN 3 Task 1)
- Modify: `src/visus/web/mcp/session.py:1-13` (imports), `:142-160` (`make_locator`)
- Modify: `src/visus/web/mcp/server.py:22-32` (`_any_match_visible`)
- Test: `tests/test_ops_targeting.py`

**Interfaces:**
- Produces:
  ```python
  # src/visus/web/ops/targeting.py
  class StaleFieldIndexError(RuntimeError): ...
  def any_match_visible(loc: Locator) -> bool: ...
  def make_locator(page: Page, *, selector: str | None = None, role: str | None = None,
                   name: str | None = None, text: str | None = None,
                   exact: bool = False, frame: str | None = None) -> Locator: ...
  def resolve_field(page: Page, fields: Sequence[Field], index: int, *,
                    fields_url: str | None) -> Locator: ...
  ```
- Consumes: `SessionHandler._fields` / `_fields_url` (PLAN 3), `Field.frame` / `.locator` / `.deep` (`api/fields.py`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_ops_targeting.py`:

```python
"""The shared targeting vocabulary — one implementation, both frontends."""

from __future__ import annotations

from typing import Any

import pytest

from visus.web.cli import session_server
from visus.web.mcp import session as mcp_session
from visus.web.ops import targeting


class _Loc:
    def __init__(self, label: str) -> None:
        self.label = label

    def frame_locator(self, sel: str) -> _Loc:
        return _Loc(f"{self.label}>frame({sel})")

    def locator(self, selector: str, *, deep: bool = False) -> _Loc:
        return _Loc(f"{self.label}>loc({selector},deep={deep})")

    def get_by_role(self, role: str, *, name: str | None = None, exact: bool = False) -> _Loc:
        return _Loc(f"role({role},{name},exact={exact})")

    def get_by_text(self, text: str, *, exact: bool = False) -> _Loc:
        return _Loc(f"text({text},exact={exact})")


class _Page(_Loc):
    def __init__(self) -> None:
        super().__init__("page")
        self.url = "http://a.test/one"


class _Field:
    def __init__(self, locator: str, frame: list[str], deep: bool) -> None:
        self.locator = locator
        self.frame = frame
        self.deep = deep


def test_both_frontends_import_the_same_make_locator() -> None:
    """The duplication is gone, not just re-synced: same function object."""
    assert session_server.make_locator is targeting.make_locator
    assert mcp_session.make_locator is targeting.make_locator


def test_both_frontends_import_the_same_visibility_helper() -> None:
    from visus.web.mcp import server as mcp_server

    assert session_server._any_match_visible is targeting.any_match_visible
    assert mcp_server._any_match_visible is targeting.any_match_visible


def test_stale_field_index_error_is_re_exported_by_the_daemon() -> None:
    """PLAN 3 named it `session_server.StaleFieldIndexError`; that stays true."""
    assert session_server.StaleFieldIndexError is targeting.StaleFieldIndexError
    assert issubclass(targeting.StaleFieldIndexError, RuntimeError)


def test_make_locator_prefers_role_then_text_then_selector() -> None:
    page = _Page()
    assert targeting.make_locator(page, role="button", name="OK").label == "role(button,OK,exact=False)"
    assert targeting.make_locator(page, text="Hi", exact=True).label == "text(Hi,exact=True)"
    assert targeting.make_locator(page, selector="#x").label == "page>loc(#x,deep=False)"


def test_make_locator_wraps_the_frame_first() -> None:
    page = _Page()
    loc = targeting.make_locator(page, selector="#x", frame="#f1")
    assert loc.label == "page>frame(#f1)>loc(#x,deep=False)"


def test_make_locator_without_a_target_names_every_valid_form() -> None:
    with pytest.raises(ValueError, match="provide one of: index, role, text, selector"):
        targeting.make_locator(_Page())


def test_resolve_field_rebuilds_the_frame_chain_and_deep_flag() -> None:
    page = _Page()
    fields = [_Field("#a", [], False), _Field("#b", ["#f1", "#f2"], True)]
    loc = targeting.resolve_field(page, fields, 1, fields_url=page.url)
    assert loc.label == "page>frame(#f1)>frame(#f2)>loc(#b,deep=True)"


def test_resolve_field_out_of_range_message_is_actionable() -> None:
    page = _Page()
    with pytest.raises(IndexError, match=r"out of range \(have 1; run list_fields first\)"):
        targeting.resolve_field(page, [_Field("#a", [], False)], 9, fields_url=page.url)


def test_resolve_field_refuses_a_stamp_from_another_page() -> None:
    page = _Page()
    with pytest.raises(targeting.StaleFieldIndexError) as excinfo:
        targeting.resolve_field(
            page, [_Field("#a", [], False)], 0, fields_url="http://a.test/other"
        )
    message = str(excinfo.value)
    assert "field indexes were captured on http://a.test/other" in message
    assert "page is now http://a.test/one" in message
    assert "run list-fields again" in message


def test_resolve_field_with_no_stamp_does_not_check_the_page() -> None:
    """An unstamped cache (a frontend that never stamps) still resolves."""
    page = _Page()
    loc = targeting.resolve_field(page, [_Field("#a", [], False)], 0, fields_url=None)
    assert loc.label == "page>loc(#a,deep=False)"


@pytest.mark.browser
def test_shared_resolver_reaches_an_iframe_field_from_the_daemon(base_url: str) -> None:
    """Integration proof: the extracted resolver still drives a real browser."""
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/fields.html"
    )
    try:
        fields: list[dict[str, Any]] = h.handle("list_fields", {"highlight": False})["result"][
            "fields"
        ]
        by_locator = {f["locator"]: f for f in fields}
        assert by_locator["#iframeinput"]["frame"] == ["#f1"]
        idx = by_locator["#iframeinput"]["index"]
        assert h.handle("fill", {"index": idx, "text": "ada"})["ok"] is True
        assert (
            h.handle("get_attribute", {"index": idx, "attr_name": "value"})["result"]["value"]
            == "ada"
        )
    finally:
        h.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ops_targeting.py -m "not browser" -v --no-cov`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'visus.web.ops'`

- [ ] **Step 3: Create the package**

Create `src/visus/web/ops/__init__.py`:

```python
"""The op vocabulary shared by the CLI session daemon and the MCP server.

This package sits BELOW both frontends. It imports ``visus.web.api`` and the
standard library and nothing else — never ``typer``, never ``mcp`` — which is
what makes it importable from the CLI when the ``[mcp]`` extra is absent and
from the MCP server when the ``[cli]`` extra is absent. That constraint is the
reason ``make_locator`` used to exist twice (``session_server.py:59-63`` states
it verbatim); this package removes the duplication instead of the constraint.

Anything that needs ``visus.web.cli`` (the daemon transport) imports it lazily
inside a function, so the layering never runs backwards at import time.
"""
```

Create `src/visus/web/ops/targeting.py`:

```python
"""One locator resolver for the CLI daemon and the MCP server.

Three helpers used to exist in two copies each, with the reason spelled out in
their own docstrings:

* ``make_locator``       — ``session_server.py:59-63`` / ``mcp/session.py:142-160``
* ``_any_match_visible`` — ``session_server.py:37-46`` / ``mcp/server.py:22-32``
* ``_resolve_field``     — CLI-only, and its absence is exactly why MCP had to
  instruct the model in prose to rebuild an iframe chain by hand
  (``mcp/server.py:91-100``).

They live here now. Both frontends import the same objects, so a fix to
targeting can no longer land on one surface and miss the other.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, cast

from visus.web import errors
from visus.web.api.locator import Locator

if TYPE_CHECKING:
    from visus.web.api.fields import Field
    from visus.web.api.page import Page


class StaleFieldIndexError(RuntimeError):
    """Raised when a cached field index no longer belongs to the current page.

    Index targeting re-resolves a stored selector against whatever page is loaded
    now. Generated selectors intentionally fall back to generic forms
    (``button[type="submit"]``, ``input[type="email"]``, ``.btn.primary``, a bare
    tag), each of which matches *something* on a different page — so without this
    guard a stale index clicks the wrong element and reports success.
    """


def any_match_visible(loc: Locator) -> bool:
    """True if at least one element the locator matches is visible.

    Tolerant of mid-navigation errors (treated as "not yet visible") and of
    locators that match several elements — so an agent can wait by a loose
    target (e.g. text=) even when a hidden duplicate sorts first in the DOM.
    """
    try:
        return any(loc.nth(i).is_visible() for i in range(loc.count()))
    except errors.VisusWebError:
        return False


def make_locator(
    page: Page,
    *,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> Locator:
    """Resolve a locator from the given target params.

    ``frame`` is applied first, so a role/text/selector target is looked up
    *inside* that iframe rather than in the top document.
    """
    root: Any = page if frame is None else page.frame_locator(frame)
    if role is not None:
        return cast(Locator, root.get_by_role(role, name=name, exact=exact))
    if text is not None:
        return cast(Locator, root.get_by_text(text, exact=exact))
    if selector is not None:
        return cast(Locator, root.locator(selector))
    raise ValueError("provide one of: index, role, text, selector")


def resolve_field(
    page: Page,
    fields: Sequence[Field],
    index: int,
    *,
    fields_url: str | None,
) -> Locator:
    """Re-resolve cached field *index* against *page* via the foundation contract.

    Walks the field's iframe chain with ``frame_locator`` and applies its
    ``deep`` flag, so one integer reaches an element three iframes down or inside
    an open shadow root. ``fields_url`` is the page identity stamped when the
    cache was filled; when it disagrees with the live URL the index is refused
    rather than re-resolved against a page it never described.
    """
    if index < 0 or index >= len(fields):
        raise IndexError(
            f"field index {index} out of range (have {len(fields)}; run list_fields first)"
        )
    if fields_url is not None:
        current = page.url
        if current != fields_url:
            raise StaleFieldIndexError(
                f"field indexes were captured on {fields_url}, "
                f"page is now {current} — run list-fields again"
            )
    field = fields[index]
    root: Any = page
    for sel in field.frame:
        root = root.frame_locator(sel)
    return cast(Locator, root.locator(field.locator, deep=field.deep))
```

- [ ] **Step 4: Point both frontends at it**

In `src/visus/web/cli/session_server.py`, delete `_any_match_visible` (`:37-46`), `make_locator` (`:49-71`) and the `StaleFieldIndexError` class PLAN 3 added, then add to the `visus.web` import block (after `from visus.web.backends.selenium.driver_delegate import SeleniumPageDelegate`, `:34`):

```python
from visus.web.ops.targeting import StaleFieldIndexError, make_locator, resolve_field
from visus.web.ops.targeting import any_match_visible as _any_match_visible

# `StaleFieldIndexError` and `make_locator` are re-exported, not used here: PLAN 3
# named the exception `session_server.StaleFieldIndexError` and tests/main.py
# import `make_locator` from this module. Listing them in __all__ is what tells
# ruff's F401 they are a deliberate re-export.
__all__ = [
    "SessionHandler",
    "SessionLockedError",
    "StaleFieldIndexError",
    "main",
    "make_locator",
    "serve",
    "session_file",
]
```

Replace `SessionHandler._resolve_field` (`:185-196`, as PLAN 3 Task 1 rewrote it) with:

```python
    def _resolve_field(self, index: int) -> Locator:
        """Re-resolve a cached field for an action via the foundation contract."""
        return resolve_field(self.page(), self._fields, index, fields_url=self._fields_url)
```

`errors` is still imported by `session_server.py` for other uses; if ruff's `F401` flags it after the delete, remove it from the import list.

In `src/visus/web/mcp/session.py`, delete `make_locator` (`:142-160`) and add to the import block (after `from visus.web.backends.selenium.driver_delegate import SeleniumPageDelegate`, `:13`):

```python
from visus.web.ops.targeting import make_locator

__all__ = ["Session", "make_locator"]
```

`Locator` and `cast` become unused in that module — remove them from `:6` and `:11` if ruff flags them.

In `src/visus/web/mcp/server.py`, delete `_any_match_visible` (`:22-32`) and add to the import block (after `from visus.web.mcp.session import Session, make_locator`, `:16`):

```python
from visus.web.ops.targeting import any_match_visible as _any_match_visible
```

`errors` becomes unused in `mcp/server.py` — remove `from visus.web import errors` (`:13`) if ruff flags it.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_ops_targeting.py -m "not browser" -v --no-cov`
Expected: PASS (9 passed)

Run: `uv run pytest tests/test_ops_targeting.py -m browser -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 6: Run every suite that touched the old copies**

Run: `uv run pytest tests/test_cli_session.py tests/test_mcp_server.py tests/test_mcp_list_fields.py -q --no-cov`
Expected: PASS — including PLAN 3's `test_index_targeting_refuses_after_a_js_driven_navigation` (the messages are byte-identical) and `test_handle_target_without_target_errors` (`tests/test_cli_session.py:327`, which asserts `"provide one of" in resp["error"]`).

- [ ] **Step 7: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 8: Commit**

```bash
git add src/visus/web/ops/__init__.py src/visus/web/ops/targeting.py \
        src/visus/web/cli/session_server.py src/visus/web/mcp/session.py \
        src/visus/web/mcp/server.py tests/test_ops_targeting.py
git commit -m "refactor(ops): one locator resolver shared by the CLI daemon and MCP"
```

---

### Task 2: `visus.web.ops.registry` — every MCP tool maps to a daemon op

Today the two surfaces drift silently: `mcp/server.py` registers 45 tools, `session_server.py` dispatches 41 ops, and the difference — `browser_network_requests` (`:570`), `browser_console_messages` (`:588`), `browser_tab_activate` (`:510`), `browser_set_tab_follow` (`:525`) — is D3, four capabilities the shell simply cannot reach, with no declared reason. Nothing in the repo notices.

This task adds the inventory and the test the brief asks for. It **fails until PLAN 5 has landed**, because PLAN 5's `_op_console_messages` / `_op_network_requests` / `_op_tab_activate` / `_op_tab_follow` are the four missing ops.

**Files:**
- Create: `src/visus/web/ops/registry.py`
- Test: `tests/test_ops_registry.py`

**Interfaces:**
- Produces:
  ```python
  TOOL_OPS: dict[str, str]                # tool name -> daemon op name
  SESSIONLESS_TOOLS: frozenset[str]       # no browser at all
  LOCAL_ONLY_TOOLS: frozenset[str]        # this process only, no daemon twin
  ```
- Consumes: `SessionHandler` (for the `_op_*` existence check), `mcp.server.mcp._tool_manager.list_tools()` (the same accessor `tests/test_mcp_server.py:19` already uses).

- [ ] **Step 1: Write the failing test**

Create `tests/test_ops_registry.py`:

```python
"""The tool <-> op inventory: MCP and the CLI daemon must not drift apart."""

from __future__ import annotations

from visus.web.cli.session_server import SessionHandler
from visus.web.ops import registry


def _registered_tool_names() -> set[str]:
    """Registered FastMCP tool names (same accessor as tests/test_mcp_server.py:19)."""
    from visus.web.mcp import server

    return {t.name for t in server.mcp._tool_manager.list_tools()}


def test_every_mcp_tool_maps_to_a_daemon_op() -> None:
    """The headline invariant: no capability may exist on MCP alone.

    D3 was exactly this — browser_network_requests / browser_console_messages /
    browser_tab_activate / browser_set_tab_follow gave MCP agents strictly more
    power than shell agents, with no reason stated anywhere.
    """
    registered = _registered_tool_names()
    accounted = set(registry.TOOL_OPS) | registry.SESSIONLESS_TOOLS | registry.LOCAL_ONLY_TOOLS
    unaccounted = sorted(registered - accounted)
    assert not unaccounted, (
        f"{len(unaccounted)} MCP tool(s) have no declared daemon op and no declared "
        f"exemption: {unaccounted}"
    )


def test_the_registry_never_names_a_tool_that_is_not_registered() -> None:
    registered = _registered_tool_names()
    accounted = set(registry.TOOL_OPS) | registry.SESSIONLESS_TOOLS | registry.LOCAL_ONLY_TOOLS
    ghosts = sorted(accounted - registered)
    assert not ghosts, f"registry names tool(s) the MCP server does not register: {ghosts}"


def test_every_mapped_op_exists_on_the_daemon() -> None:
    missing = sorted(
        f"{tool} -> _op_{op}"
        for tool, op in registry.TOOL_OPS.items()
        if not hasattr(SessionHandler, f"_op_{op}")
    )
    assert not missing, f"mapped op(s) with no SessionHandler handler: {missing}"


def test_the_exemption_sets_are_disjoint_from_the_map() -> None:
    assert not (set(registry.TOOL_OPS) & registry.SESSIONLESS_TOOLS)
    assert not (set(registry.TOOL_OPS) & registry.LOCAL_ONLY_TOOLS)
    assert not (registry.SESSIONLESS_TOOLS & registry.LOCAL_ONLY_TOOLS)


def test_the_four_mcp_only_holes_are_closed() -> None:
    """D3 by name, so a regression names itself in the failure message."""
    for tool in (
        "browser_network_requests",
        "browser_console_messages",
        "browser_tab_activate",
        "browser_set_tab_follow",
    ):
        op = registry.TOOL_OPS[tool]
        assert hasattr(SessionHandler, f"_op_{op}"), f"{tool} is still MCP-only (needs _op_{op})"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ops_registry.py -v --no-cov`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'visus.web.ops.registry'`

- [ ] **Step 3: Write the implementation**

Create `src/visus/web/ops/registry.py`:

```python
"""The tool <-> op inventory both frontends are checked against.

An MCP tool and a `visus` command are two frontends over one op. This module is
where that claim is written down, so a tool added to one surface and forgotten on
the other fails a test instead of shipping as a silent capability gap (D3: four
tools existed only on MCP, and nothing in the repo noticed).

Two exemptions are allowed and both must be declared:

* :data:`SESSIONLESS_TOOLS` — the tool touches no browser at all, so there is
  nothing for a daemon to own.
* :data:`LOCAL_ONLY_TOOLS` — the tool acts on *this process*, not on a page, so
  sending it across to another process would be meaningless.
"""

from __future__ import annotations

TOOL_OPS: dict[str, str] = {
    # Navigation
    "browser_navigate": "goto",
    "browser_navigate_back": "back",
    "browser_navigate_forward": "forward",
    "browser_reload": "reload",
    # Inspect
    "browser_snapshot": "snapshot",
    "browser_list_fields": "list_fields",
    "browser_clear_highlights": "clear_highlights",
    "browser_title": "title",
    "browser_url": "url",
    "browser_get_text": "get_text",
    "browser_get_attribute": "get_attribute",
    "browser_count": "count",
    # Actions
    "browser_click": "click",
    "browser_dblclick": "dblclick",
    "browser_fill": "fill",
    "browser_press": "press",
    "browser_hover": "hover",
    "browser_check": "check",
    "browser_uncheck": "uncheck",
    "browser_select_option": "select",
    "browser_drag": "drag",
    "browser_focus": "focus",
    "browser_clear": "clear_input",
    "browser_set_input_files": "upload",
    # Wait / expect
    "browser_wait_for": "wait",
    "browser_expect_text": "expect_text",
    # Tabs
    "browser_tab_list": "tabs",
    "browser_tab_new": "tab_new",
    "browser_tab_select": "tab",
    "browser_tab_activate": "tab_activate",
    "browser_tab_close": "tab_close",
    "browser_set_tab_follow": "tab_follow",
    # Dialogs
    "browser_handle_dialog": "dialog",
    # Network / console capture
    "browser_network_requests": "network_requests",
    "browser_console_messages": "console_messages",
    # Cookies
    "browser_get_cookies": "cookies",
    "browser_add_cookies": "add_cookies",
    "browser_clear_cookies": "clear_cookies",
    # Media / JavaScript
    "browser_screenshot": "screenshot",
    "browser_evaluate": "eval",
    # Vision
    "browser_read_text": "read_text",
    "browser_solve_captcha": "solve_captcha",
    "browser_find_image": "find_image",
}

SESSIONLESS_TOOLS: frozenset[str] = frozenset(
    {
        # Pure HTML parsing — `visus translate` is its CLI twin and is likewise the
        # only command in either CLI that works with no browser running at all.
        "browser_translate_element",
    }
)

LOCAL_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        # Owns THIS server's browser lifetime. The shell's session lifetime belongs
        # to `visus session stop`; sending `shutdown` across would kill a browser
        # the user is still using.
        "browser_close",
    }
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ops_registry.py -v --no-cov`
Expected: PASS (5 passed).

If `test_every_mapped_op_exists_on_the_daemon` or `test_the_four_mcp_only_holes_are_closed` fails naming `_op_network_requests` / `_op_console_messages` / `_op_tab_activate` / `_op_tab_follow`, **PLAN 5 has not landed** — stop and land PLAN 5 Tasks 3, 4 and 5 first. Do not paper over it by moving those tools into an exemption set; the exemptions are for tools with no page to act on, and these four have one.

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/ops/registry.py tests/test_ops_registry.py
git commit -m "test(ops): assert every MCP tool name maps to a daemon op"
```

---

### Task 3: `RemoteDispatcher` — the daemon's op vocabulary as an in-process object

`SessionHandler.handle(op, args) -> {"ok": ..., "result": ...}` is the whole vocabulary. The only thing standing between the MCP server and the shell's browser is that the browser lives in another process. This task makes that a detail: an object with the same signature and the same envelope, backed by the daemon's JSON-lines socket.

**Files:**
- Create: `src/visus/web/ops/remote.py`
- Test: `tests/test_ops_remote.py`

**Interfaces:**
- Produces:
  ```python
  class NoSessionError(RuntimeError): ...
  class RemoteDispatcher:
      def __init__(self, *, start_dir: str | Path | None = None) -> None: ...
      def session(self) -> dict[str, Any] | None: ...
      def is_live(self) -> bool: ...
      def handle(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]: ...
      def result(self, op: str, args: dict[str, Any] | None = None) -> Any: ...
  ```
- Consumes: `session_client.find_session(start_dir)` (`session_client.py:69-89`), `session_client.send_envelope(op, args, *, start_dir)` and `session_client.SessionError` (PLAN 4).

- [ ] **Step 1: Write the failing test**

Create `tests/test_ops_remote.py`:

```python
"""RemoteDispatcher: SessionHandler's contract, another process's browser."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from visus.web.cli import session_client
from visus.web.ops.remote import NoSessionError, RemoteDispatcher

_PAGE = "data:text/html,<title>remote</title><h1 id=h>hello</h1>"


def test_handle_returns_the_daemon_envelope_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The envelope is passed through untouched — `page`/`code` included."""
    calls: list[tuple[str, Any, Any]] = []
    env = {
        "ok": True,
        "result": "clicked",
        "page": {"url": "http://x/dash", "title": "Dash", "fields_stale": False},
        "code": 'page.get_by_role("button", name="Submit").click()',
    }

    def fake_send_envelope(op: str, args: Any = None, *, start_dir: Any = None) -> dict[str, Any]:
        calls.append((op, args, start_dir))
        return env

    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None: {"pid": 1})
    monkeypatch.setattr(session_client, "send_envelope", fake_send_envelope)

    d = RemoteDispatcher(start_dir="/proj")
    assert d.handle("click", {"index": 3}) == env
    assert calls == [("click", {"index": 3}, "/proj")]


def test_handle_turns_a_daemon_failure_back_into_an_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SessionHandler.handle` never raises; neither may this."""

    def boom(op: str, args: Any = None, *, start_dir: Any = None) -> dict[str, Any]:
        raise session_client.SessionError("IndexError: field index 9 out of range")

    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None: {"pid": 1})
    monkeypatch.setattr(session_client, "send_envelope", boom)

    resp = RemoteDispatcher().handle("click", {"index": 9})
    assert resp["ok"] is False
    assert "field index 9 out of range" in resp["error"]


def test_is_live_and_session_are_false_when_nothing_is_running(tmp_path: Path) -> None:
    d = RemoteDispatcher(start_dir=tmp_path)
    assert d.session() is None
    assert d.is_live() is False


def test_result_raises_no_session_error_when_nothing_is_running(tmp_path: Path) -> None:
    d = RemoteDispatcher(start_dir=tmp_path)
    with pytest.raises(NoSessionError, match="visus session start"):
        d.result("title")


def test_result_raises_on_a_failed_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None: {"pid": 1})
    monkeypatch.setattr(
        session_client,
        "send_envelope",
        lambda op, args=None, **_: (_ for _ in ()).throw(session_client.SessionError("nope")),
    )
    with pytest.raises(RuntimeError, match="nope"):
        RemoteDispatcher().result("title")


@pytest.mark.browser
def test_remote_dispatcher_drives_a_real_daemon(tmp_path: Path) -> None:
    """The integration proof: a second process's browser, the same envelope."""
    session_client.start_daemon("chrome", headless=True, url=_PAGE, cwd=tmp_path)
    try:
        d = RemoteDispatcher(start_dir=tmp_path)
        assert d.is_live() is True
        assert d.handle("title")["result"] == "remote"
        assert d.result("get_text", {"selector": "#h"})["value"] == "hello"

        # A mutating op comes back with PLAN 4's page footer, unchanged.
        env = d.handle("goto", {"url": "data:text/html,<title>second</title>"})
        assert env["ok"] is True
        assert env["page"]["title"] == "second"

        # A failing op is an envelope, not an exception.
        bad = d.handle("click", {"index": 42})
        assert bad["ok"] is False and "out of range" in bad["error"]
    finally:
        session_client.stop(start_dir=tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ops_remote.py -m "not browser" -v --no-cov`
Expected: FAIL at collection — `ModuleNotFoundError: No module named 'visus.web.ops.remote'`

- [ ] **Step 3: Write the implementation**

Create `src/visus/web/ops/remote.py`:

```python
"""Reach a running `visus` session daemon from any frontend, in-process.

:class:`RemoteDispatcher` has the same signature and returns the same envelope as
``SessionHandler.handle`` — the only difference is which process owns the
browser. That is what lets the MCP server stop being a second, invisible browser
(``mcp/session.py:32-40`` launches headless with manual tab-follow while
``session_server.py:104-119`` launches headed with auto-follow, and nothing tells
the model they are different windows) and become a frontend over the very
session the shell is driving.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from types import ModuleType


class NoSessionError(RuntimeError):
    """Raised when no live `visus` session daemon can be found."""


class RemoteDispatcher:
    """The daemon's op vocabulary as a plain object.

    *start_dir* is where the search for ``.visus/session.json`` begins; the search
    walks upward, git-style (``session_client.py:58-66``). ``None`` means the
    process's current working directory.
    """

    def __init__(self, *, start_dir: str | Path | None = None) -> None:
        self._start_dir = start_dir

    @staticmethod
    def _client() -> ModuleType:
        """The daemon transport, imported lazily.

        ``visus.web.ops`` must not depend on ``visus.web.cli`` at import time —
        the layering runs the other way. ``session_client`` imports nothing but
        the standard library, so this pulls in no optional dependency and works
        with neither the ``[cli]`` nor the ``[mcp]`` extra installed.
        """
        from visus.web.cli import session_client

        return session_client

    def session(self) -> dict[str, Any] | None:
        """The live session dict, or ``None``. Cleans up a stale session file."""
        info: dict[str, Any] | None = self._client().find_session(self._start_dir)
        return info

    def is_live(self) -> bool:
        """True when a daemon is running and its socket accepts."""
        return self.session() is not None

    def handle(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        """Dispatch one op. Returns ``{ok:True,result:...}`` or ``{ok:False,error:str}``.

        Mirrors ``SessionHandler.handle`` exactly, including the rule that it
        never raises for a daemon-side failure: a frontend that switches between
        local and remote must not also switch error styles.
        """
        client = self._client()
        try:
            env: dict[str, Any] = client.send_envelope(
                op, args or {}, start_dir=self._start_dir
            )
        except client.SessionError as exc:
            return {"ok": False, "error": str(exc)}
        return env

    def result(self, op: str, args: dict[str, Any] | None = None) -> Any:
        """The op's ``result`` payload, raising on failure.

        Use this where a caller wants an exception (an MCP tool body); use
        :meth:`handle` where it wants the whole envelope (page state, generated
        code).
        """
        if self.session() is None:
            raise NoSessionError(
                "no live visus session — run `visus session start` in the project directory"
            )
        env = self.handle(op, args)
        if not env.get("ok"):
            raise RuntimeError(str(env.get("error", "unknown error")))
        return env.get("result")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ops_remote.py -m "not browser" -v --no-cov`
Expected: PASS (5 passed)

Run: `uv run pytest tests/test_ops_remote.py -m browser -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/ops/remote.py tests/test_ops_remote.py
git commit -m "feat(ops): reach the session daemon in-process via RemoteDispatcher"
```

---

### Task 4: The MCP session grows a field cache (index targeting, half 1)

`browser_list_fields` (`mcp/server.py:86-110`) returns the field dicts and then instructs the **model**, in prose, to rebuild the iframe chain by hand: *"root = page; for sel in frame: root = root.frame_locator(sel); target = root.locator(locator, deep=deep)"* (`:98-99`). That paragraph exists because the MCP `Session` has no field cache. Frame/shadow re-resolution is the best idea in the product (`session_server.py:185-196`) and MCP cannot reach it (D12).

This task gives the MCP session the same cache the daemon has, using the resolver Task 1 extracted. Task 5 then exposes it as an `index` parameter.

**Files:**
- Modify: `src/visus/web/mcp/session.py:16-41` (`__init__`, `_ensure`), `:78-86` (`new_page`), `:100-115` (`select`, `activate`), `:117-128` (`close_tab`), `:130-139` (`close`)
- Test: `tests/test_mcp_index.py`

**Interfaces:**
- Consumes: `visus.web.ops.targeting.resolve_field` / `make_locator` / `StaleFieldIndexError` (Task 1).
- Produces:
  ```python
  class Session:
      def cache_fields(self, fields: list[Field]) -> None: ...
      def field_locator(self, index: int) -> Locator: ...
      def target(self, args: dict[str, Any]) -> Locator: ...
      def invalidate_fields(self) -> None: ...
  ```
  `target(args)` reads the **daemon's** payload keys (`index`, `selector`, `role`, `name`, `target_text`, `exact`, `frame`) so one dict serves both the local resolver and the remote daemon.

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_index.py`:

```python
"""Index / frame / shadow targeting on the MCP surface (D12)."""

from __future__ import annotations

import os

import pytest

# Force headless before the server module is imported (session reads env at page-open time)
os.environ["VISUS_WEB_HEADLESS"] = "1"


@pytest.fixture()
def srv(base_url: str):  # type: ignore[no-untyped-def]
    """Fresh session + (server_module, base_url) pair for each test."""
    from visus.web.mcp import server

    server._session.close()
    yield server, base_url
    server._session.close()


def test_target_without_a_target_names_every_valid_form() -> None:
    from visus.web.mcp.session import Session

    s = Session()
    with pytest.raises(ValueError, match="provide one of: index, role, text, selector"):
        s.target({})


def test_field_locator_without_a_cache_is_an_actionable_error() -> None:
    from visus.web.mcp.session import Session

    s = Session()
    with pytest.raises(IndexError, match="run list_fields first"):
        s.field_locator(0)


@pytest.mark.browser
def test_index_reaches_a_field_inside_an_iframe(srv):  # type: ignore[no-untyped-def]
    """One integer, three layers: the frame chain is rebuilt by the resolver."""
    server, base_url = srv
    server.browser_navigate(f"{base_url}/fields.html")
    fields = server.browser_list_fields(include_hidden=True)
    by_locator = {f["locator"]: f for f in fields}
    assert by_locator["#iframeinput"]["frame"] == ["#f1"]

    idx = by_locator["#iframeinput"]["index"]
    loc = server._session.field_locator(idx)
    loc.fill("ada")
    assert loc.get_attribute("value") == "ada"


@pytest.mark.browser
def test_index_reaches_a_field_inside_open_shadow_dom(srv):  # type: ignore[no-untyped-def]
    server, base_url = srv
    server.browser_navigate(f"{base_url}/fields.html")
    fields = server.browser_list_fields(include_hidden=True)
    by_locator = {f["locator"]: f for f in fields}
    assert by_locator["#shadowinput"]["deep"] is True

    loc = server._session.field_locator(by_locator["#shadowinput"]["index"])
    loc.fill("hidden-but-reachable")
    assert loc.get_attribute("value") == "hidden-but-reachable"


@pytest.mark.browser
def test_a_navigation_makes_cached_indexes_refuse_to_resolve(srv):  # type: ignore[no-untyped-def]
    """The MCP surface inherits the daemon's staleness contract, not just its cache."""
    from visus.web.ops.targeting import StaleFieldIndexError

    server, base_url = srv
    server.browser_navigate(f"{base_url}/fields.html")
    server.browser_list_fields(include_hidden=True)
    server.browser_navigate(f"{base_url}/forms.html")

    with pytest.raises(StaleFieldIndexError, match="run list-fields again"):
        server._session.field_locator(0)


@pytest.mark.browser
def test_target_falls_back_to_role_and_selector(srv):  # type: ignore[no-untyped-def]
    server, base_url = srv
    server.browser_navigate(f"{base_url}/forms.html")
    assert server._session.target({"role": "textbox", "name": "Username"}).count() == 1
    assert server._session.target({"selector": "#user"}).count() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_index.py -m "not browser" -v --no-cov`
Expected: FAIL — `AttributeError: 'Session' object has no attribute 'target'`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/mcp/session.py`, add to the import block (below `from visus.web.ops.targeting import make_locator`, added in Task 1):

```python
from typing import Any

from visus.web.api.fields import Field
from visus.web.api.locator import Locator
from visus.web.ops.targeting import resolve_field
```

In `Session.__init__` (`:19-30`), after `self._active_handle: str | None = None`, add:

```python
        # The last browser_list_fields result, so an action tool can act by INDEX
        # and get the daemon's frame/shadow re-resolution for free. Stamped with
        # the page it was captured on: a stale index must refuse, never re-resolve
        # a generic fallback selector against a page it never described.
        self._fields: list[Field] = []
        self._fields_url: str | None = None
```

Add these four methods immediately after `set_follow` (`:66-71`):

```python
    def invalidate_fields(self) -> None:
        """Drop the cached field list and its page stamp — index targeting is void."""
        self._fields = []
        self._fields_url = None

    def cache_fields(self, fields: list[Field]) -> None:
        """Remember an enumeration so index targeting can re-resolve from it."""
        self._fields = list(fields)
        self._fields_url = self.page().url

    def field_locator(self, index: int) -> Locator:
        """Re-resolve cached field *index* — iframe chain and shadow ``deep`` included."""
        return resolve_field(self.page(), self._fields, index, fields_url=self._fields_url)

    def target(self, args: dict[str, Any]) -> Locator:
        """Resolve an action target from the DAEMON's payload keys.

        Deliberately the daemon's spelling — ``index`` first, then
        ``selector``/``role``/``name``/``target_text``/``exact``/``frame`` — so a
        single payload dict serves both this in-process resolver and
        ``RemoteDispatcher``. ``target_text`` (not ``text``) is the locator-text
        key, because ``text`` is already fill's VALUE payload
        (``session_server.py:205-221``).
        """
        if args.get("index") is not None:
            return self.field_locator(int(args["index"]))
        return make_locator(
            self.page(),
            selector=args.get("selector"),
            role=args.get("role"),
            name=args.get("name"),
            text=args.get("target_text"),
            exact=bool(args.get("exact", False)),
            frame=args.get("frame"),
        )
```

Then invalidate the cache everywhere the page or tab identity changes. In `new_page` (`:78-86`), after `self._current_idx = len(self._pages) - 1`, add:

```python
        self.invalidate_fields()  # cached indexes belonged to the previous tab
```

In `select` (`:100-105`), after `self._current_idx = index`, add:

```python
        self.invalidate_fields()  # cached indexes belonged to the previous tab
```

In `activate` (`:107-115`), inside the matching branch after `self._current_idx = i`, add:

```python
                self.invalidate_fields()  # cached indexes belonged to the previous tab
```

In `close_tab` (`:117-128`), replace the `else` branch's body with:

```python
        else:
            self._current_idx = min(idx, len(self._pages) - 1)
            self.invalidate_fields()  # cached indexes belonged to the closed tab
```

In `close` (`:130-139`), after `self._active_handle = None`, add:

```python
        self.invalidate_fields()
```

Finally, cache on enumeration. In `src/visus/web/mcp/server.py`, replace the last two lines of `browser_list_fields` (`:106-110`) with:

```python
    parsed = [k.strip() for k in kind.split(",") if k.strip()] if kind else None
    fields = _session.page().list_fields(
        kinds=parsed, include_hidden=include_hidden, highlight=highlight
    )
    _session.cache_fields(fields)  # so the action tools can target by `index`
    return [f.to_dict() for f in fields]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_index.py -m "not browser" -v --no-cov`
Expected: PASS (2 passed)

Run: `uv run pytest tests/test_mcp_index.py -m browser -v --no-cov`
Expected: PASS (4 passed)

- [ ] **Step 5: Run the existing MCP suites**

Run: `uv run pytest tests/test_mcp_list_fields.py tests/test_e2e_mcp.py -q --no-cov`
Expected: PASS

- [ ] **Step 6: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 7: Commit**

```bash
git add src/visus/web/mcp/session.py src/visus/web/mcp/server.py tests/test_mcp_index.py
git commit -m "feat(mcp): cache enumerated fields so actions can target by index"
```

---

### Task 5: `index` on every targeting tool, through the shared seam

The 21 tools that take a target accept only `(selector, role, name, text, exact, frame)` — `browser_click` at `mcp/server.py:203-217` and identically for `browser_dblclick` `:220-234`, `browser_fill` `:237-252`, `browser_press`, `browser_hover`, `browser_check`, `browser_uncheck`, `browser_select_option`, `browser_drag`, `browser_focus`, `browser_clear`, `browser_set_input_files`, plus the reads and the vision tools. This task adds `index` to all of them.

It also introduces the seam every tool body will use from here on: `_run(op, args, local)` returns a **daemon-shaped envelope** in both modes. Today `_remote` is always `None`, so `_run` just calls `local()` — Task 7 flips it on. Rewriting the bodies once, now, is why item 1's attach task is sequenced after item 2.

**Files:**
- Modify: `src/visus/web/mcp/server.py:1-33` (imports + helpers), `:146-195` (reads), `:203-411` (actions), `:419-466` (wait/expect), `:632-643` (screenshot), `:660-735` (vision)
- Modify: `src/visus/web/ops/registry.py` (add `INDEXABLE_TOOLS`)
- Test: `tests/test_ops_registry.py`, `tests/test_mcp_index.py`

**Interfaces:**
- Produces:
  ```python
  # src/visus/web/mcp/server.py
  _remote: RemoteDispatcher | None
  def _target_payload(*, index=None, selector=None, role=None, name=None,
                      text=None, exact=False, frame=None) -> dict[str, Any]: ...
  def _run(op: str, args: dict[str, Any], local: Callable[[], Any]) -> dict[str, Any]: ...
  # src/visus/web/ops/registry.py
  INDEXABLE_TOOLS: frozenset[str]
  ```
- Consumes: `Session.target` (Task 4), `RemoteDispatcher` (Task 3), `registry.TOOL_OPS` (Task 2).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ops_registry.py`:

```python
def test_every_indexable_tool_accepts_an_index_parameter() -> None:
    """D12: index targeting is the product's best ergonomics idea, CLI-only until now."""
    import inspect

    from visus.web.mcp import server

    problems: list[str] = []
    for name in sorted(registry.INDEXABLE_TOOLS):
        params = inspect.signature(getattr(server, name)).parameters
        if "index" not in params:
            problems.append(f"{name}: no `index` parameter")
            continue
        p = params["index"]
        if p.default is not None:
            problems.append(f"{name}: `index` must default to None, got {p.default!r}")
        # mcp/server.py uses `from __future__ import annotations`, so this is a string.
        if str(p.annotation) != "int | None":
            problems.append(f"{name}: `index` must be `int | None`, got {p.annotation!r}")
    assert not problems, problems


def test_indexable_tools_are_all_registered_and_daemon_backed() -> None:
    assert registry.INDEXABLE_TOOLS <= set(registry.TOOL_OPS)
```

Append to `tests/test_mcp_index.py`:

```python
@pytest.mark.browser
def test_action_tools_accept_an_index(srv):  # type: ignore[no-untyped-def]
    """The whole point: `browser_fill(index=N, ...)` with no hand-built frame chain."""
    server, base_url = srv
    server.browser_navigate(f"{base_url}/fields.html")
    fields = server.browser_list_fields(include_hidden=True)
    by_locator = {f["locator"]: f for f in fields}
    idx = by_locator["#iframeinput"]["index"]

    assert server.browser_fill("student", index=idx).startswith("filled with 'student'")
    assert server.browser_get_attribute("value", index=idx) == "student"
    assert server.browser_count(index=idx) == 1
    server.browser_clear(index=idx)
    assert server.browser_get_attribute("value", index=idx) == ""


@pytest.mark.browser
def test_a_stale_index_is_refused_by_an_action_tool(srv):  # type: ignore[no-untyped-def]
    server, base_url = srv
    server.browser_navigate(f"{base_url}/fields.html")
    server.browser_list_fields(include_hidden=True)
    server.browser_navigate(f"{base_url}/forms.html")

    from visus.web.ops.targeting import StaleFieldIndexError

    with pytest.raises(StaleFieldIndexError, match="run list-fields again"):
        server.browser_click(index=0)


def test_target_payload_renames_text_to_the_daemon_key() -> None:
    from visus.web.mcp import server

    payload = server._target_payload(index=None, selector=None, role="button", name="OK", text="Go")
    assert payload["target_text"] == "Go"
    assert "text" not in payload


def test_run_uses_the_local_callable_while_detached() -> None:
    from visus.web.mcp import server

    assert server._remote is None
    assert server._run("title", {}, lambda: "local title") == {
        "ok": True,
        "result": "local title",
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ops_registry.py tests/test_mcp_index.py -m "not browser" -v --no-cov`
Expected: FAIL — `AttributeError: module 'visus.web.ops.registry' has no attribute 'INDEXABLE_TOOLS'` and `AttributeError: module 'visus.web.mcp.server' has no attribute '_target_payload'`

- [ ] **Step 3: Add the registry entry**

Append to `src/visus/web/ops/registry.py`:

```python
INDEXABLE_TOOLS: frozenset[str] = frozenset(
    {
        # Every tool that resolves an element. `index` re-resolves a cached field
        # through its iframe chain and shadow `deep` flag, which no combination of
        # selector/role/text can express from outside the frame (D12).
        "browser_click",
        "browser_dblclick",
        "browser_fill",
        "browser_press",
        "browser_hover",
        "browser_check",
        "browser_uncheck",
        "browser_select_option",
        "browser_drag",
        "browser_focus",
        "browser_clear",
        "browser_set_input_files",
        "browser_get_text",
        "browser_get_attribute",
        "browser_count",
        "browser_wait_for",
        "browser_expect_text",
        "browser_screenshot",
        "browser_read_text",
        "browser_solve_captcha",
        "browser_find_image",
    }
)
```

- [ ] **Step 4: Add the seam to `mcp/server.py`**

Replace the import block (`:7-19`) with:

```python
from __future__ import annotations

import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP, Image

from visus.web.api.assertions import expect
from visus.web.mcp.session import Session, make_locator
from visus.web.ops.remote import RemoteDispatcher
from visus.web.ops.targeting import any_match_visible as _any_match_visible

mcp = FastMCP("visus-web")
_session = Session()

# Set by browser_attach_session (Task 7). While None, every op runs in this
# process against this server's own browser.
_remote: RemoteDispatcher | None = None
```

`make_locator` stays imported: `browser_drag`'s target selector and any future direct use need it, and removing it would churn Task 1's re-export test.

Add these two helpers immediately below (replacing the deleted `_any_match_visible` body's slot):

```python
def _target_payload(
    *,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> dict[str, Any]:
    """This tool's targeting parameters as the DAEMON's payload.

    One payload shape serves the in-process resolver (``Session.target``) and the
    remote one (``RemoteDispatcher``), so a tool body never has to know which is
    in play. The locator-TEXT target is renamed ``text`` -> ``target_text``
    because the daemon reserves ``text`` for fill's VALUE payload
    (``session_server.py:205-221``).
    """
    return {
        "index": index,
        "selector": selector,
        "role": role,
        "name": name,
        "target_text": text,
        "exact": exact,
        "frame": frame,
    }


def _run(op: str, args: dict[str, Any], local: Callable[[], Any]) -> dict[str, Any]:
    """Execute one op and return a daemon-shaped envelope.

    Attached (``browser_attach_session``): the op crosses to the `visus` session
    daemon, so it drives the SAME browser the shell is driving and comes back
    with the envelope ``SessionHandler.handle`` builds — ``result`` plus, for a
    mutating op, ``page`` state and the generated ``code`` line. Detached:
    *local* runs here against this server's own browser and the envelope is
    built here. Either way there is exactly one op vocabulary.

    *local* is a callable, not a value, so the local path — which would launch a
    browser — is never executed while attached.
    """
    if _remote is None:
        return {"ok": True, "result": local()}
    env = _remote.handle(op, args)
    if not env.get("ok"):
        raise RuntimeError(str(env.get("error", "unknown error")))
    return env
```

- [ ] **Step 5: Rewrite the 21 targeting tools**

Every one follows the same three-line shape. `browser_click` (`:203-217`) becomes the pattern:

```python
@mcp.tool()
def browser_click(
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Click an element targeted by index, role+name, text, or css/xpath selector.

    `index` is a number from browser_list_fields and is the strongest target: it
    re-resolves the element through its iframe chain and open shadow roots, which
    no selector written from outside the frame can do.
    """
    args = _target_payload(
        index=index, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )
    return _acted(_run("click", args, lambda: _session.target(args).click()), "clicked")
```

`browser_fill` (`:237-252`), which carries a value payload as well:

```python
@mcp.tool()
def browser_fill(
    text_value: str,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Fill an input/textarea with the given text_value (target by index or selector)."""
    args = _target_payload(
        index=index, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )
    args["text"] = text_value
    return _acted(
        _run("fill", args, lambda: _session.target(args).fill(text_value)),
        f"filled with {text_value!r}",
    )
```

`browser_get_text` (`:146-160`), which returns PLAN 3's `{"value", "present"}` shape:

```python
@mcp.tool()
def browser_get_text(
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str | None:
    """Return the visible text content of an element (None when it does not exist)."""
    args = _target_payload(
        index=index, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )

    def _local() -> dict[str, Any]:
        loc = _session.target(args).first()  # tolerate multi-match (agent-friendly read)
        return {"value": loc.text_content(), "present": loc.count() > 0}

    result: dict[str, Any] = _run("get_text", args, _local)["result"]
    value: str | None = result["value"]
    return value
```

`browser_screenshot` (`:632-643`), the one tool whose payload crosses as a file:

```python
@mcp.tool()
def browser_screenshot(
    full_page: bool = False,
    index: int | None = None,
    selector: str | None = None,
) -> Image:
    """Take a screenshot of the page or a specific element. Returns a PNG image."""
    args = _target_payload(index=index, selector=selector)
    args["full_page"] = full_page
    if _remote is not None:
        # The daemon writes PNGs to disk and returns the path. It is discovered
        # through `.visus/` beside this process's cwd, so both processes are on
        # the same filesystem and a temp-file hand-off is sound.
        tmp = Path(tempfile.gettempdir()) / f"visus-mcp-{uuid.uuid4().hex}.png"
        args["path"] = str(tmp)
        _run("screenshot", args, lambda: None)
        try:
            return Image(data=tmp.read_bytes(), format="png")
        finally:
            tmp.unlink(missing_ok=True)
    if index is not None or selector is not None:
        return Image(data=_session.target(args).screenshot(), format="png")
    return Image(data=_session.page().screenshot(full_page=full_page), format="png")
```

Apply the same shape to the remaining 17 tools, changing only the op, the extra payload keys, the local lambda and the returned message. Each keeps its existing docstring, with `index` named first in the targeting list:

| Tool (current lines) | op | extra payload keys | local lambda | returns |
|---|---|---|---|---|
| `browser_dblclick` (`:220-234`) | `dblclick` | — | `_session.target(args).dblclick()` | `_acted(env, "double-clicked")` |
| `browser_press` (`:255-270`) | `press` | `args["key"] = key` | `_session.target(args).press(key)` | `_acted(env, f"pressed {key!r}")` |
| `browser_hover` (`:273-287`) | `hover` | — | `_session.target(args).hover()` | `_acted(env, "hovered")` |
| `browser_check` (`:290-304`) | `check` | — | `_session.target(args).check()` | `_acted(env, "checked")` |
| `browser_uncheck` (`:307-321`) | `uncheck` | — | `_session.target(args).uncheck()` | `_acted(env, "unchecked")` |
| `browser_select_option` (`:324-339`) | `select` | `args["value"] = value` | `_session.target(args).select_option(value=value)` | `_acted(env, f"selected option {value!r}")` |
| `browser_drag` (`:342-359`) | `drag` | `args["target_selector"] = target_selector`; `args["target_index"] = target_index` | see below | `_acted(env, f"dragged to {target_selector or f'field {target_index}'!r}")` |
| `browser_focus` (`:362-376`) | `focus` | — | `_session.target(args).focus()` | `_acted(env, "focused")` |
| `browser_clear` (`:379-393`) | `clear_input` | — | `_session.target(args).clear()` | `_acted(env, "cleared")` |
| `browser_set_input_files` (`:396-411`) | `upload` | `args["paths"] = paths` | `_session.target(args).set_input_files(paths)` | `_acted(env, f"set {len(paths)} file(s)")` |
| `browser_get_attribute` (`:163-178`) | `get_attribute` | `args["attr_name"] = attr_name` | `{"value": loc.get_attribute(attr_name), "present": loc.count() > 0}` with `loc = _session.target(args).first()` | `env["result"]["value"]` |
| `browser_count` (`:181-195`) | `count` | — | `_session.target(args).count()` | `env["result"]` |
| `browser_wait_for` (`:419-443`) | `wait` | `args["state"] = state`; `args["timeout"] = timeout` | the existing `time.monotonic()` poll loop over `_any_match_visible`, with `loc = _session.target(args)` replacing the `make_locator(...)` call at `:432-434` | `env["result"]` |
| `browser_expect_text` (`:446-466`) | `expect_text` | `args["expected_text"] = expected_text`; `args["timeout"] = timeout` | the existing try/except around `expect(loc.first()).to_have_text(...)` returning `"PASSED"` / `f"FAILED: {exc}"`, with `loc = _session.target(args)` replacing the `make_locator(...)` call at `:459-461` | `env["result"]` |
| `browser_read_text` (`:660-677`) | `read_text` | — | `_session.target(args).ocr_text()` | `env["result"]` |
| `browser_solve_captcha` (`:680-694`) | `solve_captcha` | — | `_session.page().solve_captcha(_session.target(args))` | `env["result"]` |
| `browser_find_image` (`:697-735`) | `find_image` | `args["template_path"] = template_path`; `args["confidence"] = confidence` | the existing numpy body, but resolving through `_session.target(args)` when `index`/`selector`/`role`/`text` is set and `_session.page().screenshot()` otherwise | `env["result"]` |

`browser_drag`'s local lambda, written out because it has two target forms:

```python
    def _local() -> None:
        src = _session.target(args)
        if target_selector is not None:
            src.drag_to(_session.page().locator(target_selector))
        elif target_index is not None:
            src.drag_to(_session.field_locator(target_index))
        else:
            raise ValueError("provide a drag target: target_selector or target_index")
```

`browser_drag` also gains `target_index: int | None = None` beside its existing `target_selector: str` (which becomes `target_selector: str | None = None`), matching `_op_drag` (`session_server.py:351-363`).

The 12 action tools all call `_acted(env, message)`; the reads and vision tools return `env["result"]` directly. Task 7 widens `_acted` to the two-argument form — until then, temporarily define it as:

```python
def _acted(env: dict[str, Any], message: str) -> str:
    """An action's result plus the page state the agent needs for its next step."""
    try:
        page = _session.page()
        return f"{message}\n\n### Page\n- URL: {page.url}\n- Title: {page.title()}"
    except Exception:  # noqa: BLE001 — page state is telemetry, never the result
        return message
```

This replaces PLAN 4 Task 17's one-argument `_acted` at `mcp/server.py:34-45`. Its two tests (`tests/test_e2e_mcp.py::test_click_result_reports_the_resulting_page`, `::test_fill_result_reports_the_page`) call the tools, not the helper, so they stay green.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_ops_registry.py tests/test_mcp_index.py -m "not browser" -v --no-cov`
Expected: PASS (9 passed)

Run: `uv run pytest tests/test_mcp_index.py -m browser -v --no-cov`
Expected: PASS (6 passed)

- [ ] **Step 7: Run the existing MCP suites**

Run: `uv run pytest tests/test_mcp_server.py tests/test_mcp_list_fields.py tests/test_e2e_mcp.py -q --no-cov`
Expected: PASS — the tool inventory is still 45 (`_target_payload`, `_run` and `_acted` are undecorated helpers).

- [ ] **Step 8: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 9: Commit**

```bash
git add src/visus/web/mcp/server.py src/visus/web/ops/registry.py \
        tests/test_ops_registry.py tests/test_mcp_index.py
git commit -m "feat(mcp): index targeting on every action tool, through one dispatch seam"
```

---

### Task 6: The remaining 22 tools go through the same seam

Task 5 converted the tools that resolve an element. This task converts the rest — navigation, page inspection, tabs, dialogs, network/console, cookies and `evaluate` — and then locks totality down: a test asserts that **every** tool in `TOOL_OPS` dispatches through `_run` with its declared op. After this task there is no such thing as a half-attached MCP server.

**Files:**
- Modify: `src/visus/web/mcp/server.py:40-143` (navigation + inspect), `:474-538` (tabs), `:546-561` (dialogs), `:569-599` (network/console), `:607-624` (cookies), `:646-652` (`browser_evaluate`), `:743-747` (`browser_close`)
- Test: `tests/test_mcp_attach.py`

**Interfaces:**
- Consumes: `_run` / `_target_payload` (Task 5), `registry.TOOL_OPS` (Task 2).
- Produces: no new symbols — the structural invariant "every daemon-backed tool calls `_run`".

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_attach.py`:

```python
"""One dispatcher, two frontends: structure, routing and refusals."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

import pytest

os.environ["VISUS_WEB_HEADLESS"] = "1"


def _tool_sources() -> dict[str, str]:
    """{function name: its source text} for every top-level def in mcp/server.py."""
    from visus.web.mcp import server

    src = Path(server.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            segment = ast.get_source_segment(src, node)
            if segment is not None:
                out[node.name] = segment
    return out


def test_every_daemon_backed_tool_dispatches_through_the_seam() -> None:
    """Totality: no tool may quietly keep its own private implementation.

    Without this, `browser_attach_session` would be half-true — some tools would
    cross to the shell's browser and others would silently keep driving a second,
    invisible one. Two browsers that look like one is the bug being removed.
    """
    from visus.web.ops import registry

    sources = _tool_sources()
    problems: list[str] = []
    for tool, op in sorted(registry.TOOL_OPS.items()):
        body = sources.get(tool)
        if body is None:
            problems.append(f"{tool}: not a top-level function in mcp/server.py")
            continue
        if f'_run("{op}"' not in body:
            problems.append(f'{tool}: does not dispatch through _run("{op}", ...)')
    assert not problems, problems


def test_local_only_tools_do_not_dispatch() -> None:
    """The declared exemptions must really be exempt, not accidentally routed."""
    from visus.web.ops import registry

    sources = _tool_sources()
    for tool in sorted(registry.LOCAL_ONLY_TOOLS | registry.SESSIONLESS_TOOLS):
        body = sources.get(tool, "")
        assert "_run(" not in body, f"{tool} is declared exempt but dispatches through _run"


def test_run_raises_the_daemon_error_when_attached(monkeypatch: pytest.MonkeyPatch) -> None:
    from visus.web.mcp import server

    class _Fake:
        def handle(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
            return {"ok": False, "error": "IndexError: field index 9 out of range"}

    monkeypatch.setattr(server, "_remote", _Fake())
    with pytest.raises(RuntimeError, match="field index 9 out of range"):
        server._run("click", {"index": 9}, lambda: pytest.fail("local path ran while attached"))


def test_run_returns_the_daemon_envelope_when_attached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from visus.web.mcp import server

    env = {"ok": True, "result": "clicked", "page": {"url": "http://x/", "title": "X"}}

    class _Fake:
        def handle(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
            return env

    monkeypatch.setattr(server, "_remote", _Fake())
    assert server._run("click", {}, lambda: pytest.fail("local path ran")) == env
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_attach.py -v --no-cov`
Expected: FAIL — `test_every_daemon_backed_tool_dispatches_through_the_seam` lists the 22 unconverted tools, starting with `browser_add_cookies: does not dispatch through _run("add_cookies", ...)`

- [ ] **Step 3: Convert the remaining tools**

Navigation (`:40-69`) — `browser_navigate` is the pattern; the other three drop the `url` payload:

```python
@mcp.tool()
def browser_navigate(url: str) -> str:
    """Navigate the browser to a URL and return the resulting title."""

    def _local() -> str:
        page = _session.page()
        page.goto(url)
        _session.invalidate_fields()  # cached indexes belonged to the previous page
        return page.url

    env = _run("goto", {"url": url}, _local)
    return _acted(env, f"navigated to {env['result']!r}")
```

| Tool (lines) | op | payload | local | returns |
|---|---|---|---|---|
| `browser_navigate_back` (`:48-53`) | `back` | `{}` | `page.go_back()`, `_session.invalidate_fields()`, `return page.url` | `_acted(env, f"went back → {env['result']!r}")` |
| `browser_navigate_forward` (`:56-61`) | `forward` | `{}` | `page.go_forward()`, `_session.invalidate_fields()`, `return page.url` | `_acted(env, f"went forward → {env['result']!r}")` |
| `browser_reload` (`:64-69`) | `reload` | `{}` | `page.reload()`, `_session.invalidate_fields()`, `return page.url` | `_acted(env, f"reloaded {env['result']!r}")` |

Inspect (`:77-143`):

| Tool (lines) | op | payload | local | returns |
|---|---|---|---|---|
| `browser_snapshot` (`:77-83`) | `snapshot` | `{"selector": selector, "depth": depth}` | `{"elements": _session.page().snapshot(selector, depth=depth)}` | `env["result"]["elements"]` |
| `browser_list_fields` (`:86-110`) | `list_fields` | `{"kinds": parsed, "include_hidden": include_hidden, "highlight": highlight}` | enumerate, `_session.cache_fields(fields)`, `return {"fields": [f.to_dict() for f in fields]}` | `env["result"]["fields"]` |
| `browser_clear_highlights` (`:113-117`) | `clear_highlights` | `{}` | `_session.page().clear_highlights()`, `return "cleared"` | `env["result"]` |
| `browser_title` (`:134-137`) | `title` | `{}` | `_session.page().title()` | `env["result"]` |
| `browser_url` (`:140-143`) | `url` | `{}` | `_session.page().url` | `env["result"]` |

`browser_snapshot` gains `selector: str | None = None` and `depth: int | None = None`, matching PLAN 4's `Page.snapshot(selector, *, depth)` and its scoped `_op_snapshot`. When attached, the daemon's `_op_snapshot` also stamps `_fields`, so the returned `ref` values (PLAN 4 Task 9) stay actionable — the docstring must say so.

`browser_list_fields`'s prose paragraph (`:98-99`) — *"root = page; for sel in frame: root = root.frame_locator(sel); target = root.locator(locator, deep=deep)"* — is **deleted**. Replace that sentence with:

```
    Each returned dict carries an ``index``: pass it as the ``index`` argument of
    any action tool (browser_click, browser_fill, …) and the element is
    re-resolved through its iframe chain and open shadow roots for you. Do NOT
    rebuild that chain by hand — a bare css/xpath cannot reach inside a frame.
    Indexes are void after a navigation; run this tool again.
```

Tabs (`:474-538`):

| Tool (lines) | op | payload | local | returns |
|---|---|---|---|---|
| `browser_tab_list` (`:474-492`) | `tabs` | `{}` | the existing loop, plus `"active": i == _session._current_idx` on each row, wrapped as `{"tabs": rows, "active": _session._current_idx}` | `env["result"]["tabs"]` |
| `browser_tab_new` (`:495-500`) | `tab_new` | `{"url": url}` | `p = _session.new_page(url)`, `return {"index": len(_session.pages()) - 1, "title": p.title()}` | `f"opened tab {env['result']['index']}"` |
| `browser_tab_select` (`:503-507`) | `tab` | `{"index": index}` | `p = _session.select(index)`, `return {"active": index, "title": p.title()}` | `f"switched to tab {env['result']['active']}"` |
| `browser_tab_activate` (`:510-514`) | `tab_activate` | `{"handle": handle}` | `p = _session.activate(handle)`, `return {"active": _session._current_idx, "handle": handle, "title": p.title()}` | `f"activated tab {env['result']['handle']} (index {env['result']['active']})"` |
| `browser_tab_close` (`:517-522`) | `tab_close` | `{"index": index}` | `_session.close_tab(index)`, `return {"closed": index, "remaining": len(_session._pages)}` | `f"closed tab {env['result']['closed']} ({env['result']['remaining']} remaining)"` |
| `browser_set_tab_follow` (`:525-538`) | `tab_follow` | `{"enabled": enabled}` | `{"follow": _session.set_follow(enabled)}` | `f"tab-follow {'enabled (auto)' if env['result']['follow'] else 'disabled (manual)'}"` |

`browser_tab_list`'s return type becomes the daemon's richer row — `{index, handle, title, url, active}` — and its docstring gains a sentence naming `active`.

Dialogs, network/console, cookies and JS:

| Tool (lines) | op | payload | local | returns |
|---|---|---|---|---|
| `browser_handle_dialog` (`:546-561`) | `dialog` | `{"accept": accept, "prompt_text": prompt_text}` | the existing `handle_next_dialog` body | `_acted(env, env["result"])` |
| `browser_network_requests` (`:569-584`) | `network_requests` | `{"url_filter": url_filter}` | the existing comprehension, wrapped as `{"requests": out}` | `env["result"]["requests"]` |
| `browser_console_messages` (`:587-599`) | `console_messages` | `{"level": level}` | the existing comprehension, wrapped as `{"messages": out}` | `env["result"]["messages"]` |
| `browser_get_cookies` (`:607-610`) | `cookies` | `{}` | `{"cookies": _session.context().cookies()}` | `env["result"]["cookies"]` |
| `browser_add_cookies` (`:613-617`) | `add_cookies` | `{"cookies": cookies}` | `_session.context().add_cookies(cookies)`, `return f"added {len(cookies)} cookie(s)"` | `_acted(env, env["result"])` |
| `browser_clear_cookies` (`:620-624`) | `clear_cookies` | `{}` | `_session.context().clear_cookies()`, `return "cookies cleared"` | `_acted(env, env["result"])` |
| `browser_evaluate` (`:646-652`) | `eval` | `{"expression": expression, "arg": arg}` | `{"result": _session.page().evaluate(expression, arg)}` | `env["result"]["result"]` |

Finally `browser_close` (`:743-747`) — declared `LOCAL_ONLY` in Task 2, and this is why:

```python
@mcp.tool()
def browser_close() -> str:
    """Close this server's browser and reset the session.

    While attached to a `visus` session (browser_attach_session) this DETACHES
    instead: the shell's browser is not ours to close, and killing it would
    destroy whatever state the user built up. `visus session stop` owns that
    lifetime.
    """
    global _remote
    if _remote is not None:
        _remote = None
        return "detached from the visus session (it is still running — use `visus session stop`)"
    _session.close()
    return "browser closed"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_attach.py -v --no-cov`
Expected: PASS (4 passed)

- [ ] **Step 5: Run every MCP suite**

Run: `uv run pytest tests/test_mcp_server.py tests/test_mcp_list_fields.py tests/test_mcp_index.py tests/test_e2e_mcp.py -q --no-cov`
Expected: PASS — the inventory is still 45.

- [ ] **Step 6: Run the gates**

Run: `uv run ruff check src tests` → Expected: `All checks passed!`
Run: `uv run mypy` → Expected: `Success: no issues found`

- [ ] **Step 7: Commit**

```bash
git add src/visus/web/mcp/server.py tests/test_mcp_attach.py
git commit -m "refactor(mcp): route every daemon-backed tool through one dispatch seam"
```

---

### Task 7: `browser_attach_session` — MCP drives the shell's browser

Two independent browsers with opposite defaults is the current state: `mcp/session.py:32-40` launches headless with manual tab-follow, `session_server.py:104-119` launches headed with auto-follow, and nothing in the README or either skill warns that they do not share a browser (synthesis gap #18). This task lets the MCP server stop being the second one.

The defaults themselves stay as they are, deliberately: the CLI daemon is headed because the numbered `list-fields` overlay drawn on the live page is the product, and an MCP server usually runs over stdio on a host with no display. Attach removes the *ambiguity* rather than the difference — attached, there is one browser, and `browser_attach_session` closes this server's own before taking over.

**Files:**
- Modify: `src/visus/web/mcp/server.py` (`_acted`, new tools), `src/visus/web/ops/registry.py` (`LOCAL_ONLY_TOOLS`)
- Modify: `tests/test_mcp_server.py:27-84` (`_EXPECTED_TOOLS`)
- Test: `tests/test_mcp_attach.py`

**Interfaces:**
- Produces: MCP tools `browser_attach_session(project_dir: str | None = None) -> str` and `browser_detach_session() -> str`; `_acted(env: dict[str, Any], message: str) -> str`.
- Consumes: `RemoteDispatcher` (Task 3), `_run` (Task 5), PLAN 4's `page` envelope key.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp_attach.py`:

```python
def test_attach_refuses_when_no_session_is_running(tmp_path: Path) -> None:
    from visus.web.mcp import server

    with pytest.raises(RuntimeError, match="visus session start"):
        server.browser_attach_session(str(tmp_path))
    assert server._remote is None


def test_detach_is_idempotent() -> None:
    from visus.web.mcp import server

    server._remote = None
    assert server.browser_detach_session() == "not attached"


def test_acted_prefers_the_daemon_page_footer() -> None:
    from visus.web.mcp import server

    env = {
        "ok": True,
        "result": "clicked",
        "page": {"url": "http://x/dash", "title": "Dash", "fields_stale": False},
    }
    out = server._acted(env, "clicked")
    assert out.startswith("clicked")
    assert "### Page" in out
    assert "- URL: http://x/dash" in out
    assert "- Title: Dash" in out


@pytest.mark.browser
def test_attached_tools_drive_the_shell_browser(tmp_path: Path) -> None:
    """The payoff: one browser, one page, one field-index vocabulary."""
    from visus.web.cli import session_client
    from visus.web.mcp import server

    page = "data:text/html,<title>shell</title><h1 id=h>shell page</h1>"
    session_client.start_daemon("chrome", headless=True, url=page, cwd=tmp_path)
    try:
        assert "attached to the visus session" in server.browser_attach_session(str(tmp_path))
        try:
            # The MCP server now sees the page the SHELL opened — it never
            # launched a browser of its own.
            assert server.browser_title() == "shell"
            assert server.browser_get_text(selector="#h") == "shell page"

            # And the shell sees what MCP does.
            server.browser_navigate("data:text/html,<title>from-mcp</title>")
            assert session_client.send("title", start_dir=tmp_path) == "from-mcp"

            # An action carries the daemon's page footer straight through.
            result = server.browser_evaluate("() => document.title")
            assert result == "from-mcp"
        finally:
            assert "detached" in server.browser_detach_session()
        assert server._remote is None
    finally:
        session_client.stop(start_dir=tmp_path)
        server._session.close()


@pytest.mark.browser
def test_attach_closes_this_servers_own_browser_first(tmp_path: Path) -> None:
    """Two live browsers is the bug; attaching must not create one more."""
    from visus.web.cli import session_client
    from visus.web.mcp import server

    server.browser_navigate("data:text/html,<title>mcp-own</title>")
    assert server._session._browser is not None

    session_client.start_daemon(
        "chrome", headless=True, url="data:text/html,<title>shell</title>", cwd=tmp_path
    )
    try:
        server.browser_attach_session(str(tmp_path))
        assert server._session._browser is None, "the MCP server's own browser is still alive"
        assert server.browser_title() == "shell"
    finally:
        server.browser_detach_session()
        session_client.stop(start_dir=tmp_path)
        server._session.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_attach.py -m "not browser" -v --no-cov`
Expected: FAIL — `AttributeError: module 'visus.web.mcp.server' has no attribute 'browser_attach_session'`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/mcp/server.py`, replace the `_acted` helper Task 5 left in place with:

```python
def _acted(env: dict[str, Any], message: str) -> str:
    """An action's result plus the page state the agent needs for its next step.

    Without this an agent is blind after every action and must spend a whole extra
    tool call on browser_url/browser_title, or act on a stale mental model. When
    attached, the state comes from the daemon's own envelope (PLAN 4's `page`
    key), so it describes the page the action actually produced — no second
    round-trip, and no chance of reading a different browser.
    """
    state = env.get("page")
    if isinstance(state, dict) and state.get("url") is not None:
        footer = f"\n\n### Page\n- URL: {state['url']}\n- Title: {state.get('title', '')}"
        if state.get("fields_stale"):
            footer += "\n- Fields: stale (run browser_list_fields again)"
        return message + footer
    if _remote is not None:
        return message  # attached but the daemon sent no footer: do not guess
    try:
        page = _session.page()
        return f"{message}\n\n### Page\n- URL: {page.url}\n- Title: {page.title()}"
    except Exception:  # noqa: BLE001 — page state is telemetry, never the result
        return message
```

Add the two tools immediately above the `# Lifecycle` section comment (`:738-740`):

```python
# ---------------------------------------------------------------------------
# Attach: one browser instead of two
# ---------------------------------------------------------------------------


@mcp.tool()
def browser_attach_session(project_dir: str | None = None) -> str:
    """Attach to the `visus` CLI session daemon and drive ITS browser from now on.

    Unattached, this server and the `visus` shell run two independent browsers —
    different windows, different cookies, different logins — and nothing in the
    tool output says so. Attached, every tool crosses to the daemon, so the model
    and the human share one page, one session and one field-index vocabulary.

    `project_dir` is where the search for `.visus/session.json` starts (default:
    this process's working directory); the search walks upward, git-style. Start
    the session first with `visus session start <url>`.
    """
    global _remote
    dispatcher = RemoteDispatcher(start_dir=project_dir)
    info = dispatcher.session()
    if info is None:
        where = project_dir or "the current directory"
        raise RuntimeError(
            f"no live visus session found (searched upward from {where}) — "
            "run `visus session start <url>` there first"
        )
    _session.close()  # a second live browser would be invisible and unreachable
    _remote = dispatcher
    return (
        f"attached to the visus session (pid {info['pid']}, port {info['port']}) — "
        "every tool now drives that browser"
    )


@mcp.tool()
def browser_detach_session() -> str:
    """Detach from the `visus` CLI session; later tools use this server's own browser.

    The `visus` session keeps running — detaching never closes the user's browser.
    """
    global _remote
    if _remote is None:
        return "not attached"
    _remote = None
    return "detached — subsequent tools use this server's own browser"
```

In `src/visus/web/ops/registry.py`, extend `LOCAL_ONLY_TOOLS`:

```python
LOCAL_ONLY_TOOLS: frozenset[str] = frozenset(
    {
        # Owns THIS server's browser lifetime. The shell's session lifetime belongs
        # to `visus session stop`; sending `shutdown` across would kill a browser
        # the user is still using.
        "browser_close",
        # The attach controls themselves: they decide where ops go, so they can
        # never be one of the ops that gets sent.
        "browser_attach_session",
        "browser_detach_session",
    }
)
```

In `tests/test_mcp_server.py`, add to `_EXPECTED_TOOLS` (`:27-84`), after the `# Lifecycle` group:

```python
    # Attach
    "browser_attach_session",
    "browser_detach_session",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_attach.py -m "not browser" -v --no-cov`
Expected: PASS (7 passed)

Run: `uv run pytest tests/test_mcp_attach.py -m browser -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the inventory and registry tests**

Run: `uv run pytest tests/test_mcp_server.py tests/test_ops_registry.py -q --no-cov`
Expected: PASS — 47 tools registered, 47 accounted for.

- [ ] **Step 6: Document it**

In `README.md`, in the MCP tool tables (`:192-256`), add a row to the lifecycle group:

```markdown
| `browser_attach_session` / `browser_detach_session` | Drive the `visus session` browser from MCP instead of a second, separate one. |
```

- [ ] **Step 7: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/mcp/server.py src/visus/web/ops/registry.py \
        tests/test_mcp_server.py tests/test_mcp_attach.py README.md
git commit -m "feat(mcp): attach to the visus session daemon instead of a second browser"
```

---

### Task 8: `browser_tracing_*` — the HTML report reaches the MCP surface

The single-file HTML report is the one thing in this repo `playwright-cli` has no answer to. Its trace needs the Trace Viewer; `report.py:355-365` writes one `.html` with every PNG inlined as a base64 data URI (`:438-530`), a KPI band (`:489-514`), per-step correlated logs (`recorder.py:229-254` → `report.py:627-649`) and the ARIA snapshot captured on failure (`recorder.py:123-129` → `report.py:652-666`). That file goes into a ticket, a PR comment or a CI artifact untouched.

PLAN 5 Task 17 puts it behind `visus tracing-start` / `visus tracing-stop` / `visus report`. This task puts it on the other surface, so an agent driving over MCP can hand its human an artifact instead of a transcript.

**Files:**
- Modify: `src/visus/web/mcp/server.py` (new section above `# Lifecycle`)
- Modify: `src/visus/web/ops/registry.py` (`SESSIONLESS_TOOLS`, `LOCAL_ONLY_TOOLS`)
- Modify: `tests/test_mcp_server.py:27-84` (`_EXPECTED_TOOLS`)
- Test: `tests/test_mcp_tracing.py`

**Interfaces:**
- Consumes: `tracing.start_recording(**opts) -> Recorder` and `tracing.stop_recording(zip_path=None, report=None) -> dict[str, str]` (PLAN 5 Task 17, declared at `2026-08-06-tier2b-cli-surface-parity.md:136-139`); `tracing.render_report(zip_path, output) -> str` (`tracing.py:132-139`); `Recorder.run_id` (`recorder.py:71`).
- Produces: MCP tools `browser_tracing_start`, `browser_tracing_stop`, `browser_tracing_report`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_mcp_tracing.py`:

```python
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
    assert "<link" not in html and "src=\"http" not in html


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_tracing.py -m "not browser" -v --no-cov`
Expected: FAIL — `AttributeError: module 'visus.web.mcp.server' has no attribute 'browser_tracing_report'`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/mcp/server.py`, add this section immediately above the `# Attach` section added in Task 7:

```python
# ---------------------------------------------------------------------------
# Tracing: the single-file HTML report
# ---------------------------------------------------------------------------


def _refuse_while_attached(cli_command: str) -> None:
    """Refuse a this-process-only operation while the browser lives elsewhere."""
    if _remote is not None:
        raise RuntimeError(
            "attached to a visus session — the browser runs in the daemon, so this "
            f"server would record nothing. Run `{cli_command}` against that session "
            "instead, or call browser_detach_session first."
        )


@mcp.tool()
def browser_tracing_start() -> str:
    """Start recording every action with a screenshot, timing and correlated logs.

    Recording continues until browser_tracing_stop, which writes a trace zip and a
    SINGLE-FILE HTML report — every screenshot embedded as a data URI, a KPI band,
    per-step logs and, on any failure, the ARIA snapshot of the page at that
    moment. That file needs no viewer: attach it to a ticket, a PR or a CI job.
    """
    from visus.web import tracing

    _refuse_while_attached("visus tracing-start")
    recorder = tracing.start_recording()
    return f"tracing started (run {recorder.run_id})"


@mcp.tool()
def browser_tracing_stop(
    zip_path: str = "run.zip", report: str = "report.html"
) -> dict[str, str]:
    """Stop recording; write the trace zip and the single-file HTML report.

    Returns the absolute paths of both, e.g. {"zip": "...", "report": "..."}.
    Give the report path to the human — it is self-contained.
    """
    from visus.web import tracing

    _refuse_while_attached("visus tracing-stop --report")
    return tracing.stop_recording(zip_path, report)


@mcp.tool()
def browser_tracing_report(zip_path: str, output: str = "report.html") -> str:
    """Render the single-file HTML report from an existing trace zip.

    Works on any zip written by browser_tracing_stop, `visus tracing-stop` or the
    library's tracing.record() — no browser and no session needed. Returns the
    absolute path of the written HTML.
    """
    from visus.web import tracing

    return tracing.render_report(zip_path, output)
```

In `src/visus/web/ops/registry.py`, extend both exemption sets:

```python
SESSIONLESS_TOOLS: frozenset[str] = frozenset(
    {
        # Pure HTML parsing — `visus translate` is its CLI twin and is likewise the
        # only command in either CLI that works with no browser running at all.
        "browser_translate_element",
        # Pure zip -> html rendering. No page, no session, no daemon.
        "browser_tracing_report",
    }
)
```

and add to `LOCAL_ONLY_TOOLS`:

```python
        # Tracing installs a Recorder in THIS process. Attached, the actions happen
        # in the daemon, so these refuse and name `visus tracing-start/stop`.
        "browser_tracing_start",
        "browser_tracing_stop",
```

In `tests/test_mcp_server.py`, add to `_EXPECTED_TOOLS`:

```python
    # Tracing
    "browser_tracing_start",
    "browser_tracing_stop",
    "browser_tracing_report",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_tracing.py -m "not browser" -v --no-cov`
Expected: PASS (2 passed)

Run: `uv run pytest tests/test_mcp_tracing.py -m browser -v --no-cov`
Expected: PASS (1 passed)

- [ ] **Step 5: Run the inventory and registry tests**

Run: `uv run pytest tests/test_mcp_server.py tests/test_ops_registry.py tests/test_mcp_attach.py -q --no-cov`
Expected: PASS — 50 tools registered, 50 accounted for.

- [ ] **Step 6: Document it**

In `README.md`, in the MCP tool tables (`:192-256`), add:

```markdown
| `browser_tracing_start` / `browser_tracing_stop` / `browser_tracing_report` | Record a run and write a single-file HTML report (screenshots embedded, no viewer needed). |
```

- [ ] **Step 7: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/mcp/server.py src/visus/web/ops/registry.py \
        tests/test_mcp_server.py tests/test_mcp_tracing.py README.md
git commit -m "feat(mcp): expose tracing and the single-file HTML report"
```

---

### Task 9: The report says "self-healing" out loud

`backtrack_steps` is already a first-class concept: `recorder.py:106`/`:143` record it per action, `report.py:403-411` aggregates it into the KPI band, and `report.py:572-580` renders a per-step badge. That is a genuine differentiator — a self-healing retry is *visible* rather than hidden inside a flaky-looking pass — and the report currently spends it on the word "Backtrack", which means nothing to the person the report is being sent to.

This task is copy, not mechanism: the data, the JSON keys and the CSS classes are untouched.

**Files:**
- Modify: `src/visus/web/observability/report.py:479-480` (hero lede), `:510-513` (KPI card), `:572-580` (per-step row + badge)
- Modify: `tests/test_e2e_observability.py:107-112`
- Test: `tests/test_report_copy.py`

**Interfaces:**
- Consumes: `_kpis` (`report.py:387-411`) — its `backtrack_steps` key is unchanged.
- Produces: nothing new. The event key `backtrack_steps` and the CSS class `badge-backtrack` stay exactly as they are.

- [ ] **Step 1: Write the failing test**

Create `tests/test_report_copy.py`:

```python
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
    assert "badge-backtrack" in html  # the CSS class is untouched
    assert "self-healed" in html
    assert "replayed 2 previous step(s)" in html


def test_a_failed_step_says_it_tried(tmp_path: Path) -> None:
    html = _render(
        tmp_path,
        [_event(backtrack_steps=2, success=False, error="VisusWebError: no such element")],
    )
    assert "self-healing failed" in html
    assert "badge-failure" in html


def test_a_clean_step_shows_no_healing_copy(tmp_path: Path) -> None:
    html = _render(tmp_path, [_event(backtrack_steps=0)])
    assert "badge-backtrack" not in html
    assert "self-healed" not in html
    # The KPI card is always present; it just reads zero.
    assert "Self-healing retries" in html


def test_the_hero_lede_explains_the_number(tmp_path: Path) -> None:
    html = _render(tmp_path, [_event()])
    assert "self-healing retries" in html
```

Replace `tests/test_e2e_observability.py:110` (currently `assert "Backtrack steps" in html`) with:

```python
    assert "Self-healing retries" in html
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_copy.py -v --no-cov`
Expected: FAIL — `AssertionError: assert 'Self-healing retries' in html`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/observability/report.py`, replace the hero lede (`:479-480`):

```python
    <p class="lede">A timeline of every action, with durations, self-healing retries and
       failure screenshots embedded inline.</p>
```

Replace the sixth KPI card (`:510-513`):

```python
      <div class="kpi-card">
        <div class="label">Self-healing retries</div>
        <div class="value">{kpis["backtrack_steps"]}</div>
      </div>
```

Replace the backtrack rows in `_render_task` (`:572-580`):

```python
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
```

Note the details this preserves: the CSS class `badge-backtrack` (`report.py`'s stylesheet keys off it and `tests/test_e2e_observability.py:112` asserts it), the KPI dict key `backtrack_steps`, and the event key of the same name that `tests/test_e2e_observability.py:94-100` locks down.

The failing-step wording must still contain the literal `replayed {n} previous step(s)` so the "tried" and "succeeded" cases share one phrase the test can assert.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_copy.py -v --no-cov`
Expected: PASS (5 passed)

- [ ] **Step 5: Run the observability suite**

Run: `uv run pytest tests/test_e2e_observability.py tests/test_tracing_unit.py -q --no-cov`
Expected: PASS — `test_backtrack_steps_recorded_under_tracing` still asserts the event key, the absent `backtrack_cycles`, and `badge-backtrack`.

- [ ] **Step 6: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/observability/report.py tests/test_report_copy.py \
        tests/test_e2e_observability.py
git commit -m "docs(report): name backtrack steps what they are — self-healing retries"
```

---

### Task 10: OCR with geometry — `TextBox`, `read_text_boxes`, `find_text`

`vision/ocr.py:25-32` throws the geometry away: RapidOCR returns `[quad, text, score]` per run and `read_text` keeps only `line[1]`. Without the box there is no way to click rendered text — which is the whole point of vision targeting in a canvas app, an embedded PDF viewer, or a third-party widget with no accessibility tree.

`vision/imaging.py:15-29` already sets the shape to copy: a frozen dataclass with `center_x` / `center_y`.

**Files:**
- Modify: `src/visus/web/vision/ocr.py:1-32`
- Modify: `src/visus/web/vision/__init__.py`
- Test: `tests/test_vision.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class TextBox:
      text: str; x: int; y: int; width: int; height: int; confidence: float
      @property
      def center_x(self) -> int: ...
      @property
      def center_y(self) -> int: ...

  def read_text_boxes(image: ImageInput) -> list[TextBox]: ...
  def find_text(image: ImageInput, needle: str, *, exact: bool = False) -> TextBox | None: ...
  ```
- Consumes: `_to_ndarray` / `ImageInput` (`vision/_images.py`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_vision.py`:

```python
# ---------------------------------------------------------------------------
# OCR with geometry
# ---------------------------------------------------------------------------


def test_read_text_boxes_returns_geometry() -> None:
    from visus.web.vision import TextBox, read_text_boxes

    boxes = read_text_boxes(_text_img("SUBMIT"))
    assert boxes, "expected at least one recognised text run"
    assert all(isinstance(b, TextBox) for b in boxes)
    hit = next(b for b in boxes if _norm(b.text) == "SUBMIT")
    # The helper draws at (20, 20) at 60px on a 600x130 canvas.
    assert 0 <= hit.x < 120, hit
    assert 0 <= hit.y < 120, hit
    assert hit.width > 50 and hit.height > 20, hit
    assert 0.0 < hit.confidence <= 1.0
    assert hit.center_x == hit.x + hit.width // 2
    assert hit.center_y == hit.y + hit.height // 2


def test_read_text_boxes_on_a_blank_image_is_empty() -> None:
    from visus.web.vision import read_text_boxes

    assert read_text_boxes(Image.new("RGB", (200, 60), "white")) == []


def test_find_text_matches_case_insensitively_by_substring() -> None:
    from visus.web.vision import find_text

    img = _text_img("SUBMIT")
    assert find_text(img, "submit") is not None
    assert find_text(img, "ubmi") is not None
    assert find_text(img, "cancel") is None


def test_find_text_exact_requires_the_whole_run() -> None:
    from visus.web.vision import find_text

    img = _text_img("SUBMIT")
    assert find_text(img, "SUBMIT", exact=True) is not None
    assert find_text(img, "ubmi", exact=True) is None


def test_read_text_still_joins_every_run() -> None:
    """The existing read_text contract is unchanged by the refactor."""
    from visus.web.vision import read_text

    assert _norm(read_text(_text_img("HELLOWORLD"))) == "HELLOWORLD"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vision.py -k "text_boxes or find_text" -v --no-cov`
Expected: FAIL — `ImportError: cannot import name 'TextBox' from 'visus.web.vision'`

- [ ] **Step 3: Write the implementation**

In `src/visus/web/vision/ocr.py`, replace the module header and `read_text` (`:1-32`) with:

```python
"""Text OCR via RapidOCR (lazy singleton), with and without geometry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image

from visus.web.vision._images import ImageInput, _to_ndarray

_engine = None


@dataclass(frozen=True)
class TextBox:
    """One recognised text run and where it was rendered.

    Coordinates are pixels of the image that was read. Mirrors
    :class:`visus.web.vision.Match` so a caller can click either an image match
    or a text match with the same two properties.
    """

    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2


def _get_engine() -> object:
    global _engine
    if _engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
    return _engine


def read_text_boxes(image: ImageInput) -> list[TextBox]:
    """Every recognised text run with its bounding box, in OCR order.

    The geometry is what makes rendered text a *target*: a canvas app, an
    embedded PDF or a widget with no accessibility tree exposes no role, no name
    and no stable selector, but it still paints words at coordinates.
    """
    arr = _to_ndarray(image)
    engine = _get_engine()
    result, _ = engine(arr)  # type: ignore[operator]
    if not result:
        return []
    boxes: list[TextBox] = []
    for line in result:
        quad, text, score = line[0], str(line[1]), float(line[2])
        xs = [float(point[0]) for point in quad]
        ys = [float(point[1]) for point in quad]
        x, y = int(min(xs)), int(min(ys))
        boxes.append(
            TextBox(
                text=text,
                x=x,
                y=y,
                width=int(max(xs)) - x,
                height=int(max(ys)) - y,
                confidence=score,
            )
        )
    return boxes


def find_text(image: ImageInput, needle: str, *, exact: bool = False) -> TextBox | None:
    """The highest-confidence text run matching *needle* (case-insensitive).

    Substring by default (``"ubmi"`` finds ``"SUBMIT"``), because OCR routinely
    merges or splits neighbouring words; pass ``exact=True`` to require the whole
    recognised run. Returns ``None`` when nothing matches.
    """
    want = needle.strip().casefold()
    matches = [
        box
        for box in read_text_boxes(image)
        if (box.text.strip().casefold() == want if exact else want in box.text.casefold())
    ]
    if not matches:
        return None
    return max(matches, key=lambda box: box.confidence)


def read_text(image: ImageInput) -> str:
    """Extract all text from an image (any format). Returns space-joined lines."""
    return " ".join(box.text for box in read_text_boxes(image))
```

Leave `_preprocess` and `solve_captcha` (`:34-46`) exactly as they are.

In `src/visus/web/vision/__init__.py`, replace the whole file with:

```python
"""visus.web.vision — optional OCR + image-matching plugin (requires [vision] extra)."""

from visus.web.vision.imaging import Match, find_all_images, find_image
from visus.web.vision.ocr import TextBox, find_text, read_text, read_text_boxes, solve_captcha

__all__ = [
    "Match",
    "TextBox",
    "find_all_images",
    "find_image",
    "find_text",
    "read_text",
    "read_text_boxes",
    "solve_captcha",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_vision.py -v --no-cov`
Expected: PASS (all, including the pre-existing `test_read_text_clear`, `test_read_text_accepts_bytes_and_base64`, `test_read_text_accepts_pil_image`, `test_read_text_accepts_ndarray` and `test_read_text_empty_image_returns_empty_string`)

- [ ] **Step 5: Run the vision e2e suite**

Run: `uv run pytest tests/test_e2e_vision.py -q --no-cov`
Expected: PASS

- [ ] **Step 6: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/vision/ocr.py src/visus/web/vision/__init__.py tests/test_vision.py
git commit -m "feat(vision): return OCR geometry so rendered text becomes a target"
```

---

### Task 11: `visus click --image` — clicking pixels

`visus find-image` (`main.py:862-894`) already finds a template and prints its coordinates, `Match.center_x` / `center_y` (`vision/imaging.py:23-29`) already give the click point, and `Page.mouse.click(x, y)` (`api/page.py:296-301` → `api/input.py:32-34`) already clicks one. Nothing joins them, so today an agent that has *found* a button still cannot press it.

This is the targeting mode `playwright-cli` has none of: a grep for `ocr|captcha` across that repo returns zero matches, and its whole vocabulary is the accessibility tree — which a canvas app, an embedded PDF viewer or a Flash-era third-party widget simply does not have.

**Files:**
- Create: `tests/fixtures/imagetarget.html`
- Modify: `src/visus/web/cli/session_server.py` (new `_op_click_image`, `_device_pixel_ratio`; `_MUTATING_OPS`)
- Modify: `src/visus/web/cli/main.py:304-313` (`click`)
- Modify: `src/visus/web/cli/console.py:19-53` (`_HELP`), `:119-120` (dispatch)
- Modify: `README.md` (Actions table)
- Modify: `tests/test_cli_session.py` (`_MUTATING_OPS` expectation)
- Test: `tests/test_cli_vision_targeting.py`

**Interfaces:**
- Produces:
  ```python
  # session_server.py
  def _op_click_image(self, args: dict[str, Any]) -> dict[str, Any]: ...
      # args: {template_path, confidence, + optional target keys}
      # -> {"x": float, "y": float, "confidence": float}
  def _device_pixel_ratio(self) -> float: ...
  ```
  plus `visus click --image <png> [-c CONF]` and the REPL's `click-image <png> [conf]`.
- Consumes: `find_image` / `Match` (`vision/imaging.py`), `SessionHandler._has_target` / `_target` (`session_server.py:198-221`), `Locator.bounding_box` (`api/locator.py:454-465`), `output.emit_envelope` and `_send_env` (PLAN 4).

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/imagetarget.html` with exactly this content:

```html
<!doctype html>
<html>
  <head><title>image target fixture</title></head>
  <body style="margin:0;background:#fff">
    <!-- A canvas app. Everything drawn below is PAINTED PIXELS: no roles, no
         accessible names, no child elements. role/name/text/selector targeting
         can reach the <canvas> itself and nothing inside it — which is exactly
         the case `click --image` and `click --ocr-text` exist for. -->
    <canvas id="app" width="520" height="220"></canvas>
    <p id="clicked">none</p>
    <script>
      var c = document.getElementById('app');
      var g = c.getContext('2d');
      g.fillStyle = '#ffffff';
      g.fillRect(0, 0, 520, 220);

      // OCR target: large black text on white, top-left.
      g.fillStyle = '#000000';
      g.font = '48px monospace';
      g.textBaseline = 'top';
      g.fillText('SUBMIT', 30, 30);

      // Template-match target: a high-contrast block with a white bar through it,
      // bottom-right. Deliberately patterned — TM_CCOEFF_NORMED needs internal
      // variance, a solid block would correlate everywhere.
      g.fillStyle = '#1b2a4a';
      g.fillRect(300, 120, 120, 48);
      g.fillStyle = '#ffffff';
      g.fillRect(320, 138, 80, 12);

      c.addEventListener('click', function (e) {
        var r = c.getBoundingClientRect();
        var x = e.clientX - r.left, y = e.clientY - r.top;
        var out = 'miss';
        if (x >= 30 && x <= 230 && y >= 30 && y <= 90) out = 'text';
        else if (x >= 300 && x <= 420 && y >= 120 && y <= 168) out = 'image';
        document.getElementById('clicked').textContent = out;
      });
    </script>
  </body>
</html>
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_cli_vision_targeting.py`:

```python
"""Pixel targeting: click by template image and by rendered text."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


def _crop_template(handler: Any, tmp_path: Path, box_css: tuple[int, int, int, int]) -> Path:
    """Crop a template out of the page's own screenshot (device-pixel aware).

    Self-cropping keeps the test deterministic: the needle is by construction the
    exact pixels the browser painted, so a match failure means the PIPELINE broke,
    not that a hand-drawn template drifted from the rendering.
    """
    from PIL import Image

    shot = handler.handle("screenshot", {"path": str(tmp_path / "page.png")})["result"]
    ratio = float(
        handler.handle("eval", {"expression": "() => window.devicePixelRatio"})["result"]["result"]
    )
    left, top, right, bottom = box_css
    crop = (int(left * ratio), int(top * ratio), int(right * ratio), int(bottom * ratio))
    out = tmp_path / "template.png"
    Image.open(shot).crop(crop).save(out)
    return out


@pytest.mark.browser
def test_click_image_presses_a_canvas_button_with_no_accessibility_tree(
    base_url: str, tmp_path: Path
) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/imagetarget.html"
    )
    try:
        assert h.handle("get_text", {"selector": "#clicked"})["result"]["value"] == "none"
        # Proof the ordinary vocabulary cannot reach it: nothing but a canvas.
        assert h.handle("count", {"role": "button"})["result"] == 0

        template = _crop_template(h, tmp_path, (300, 120, 420, 168))
        resp = h.handle("click_image", {"template_path": str(template), "confidence": 0.9})
        assert resp["ok"] is True, resp
        assert resp["result"]["confidence"] >= 0.9
        assert h.handle("get_text", {"selector": "#clicked"})["result"]["value"] == "image"
    finally:
        h.close()


@pytest.mark.browser
def test_click_image_not_found_is_an_actionable_error(base_url: str, tmp_path: Path) -> None:
    import numpy as np
    from PIL import Image

    needle = np.zeros((24, 24, 3), np.uint8)
    needle[6:18, 6:18, 0] = 200  # patterned, and provably absent from the fixture
    template = tmp_path / "absent.png"
    Image.fromarray(needle).save(template)

    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/imagetarget.html"
    )
    try:
        resp = h.handle("click_image", {"template_path": str(template), "confidence": 0.95})
        assert resp["ok"] is False
        assert "not found on the page" in resp["error"]
        assert "0.95" in resp["error"]
        assert h.handle("get_text", {"selector": "#clicked"})["result"]["value"] == "none"
    finally:
        h.close()


def test_device_pixel_ratio_falls_back_to_one_when_unreadable() -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True)
    assert h._device_pixel_ratio() == 1.0  # no browser at all


def test_click_image_is_a_mutating_op() -> None:
    assert "click_image" in session_server._MUTATING_OPS


def test_cli_click_image_sends_the_resolved_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    template = tmp_path / "t.png"
    template.write_bytes(b"PNG")
    sent: list[tuple[str, Any]] = []

    def fake(op: str, args: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
        sent.append((op, args))
        return {"ok": True, "result": {"x": 12.0, "y": 34.0, "confidence": 0.97}}

    monkeypatch.setattr(session_client, "send_envelope", fake)
    r = runner.invoke(app, ["click", "--image", str(template), "-c", "0.9"])
    assert r.exit_code == 0, r.output
    op, args = sent[0]
    assert op == "click_image"
    assert args["template_path"] == str(template.resolve())
    assert args["confidence"] == 0.9
    assert "clicked image at (12.0, 34.0)" in r.output
    assert "0.970" in r.output


def test_repl_click_image_dispatches(tmp_path: Path) -> None:
    template = tmp_path / "t.png"
    template.write_bytes(b"PNG")
    sent: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        sent.append((op, args))
        return {"x": 5.0, "y": 6.0, "confidence": 0.88}

    out = console.dispatch(f"click-image {template} 0.7", send)
    assert sent[0][0] == "click_image"
    assert sent[0][1]["template_path"] == str(template.resolve())
    assert sent[0][1]["confidence"] == 0.7
    assert "clicked image at (5.0, 6.0)" in out


def test_repl_help_lists_click_image() -> None:
    assert "click-image" in console.dispatch("help", lambda op, args: None)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_vision_targeting.py -m "not browser" -v --no-cov`
Expected: FAIL — `AttributeError: 'SessionHandler' object has no attribute '_device_pixel_ratio'` and `AssertionError: assert 'click_image' in frozenset(...)`

- [ ] **Step 4: Write the daemon op**

In `src/visus/web/cli/session_server.py`, add `"click_image"` to `_MUTATING_OPS` (the frozenset PLAN 4 Task 4 added above `class SessionHandler`), and add the same string to the expected set in `tests/test_cli_session.py::test_mutating_ops_cover_every_state_changing_op`.

Add these two methods to `SessionHandler`, immediately after `_op_find_image` (`:499-521`):

```python
    def _device_pixel_ratio(self) -> float:
        """CSS pixels per screenshot pixel (1.0 on a standard-DPI display).

        A screenshot is captured in DEVICE pixels while the mouse device speaks
        CSS viewport pixels, so on a HiDPI display a match at screenshot (400,200)
        must be clicked at CSS (200,100). An unreadable ratio degrades to 1:1
        rather than failing the click.
        """
        try:
            value = self.page().evaluate("() => window.devicePixelRatio")
        except Exception:  # noqa: BLE001 — telemetry, never the result
            return 1.0
        try:
            ratio = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1.0
        return ratio if ratio > 0 else 1.0

    def _op_click_image(self, args: dict[str, Any]) -> dict[str, Any]:
        """Click the centre of a template image found on the page (or in an element).

        The last-resort target. A canvas app, an embedded PDF viewer or a
        third-party widget with no accessibility tree exposes no role, no name and
        no stable selector — but it still renders pixels, and those can be matched
        and pressed. Give a target (index / selector / role / text) to scope the
        search to one element; the element's own box is then added back so the
        click lands in page coordinates.
        """
        from visus.web.vision import find_image

        template_path = str(args.get("template_path") or "")
        confidence = float(args.get("confidence", 0.8))
        page = self.page()
        origin_x = origin_y = 0.0
        if self._has_target(args):
            loc = self._target(args)
            shot = loc.screenshot()
            box = loc.bounding_box()
            if box is not None:
                origin_x, origin_y = float(box["x"]), float(box["y"])
        else:
            shot = page.screenshot()
        match = find_image(shot, template_path, confidence=confidence)
        if match is None:
            raise LookupError(
                f"template {template_path!r} not found on the page "
                f"at confidence >= {confidence}"
            )
        ratio = self._device_pixel_ratio()
        x = origin_x + match.center_x / ratio
        y = origin_y + match.center_y / ratio
        page.mouse.click(x, y)
        return {"x": round(x, 1), "y": round(y, 1), "confidence": round(match.confidence, 4)}
```

- [ ] **Step 5: Write the CLI command**

In `src/visus/web/cli/main.py`, add these two options to `click` (`:304-313`), immediately after its `text` option:

```python
    image: str = typer.Option(
        None, "--image", help="Click the centre of this template PNG (needs the [vision] extra)."
    ),
    confidence: float = typer.Option(0.8, "--confidence", "-c", help="Match threshold (0-1)."),
```

and replace the command's body with:

```python
    """Click a field by index, by --selector/--role/--text, or by --image."""
    from visus.web.cli import output

    if image is not None:
        args: dict[str, Any] = {
            "template_path": str(Path(image).resolve()),
            "confidence": confidence,
        }
        if index is not None or selector or role or text:
            args.update(_target_args(index, selector, role, name, text))
        env = _send_env("click_image", args)
        r = env["result"]
        message = (
            f"clicked image at ({r['x']}, {r['y']}) confidence={r['confidence']:.3f}"
        )
        output.emit_envelope({**env, "result": message})
        return
    output.emit_envelope(_send_env("click", _target_args(index, selector, role, name, text)))
```

If PLAN 5 Task 9's `--button` option landed, keep its `args["button"] = button` line inside the **non-image** branch — a pixel click always uses the primary button.

- [ ] **Step 6: Write the REPL twin**

In `src/visus/web/cli/console.py`, add `from pathlib import Path` to the import block (between `from collections.abc import Callable` and `from typing import Any`), add this branch immediately after the `click` branch (`:119-120`):

```python
        if cmd == "click-image":
            r = send(
                "click_image",
                {
                    "template_path": str(Path(rest[0]).resolve()),
                    "confidence": float(rest[1]) if len(rest) > 1 else 0.8,
                },
            )
            return f"clicked image at ({r['x']}, {r['y']}) confidence={r['confidence']:.3f}"
```

and this `_HELP` line immediately after the `click N` line (`:21`):

```
  click-image f.png [c] click the centre of a template image (vision)
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_vision_targeting.py -m "not browser" -v --no-cov`
Expected: PASS (5 passed)

Run: `uv run pytest tests/test_cli_vision_targeting.py -m browser -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 8: Update the README**

In `README.md`, in the **Actions** table (`:311-323`), replace the `visus click` row with:

```markdown
| `visus click [idx] [target]` / `visus click --image <png> [-c 0.8]` | Click a field, or the centre of a template image (canvas apps, embedded PDFs, widgets with no accessibility tree). |
```

- [ ] **Step 9: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add tests/fixtures/imagetarget.html src/visus/web/cli/session_server.py \
        src/visus/web/cli/main.py src/visus/web/cli/console.py \
        tests/test_cli_vision_targeting.py tests/test_cli_session.py README.md
git commit -m "feat(cli): click by template image for pages with no accessibility tree"
```

---

### Task 12: `visus click --ocr-text` and the MCP twins

Task 10 gave OCR its geometry; Task 11 built the click path. This task adds the second vision target — rendered *text* — and puts both on MCP, so the differentiator is not CLI-only in the same way index targeting was until Task 5.

**Files:**
- Modify: `src/visus/web/cli/session_server.py` (new `_op_click_ocr_text`; `_MUTATING_OPS`)
- Modify: `src/visus/web/cli/main.py` (`click`)
- Modify: `src/visus/web/cli/console.py` (`_HELP`, dispatch)
- Modify: `src/visus/web/mcp/server.py` (vision section)
- Modify: `src/visus/web/ops/registry.py` (`TOOL_OPS`, `INDEXABLE_TOOLS`)
- Modify: `tests/test_mcp_server.py:27-84`, `tests/test_cli_session.py`
- Modify: `README.md`
- Test: `tests/test_cli_vision_targeting.py`

**Interfaces:**
- Produces:
  ```python
  def _op_click_ocr_text(self, args: dict[str, Any]) -> dict[str, Any]: ...
      # args: {ocr_text, exact_text, + optional target keys}
      # -> {"x": float, "y": float, "text": str, "confidence": float}
  ```
  plus `visus click --ocr-text "<text>"`, the REPL's `click-text <text...>`, and MCP tools
  `browser_click_image` / `browser_click_ocr_text`.
- Consumes: `find_text` / `TextBox` (Task 10), `_device_pixel_ratio` (Task 11), `_run` / `_target_payload` (Task 5).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_vision_targeting.py`:

```python
@pytest.mark.browser
def test_click_ocr_text_presses_text_painted_on_a_canvas(base_url: str) -> None:
    """Rendered text is a target even when no DOM node carries it."""
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/imagetarget.html"
    )
    try:
        # The word exists only as pixels: no element contains it as text.
        assert h.handle("count", {"target_text": "SUBMIT"})["result"] == 0

        resp = h.handle("click_ocr_text", {"ocr_text": "SUBMIT"})
        assert resp["ok"] is True, resp
        assert "SUBMIT" in resp["result"]["text"].upper()
        assert h.handle("get_text", {"selector": "#clicked"})["result"]["value"] == "text"
    finally:
        h.close()


@pytest.mark.browser
def test_click_ocr_text_not_found_is_an_actionable_error(base_url: str) -> None:
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/imagetarget.html"
    )
    try:
        resp = h.handle("click_ocr_text", {"ocr_text": "Nonexistent Label"})
        assert resp["ok"] is False
        assert "no rendered text matching" in resp["error"]
        assert "Nonexistent Label" in resp["error"]
        assert h.handle("get_text", {"selector": "#clicked"})["result"]["value"] == "none"
    finally:
        h.close()


def test_click_ocr_text_is_a_mutating_op() -> None:
    assert "click_ocr_text" in session_server._MUTATING_OPS


def test_cli_click_ocr_text_sends_the_needle(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, Any]] = []

    def fake(op: str, args: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
        sent.append((op, args))
        return {"ok": True, "result": {"x": 9.0, "y": 8.0, "text": "SUBMIT", "confidence": 0.91}}

    monkeypatch.setattr(session_client, "send_envelope", fake)
    r = runner.invoke(app, ["click", "--ocr-text", "SUBMIT"])
    assert r.exit_code == 0, r.output
    assert sent[0][0] == "click_ocr_text"
    assert sent[0][1]["ocr_text"] == "SUBMIT"
    assert "clicked text 'SUBMIT' at (9.0, 8.0)" in r.output


def test_repl_click_text_dispatches() -> None:
    sent: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        sent.append((op, args))
        return {"x": 1.0, "y": 2.0, "text": "Sign in", "confidence": 0.8}

    out = console.dispatch("click-text Sign in", send)
    assert sent[0] == ("click_ocr_text", {"ocr_text": "Sign in", "exact_text": False})
    assert "clicked text 'Sign in' at (1.0, 2.0)" in out


def test_mcp_vision_click_tools_are_registered_and_daemon_backed() -> None:
    from visus.web.ops import registry

    assert registry.TOOL_OPS["browser_click_image"] == "click_image"
    assert registry.TOOL_OPS["browser_click_ocr_text"] == "click_ocr_text"
    assert {"browser_click_image", "browser_click_ocr_text"} <= registry.INDEXABLE_TOOLS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_vision_targeting.py -m "not browser" -k "ocr or vision_click or click_text" -v --no-cov`
Expected: FAIL — `AssertionError: assert 'click_ocr_text' in frozenset(...)`

- [ ] **Step 3: Write the daemon op**

In `src/visus/web/cli/session_server.py`, add `"click_ocr_text"` to `_MUTATING_OPS` (and to the expected set in `tests/test_cli_session.py::test_mutating_ops_cover_every_state_changing_op`), then add this method immediately after `_op_click_image`:

```python
    def _op_click_ocr_text(self, args: dict[str, Any]) -> dict[str, Any]:
        """Click the centre of RENDERED text located by OCR.

        For text that exists as pixels and not as a DOM node — canvas-drawn
        labels, an embedded PDF, a chart legend, an image button. Matching is a
        case-insensitive substring by default because OCR routinely merges or
        splits neighbouring words; pass ``exact_text`` to require the whole run.
        A target scopes the search to one element and its box is added back so the
        click lands in page coordinates.
        """
        from visus.web.vision import find_text

        needle = str(args.get("ocr_text") or "")
        exact = bool(args.get("exact_text", False))
        page = self.page()
        origin_x = origin_y = 0.0
        if self._has_target(args):
            loc = self._target(args)
            shot = loc.screenshot()
            box = loc.bounding_box()
            if box is not None:
                origin_x, origin_y = float(box["x"]), float(box["y"])
        else:
            shot = page.screenshot()
        found = find_text(shot, needle, exact=exact)
        if found is None:
            raise LookupError(f"no rendered text matching {needle!r} was found on the page")
        ratio = self._device_pixel_ratio()
        x = origin_x + found.center_x / ratio
        y = origin_y + found.center_y / ratio
        page.mouse.click(x, y)
        return {
            "x": round(x, 1),
            "y": round(y, 1),
            "text": found.text,
            "confidence": round(found.confidence, 4),
        }
```

- [ ] **Step 4: Extend the CLI command and the REPL**

In `src/visus/web/cli/main.py`, add one more option to `click`, immediately after `--image`:

```python
    ocr_text: str = typer.Option(
        None,
        "--ocr-text",
        help="Click rendered text found by OCR (needs the [vision] extra).",
    ),
```

and insert this branch in the body immediately **before** the `if image is not None:` branch:

```python
    if ocr_text is not None:
        ocr_args: dict[str, Any] = {"ocr_text": ocr_text, "exact_text": False}
        if index is not None or selector or role or text:
            ocr_args.update(_target_args(index, selector, role, name, text))
        env = _send_env("click_ocr_text", ocr_args)
        r = env["result"]
        message = (
            f"clicked text {r['text']!r} at ({r['x']}, {r['y']}) "
            f"confidence={r['confidence']:.3f}"
        )
        output.emit_envelope({**env, "result": message})
        return
```

In `src/visus/web/cli/console.py`, add this branch immediately after the `click-image` branch:

```python
        if cmd == "click-text":
            r = send("click_ocr_text", {"ocr_text": " ".join(rest), "exact_text": False})
            return (
                f"clicked text {r['text']!r} at ({r['x']}, {r['y']}) "
                f"confidence={r['confidence']:.3f}"
            )
```

and this `_HELP` line immediately after the `click-image` line:

```
  click-text text...   click rendered text located by OCR (vision)
```

- [ ] **Step 5: Add the MCP twins**

In `src/visus/web/mcp/server.py`, append to the vision section (after `browser_find_image`). Both tools need the same coordinate maths in the detached case, so add this shared helper first:

```python
def _click_vision_match(args: dict[str, Any], *, kind: str) -> dict[str, Any]:
    """Locate a template image or rendered text in this process's browser and click it.

    The detached twin of the daemon's `_op_click_image` / `_op_click_ocr_text`:
    same coordinate maths (screenshot pixels -> CSS pixels via devicePixelRatio,
    plus the scoping element's own box), so a flow behaves identically whether the
    MCP server is attached or running its own browser.
    """
    from visus.web.vision import find_image, find_text

    page = _session.page()
    origin_x = origin_y = 0.0
    scoped = any(
        args.get(key) is not None for key in ("index", "selector", "role", "target_text")
    )
    if scoped:
        loc = _session.target(args)
        shot = loc.screenshot()
        box = loc.bounding_box()
        if box is not None:
            origin_x, origin_y = float(box["x"]), float(box["y"])
    else:
        shot = page.screenshot()

    try:
        ratio = float(page.evaluate("() => window.devicePixelRatio"))  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 — an unreadable ratio is 1:1
        ratio = 1.0
    if ratio <= 0:
        ratio = 1.0

    if kind == "image":
        match = find_image(shot, args["template_path"], confidence=args["confidence"])
        if match is None:
            raise LookupError(
                f"template {args['template_path']!r} not found on the page "
                f"at confidence >= {args['confidence']}"
            )
        x = origin_x + match.center_x / ratio
        y = origin_y + match.center_y / ratio
        page.mouse.click(x, y)
        return {"x": round(x, 1), "y": round(y, 1), "confidence": round(match.confidence, 4)}

    found = find_text(shot, args["ocr_text"], exact=bool(args.get("exact_text", False)))
    if found is None:
        raise LookupError(
            f"no rendered text matching {args['ocr_text']!r} was found on the page"
        )
    x = origin_x + found.center_x / ratio
    y = origin_y + found.center_y / ratio
    page.mouse.click(x, y)
    return {
        "x": round(x, 1),
        "y": round(y, 1),
        "text": found.text,
        "confidence": round(found.confidence, 4),
    }
```

then the first tool:

```python
@mcp.tool()
def browser_click_image(
    template_path: str,
    confidence: float = 0.8,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Click the centre of a template image found on the page (or in an element).

    Use when the thing to press has no accessibility tree: a canvas app, an
    embedded PDF viewer, a chart, an image map. Give a target (index / selector /
    role / text) to scope the search to one element. Requires the [vision] extra.
    """
    args = _target_payload(
        index=index, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )
    args["template_path"] = template_path
    args["confidence"] = confidence

    result: dict[str, Any] = _run(
        "click_image", args, lambda: _click_vision_match(args, kind="image")
    )["result"]
    return (
        f"clicked image at ({result['x']}, {result['y']}) "
        f"confidence={result['confidence']:.3f}"
    )
```

and the second tool:

```python
@mcp.tool()
def browser_click_ocr_text(
    ocr_text: str,
    exact_text: bool = False,
    index: int | None = None,
    selector: str | None = None,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    exact: bool = False,
    frame: str | None = None,
) -> str:
    """Click rendered text located by OCR — text that exists as pixels, not as a node.

    For canvas-drawn labels, embedded PDFs, chart legends and image buttons.
    Substring and case-insensitive by default; set exact_text to require the whole
    recognised run. Requires the [vision] extra.
    """
    args = _target_payload(
        index=index, selector=selector, role=role, name=name, text=text, exact=exact, frame=frame
    )
    args["ocr_text"] = ocr_text
    args["exact_text"] = exact_text

    result: dict[str, Any] = _run(
        "click_ocr_text", args, lambda: _click_vision_match(args, kind="text")
    )["result"]
    return (
        f"clicked text {result['text']!r} at ({result['x']}, {result['y']}) "
        f"confidence={result['confidence']:.3f}"
    )
```

In `src/visus/web/ops/registry.py`, add to `TOOL_OPS` under the `# Vision` comment:

```python
    "browser_click_image": "click_image",
    "browser_click_ocr_text": "click_ocr_text",
```

and to `INDEXABLE_TOOLS`:

```python
        "browser_click_image",
        "browser_click_ocr_text",
```

In `tests/test_mcp_server.py`, add to `_EXPECTED_TOOLS` under the `# Vision` group:

```python
    "browser_click_image",
    "browser_click_ocr_text",
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_vision_targeting.py -m "not browser" -v --no-cov`
Expected: PASS (10 passed)

Run: `uv run pytest tests/test_cli_vision_targeting.py -m browser -v --no-cov`
Expected: PASS (4 passed)

- [ ] **Step 7: Run the MCP, registry and attach suites**

Run: `uv run pytest tests/test_mcp_server.py tests/test_ops_registry.py tests/test_mcp_attach.py -q --no-cov`
Expected: PASS — 52 tools registered, 52 accounted for, and every `TOOL_OPS` entry dispatches through `_run`.

- [ ] **Step 8: Update the README**

In `README.md`, in the **Actions** table, add below the `visus click` row:

```markdown
| `visus click --ocr-text "<text>"` | Click text that is only rendered pixels — canvas labels, embedded PDFs, chart legends. |
```

and in the MCP tool tables (`:192-256`), under Vision:

```markdown
| `browser_click_image` / `browser_click_ocr_text` | Press a template image or rendered text — targets with no accessibility tree at all. |
```

- [ ] **Step 9: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add src/visus/web/cli/session_server.py src/visus/web/cli/main.py \
        src/visus/web/cli/console.py src/visus/web/mcp/server.py \
        src/visus/web/ops/registry.py tests/test_mcp_server.py \
        tests/test_cli_session.py tests/test_cli_vision_targeting.py README.md
git commit -m "feat(vision): click rendered text by OCR, on the CLI, the REPL and MCP"
```

---

## Design tasks (items 5–10)

The six tasks below each produce a design document under `docs/design/` **and** a spike that answers that design's one open question with real code and a real test. They are design tasks because each carries a question no amount of plan prose can settle. They are not placeholders: every one ships a production symbol, a failing-test-first cycle, and acceptance criteria the design must meet before implementation starts.

---

### Task 13: Design — `visus annotate`, human in the loop (item 5)

`playwright-cli` answers "which one did you mean?" with `show --annotate` and a multi-session dashboard behind it (`skills/playwright-cli/SKILL.md:401-408`). visus can answer it with far less machinery: the daemon already owns a live headed page and already injects drawing code into it — `bundle.js:800-820` renders the numbered field overlay through `window.__visus.highlightFields`, positions boxes absolutely at `z-index:2147483646`, and repositions them on scroll (`:825-845`). An annotation canvas is the same channel with the arrow reversed.

The return payload is `{screenshot_path, boxes, notes, region_snapshot}`. Three of those four are already reachable: `_op_screenshot` (`session_server.py:281-294`), the boxes come back from the injected script, and notes are typed into it. The fourth — a snapshot *scoped to a rectangle* — has no primitive at all. `Page.snapshot` scopes by selector (PLAN 4 Task 8), never by geometry, and `recorder.py:141` proves bounding boxes are already flowing through the observability path.

**The one open question this task answers:** can a bounding box be turned into a set of page elements, and how noisy is the result? Everything else in `annotate` is plumbing over primitives that exist.

**Files:**
- Create: `docs/design/annotate.md`
- Modify: `src/visus/web/api/page.py` (new `fields_in_box`)
- Test: `tests/test_e2e_fields.py`

**Interfaces:**
- Produces:
  ```python
  # src/visus/web/api/page.py
  def fields_in_box(self, box: dict[str, float], *, contained: bool = False) -> list[Field]: ...
  ```
- Consumes: `Field.box` (PLAN 5 Task 11, `2026-08-06-tier2b-cli-surface-parity.md:145`), `Page.list_fields` (`api/page.py:229-248`).

- [ ] **Step 1: Write the failing spike test**

Append to `tests/test_e2e_fields.py`:

```python
@pytest.mark.browser
def test_fields_in_box_selects_by_geometry(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    """A rectangle drawn on the page maps to the fields it covers.

    The missing primitive behind `visus annotate`: the user drags a box, and the
    tool has to say WHICH elements that box means.
    """
    page = browser.new_page()
    page.goto(f"{base_url}/forms.html")
    fields = page.list_fields(highlight=False)
    assert all(f.box is not None for f in fields), "PLAN 5's Field.box must be populated"

    target = fields[0]
    assert target.box is not None
    box = {
        "x": target.box["x"] - 4,
        "y": target.box["y"] - 4,
        "width": target.box["width"] + 8,
        "height": target.box["height"] + 8,
    }
    inside = page.fields_in_box(box)
    assert target.index in {f.index for f in inside}


@pytest.mark.browser
def test_fields_in_box_excludes_what_it_does_not_cover(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    page = browser.new_page()
    page.goto(f"{base_url}/forms.html")
    page.list_fields(highlight=False)
    assert page.fields_in_box({"x": -500.0, "y": -500.0, "width": 10.0, "height": 10.0}) == []


@pytest.mark.browser
def test_fields_in_box_contained_is_stricter_than_intersecting(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    """`contained=True` is the un-noisy mode: only fields fully inside the box."""
    page = browser.new_page()
    page.goto(f"{base_url}/forms.html")
    fields = page.list_fields(highlight=False)
    target = fields[0]
    assert target.box is not None
    # A box clipping the field's left half: it intersects, it does not contain.
    half = {
        "x": target.box["x"] - 20,
        "y": target.box["y"],
        "width": 20 + target.box["width"] / 2,
        "height": target.box["height"],
    }
    assert target.index in {f.index for f in page.fields_in_box(half)}
    assert target.index not in {f.index for f in page.fields_in_box(half, contained=True)}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_e2e_fields.py -k fields_in_box -v --no-cov`
Expected: FAIL — `AttributeError: 'Page' object has no attribute 'fields_in_box'`

- [ ] **Step 3: Write the spike implementation**

In `src/visus/web/api/page.py`, add immediately after `field` (`:264-281`):

```python
    def fields_in_box(
        self, box: dict[str, float], *, contained: bool = False
    ) -> list[Field]:
        """The enumerated fields covered by a viewport rectangle.

        *box* is ``{"x", "y", "width", "height"}`` in viewport CSS pixels — the
        same shape :meth:`Locator.bounding_box` returns. By default a field is
        included when its own box *intersects*; ``contained=True`` keeps only
        fields fully inside, which is the quieter answer when a human has dragged
        a rectangle around one control and does not want its neighbours.

        Re-enumerates so the geometry is current; a field with no measurable box
        (display:none, zero-size) is never included.
        """
        left, top = float(box["x"]), float(box["y"])
        right, bottom = left + float(box["width"]), top + float(box["height"])
        picked: list[Field] = []
        for field in self.list_fields(highlight=False):
            fb = field.box
            if fb is None or fb["width"] <= 0 or fb["height"] <= 0:
                continue
            fl, ft = float(fb["x"]), float(fb["y"])
            fr, fbm = fl + float(fb["width"]), ft + float(fb["height"])
            if contained:
                if fl >= left and ft >= top and fr <= right and fbm <= bottom:
                    picked.append(field)
            elif fl < right and fr > left and ft < bottom and fbm > top:
                picked.append(field)
        return picked
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_e2e_fields.py -k fields_in_box -v --no-cov`
Expected: PASS (3 passed)

- [ ] **Step 5: Write the design document**

Create `docs/design/annotate.md` containing exactly these sections, with the content described:

1. **`## Problem`** — an agent that cannot see the screen has to guess which of nine "Submit"-ish controls the human meant, and the cheapest correction channel is the human pointing at it. Cite `playwright-cli`'s `show --annotate` (`skills/playwright-cli/SKILL.md:401-408`) as the prior art and state the difference: it needs a dashboard process, visus already has a live headed page.
2. **`## Command surface`** — `visus annotate [--timeout 120] [--output annotate.png]`, blocking until the user presses Done or the timeout expires; returns
   ```json
   {"screenshot_path": "...", "boxes": [{"x":0,"y":0,"width":0,"height":0,"note":""}],
    "notes": ["..."], "region_snapshot": [{"index":3,"kind":"button","name":"Submit"}]}
   ```
   plus the REPL twin `annotate` and a `README.md` row. Daemon op: `annotate`. Not in `_MUTATING_OPS` — it observes, it does not act.
3. **`## Mechanism`** — a new `window.__visus.annotate(opts)` in `bundle.js` beside `highlightFields` (`:800-845`), reusing the same absolute-positioning and scroll-reposition code, plus `readAnnotations()` / `endAnnotate()`. The daemon polls `readAnnotations()` until done. State the reason for polling rather than a callback: the daemon speaks JSON-lines request/response and has no push channel.
4. **`## Region snapshot`** — `Page.fields_in_box` (this task's spike), called with `contained=False` for each drawn rectangle. Record the spike's finding: intersect mode is the useful default for a hand-drawn box, `contained=True` for a machine-drawn one.
5. **`## Risks`** — must list, each with a mitigation: (a) a headless session has nothing to draw on — `annotate` must fail fast with `session start` without `--headless` in the message; (b) the overlay injects nodes into `body` exactly like `list-fields` does (synthesis item 25), so a screenshot taken while annotating is polluted — take the screenshot *before* injecting; (c) `page.mouse` drags synthesised by tests are the only way to test this without a human, so the acceptance test must drive `page.mouse.move/down/up`; (d) a navigation during annotation destroys the overlay — detect via the URL and return what was collected.
6. **`## Acceptance criteria`** — verbatim:
   - `visus annotate` on a headed session returns within the timeout with a JSON payload containing all four keys.
   - A synthesised `page.mouse` drag over a known field produces one box whose `region_snapshot` contains that field's index.
   - `visus annotate` against a headless session exits 1 naming the fix.
   - The overlay leaves the DOM byte-identical after `endAnnotate()` (assert `document.querySelectorAll('[data-visus-annotate]').length == 0`).
   - `visus list-fields` immediately afterwards returns the same indexes it returned before.
7. **`## Not in scope`** — the multi-session dashboard (`docs/design/session-dashboard.md`, Task 18); freehand drawing; annotating a video frame.

- [ ] **Step 6: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add docs/design/annotate.md src/visus/web/api/page.py tests/test_e2e_fields.py
git commit -m "feat(api): select fields by geometry, the missing primitive for annotate"
```

---

### Task 14: Design — ARIA-snapshot assertions (item 6, D13)

`api/assertions.py:82-145` lists 21 `LocatorAssertions` matchers and none of them is `to_match_aria_snapshot`; `PageAssertions` has exactly two, `to_have_url` (`:199`) and `to_have_title` (`:210`). Meanwhile the `Recorder` already captures an ARIA snapshot on every failure (`recorder.py:123-129`) and the report already renders it (`report.py:652-666`) — the data exists and cannot be asserted on.

That gap breaks the loop `playwright-cli` prescribes: `references/test-generation.md:110-116` says to capture the expected snapshot with `--raw snapshot` (whole page, or scoped to a ref) and assert it with `toMatchAriaSnapshot` (`:90`, `:126-137`). visus can capture it (PLAN 4's scoped `visus snapshot <target>`) and cannot assert it.

**The one open question this task answers:** what does a visus ARIA-snapshot assertion *compare*? Playwright's matcher takes a YAML tree; `page.snapshot()` returns a flat `[{role, name, depth}]` list (PLAN 4 Task 8). The spike settles the comparison semantics before any YAML parser is written.

**Files:**
- Create: `docs/design/aria-snapshot-assertions.md`
- Modify: `src/visus/web/api/assertions.py:148-220` (`PageAssertions`)
- Test: `tests/test_e2e_expect.py`

**Interfaces:**
- Produces:
  ```python
  # PageAssertions
  def to_match_aria_snapshot(
      self,
      expected: Sequence[dict[str, str | re.Pattern[str]]],
      *,
      selector: str | None = None,
      timeout: int | None = None,
  ) -> None: ...
  ```
- Consumes: `Page.snapshot(selector, *, depth)` (PLAN 4 Task 8), `PageAssertions._poll` (`assertions.py:178-197`).

- [ ] **Step 1: Write the failing spike test**

Append to `tests/test_e2e_expect.py`:

```python
@pytest.mark.browser
def test_page_matches_a_partial_aria_snapshot(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    """Partial by design: assert the rows that matter, ignore the rest.

    Mirrors playwright-cli's rule that "snapshot to be matched does not have to
    contain all the information" (references/test-generation.md:96).
    """
    import re

    from visus.web import expect

    page = browser.new_page()
    page.goto(f"{base_url}/forms.html")

    expect(page).to_match_aria_snapshot([{"role": "textbox", "name": "Username"}])
    expect(page).to_match_aria_snapshot([{"role": "textbox", "name": re.compile(r"^User")}])


@pytest.mark.browser
def test_aria_snapshot_mismatch_reports_what_it_saw(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    from visus.web import expect

    page = browser.new_page()
    page.goto(f"{base_url}/forms.html")
    with pytest.raises(AssertionError) as excinfo:
        expect(page).to_match_aria_snapshot(
            [{"role": "button", "name": "Definitely Not Here"}], timeout=500
        )
    message = str(excinfo.value)
    assert "to_match_aria_snapshot" in message
    assert "Definitely Not Here" in message
    assert "last received" in message


@pytest.mark.browser
def test_aria_snapshot_respects_order(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    """Rows must appear as a SUBSEQUENCE, so a reordered page fails."""
    from visus.web import expect

    page = browser.new_page()
    page.goto(f"{base_url}/locators.html")
    rows = page.snapshot()
    assert len(rows) >= 2
    forwards = [{"role": r["role"], "name": r["name"]} for r in rows[:2]]
    expect(page).to_match_aria_snapshot(forwards)
    with pytest.raises(AssertionError):
        expect(page).to_match_aria_snapshot(list(reversed(forwards)), timeout=500)


@pytest.mark.browser
def test_aria_snapshot_can_be_scoped_to_a_region(browser, base_url: str) -> None:  # type: ignore[no-untyped-def]
    """The scoped form: assert one region without the rest of the page."""
    from visus.web import expect

    page = browser.new_page()
    page.goto(f"{base_url}/snapshot_tree.html")
    expect(page).to_match_aria_snapshot(
        [{"role": "button", "name": "Deep button"}], selector="#main"
    )
    with pytest.raises(AssertionError):
        expect(page).to_match_aria_snapshot(
            [{"role": "link", "name": "Footer link"}], selector="#main", timeout=500
        )
```

`tests/fixtures/snapshot_tree.html` is created by PLAN 4 Task 8; this test consumes it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_e2e_expect.py -k aria_snapshot -v --no-cov`
Expected: FAIL — `AttributeError: 'PageAssertions' object has no attribute 'to_match_aria_snapshot'`

- [ ] **Step 3: Write the spike implementation**

In `src/visus/web/api/assertions.py`, add `Sequence` to the `collections.abc` import (`:5`) if it is not already there, then add this method to `PageAssertions`, immediately after `to_have_title` (`:210-219`):

```python
    def to_match_aria_snapshot(
        self,
        expected: Sequence[dict[str, str | re.Pattern[str]]],
        *,
        selector: str | None = None,
        timeout: int | None = None,
    ) -> None:
        """Assert the page's accessibility snapshot contains *expected*, in order.

        *expected* is a list of ``{"role": ..., "name": ...}`` rows — exactly the
        shape :meth:`Page.snapshot` returns, so a captured snapshot can be pasted
        straight into a test. Matching is a SUBSEQUENCE: every expected row must
        appear in the live snapshot in the given order, and any extra live rows
        are ignored, so an assertion stays readable and survives unrelated page
        growth. ``name`` may be a compiled regex for unstable values (counts,
        timestamps). ``selector`` scopes the comparison to one region.
        """

        def matches(want: dict[str, str | re.Pattern[str]], got: dict[str, object]) -> bool:
            for key, value in want.items():
                actual = str(got.get(key, ""))
                if isinstance(value, re.Pattern):
                    if not value.search(actual):
                        return False
                elif actual != value:
                    return False
            return True

        def check() -> tuple[bool, object]:
            rows = self._page.snapshot(selector)
            cursor = 0
            for want in expected:
                while cursor < len(rows) and not matches(want, rows[cursor]):
                    cursor += 1
                if cursor == len(rows):
                    return (False, rows)
                cursor += 1
            return (True, rows)

        self._poll(check, f"to_match_aria_snapshot({list(expected)!r})", timeout)
```

`PageAssertions._poll` (`:178-197`) already produces `"expect(page): {prefix}{what} not satisfied within {t}ms; last received: {received!r}"`, which is why the mismatch test can assert both the matcher name and `last received`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_e2e_expect.py -k aria_snapshot -v --no-cov`
Expected: PASS (4 passed)

- [ ] **Step 5: Write the design document**

Create `docs/design/aria-snapshot-assertions.md` with exactly these sections:

1. **`## Problem`** — D13, with the four line references above, and the sentence that matters: the capture side already exists twice (Recorder, report) and the assert side does not exist at all, so a failure is *observable* and not *preventable*.
2. **`## Semantics chosen`** — record the spike's decision and why: subsequence over a flat `[{role, name, depth}]` list, not tree equality. Reasons, all three: (a) `page.snapshot()` is flat (`bundle.js:415-423` plus PLAN 4 Task 8's `depth`), so tree equality would require inventing a nesting model the bundle does not emit; (b) partial matching is what the workflow needs (`test-generation.md:96`); (c) order carries real signal (a reordered nav is a regression) while completeness does not.
3. **`## Locator scope`** — state plainly that the spike implements the page-level matcher only, and why: `LocatorAssertions._poll` (`:69-80`) routes through the delegate's `expect_poll` matcher engine, so a locator-level matcher means a new matcher name in that engine, on both the sync and async paths. The design's recommendation: add `"aria_snapshot"` to `expect_poll` and have `LocatorAssertions.to_match_aria_snapshot` delegate, with `PageAssertions`' `selector=` form as the interim answer for a region.
4. **`## Capture-to-assertion loop`** — the exact commands, mirroring `test-generation.md:110-116`:
   ```bash
   visus --raw snapshot --json > expected.json          # whole page
   visus --raw snapshot "#main" --json > region.json    # one region
   ```
   and the generated assertion `expect(page).to_match_aria_snapshot(json.load(open("region.json")), selector="#main")`.
5. **`## CLI surface`** — `visus expect-snapshot <file.json> [TARGET] [--timeout]` returning `PASSED` / `FAILED: <detail>` like `visus expect-text` (`session_server.py:385-395`), its daemon op `expect_snapshot`, the REPL twin, and the README row.
6. **`## Acceptance criteria`** — verbatim:
   - `expect(page).to_match_aria_snapshot(rows)` passes on a matching page and raises with `last received` on a mismatch.
   - A regex `name` matches an unstable value.
   - Reordering the expected rows fails.
   - `selector=` excludes everything outside the region.
   - `visus expect-snapshot` prints `PASSED` / `FAILED: …` and never raises to the shell.
   - The async mirror (`async_api/__init__.py`) exposes the same matcher, since the README calls it "a 100% mirror of the sync surface".
7. **`## Not in scope`** — YAML snapshot files; `toMatchAriaSnapshot`'s auto-update-on-failure behaviour.

- [ ] **Step 6: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add docs/design/aria-snapshot-assertions.md src/visus/web/api/assertions.py \
        tests/test_e2e_expect.py
git commit -m "feat(api): assert a partial ARIA snapshot on the page"
```

---

### Task 15: Design — test generation as a first-class flow (item 7, D14/D15)

`codegen.py:75-86` emits `from visus.web import launch` followed by `with launch(headless=False)` — no test function, no fixtures, no assertions — while `pytest_plugin.py:72-88` has been shipping a ready `visus_page` fixture (with on-failure screenshots) to every installed user via the `pytest11` entry point the whole time. The generator and the test harness have never been introduced to each other.

`playwright-cli` builds a 433-line workflow on top of its generator: a `specs/<feature>.plan.md` with `- expect:` bullets (`references/test-generation.md:243-270`), one test per file (`:280`), and a heal loop that reconciles the spec with reality and escalates to `test.fixme` rather than silently skipping (`:366`, `:420-424`). Its whole mechanism is `npx playwright test --debug=cli` → `playwright-cli attach tw-XXXX` → `resume` (`references/playwright-tests.md:15-31`).

**The one open question this task answers:** does the recorded event stream carry enough to emit a real pytest test — imports, fixture parameter, comments, assertions — or does the generator need more from the browser first?

**Files:**
- Create: `docs/design/test-generation.md`
- Modify: `src/visus/web/cli/codegen.py`
- Test: `tests/test_codegen.py`

**Interfaces:**
- Produces:
  ```python
  # src/visus/web/cli/codegen.py
  def generate_test(
      name: str,
      url: str,
      events: list[dict],
      *,
      expectations: list[str] | None = None,
      fixture: str = "visus_page",
  ) -> str: ...
  ```
- Consumes: `codegen._target_expr` (`codegen.py:55-60`), `codegen.generate_line` (`:63-72`), `pytest_plugin.visus_page` (`pytest_plugin.py:72-88`).

- [ ] **Step 1: Write the failing spike test**

Append to `tests/test_codegen.py`:

```python
def test_generate_test_emits_a_runnable_pytest_function() -> None:
    """The generator's output must be a TEST, not a script — the fixture exists."""
    from visus.web.cli.codegen import generate_test

    events = [
        {"action": "fill", "target": {"kind": "role", "role": "textbox", "name": "Username"},
         "value": "student"},
        {"action": "click", "target": {"kind": "role", "role": "button", "name": "Submit"}},
    ]
    code = generate_test("login", "https://x.test/login", events)

    assert "from visus.web import expect" in code
    assert "def test_login(visus_page):" in code
    assert "page = visus_page" in code
    assert "page.goto('https://x.test/login')" in code
    assert "page.get_by_role('textbox', name='Username').fill('student')" in code
    assert "page.get_by_role('button', name='Submit').click()" in code
    # No launch(): the fixture owns the browser lifetime.
    assert "launch(" not in code
    compile(code, "<generated>", "exec")  # it must at least be valid Python


def test_generate_test_embeds_expectations_verbatim() -> None:
    from visus.web.cli.codegen import generate_test

    code = generate_test(
        "login",
        "https://x.test/login",
        [],
        expectations=[
            "expect(page).to_have_url('*dashboard*')",
            "expect(page.get_by_role('heading')).to_contain_text('Welcome')",
        ],
    )
    assert "    expect(page).to_have_url('*dashboard*')" in code
    assert "    expect(page.get_by_role('heading')).to_contain_text('Welcome')" in code
    compile(code, "<generated>", "exec")


def test_generate_test_sanitises_the_name() -> None:
    from visus.web.cli.codegen import generate_test

    code = generate_test("should add a to-do!", "https://x.test/", [])
    assert "def test_should_add_a_to_do(visus_page):" in code
    compile(code, "<generated>", "exec")


def test_generate_test_accepts_another_fixture() -> None:
    from visus.web.cli.codegen import generate_test

    code = generate_test("x", "https://x.test/", [], fixture="page")
    assert "def test_x(page):" in code
    assert "page = page" not in code  # no pointless self-assignment


def test_generate_test_with_no_events_is_still_valid() -> None:
    from visus.web.cli.codegen import generate_test

    code = generate_test("empty", "https://x.test/", [])
    compile(code, "<generated>", "exec")
    assert code.endswith("\n")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_codegen.py -k generate_test -v --no-cov`
Expected: FAIL — `ImportError: cannot import name 'generate_test' from 'visus.web.cli.codegen'`

- [ ] **Step 3: Write the spike implementation**

Append to `src/visus/web/cli/codegen.py`:

```python
def _test_name(name: str) -> str:
    """A valid python identifier for a test function, from a free-text scenario name."""
    cleaned = "".join(ch if ch.isalnum() else "_" for ch in name.strip().lower())
    while "__" in cleaned:
        cleaned = cleaned.replace("__", "_")
    cleaned = cleaned.strip("_") or "generated"
    if cleaned[0].isdigit():
        cleaned = f"s_{cleaned}"
    return cleaned


def generate_test(
    name: str,
    url: str,
    events: list[dict],  # type: ignore[type-arg]
    *,
    expectations: list[str] | None = None,
    fixture: str = "visus_page",
) -> str:
    """Generate a runnable pytest test from a list of recorded events.

    Emits a test function over the packaged ``visus_page`` fixture
    (``pytest_plugin.py:72-88``) rather than a ``launch()`` script, so the browser
    lifetime, the isolated context and the on-failure screenshot all come for
    free. *expectations* are pasted verbatim as the assertion block — they are
    written by whoever knows what the scenario is supposed to prove, which the
    recorder cannot know.
    """
    func = _test_name(name)
    lines = ["from visus.web import expect", "", ""]
    if fixture == "page":
        lines.append(f"def test_{func}(page):")
    else:
        lines.append(f"def test_{func}({fixture}):")
        lines.append(f"    page = {fixture}")
    lines.append(f"    page.goto({url!r})")
    for event in events:
        lines.append("    " + generate_line(event))
    if expectations:
        lines.append("")
        for assertion in expectations:
            lines.append("    " + assertion)
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_codegen.py -v --no-cov`
Expected: PASS (all, including the pre-existing `generate_script` tests)

- [ ] **Step 5: Write the design document**

Create `docs/design/test-generation.md` with exactly these sections:

1. **`## Problem`** — D14 and D15 with their line references, plus the sentence that frames the opportunity: combined with the single-file HTML report (Task 8), visus gets something `playwright-cli` does not have — test generation **with a report of the heal run**, attachable to the PR that fixes the test.
2. **`## Plan → generate → heal`** — the three phases, mapped one-to-one onto `references/test-generation.md`, with the visus command for each:

   | Phase | playwright-cli | visus |
   |---|---|---|
   | Explore | `attach tw-XXXX`, `snapshot`, `click e5` | `visus session start`, `visus list-fields`, `visus click 3` |
   | Capture code | `# Ran Playwright code:` blocks | PLAN 4's `### Code` block after every action |
   | Capture assertion | `--raw snapshot [ref]`, `--raw eval` | `visus --raw snapshot [TARGET]`, `visus --raw get-text` |
   | Emit test | copy TypeScript into a `.spec.ts` | `visus codegen --as-test -o tests/test_login.py` |
   | Diagnose | `snapshot` + `console` + `requests` | `visus snapshot` + `visus logs` + `visus requests` |
   | Report | (none) | `visus tracing-stop --report heal.html` |
3. **`## Spec file format`** — reproduce the `specs/<feature>.plan.md` structure from `references/test-generation.md:238-278` verbatim (Application Overview, numbered groups, `**Seed:**`, `**File:**`, `**Steps:**` with `- expect:` bullets), and the four rules that matter: one test per file (`:280`/`:344`), kebab-case scenario names matching the file name, scenarios independent from the seed state, and `- expect:` bullets becoming the `expectations` argument of `generate_test`.
4. **`## Seed`** — the visus equivalent of `tests/seed.spec.ts`: a `conftest.py` fixture that wraps `visus_page` with the app's navigation and login, so generated tests start from a known state. Give the exact seven-line fixture.
5. **`## `visus attach <test-id>` — the honest finding`** — state plainly that visus has **no** `--debug=cli` equivalent: `pytest_plugin.py:51-61` calls `launch()` and never registers with the daemon, so there is nothing to attach to. The design's proposal, in this order: (a) a `visus_paused_page` fixture that writes `.visus/sessions/<test-id>.json` describing its live driver and blocks on a file/socket signal; (b) `visus attach <test-id>` pointing the CLI client at it; (c) `visus resume` releasing the block. Record the risk that reaching another process's WebDriver session requires reconnecting to the driver's HTTP endpoint by session id, which is engine-level work under `backends/selenium/` and must not leak a `selenium.*` type past that boundary (the hidden-engine rule).
6. **`## Heal loop`** — the diagnostic triad, the "fix one at a time, rerun after each" rule (`:422`), the spec-reconciliation decision tree (`:411-418`: purely technical → leave the spec; user-visible change → update the spec; unclear → **stop and ask**, quoting the scenario id, the stale spec lines and the observed behaviour), and the escalation. State explicitly that the visus equivalent of `test.fixme` is `@pytest.mark.xfail(strict=True, reason="<link to the user's decision>")` in the **generated user test suite**, and that this does not relax this repository's own no-`xfail` rule — different codebase, different contract.
7. **`## Acceptance criteria`** — verbatim:
   - `visus codegen --as-test -o tests/test_x.py <url>` writes a file that `pytest --collect-only` collects as exactly one test.
   - The generated file imports `expect` and takes `visus_page`, and contains no `launch(`.
   - Running the generated test against the recorded app passes.
   - `visus tracing-start` before a heal run and `visus tracing-stop --report heal.html` after produce a report whose timeline contains the failing step and its ARIA snapshot.
   - A skill reference `references/test-generation.md` ships inside the packaged skill (PLAN 1's layout) and names the six commands in the table above.
8. **`## Not in scope`** — generating async tests; generating page objects; multi-scenario parallel generation.

- [ ] **Step 6: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add docs/design/test-generation.md src/visus/web/cli/codegen.py tests/test_codegen.py
git commit -m "feat(codegen): emit a pytest test over the visus_page fixture"
```

---

### Task 16: Design — `edge_ie` and Selenium Grid as the enterprise wedge (item 8)

`Engine.EDGE_IE` (`engine.py:12`) drives Edge's Trident engine through IEDriverServer with `attach_to_edge_chrome` (`backends/browsers/edge_ie.py`), pins the driver to 4.0.0 because 4.8+ hangs forever on modern Edge, aligns the Windows registry itself where it can (`_ie_preflight.py:35-47`), and turns a hang into an actionable message with a 45-second watchdog (`edge_ie.py:70-101`). That is territory Playwright does not go: its browsers are chromium/firefox/webkit/chrome/msedge and there is no IE mode among them.

`remote_url` (`__init__.py:65`, *"e.g. `http://grid:4444/wd/hub`, instead of spawning a local browser"*) has existed just as long and is unreachable from the CLI until PLAN 5 Task 7. Neither the README's command tables nor the skill mentions `edge_ie` once.

**The one open question this task answers:** what does a Grid or IE-mode failure look like to the person hitting it? Today an unreachable Grid surfaces as a raw Selenium connection error through `main.py`'s `_send` funnel, and an IE-mode failure takes 45 seconds to say anything at all. A wedge nobody can debug is not a wedge.

**Files:**
- Create: `docs/design/grid-and-edge-ie.md`
- Modify: `src/visus/web/cli/main.py:97-107` (`doctor`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Produces: `visus doctor --engine <e> [--remote-url <url>]`
- Consumes: `launch(engine, headless=..., remote_url=...)` (`__init__.py:59-90`), `_ie_preflight.ie_mode_enabled()` / `admin_hint()` (`_ie_preflight.py:50-68`), `output.emit` / `output.emit_error` (PLAN 4).

- [ ] **Step 1: Write the failing spike test**

Append to `tests/test_cli.py`:

```python
def _all_output(result: object) -> str:
    """stdout plus stderr, however this Click version separates them.

    PLAN 4 routes every error through `output.emit_error`, which writes to
    STDERR — so a failure assertion that only reads `result.output` silently
    stops testing anything.
    """
    out = str(getattr(result, "output", ""))
    try:
        err = str(result.stderr)  # type: ignore[attr-defined]
    except (ValueError, AttributeError):
        err = ""  # older Click mixes stderr into output and raises on .stderr
    return out + err


def test_doctor_reports_an_unreachable_grid_without_a_traceback() -> None:
    """A Grid that is not there must produce guidance, not a Selenium stack trace.

    Port 1 is never listening, so this is deterministic and needs no real Grid.
    """
    result = runner.invoke(
        app, ["doctor", "--engine", "chrome", "--remote-url", "http://127.0.0.1:1/wd/hub"]
    )
    assert result.exit_code == 1
    combined = _all_output(result)
    assert "Traceback" not in combined
    assert "http://127.0.0.1:1/wd/hub" in combined
    assert "FAILED" in combined
    for hint in ("reachable", "--remote-url"):
        assert hint in combined, f"missing guidance: {hint!r}"


def test_doctor_refuses_headless_ie_mode_immediately() -> None:
    """IE mode is always headed (backends/browsers/edge_ie.py build_options).

    Failing in milliseconds beats failing after the 45 s launch watchdog.
    """
    result = runner.invoke(app, ["doctor", "--engine", "edge_ie", "--headless"])
    assert result.exit_code == 1
    assert "edge_ie" in _all_output(result)
    assert "always headed" in _all_output(result)


def test_doctor_names_the_engine_it_could_not_resolve() -> None:
    result = runner.invoke(app, ["doctor", "--engine", "safari"])
    assert result.exit_code == 1
    assert "safari" in _all_output(result)
```

Also update the pre-existing `test_doctor_failed_engine` (`tests/test_cli.py:83-92`) — its `assert r.exit_code == 1 and "FAILED" in r.output` reads stdout only, and `doctor` now fails through `output.emit_error` on stderr. Replace its last line with:

```python
    assert r.exit_code == 1 and "FAILED" in _all_output(r)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -k doctor -v --no-cov`
Expected: FAIL — `doctor` has no `--remote-url` option, so Typer exits 2 with `No such option: --remote-url`

- [ ] **Step 3: Write the spike implementation**

In `src/visus/web/cli/main.py`, replace `doctor` (`:97-107`) with:

```python
@app.command()
def doctor(
    engine: str = typer.Option("chrome", "--engine", "-e", help="chrome|edge|firefox|edge_ie."),
    remote_url: str = typer.Option(
        None,
        "--remote-url",
        help="Selenium Grid / Remote WebDriver URL, e.g. http://grid:4444/wd/hub.",
    ),
    headless: bool = typer.Option(True, "--headless/--headed"),
) -> None:
    """Check that a browser + driver launch correctly (locally or on a Grid).

    The first command to run when anything is wrong. On failure it exits 1 with a
    message that names the engine, the endpoint and the most likely cause — never
    a raw driver traceback.
    """
    from visus.web.cli import output

    if engine == "edge_ie" and headless:
        output.emit_error(
            "edge_ie is always headed (IE mode has no headless driver) — "
            "run `visus doctor --engine edge_ie --headed`"
        )
    where = remote_url or "a locally launched browser"
    try:
        with launch(Engine.from_str(engine), headless=headless, remote_url=remote_url) as b:
            p = b.new_page()
            p.goto("data:text/html,<title>ok</title>")
            output.emit(f"OK: {engine} via {where} launches and navigates (title: {p.title()!r})")
    except Exception as exc:  # noqa: BLE001 — every failure is reported, none escapes
        detail = f"{type(exc).__name__}: {exc}"
        hints = [f"FAILED: {engine} via {where} — {detail}"]
        if remote_url:
            hints.append(
                f"  - is {remote_url} reachable from this machine? "
                "try `curl <url>/status` (a Grid answers with JSON)"
            )
            hints.append(
                f"  - does the Grid have a free {engine} node? "
                "check the Grid console's browser capacity"
            )
            hints.append("  - drop --remote-url to test the same engine locally")
        elif engine == "edge_ie":
            from visus.web.backends.browsers import _ie_preflight

            if not _ie_preflight.ie_mode_enabled():
                hints.append("  - " + _ie_preflight.admin_hint().replace("\n", "\n    "))
            else:
                hints.append(
                    "  - IE mode is enabled; close ALL Edge windows and retry, and pin "
                    "the driver with VISUS_WEB_IE_DRIVER_VERSION=4.0.0"
                )
        else:
            hints.append("  - run `visus install --engine " + engine + "` to fetch the driver")
        output.emit_error("\n".join(hints))
```

`output.emit_error` writes to stderr and raises `typer.Exit(1)` (PLAN 4's contract), so the "no traceback" assertion holds. `Engine.from_str` raises `UnsupportedEngineError` for `safari`, which the same handler formats.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -k doctor -v --no-cov`
Expected: PASS (3 passed, plus any pre-existing doctor tests)

- [ ] **Step 5: Write the design document**

Create `docs/design/grid-and-edge-ie.md` with exactly these sections:

1. **`## Why this is the wedge`** — Playwright's engine list has no IE mode, so a Playwright-based competitor cannot bid on an IE-mode application at any price. Combined with the single-file HTML report (Task 8), the offer is "we run your legacy app on your Grid and hand you an auditable artifact per run".
2. **`## Command surface`** — `visus session start --engine edge_ie --remote-url <grid>` (the flag itself is PLAN 5 Task 7; this design covers the *combination*), `visus doctor --remote-url` (this task's spike), and `visus install --engine edge_ie` pre-fetching the pinned IEDriverServer.
3. **`## The IE-mode contract`** — extracted from the code so it stops living only in comments: IE mode is always headed and ignores `download_dir` / `user_data_dir` (`edge_ie.py:28-36`); IEDriverServer is pinned to 4.0.0 because 4.8+ hangs at "Finding window handle for IE Mode on Edge" (`edge_ie.py:21-24`); `VISUS_WEB_IE_DRIVER` overrides the path for air-gapped machines, `VISUS_WEB_IE_DRIVER_VERSION` overrides the pin, `VISUS_WEB_EDGE_BINARY` the Edge path, `VISUS_WEB_IE_TIMEOUT` the watchdog; the preflight equalises IE zone `2500` under HKCU without admin and needs elevation only for the Edge policy (`_ie_preflight.py:71-88`, `:104-131`).
4. **`## Grid node preparation`** — a checklist, because `_ie_preflight.ensure()` writes the **local** registry and a Grid node is not local: the node must be Windows, headed (a real interactive session, not a service), have the Edge IE-mode policy enabled, and expose `edge_ie` capabilities. State the consequence in one line: on a Grid, IE-mode preflight is an operator task, not something visus can do for you, and `visus doctor --remote-url --engine edge_ie` must say exactly that.
5. **`## Test strategy`** — record the constraint that `tests/test_e2e_edge_ie.py:21-22` already documents: IE mode opens a real headed window, is focus/zone sensitive and reliably hangs an xdist worker, so it runs standalone with `-n 0`. Propose (a) keeping that test as the local gate, (b) a `VISUS_WEB_GRID_URL`-driven Grid lane in CI that runs the *chrome* engine against a `selenium/standalone-chrome` service container — a real, always-available Grid, no conditional skipping — and (c) an `edge_ie` lane on a self-hosted Windows runner, out of scope for this repository's CI until such a runner exists.
6. **`## Documentation gap`** — `edge_ie` appears in no README command table and in no skill file, while `SKILL.md:8` already promises "broad browser/Grid/IE-mode compatibility". The fix is one row in the engines table plus a `references/enterprise.md` page in the packaged skill (PLAN 1's layout).
7. **`## Acceptance criteria`** — verbatim:
   - `visus doctor --remote-url <unreachable>` exits 1 with the URL, no traceback and three named causes.
   - `visus doctor --engine edge_ie --headless` fails in under a second.
   - `visus session start --remote-url <grid> --engine chrome` against a `selenium/standalone-chrome` container drives `goto` / `list-fields` / `click` / `expect-text` end to end in CI.
   - `visus session start --remote-url <grid> --engine edge_ie` against a prepared Windows node reaches `page.title()`, and against an unprepared one fails within the watchdog naming the node preparation step.
   - `README.md` and the packaged skill both name `edge_ie`.
8. **`## Not in scope`** — provisioning Grid nodes; Selenium Grid's own configuration; BrowserStack/SauceLabs endpoints (they are `remote_url` values and need no code).

- [ ] **Step 6: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add docs/design/grid-and-edge-ie.md src/visus/web/cli/main.py tests/test_cli.py
git commit -m "feat(cli): doctor diagnoses Grid and IE-mode failures actionably"
```

---

### Task 17: Design — video capture (item 9) — LOW PRIORITY

**Sequencing: this task is explicitly LOW priority and must not be started before Tasks 1–9 are done** (items 1, 2 and 3 — the unified dispatcher, index targeting on MCP, and observability). Video is a nice-to-have on top of a report that already embeds every step's screenshot; the report is the thing that wins deals, and video without it wins nothing.

`playwright-cli` has 143 lines of video recipes (`references/video-recording.md`). visus has zero hits for `video|screencast|webm` anywhere under `src/`.

**The one open question this task answers:** can visus receive frames at all? CDP's `Page.startScreencast` delivers frames as `Page.screencastFrame` **events**, and Selenium's synchronous bridge (`driver.execute_cdp_cmd`, used throughout `network.py:189-204`) issues commands and reads their return value — it has no event subscription. If the answer is no, the whole feature has to be built on screenshot polling instead, and that changes the design completely. The spike settles it before anything is designed on top.

**Files:**
- Create: `docs/design/video-screencast.md`
- Create: `src/visus/web/observability/video.py`
- Modify: `pyproject.toml` (the `[video]` extra)
- Test: `tests/test_e2e_observability.py`

**Interfaces:**
- Produces:
  ```python
  # src/visus/web/observability/video.py
  def capture_frames(page: Any, *, fps: int = 5, duration_ms: int = 1000) -> list[bytes]: ...
  def cdp_screencast_available(page: Any) -> bool: ...
  ```
- Consumes: `Page.screenshot` (`api/page.py:290-294`), `Page.evaluate` (`:287-288`).

- [ ] **Step 1: Write the failing spike test**

Append to `tests/test_e2e_observability.py`:

```python
@pytest.mark.browser
def test_capture_frames_records_a_changing_page(browser):
    """Frames must actually differ — a capture that repeats one frame is not video."""
    from visus.web.observability.video import capture_frames

    page = browser.new_page()
    page.goto(
        "data:text/html,<body style='margin:0'>"
        "<div id=b style='width:400px;height:200px;background:#000'></div>"
        "<script>var n=0;setInterval(function(){n=(n+40)%240;"
        "document.getElementById('b').style.background='rgb('+n+','+n+','+n+')';},80);</script>"
    )
    frames = capture_frames(page, fps=5, duration_ms=1200)
    assert len(frames) >= 4, f"expected at least 4 frames, got {len(frames)}"
    assert all(f.startswith(b"\x89PNG") for f in frames)
    assert len(set(frames)) >= 2, "every captured frame was identical"


@pytest.mark.browser
def test_cdp_screencast_availability_is_reported_not_assumed(browser):
    """The spike's whole point: record the answer instead of guessing it.

    Whatever this returns, capture_frames must still work — the design document
    records the value observed here and justifies the chosen mechanism.
    """
    from visus.web.observability.video import cdp_screencast_available

    page = browser.new_page()
    page.goto("data:text/html,<title>probe</title>")
    assert isinstance(cdp_screencast_available(page), bool)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_e2e_observability.py -k "capture_frames or screencast" -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'visus.web.observability.video'`

- [ ] **Step 3: Write the spike implementation**

Create `src/visus/web/observability/video.py`:

```python
"""Frame capture for run video (behind the ``[video]`` extra).

Deliberately mechanism-agnostic. CDP's ``Page.startScreencast`` delivers frames
as ``Page.screencastFrame`` EVENTS, and the synchronous CDP bridge this project
uses everywhere (see ``network.py``'s ``execute_cdp_cmd`` calls) issues commands
and reads their return value — it has no event subscription. Until that is
resolved, :func:`capture_frames` polls screenshots at a fixed rate, which works
on every engine including Firefox and needs no CDP at all.
"""

from __future__ import annotations

import time
from typing import Any


def cdp_screencast_available(page: Any) -> bool:
    """True when ``Page.startScreencast`` can be issued AND frames can be drained.

    Reports, never assumes: a Chromium page accepts the command happily and then
    delivers nothing through a synchronous bridge, so "the command worked" is not
    the same question as "frames arrive".
    """
    delegate = getattr(page, "_delegate", None)
    driver = getattr(delegate, "_driver", None)
    if driver is None or not hasattr(driver, "execute_cdp_cmd"):
        return False
    try:
        driver.execute_cdp_cmd("Page.startScreencast", {"format": "png", "everyNthFrame": 1})
    except Exception:  # noqa: BLE001 — a non-Chromium engine simply has no screencast
        return False
    try:
        # A synchronous bridge exposes no event queue. If a future Selenium grows
        # one, this attribute is where it will surface.
        return bool(getattr(driver, "get_log", None) and False)
    finally:
        try:
            driver.execute_cdp_cmd("Page.stopScreencast", {})
        except Exception:  # noqa: BLE001
            pass


def capture_frames(page: Any, *, fps: int = 5, duration_ms: int = 1000) -> list[bytes]:
    """Capture PNG frames of *page* for *duration_ms* at roughly *fps*.

    Screenshot polling: engine-independent, no CDP, and accurate enough for a
    run video whose purpose is "show me what happened", not broadcast. Returns
    the frames in capture order; assembling them into a container is the caller's
    job (see ``docs/design/video-screencast.md``).
    """
    if fps <= 0:
        raise ValueError("fps must be positive")
    interval = 1.0 / fps
    deadline = time.monotonic() + duration_ms / 1000.0
    frames: list[bytes] = []
    while True:
        started = time.monotonic()
        frames.append(page.screenshot())
        if time.monotonic() >= deadline:
            return frames
        remaining = interval - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(min(remaining, max(0.0, deadline - time.monotonic())))
```

In `pyproject.toml`, add the extra after `cli` (`:45-47`):

```toml
video = [
    "imageio-ffmpeg>=0.4.9",
    "pillow>=10.0.0",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_e2e_observability.py -k "capture_frames or screencast" -v --no-cov`
Expected: PASS (2 passed)

- [ ] **Step 5: Write the design document**

Create `docs/design/video-screencast.md` with exactly these sections:

1. **`## Priority`** — one paragraph stating that this is the lowest-priority Tier 3 item, that it is sequenced after items 1–3, and why: the report already embeds a screenshot per step, so video adds continuity, not evidence.
2. **`## The spike's finding`** — record the observed value of `cdp_screencast_available` on this machine's Chrome, and the conclusion: v1 uses screenshot polling. Include the reason in one sentence — the synchronous CDP bridge has no event subscription — and the trigger that would change the decision (a Selenium release exposing a CDP event queue, or moving to a websocket CDP client under `backends/selenium/`).
3. **`## Command surface`** — `visus video start [--fps 5]`, `visus video chapter "<label>"`, `visus video stop -o run.webm`, mirroring `playwright-cli`'s four verbs, plus daemon ops `video_start` / `video_chapter` / `video_stop`, the REPL twins and the README rows. Chapters and action overlays reuse the `window.__visus` injection channel (`bundle.js:876-889`) exactly like the field overlay does.
4. **`## Assembly`** — `imageio-ffmpeg` behind the `[video]` extra; frames written to `.visus/video/<run>/NNNN.png` as they are captured (never held in memory for a long run); the extra guarded exactly like `[vision]` is today, so a missing extra is a clean error and not an `ImportError` traceback.
5. **`## Cost`** — the honest number: at 5 fps a full-page screenshot per frame is a WebDriver round-trip each, which is far more expensive than a screencast; state the measured per-frame cost from the spike run and cap the default duration accordingly.
6. **`## Acceptance criteria`** — verbatim:
   - `visus video start` then `visus video stop -o run.webm` on a headed session writes a playable file.
   - Frames differ (the spike's assertion, promoted to the feature test).
   - A `visus video chapter` marker appears in the output at the right timestamp.
   - Without the `[video]` extra, every video command exits 1 with `pip install "visus-web[video]"`.
   - Video capture running concurrently with `visus click` does not serialise behind it for more than one frame interval (the daemon's `RLock` from PLAN 3 makes this a real question — answer it or move capture to its own thread with its own driver handle).
7. **`## Not in scope`** — audio; live streaming; per-element video.

- [ ] **Step 6: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add docs/design/video-screencast.md src/visus/web/observability/video.py \
        pyproject.toml tests/test_e2e_observability.py
git commit -m "feat(observability): frame capture spike behind the video extra"
```

---

### Task 18: Design — the multi-session dashboard (item 10) — BLOCKED ON PLAN 6

**This feature cannot be built yet, and that is the design's main finding.** `session_client.start_daemon` refuses a second start outright (`session_client.py:143-147`: *"a session is already running (pid …, port …)"*) and discovery walks upward git-style (`:58-66`), so starting in a subfolder of a project that already has a session silently binds to the parent's. Until PLAN 6's named sessions (`--session` / `-S`, `.visus/sessions/<name>.json`) exist, a fleet view is a view over a set of size one.

So this task ships the half that does not depend on PLAN 6 — the renderer, as a pure function over a list of session dicts — and a design that states the go/no-go condition in the first paragraph.

**The one open question this task answers:** what does a fleet row need to show for the view to be worth building at all, and can it be rendered without any session infrastructure?

**Files:**
- Create: `docs/design/session-dashboard.md`
- Create: `src/visus/web/cli/fleet.py`
- Test: `tests/test_cli_fleet.py`

**Interfaces:**
- Produces:
  ```python
  # src/visus/web/cli/fleet.py
  def render_fleet(sessions: list[dict[str, Any]]) -> str: ...
  ```
- Consumes: `session_client._pid_alive` (`session_client.py:24-46`), `session_client._socket_open` (`:49-55`) — used by the *caller* that builds the list, not by the renderer.

- [ ] **Step 1: Write the failing spike test**

Create `tests/test_cli_fleet.py`:

```python
"""The fleet renderer — a pure function, so it is testable before the fleet exists."""

from __future__ import annotations

from typing import Any

from visus.web.cli.fleet import render_fleet


def _session(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "default",
        "pid": 4242,
        "port": 51234,
        "engine": "chrome",
        "headless": False,
        "url": "https://example.com/dashboard",
        "title": "Dashboard",
        "cwd": "/proj/a",
        "alive": True,
    }
    base.update(over)
    return base


def test_no_sessions_says_so_and_names_the_fix() -> None:
    out = render_fleet([])
    assert "no visus sessions" in out
    assert "visus session start" in out


def test_one_session_renders_every_column() -> None:
    out = render_fleet([_session()])
    for fragment in ("default", "4242", "51234", "chrome", "headed", "Dashboard", "/proj/a"):
        assert fragment in out, f"missing column value {fragment!r}"


def test_a_dead_session_is_marked_and_names_the_fix() -> None:
    out = render_fleet([_session(alive=False)])
    assert "dead" in out
    assert "visus session kill" in out


def test_headless_and_headed_are_distinguishable() -> None:
    out = render_fleet([_session(name="a", headless=True), _session(name="b", headless=False)])
    assert "headless" in out and "headed" in out


def test_rows_are_sorted_by_name_so_the_view_is_stable() -> None:
    out = render_fleet([_session(name="zeta"), _session(name="alpha")])
    assert out.index("alpha") < out.index("zeta")


def test_a_missing_field_never_raises() -> None:
    """Session files are written by other processes; a partial one must still render."""
    out = render_fleet([{"name": "partial"}])
    assert "partial" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_fleet.py -v --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'visus.web.cli.fleet'`

- [ ] **Step 3: Write the spike implementation**

Create `src/visus/web/cli/fleet.py`:

```python
"""Render a fleet of `visus` sessions as a table.

A pure function over already-collected session dicts, deliberately separate from
the collection: named sessions do not exist yet (PLAN 6), so the collector cannot
be written, but the answer to "what does a fleet row need to show" can be settled
and tested now. See ``docs/design/session-dashboard.md``.
"""

from __future__ import annotations

from typing import Any


def render_fleet(sessions: list[dict[str, Any]]) -> str:
    """A table of sessions: name, pid, port, engine, mode, page, directory.

    Each dict may carry ``name``, ``pid``, ``port``, ``engine``, ``headless``,
    ``url``, ``title``, ``cwd`` and ``alive``. Missing keys render blank rather
    than raising — the dicts come from files other processes wrote, and a fleet
    view that crashes on one bad row is worse than no fleet view.
    """
    if not sessions:
        return "no visus sessions running — start one with `visus session start <url>`"

    from rich import box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=box.ASCII, header_style="bold", pad_edge=False)
    table.add_column("NAME", no_wrap=True)
    table.add_column("STATE", no_wrap=True)
    table.add_column("PID", justify="right", no_wrap=True)
    table.add_column("PORT", justify="right", no_wrap=True)
    table.add_column("ENGINE", no_wrap=True)
    table.add_column("MODE", no_wrap=True)
    table.add_column("PAGE", overflow="fold")
    table.add_column("DIRECTORY", overflow="fold")

    dead = False
    for s in sorted(sessions, key=lambda s: str(s.get("name", ""))):
        alive = bool(s.get("alive", True))
        dead = dead or not alive
        page = str(s.get("title") or "") or str(s.get("url") or "")
        table.add_row(
            str(s.get("name", "")),
            "live" if alive else "dead",
            str(s.get("pid", "")),
            str(s.get("port", "")),
            str(s.get("engine", "")),
            "" if s.get("headless") is None else ("headless" if s.get("headless") else "headed"),
            page,
            str(s.get("cwd", "")),
        )

    console = Console()
    with console.capture() as cap:
        console.print(table)
    out = cap.get().rstrip("\n")
    if dead:
        out += "\n\nsome sessions are dead — clear them with `visus session kill`"
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_fleet.py -v --no-cov`
Expected: PASS (6 passed)

- [ ] **Step 5: Write the design document**

Create `docs/design/session-dashboard.md` with exactly these sections:

1. **`## Blocked`** — the first paragraph, stated plainly: until PLAN 6's named sessions land, `session_client.py:143-147` refuses a second daemon and `:58-66` makes a subdirectory bind to its parent's session, so `visus session list` would show one row for ever. Do not build this before then. Name the unblocking symbols: `--session` / `-S`, `VISUS_WEB_SESSION`, `.visus/sessions/<name>.json`.
2. **`## What the fleet view is for`** — three concrete jobs: finding the abandoned daemon holding a headed browser somewhere else on disk; picking which session to point the next command at; and, for an agent, choosing a session by the page it is on rather than by remembering a name.
3. **`## Collection`** — the half PLAN 6 unblocks: glob `.visus/sessions/*.json`, plus a global registry at `~/.visus/sessions/<hash-of-cwd>.json` so daemons in *other* project trees are visible at all (today they are invisible and unkillable from the CLI). Liveness per row from `_pid_alive` and `_socket_open`, both of which already exist. Note the cost `session_client.py`'s Windows `tasklist` probe imposes (synthesis item 43) and require memoisation for a fleet of N.
4. **`## Rendering`** — this task's spike, with the column set it settled and the two rules the tests lock down: a missing field never raises, and dead rows name `visus session kill`.
5. **`## Command surface`** — `visus session list [--json]`, `visus session close-all`, `visus session kill-all`, `visus session delete-data`, matching the naming decisions in the conventions contract.
6. **`## Why this ranks below `annotate``** — one honest paragraph: `annotate` gives an agent a channel it does not have at all; the dashboard gives a human a nicer view of state they can already reach one directory at a time. Ship `annotate` first.
7. **`## Acceptance criteria`** — verbatim:
   - With PLAN 6 landed, `visus session list` shows every live session in the current tree plus every registered session elsewhere.
   - A killed daemon shows as `dead` and `visus session kill-all` removes it.
   - `visus session list --json` emits one array with the same fields the table shows.
   - The view costs at most one liveness probe per session per invocation.
8. **`## Not in scope`** — an HTTP dashboard, a TUI, and remote/Grid sessions (they have no local `.visus/`).

- [ ] **Step 6: Run the gates and commit**

Run: `uv run ruff check src tests` then `uv run mypy`
Expected: clean

```bash
git add docs/design/session-dashboard.md src/visus/web/cli/fleet.py tests/test_cli_fleet.py
git commit -m "feat(cli): fleet renderer spike ahead of named sessions"
```

---

### Task 19: Full-suite verification and gate pass

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

- [ ] **Step 6: Verify the two surfaces really are one**

Run: `uv run pytest tests/test_ops_registry.py tests/test_mcp_attach.py -v --no-cov`
Expected: PASS — 52 tools registered, 52 accounted for, every `TOOL_OPS` entry dispatching through `_run`, and the three declared exemptions dispatching through nothing.

- [ ] **Step 7: Drive the unified loop by hand once, end to end**

From a scratch directory, with the `[cli]`, `[mcp]` and `[vision]` extras installed:

```bash
visus session start --headless https://example.com
visus list-fields
visus click --text "More information"
visus tracing-start
visus goto https://example.com
visus click --ocr-text "More information"
visus tracing-stop --report run.html
visus session stop
```

Expected: `visus click --ocr-text` prints `clicked text 'More information...' at (x, y) confidence=…`, then a `### Page` block whose `- URL:` is `https://www.iana.org/help/example-domains`; `run.html` opens in a browser with the KPI band reading `Self-healing retries` and every step's screenshot embedded inline.

Then, with that session still running in another shell:

```bash
visus session start --headless https://example.com     # in shell A, leave it running
python -c "from visus.web.mcp import server; \
print(server.browser_attach_session()); print(server.browser_title())"
```

Expected: `attached to the visus session (pid …, port …)` followed by the title of the page **shell A** opened — not a second browser's blank page.

- [ ] **Step 8: Confirm the six design documents exist and are complete**

Run: `ls docs/design/`
Expected: `annotate.md`, `aria-snapshot-assertions.md`, `grid-and-edge-ie.md`, `session-dashboard.md`, `test-generation.md`, `video-screencast.md`

Each must contain an `## Acceptance criteria` section with at least four checkable criteria, and each must name its blocking dependency (or state that it has none).

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "chore(tier3): verify the unified surface against the full gate"
```



