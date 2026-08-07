# Remediation plans — index and execution order

Seven implementation plans closing the gaps a deep comparative analysis found between
the `visus` CLI and [microsoft/playwright-cli](https://github.com/microsoft/playwright-cli).

**113 tasks, 33,288 lines.** Every task is TDD (failing test → run → minimal
implementation → run → commit) with real code, real tests, and `file:line` evidence
verified against the source.

---

## The plans

| # | Plan | Tasks | Lines | Closes |
|---|---|---:|---:|---|
| 1 | [`tier1-skill-distribution`](2026-08-06-tier1-skill-distribution.md) | 13 | 3,223 | A1–A7, E3, rows 15–17, 19–23, 31, 36–39, 42 |
| 2 | [`tier1-ci-and-release`](2026-08-06-tier1-ci-and-release.md) | 9 | 2,328 | E1, E2, E4, E5, rows 32, 34, 35, 40, **+ Task 0: dependency pinning** |
| 3 | [`tier2a-daemon-correctness`](2026-08-06-tier2a-daemon-correctness.md) | 18 | 3,099 | B1–B9, rows 29, 30, 41, 43 |
| 4 | [`tier2c-agent-driving-loop`](2026-08-06-tier2c-agent-driving-loop.md) | 18 | 4,348 | C1–C7, rows 25, 33 |
| 5 | [`tier2b-cli-surface-parity`](2026-08-06-tier2b-cli-surface-parity.md) | 22 | 8,424 | D2, D3, D5–D7, D10, D11, rows 1–5, 8, 10, 13, 26–28 |
| 6 | [`tier2d-new-engineering`](2026-08-06-tier2d-new-engineering.md) | 15 | 6,799 | D1, D4, D8, D9, rows 6, 7, 9, 14 |
| 7 | [`tier3-differentiation`](2026-08-06-tier3-differentiation.md) | 19 | 5,067 | D12–D15, plus the nine differentiation items |

Issue IDs (`A1`, `B3`, `D8`, `row 26`, …) refer to the gap analysis. That analysis is
**not in this repo** — each plan restates the evidence it depends on inline, so no
task requires it.

---

## Dependency graph

```
PLAN 1  skill-distribution   ──┬──────────────────────────► PLAN 2  ci-and-release
                               │                            (Tasks 3 and 5 only;
                               │                             1,2,4,6,7,8 independent)
                               ├──┐
PLAN 3  daemon-correctness   ──┼──┴──► PLAN 4  agent-driving-loop
                               │              │
                               │              ├──► PLAN 5  cli-surface-parity
                               │              │           │
                               ├──────────────┴───────────┴──► PLAN 6  new-engineering
                               │                                       ╎
                               └──────────────────────────────────► PLAN 7  differentiation
                                                                        ╎
                          (PLAN 6 ╌╌► PLAN 7 unblocks Task 18 only, not a prerequisite)
```

**Topological order: `2·Task 0 → 1 → 3 → 2 → 4 → 5 → 6 → 7`.** Acyclic — verified by
grepping the produces/consumes graph across all seven files.

> **`PLAN 2 Task 0` comes before everything.** It pins the dependency floors that
> currently leave the repo red on a fresh install. Until it lands, `mypy` checks
> nothing and 55 tests fail — including the MCP tool-count assertion PLAN 1 Task 7
> depends on. See "Baseline" below.

Plans **1 and 3 have no prerequisites** and can run in parallel. Everything else is
sequential.

The one reverse-flowing obligation is a *gate*, not a symbol: PLAN 1 Task 7's
`test_every_cli_command_is_documented` walks `app.registered_commands` and fails on any
command missing a docs row — so every command PLANS 5, 6 and 7 add must ship its
documentation in the same commit.

### What crosses plan boundaries

| Contract | Produced by | Consumed by |
|---|---|---|
| `@app.callback()` (`main._root`) | PLAN 1 Task 4 | PLAN 4 (`--json`/`--raw`), PLAN 6 (`--session`) — **extend, never redefine** |
| `cli/skills.py`, `cli/skill_check.py`, `cli/_entry.py` | PLAN 1 | PLAN 2 (entry-point tests, wheel assertion) |
| `StaleFieldIndexError`, `_fields`/`_fields_url` invalidation | PLAN 3 Task 1 | PLAN 4, PLAN 5 |
| `{'value': …, 'present': …}` from `get_text`/`get_attribute` | PLAN 3 Task 12 | PLAN 4 Task 3, PLAN 5 |
| `SessionHandler._lock` (RLock around `handle()`) | PLAN 3 Task 3 | PLAN 5 Tasks 17–18, PLAN 6 |
| `cli/output.py` — `Mode`, `set_mode`, `emit`, `emit_error`, `emit_envelope` | PLAN 4 Task 1 | PLANS 5, 6, 7 |
| Daemon envelope `{ok, result, page, code, snapshot}` | PLAN 4 Task 3 | PLANS 5, 6, 7 |
| `_MUTATING_OPS` frozenset | PLAN 4 Task 4 | PLANS 5, 6, 7 — see the trap below |

> **`_MUTATING_OPS` is an exact-equality inventory test.** PLAN 4 Task 4 writes
> `test_mutating_ops_cover_every_state_changing_op` as a frozenset `==` assertion. Any
> plan adding a state-changing op **must** add its name to that frozenset in the same
> commit, or the suite goes red at its own commit gate. PLAN 5 adds 14 names, PLAN 6
> adds 4, PLAN 7 extends it further.

**Never cite a sibling plan by line number.** Line numbers rot on the next edit — 25
such citations had already gone stale before reconciliation. Cite the task heading
("PLAN 4 Task 6") or the symbol name.

---

## How to execute

Each plan carries this header:

> REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task.

Steps use `- [ ]` checkboxes for tracking. Work one task at a time; each ends in an
independently testable deliverable and its own commit.

### Gates (from `.claude/skills/developing-visus-web/SKILL.md` after PLAN 1 Task 1)

```bash
uv run ruff check src tests
uv run mypy
uv run pytest -q          # ≥90% coverage on visus.web
```

Single-test runs pass `--no-cov` — the coverage gate only makes sense on a full run.

### If you only do two things

**PLAN 1** and **PLAN 3.** The first is what makes the product discoverable at all:
today `pip install visus-web` ships zero bytes of skill, and the skill that exists
documents 8 of 53 commands. The second fixes the only bug that produces a *wrong
result* rather than failing loudly — `visus goto <url>` followed by `visus click 3`
re-resolves a stale locator against the new page, clicks the wrong element, and
returns `"clicked"`.

---

## Validation status

These plans were adversarially verified, not just written.

**Done:**

- **531 `file:line` citations validated mechanically** — every one resolves to a real
  file with the cited lines in range. An earlier pass found 2 broken; both fixed.
- **Per-plan adversarial hardening** — 506 citations opened and read for *content*, not
  just line existence. **54 were wrong (10.7%)** and were corrected. `tier3` was the
  worst at 22 of 68.
- **21 placeholders** found and replaced with real content beyond the obvious
  `TODO`/`TBD` patterns.
- **Cross-plan reconciliation** — the produces/consumes graph rebuilt by grep and every
  consumed symbol checked against its named producer. Found and fixed: 25 rotted
  cross-plan line citations, the `_MUTATING_OPS` trap above, a
  `--snapshot-sink`/`--snapshot` signature mismatch, and two callback-ordering
  violations in PLAN 6 (one of which emitted plain text into a `--json` pipeline).
- **Numbers corrected against the repo** — the suite has **775** test functions (61
  modules, 298 browser, 477 non-browser), not the 755 or 778 earlier drafts claimed;
  `-s` is `--selector` in **21** places, not 29.

**Not done — know this before you start:**

- **The gates were run, and the baseline is RED.** See "Baseline" below — this changed
  the plans.

- **No browser test was run.** The 298 browser-marked tests need a real Chrome plus a
  driver; only the 557 non-browser test instances were executed. Coverage was never
  measured, so **PLAN 2 Task 2 Step 6 remains unverified**: it runs the suite to freeze
  current per-package coverage into `coverage-floors.json`, and if real coverage is
  below the 90% the config claims, that step yields different floors than the plan
  assumes.

- **The plans' own code still cannot be validated by running anything** — it does not
  exist yet. Each task's failing-test step is that validation.

---

## Baseline — measured 2026-08-06

`python -m venv .venv && pip install -e ".[dev,cli,mcp,vision]"`, then the three gates:

| Gate | Result |
|---|---|
| `ruff check src tests` | ✅ All checks passed |
| `mypy` | ❌ fatal — exits before checking anything |
| `pytest -m "not browser"` | ❌ **55 failed, 502 passed** |

**None of it is the repo's own code.** Every failure traces to a dependency floor with
no upper bound resolving to a newer major:

1. **`mcp>=1.2.0` admitted `mcp` 2.0.0, which deleted `mcp.server.fastmcp`.**
   `src/visus/web/mcp/server.py:11` imports exactly that, so the module raises
   `ModuleNotFoundError` — 49 test failures and 45 mypy errors from one line. This is
   **live in production**: `pip install "visus-web[mcp]"` ships a dead MCP server
   today. Last working release is 1.29.0.
2. **`numpy>=1.24.0` admitted 2.5.1**, whose stubs use 3.12-only `type` statements;
   under `python_version = "3.10"` mypy dies at
   `numpy/__init__.pyi:737` and checks nothing.
3. **`rpa.py:198` imports `runpilot`, undeclared** — but deliberately so (lazy,
   env-guarded, `try/except`, and the docstring says so). The code is right; the mypy
   config just lacks an override.

Unattributed: 6 `tests/test_vision.py` failures with an onnxruntime
`bad allocation` runtime error. Possibly environment memory pressure — not confidently
a repo bug.

**This is why `PLAN 2 Task 0` exists.** It was added after the run. **Do it first, before
anything else in any plan** — PLAN 1 Task 7's test asserts the MCP tool count, and it
cannot even import the server until Task 0 lands.
- **Two citations point at reference clones not in this checkout** —
  `playwright.config.ts:22` and one `playwright-cli/…` path in PLAN 2. The
  playwright-cli citations in PLAN 7 are prefixed with that repo's path; it lives at
  `../playwright-cli` relative to this one.
- **Known task-level caveats** are recorded inside each plan where they apply — e.g.
  PLAN 3 Task 16's private-file-mode test only fails on POSIX (`hasattr(os, "getuid")`
  is False on Windows), and several manual end-to-end steps depend on live network.
- **PLAN 1 Task 13 is a genuine either/or the plan refuses to decide:** `LICENSE` and
  `pyproject.toml` say Apache-2.0 while `README.md` says "Proprietary — all rights
  reserved", and both render on the same PyPI page. Both branches are written out;
  someone has to choose, and it must resolve before the next release.

---

## A note on `docs/`

`.gitignore` carries `/docs/` under the comment *"Local-only planning docs (specs/plans
kept on disk, NOT tracked)"*. These files were force-added to this branch deliberately.
PLAN 1 Task 12 narrows that rule; until it lands, new files here stay invisible to git
without `git add -f`.
