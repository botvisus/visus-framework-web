# Tier 1 — CI and Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the 755 existing test functions run on every push across Windows and Linux, and make it impossible to publish an untested or unintended build to PyPI.

**Architecture:** The 90% coverage gate moves out of unconditional `addopts` into coverage's own config, so a filtered lane waives it with one explicit flag instead of throwing measurement away; a new `scripts/check_coverage.py` adds per-package floors on top of the single global number. A new `.github/workflows/ci.yml` runs four jobs (lint+types, fast tests on a 2×2 OS/Python matrix, installed-console-script tests on both OSes, and the full real-browser suite plus both coverage gates on `windows-latest`), and is exposed as a reusable workflow so `publish.yml` can make `build` depend on it. `publish.yml` gains an `if: github.event_name == 'release'` guard on every job and an assertion that the built wheel actually contains the packaged agent skill.

**Tech Stack:** Python 3.10+, Typer, Rich, Selenium 4.38, pytest + pytest-xdist, hatchling, mypy --strict, ruff

## Global Constraints

- Gates: `uv run ruff check src tests` (this plan widens it to `src tests scripts`), `uv run mypy` (strict), `uv run pytest -q` (≥90% coverage).
- **THE HIDDEN-ENGINE RULE (inviolable):** no `selenium.*` type may appear in any public signature/return/exception/docstring. Selenium imports allowed ONLY in `backends/browsers/*.py`, `backends/selenium/*.py`, `backends/selenium_backend.py`. (No task in this plan touches those files.)
- Test convention: **real browser, no fakes**, `@pytest.mark.browser`, fixtures in `tests/fixtures/*.html` served by the session-scoped `base_url` fixture. Test doubles isolate a unit ONLY when its real behaviour is also covered by an integration test. No `skip`/`xfail`/mock-to-pass.
- **This plan adds no browser tests and therefore no new HTML fixtures.** Every test it adds is either a pure-logic unit test or a real subprocess test that installs and runs the real artifact.
- Ruff: line-length 100, select `["E","F","I","UP","B"]`.
- mypy: `strict = true`, python_version 3.10. `[tool.mypy] packages = ["visus.web"]` — `scripts/` and `tests/` are linted by ruff but not type-checked by mypy; write `scripts/check_coverage.py` fully annotated anyway.
- Commits: small, TDD (failing test → minimal impl → green → commit), semantic messages `label(scope): description`. Labels: `fix`, `feat`, `chore`, `docs`, `test`, `devops`. **Never** add `Co-Authored-By` lines.
- Single-test runs use `--no-cov` (the 90% gate only makes sense on a full run).

## Prerequisites

**PLAN 1 (`2026-08-06-tier1-skill-distribution.md`) MUST land before Task 3 of this plan.** This plan consumes these exact symbols and artifacts from it:

| Consumed | From | Used by |
|---|---|---|
| `src/visus/web/cli/_entry.py` → `cli_main() -> None` | PLAN 1 | Task 3, Task 5 |
| `src/visus/web/cli/_entry.py` → `mcp_main() -> None` | PLAN 1 | Task 3 |
| `pyproject.toml` `[project.scripts]` repointed to `visus = "visus.web.cli._entry:cli_main"` and `visus-web-mcp = "visus.web.cli._entry:mcp_main"` | PLAN 1 | Task 3 |
| `src/visus/web/skills/visus-web/SKILL.md` packaged inside the `visus.web` package directory | PLAN 1 | Task 3, Task 5 |
| The message `cli_main()` prints when the `[cli]` extra is absent **must contain the literal substring `visus-web[cli]`** | PLAN 1 | Task 3 |

**Tasks 1, 2, 4, 6, 7 and 8 have no dependency on PLAN 1** and may be executed before it lands.

**Files this plan must NOT touch** (owned by other plans, editing them causes a merge collision):

- `skills/developing-visus-web/SKILL.md` — PLAN 1 moves it to `.claude/skills/developing-visus-web/SKILL.md` and rewrites the gates section. Do not edit it here, even though it declares the gates this plan changes.
- `src/visus/web/cli/main.py`, `session_server.py`, `session_client.py`, `console.py` — PLANS 3/4/5/6.
- `README.md` — PLAN 1 owns metadata/README hygiene.

## File Structure

**Created:**

| Path | Single responsibility |
|---|---|
| `scripts/check_coverage.py` | Re-aggregate `coverage.json` per sub-package of `visus.web` and fail when any package drops below its recorded floor. |
| `coverage-floors.json` | The recorded per-package floors (data, committed). |
| `tests/test_pytest_config.py` | Assert the pytest/coverage configuration contract and prove a partial run can waive the gate without losing measurement. |
| `tests/test_coverage_floors.py` | Unit tests for `scripts/check_coverage.py`. |
| `tests/test_installed_entry_points.py` | Build the real wheel, install it into throw-away venvs, run the real `visus` executable. |
| `tests/test_ci_workflows.py` | Assert the CI and publish workflow contracts (triggers, matrix, guards, `needs:` wiring, wheel assertion). |
| `tests/test_repo_hygiene.py` | Forbid-only equivalents: no new skip/xfail, no test returning a value, plus the presence contract for the repo-hygiene files. |
| `.github/workflows/ci.yml` | Lint+types, fast tests, packaging tests, full browser suite + coverage gates. Reusable via `workflow_call`. |
| `.github/dependabot.yml` | Weekly pip + github-actions update PRs. |
| `.pre-commit-config.yaml` | Local-only ruff + mypy hooks mirroring the CI gates. |
| `CONTRIBUTING.md` | Setup, the exact gate commands, TDD and real-browser rules, commit convention. |
| `SECURITY.md` | How to report a vulnerability; the daemon's loopback/token threat model. |
| `RELEASING.md` | Release runbook (both version strings, gates, tag, Release) + the Selenium roll procedure. |

**Modified:**

| Path | Change |
|---|---|
| `pyproject.toml:26-35` | `[dev]` gains `tomli` (3.10 only), `build`, `hatchling`, `pyyaml`. |
| `pyproject.toml:64-74` | `addopts` loses `--cov-fail-under=90`, gains `--strict-markers --strict-config`; new `markers` entry `packaging`; new `filterwarnings`; new `[tool.coverage.run]` / `[tool.coverage.report]`. |
| `.github/workflows/publish.yml:7-51` | Release guard on every job, `test` job calling `ci.yml`, `needs:` wiring, wheel-content assertion. |
| `.gitignore:32-41` | Ignore `coverage.json`. |
| `TESTING.md:12-24, 41-46` | Document the two-command full gate and the `--cov-fail-under=0` partial-run form. |

---

### Task 1: Move the coverage gate out of unconditional `addopts` (E5)

**Files:**
- Modify: `pyproject.toml:26-35` (add `tomli` to `[dev]`), `pyproject.toml:64-74` (`addopts` + new `[tool.coverage.*]` sections)
- Modify: `TESTING.md:12-24`, `TESTING.md:41-46`
- Test: `tests/test_pytest_config.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `[tool.coverage.report] fail_under = 90` — the single source of truth for the global gate, read by Task 2's `scripts/check_coverage.py` via `global_floor()` and asserted by Task 6's config tests.

**Why this design (the two-sentence justification the reviewer will ask for):** `fail_under` now lives in `[tool.coverage.report]`, coverage's own config section, so exactly one number defines the global gate and every consumer reads it from the same place — pytest-cov (which adopts it when `--cov-fail-under` is absent), a bare `coverage report`, and `scripts/check_coverage.py`. Taking it out of `addopts` means a filtered lane waives the gate with one explicit flag, `--cov-fail-under=0`, which keeps coverage **measured**, instead of `--no-cov`, which throws the measurement away entirely — and it puts the real gate where a reader can see it, as an explicit argument in `ci.yml`.

Because every gated invocation passes `--cov-fail-under=90` explicitly and every filtered invocation passes `--cov-fail-under=0` explicitly, the behaviour is identical whether or not the installed pytest-cov auto-adopts `fail_under` from the coverage config. Do not rely on the auto-adoption.

**Current state (verified):** `pyproject.toml:74` is

```
addopts = "-p no:visus_web -n auto --dist loadfile --cov=visus.web --cov-report=term-missing --cov-fail-under=90"
```

and there is no `[tool.coverage]` section anywhere in the repo.

- [ ] **Step 1: Add `tomli` to the `[dev]` extra**

`tomllib` is stdlib only from Python 3.11, and `requires-python = ">=3.10"`. The config tests read the real `pyproject.toml`, so 3.10 needs the backport.

In `pyproject.toml`, replace lines 26-35:

```toml
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "pytest-xdist>=3.5.0",
    "pytest-timeout>=2.2.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.6.0",
    "mypy>=1.8.0",
    "pre-commit>=3.5.0",
]
```

with:

```toml
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "pytest-xdist>=3.5.0",
    "pytest-timeout>=2.2.0",
    "pytest-asyncio>=0.23.0",
    "ruff>=0.6.0",
    "mypy>=1.8.0",
    "pre-commit>=3.5.0",
    # tomllib is stdlib from 3.11; the config tests and scripts/check_coverage.py
    # read pyproject.toml directly and must also work on the declared 3.10 floor.
    "tomli>=2.0.1; python_version < '3.11'",
]
```

- [ ] **Step 2: Sync the environment**

Run: `uv pip install -e ".[dev,vision,mcp,cli]"`
Expected: exits 0. On Python 3.11+ `tomli` is simply not selected by the marker.

- [ ] **Step 3: Write the failing test**

Create `tests/test_pytest_config.py`:

```python
"""The pytest + coverage configuration is a contract — assert it directly.

`--cov-fail-under=90` used to sit unconditionally in `addopts`, which made a
filtered lane (`-m "not browser"` selects 456 of the 755 tests) fail the coverage
gate on arrival. The gate now lives in `[tool.coverage.report]` and is passed
explicitly by whichever invocation is supposed to enforce it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10 — tomllib landed in 3.11
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject() -> dict[str, Any]:
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    data: dict[str, Any] = tomllib.loads(text)
    return data


def _addopts() -> str:
    opts: str = _pyproject()["tool"]["pytest"]["ini_options"]["addopts"]
    return opts


def test_coverage_gate_is_not_baked_into_addopts() -> None:
    assert "--cov-fail-under" not in _addopts(), (
        "the 90% gate must not be unconditional: a `-m 'not browser'` lane can "
        "never reach it (299 of 755 tests need a real browser) and would fail on "
        "arrival. Pass the gate explicitly on the invocation that enforces it."
    )


def test_coverage_measurement_stays_on_by_default() -> None:
    addopts = _addopts()
    assert "--cov=visus.web" in addopts
    assert "--cov-report=term-missing" in addopts


def test_the_global_gate_lives_in_the_coverage_config() -> None:
    report = _pyproject()["tool"]["coverage"]["report"]
    assert report["fail_under"] == 90, (
        "one number, one place: pytest-cov, `coverage report` and "
        "scripts/check_coverage.py all read this value"
    )


def test_coverage_measures_the_source_tree() -> None:
    run = _pyproject()["tool"]["coverage"]["run"]
    assert run["source"] == ["visus.web"]


@pytest.mark.timeout(600)
def test_partial_run_waives_the_gate_but_keeps_measuring(tmp_path: Path) -> None:
    """A filtered run needs ONE flag to waive the gate, and still prints coverage.

    Runs the real pytest against the real pyproject in a subprocess with its own
    COVERAGE_FILE so it cannot clobber the outer run's `.coverage`.
    """
    env = dict(os.environ)
    env["COVERAGE_FILE"] = str(tmp_path / ".coverage.inner")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_engine.py",
            "-q",
            "-n",
            "0",
            "-p",
            "no:cacheprovider",
            "--cov-fail-under=0",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=540,
        check=False,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "Required test coverage" not in combined
    assert "visus" in proc.stdout, "the term-missing table should still be printed"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest tests/test_pytest_config.py -v --no-cov`
Expected: FAIL — `test_coverage_gate_is_not_baked_into_addopts` fails its assertion, and `test_the_global_gate_lives_in_the_coverage_config` / `test_coverage_measures_the_source_tree` fail with `KeyError: 'coverage'`.

- [ ] **Step 5: Rewrite `addopts` and add the coverage config**

In `pyproject.toml`, replace line 74:

```toml
addopts = "-p no:visus_web -n auto --dist loadfile --cov=visus.web --cov-report=term-missing --cov-fail-under=90"
```

with:

```toml
# No --cov-fail-under here: a filtered lane (-m "not browser" selects 456 of 755
# tests) can never reach 90% and would fail on arrival. Measurement stays on;
# the gate is passed explicitly by whoever enforces it (ci.yml, CONTRIBUTING.md)
# and waived with --cov-fail-under=0 by whoever cannot.
addopts = "-p no:visus_web -n auto --dist loadfile --cov=visus.web --cov-report=term-missing"
```

Then append these two sections immediately after the `[tool.pytest.ini_options]` block (i.e. before `[tool.ruff]` on line 76):

```toml
[tool.coverage.run]
source = ["visus.web"]
branch = false

[tool.coverage.report]
# THE global gate. One number, one place: pytest-cov adopts it when
# --cov-fail-under is absent, `coverage report` honours it, and
# scripts/check_coverage.py reads it as the global floor.
fail_under = 90
show_missing = true
exclude_also = [
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest tests/test_pytest_config.py -v --no-cov`
Expected: PASS, 5 passed.

- [ ] **Step 7: Prove the previously-failing lane now works**

Run: `uv run pytest -q -m "not browser" --cov-fail-under=0`
Expected: exits 0. The terminal shows the `term-missing` coverage table and **no** `FAIL Required test coverage of 90% not reached` line. (Before this task, the same command exited 1 on the coverage gate.)

- [ ] **Step 8: Update TESTING.md**

In `TESTING.md`, replace lines 12-24:

````markdown
## Run the suite

```bash
uv run pytest -q
```
- Runs in **parallel** via `pytest-xdist` (`-n auto`, `--dist loadfile`).
- Enforces a **90% coverage gate** on `visus.web` (`--cov-fail-under=90`).
- Browser tests are marked `@pytest.mark.browser`.

Run a single file fast (skip the coverage gate, which only makes sense on the full run):
```bash
uv run pytest tests/test_e2e_locators.py -m browser --no-cov
```
````

with:

````markdown
## Run the suite

The full gate is two commands:

```bash
uv run pytest -q --cov-fail-under=90 --cov-report=json
uv run python scripts/check_coverage.py
```
- Runs in **parallel** via `pytest-xdist` (`-n auto`, `--dist loadfile`).
- The **90% global gate** lives in `[tool.coverage.report] fail_under` and is passed
  explicitly here, so a *partial* run can waive it without editing config.
- `scripts/check_coverage.py` adds **per-package floors** from `coverage-floors.json`,
  so `cli/` or `mcp/` cannot rot behind a healthy global total.
- Browser tests are marked `@pytest.mark.browser`; the wheel/console-script tests are
  marked `@pytest.mark.packaging` (they build a wheel and install it into temp venvs,
  so they need network).

Run a single file fast — drop coverage entirely:
```bash
uv run pytest tests/test_e2e_locators.py -m browser --no-cov
```
…or keep the coverage table and only waive the gate:
```bash
uv run pytest tests/test_e2e_locators.py -m browser --cov-fail-under=0
```
````

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml TESTING.md tests/test_pytest_config.py
git commit -m "chore(test): move the 90% coverage gate out of unconditional addopts"
```

---

### Task 2: Per-package coverage floors (medium/low row 40)

**Files:**
- Create: `scripts/check_coverage.py`
- Create: `coverage-floors.json`
- Create: `tests/test_coverage_floors.py`
- Modify: `.gitignore:32-41`

**Interfaces:**
- Consumes: `[tool.coverage.report] fail_under` from Task 1.
- Produces:
  - `scripts/check_coverage.py::package_of(path: str) -> str | None`
  - `scripts/check_coverage.py::package_totals(report: dict[str, Any]) -> dict[str, float]`
  - `scripts/check_coverage.py::global_floor(pyproject: Path = PYPROJECT) -> float`
  - `scripts/check_coverage.py::violations(totals, floors, *, global_total, global_min) -> list[str]`
  - `scripts/check_coverage.py::freeze(totals: dict[str, float], slack: float) -> dict[str, float]`
  - `scripts/check_coverage.py::main(argv: list[str] | None = None) -> int`
  - `coverage-floors.json` — `{"slack": float, "packages": {name: float}}`
- Task 4's `ci.yml` runs `python scripts/check_coverage.py` in the browser lane; Task 8's `CONTRIBUTING.md` documents it.

**Why:** `--cov-fail-under` is one number over ~11,290 statements. `visus/web/cli` + `visus/web/mcp` are 3,172 of them (28%); in the worst case ~36% of those two packages can be uncovered while the global total still reads 90%. Re-aggregating per sub-package closes that.

**Note on test doubles:** `tests/test_coverage_floors.py` feeds the functions synthetic `coverage.json` dictionaries. Those are *inputs*, not doubles — nothing is patched or faked. The real integration coverage is Task 4's browser lane, which runs the script against a real `coverage.json` produced by a real full-suite run.

- [ ] **Step 1: Write the failing test**

Create `tests/test_coverage_floors.py`:

```python
"""Unit tests for scripts/check_coverage.py — the per-package coverage floors.

The script is loaded by path because `scripts/` is a repo tool, not an importable
package. Inputs are synthetic coverage.json documents; nothing is patched. The
real end-to-end exercise is ci.yml's browser lane, which runs the script against
a coverage.json produced by an actual full-suite run.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_coverage.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_coverage", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_coverage"] = module
    spec.loader.exec_module(module)
    return module


cc = _load_script()


def _report(files: dict[str, tuple[int, int]], total_pct: float) -> dict[str, Any]:
    """Build a minimal coverage.json: {path: (covered_lines, num_statements)}."""
    return {
        "files": {
            path: {"summary": {"covered_lines": covered, "num_statements": stmts}}
            for path, (covered, stmts) in files.items()
        },
        "totals": {"percent_covered": total_pct},
    }


def test_package_of_buckets_subpackages() -> None:
    assert cc.package_of("src/visus/web/cli/main.py") == "cli"
    assert cc.package_of("src/visus/web/backends/selenium/driver_delegate.py") == "backends"


def test_package_of_buckets_top_level_modules_as_root() -> None:
    assert cc.package_of("src/visus/web/engine.py") == "_root"
    assert cc.package_of("src/visus/web/__init__.py") == "_root"


def test_package_of_handles_windows_separators_and_site_packages() -> None:
    assert cc.package_of(r"src\visus\web\mcp\server.py") == "mcp"
    assert cc.package_of(".venv/Lib/site-packages/visus/web/mcp/server.py") == "mcp"


def test_package_of_ignores_paths_outside_the_package() -> None:
    assert cc.package_of("tests/test_cli.py") is None
    assert cc.package_of("scripts/check_coverage.py") is None


def test_package_totals_weight_by_statement_count() -> None:
    report = _report(
        {
            "src/visus/web/cli/main.py": (5, 10),
            "src/visus/web/cli/session_server.py": (45, 90),
            "src/visus/web/mcp/server.py": (30, 30),
        },
        total_pct=61.5,
    )
    assert cc.package_totals(report) == {"cli": 50.0, "mcp": 100.0}


def test_package_totals_treats_an_empty_package_as_fully_covered() -> None:
    report = _report({"src/visus/web/vision/__init__.py": (0, 0)}, total_pct=100.0)
    assert cc.package_totals(report) == {"vision": 100.0}


def test_violations_flag_a_package_below_its_floor() -> None:
    bad = cc.violations(
        {"cli": 71.0, "mcp": 95.0},
        {"cli": 80.0, "mcp": 90.0},
        global_total=93.0,
        global_min=90.0,
    )
    assert bad == ["cli: 71.00% < floor 80.00%"]


def test_violations_flag_the_global_total() -> None:
    bad = cc.violations({"cli": 99.0}, {"cli": 80.0}, global_total=88.5, global_min=90.0)
    assert bad == ["TOTAL: 88.50% < global floor 90.00%"]


def test_violations_flag_a_package_that_vanished_from_the_report() -> None:
    bad = cc.violations({"cli": 99.0}, {"cli": 80.0, "mcp": 90.0}, global_total=99.0,
                        global_min=90.0)
    assert bad == ["mcp: no statements in the report (package renamed or deleted?)"]


def test_violations_are_empty_when_everything_holds() -> None:
    assert cc.violations({"cli": 81.0}, {"cli": 80.0}, global_total=90.0, global_min=90.0) == []


def test_freeze_records_todays_numbers_minus_slack() -> None:
    assert cc.freeze({"cli": 84.0, "mcp": 1.5}, slack=3.0) == {"cli": 81.0, "mcp": 0.0}


def test_main_freeze_then_enforce_round_trip(tmp_path: Path) -> None:
    report_path = tmp_path / "coverage.json"
    floors_path = tmp_path / "coverage-floors.json"
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.coverage.report]\nfail_under = 90\n", encoding="utf-8")
    report_path.write_text(
        json.dumps(
            _report(
                {
                    "src/visus/web/cli/main.py": (80, 100),
                    "src/visus/web/mcp/server.py": (95, 100),
                },
                total_pct=91.0,
            )
        ),
        encoding="utf-8",
    )
    argv = [
        "--report", str(report_path),
        "--floors", str(floors_path),
        "--pyproject", str(pyproject),
    ]

    assert cc.main([*argv, "--freeze", "--slack", "3"]) == 0
    recorded = json.loads(floors_path.read_text(encoding="utf-8"))
    assert recorded == {"slack": 3.0, "packages": {"cli": 77.0, "mcp": 92.0}}

    assert cc.main(argv) == 0

    recorded["packages"]["cli"] = 100.0
    floors_path.write_text(json.dumps(recorded), encoding="utf-8")
    assert cc.main(argv) == 1


def test_main_reports_a_missing_coverage_report(tmp_path: Path) -> None:
    assert cc.main(["--report", str(tmp_path / "nope.json")]) == 2


def test_the_committed_floors_file_is_wellformed() -> None:
    data = json.loads((REPO_ROOT / "coverage-floors.json").read_text(encoding="utf-8"))
    assert isinstance(data["slack"], (int, float))
    assert data["packages"], "floors were never frozen — run --freeze once"
    assert {"cli", "mcp"} <= set(data["packages"]), (
        "cli/ and mcp/ are 3,172 of 11,290 lines; they are exactly what the "
        "global gate can hide"
    )
    assert all(0.0 <= float(v) <= 100.0 for v in data["packages"].values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_coverage_floors.py -v --no-cov`
Expected: FAIL at collection — `FileNotFoundError` / `ModuleNotFoundError` raised from `_load_script()` because `scripts/check_coverage.py` does not exist.

- [ ] **Step 3: Write the implementation**

Create `scripts/check_coverage.py`:

```python
"""Per-package coverage floors, on top of the single global gate.

`--cov-fail-under` is one number over ~11,290 statements: `visus/web/cli` and
`visus/web/mcp` are 3,172 of them, so either could rot for months while the
global total stays above 90%. This script re-aggregates the machine-readable
`coverage.json` per top-level sub-package of `visus/web` and fails when any
package falls below the floor recorded in `coverage-floors.json`.

    uv run pytest -q --cov-report=json          # writes coverage.json
    uv run python scripts/check_coverage.py     # enforce global + per-package
    uv run python scripts/check_coverage.py --freeze   # (re)record the floors
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10 — tomllib landed in 3.11
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT = REPO_ROOT / "coverage.json"
DEFAULT_FLOORS = REPO_ROOT / "coverage-floors.json"
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: Everything under ``visus/web/<name>/`` buckets as ``<name>``; modules sitting
#: directly in ``visus/web/`` bucket as ``_root``.
MARKER = "visus/web/"
ROOT_BUCKET = "_root"
DEFAULT_SLACK = 3.0


def package_of(path: str) -> str | None:
    """Bucket one coverage.json file key. ``None`` for paths outside visus.web."""
    rel = path.replace("\\", "/")
    idx = rel.rfind(MARKER)
    if idx < 0:
        return None
    tail = rel[idx + len(MARKER) :]
    head, sep, _rest = tail.partition("/")
    return head if sep else ROOT_BUCKET


def package_totals(report: dict[str, Any]) -> dict[str, float]:
    """Statement-coverage percent per sub-package, weighted by statement count."""
    acc: dict[str, list[int]] = {}
    files: dict[str, Any] = report.get("files") or {}
    for path, entry in files.items():
        package = package_of(path)
        if package is None:
            continue
        summary = entry["summary"]
        bucket = acc.setdefault(package, [0, 0])
        bucket[0] += int(summary["covered_lines"])
        bucket[1] += int(summary["num_statements"])
    return {
        package: (100.0 if statements == 0 else round(100.0 * covered / statements, 2))
        for package, (covered, statements) in sorted(acc.items())
    }


def global_floor(pyproject: Path = PYPROJECT) -> float:
    """The one global gate, read from ``[tool.coverage.report] fail_under``."""
    data: dict[str, Any] = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return float(data["tool"]["coverage"]["report"]["fail_under"])


def violations(
    totals: dict[str, float],
    floors: dict[str, float],
    *,
    global_total: float,
    global_min: float,
) -> list[str]:
    """Human-readable lines describing every floor that was not met."""
    out: list[str] = []
    if global_total + 1e-9 < global_min:
        out.append(f"TOTAL: {global_total:.2f}% < global floor {global_min:.2f}%")
    for package in sorted(floors):
        floor = float(floors[package])
        actual = totals.get(package)
        if actual is None:
            out.append(f"{package}: no statements in the report (package renamed or deleted?)")
        elif actual + 1e-9 < floor:
            out.append(f"{package}: {actual:.2f}% < floor {floor:.2f}%")
    return out


def freeze(totals: dict[str, float], slack: float) -> dict[str, float]:
    """Record today's numbers, minus *slack*, as tomorrow's floors."""
    return {package: round(max(0.0, pct - slack), 2) for package, pct in sorted(totals.items())}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enforce per-package coverage floors.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--floors", type=Path, default=DEFAULT_FLOORS)
    parser.add_argument("--pyproject", type=Path, default=PYPROJECT)
    parser.add_argument(
        "--freeze", action="store_true", help="Rewrite the floors file from this report."
    )
    parser.add_argument(
        "--slack",
        type=float,
        default=DEFAULT_SLACK,
        help="Points below today's number to record when freezing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not args.report.is_file():
        print(
            f"error: {args.report} not found — run `pytest --cov-report=json` first",
            file=sys.stderr,
        )
        return 2

    report: dict[str, Any] = json.loads(args.report.read_text(encoding="utf-8"))
    totals = package_totals(report)
    global_total = float(report["totals"]["percent_covered"])
    minimum = global_floor(args.pyproject)

    width = max((len(name) for name in totals), default=8)
    for package, pct in totals.items():
        print(f"  {package:<{width}}  {pct:6.2f}%")
    print(f"  {'TOTAL':<{width}}  {global_total:6.2f}%  (global floor {minimum:.2f}%)")

    if args.freeze:
        payload = {"slack": args.slack, "packages": freeze(totals, args.slack)}
        args.floors.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\nfroze {len(payload['packages'])} per-package floors into {args.floors}")
        return 0

    if not args.floors.is_file():
        print(
            f"error: {args.floors} not found — run once with --freeze to record it",
            file=sys.stderr,
        )
        return 2

    recorded: dict[str, Any] = json.loads(args.floors.read_text(encoding="utf-8"))
    floors = {name: float(value) for name, value in recorded["packages"].items()}
    failures = violations(totals, floors, global_total=global_total, global_min=minimum)
    if failures:
        print("\nCoverage floors NOT met:", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print("\nAll coverage floors met.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Ignore the generated report**

In `.gitignore`, replace line 36-39:

```
.coverage
.coverage.*
htmlcov/
coverage.xml
```

with:

```
.coverage
.coverage.*
htmlcov/
coverage.xml
# machine-readable report consumed by scripts/check_coverage.py — regenerated,
# never committed (coverage-floors.json IS committed)
coverage.json
```

- [ ] **Step 5: Run the unit tests to verify all but one pass**

Run: `uv run pytest tests/test_coverage_floors.py -v --no-cov`
Expected: 13 passed, 1 failed — `test_the_committed_floors_file_is_wellformed` fails with `FileNotFoundError: ... coverage-floors.json`. Every other test passes.

- [ ] **Step 6: Freeze the real floors from a real full-suite run**

This is the one long step in the plan. It runs the complete suite (755 tests, 299 of them real-browser) to produce a truthful `coverage.json`. Budget 20-40 minutes; a headless Chrome window churns for the duration.

Run: `uv run pytest -q -m "not packaging" --cov-fail-under=0 --cov-report=json`
Expected: exits 0, writes `coverage.json` in the repo root.

Then run: `uv run python scripts/check_coverage.py --freeze`
Expected output shape (your numbers will differ):

```
  _root      95.12%
  api        96.40%
  async_api  94.02%
  backends   91.77%
  cli        84.55%
  mcp        88.31%
  observability  93.10%
  vision     90.44%
  TOTAL      92.68%  (global floor 90.00%)

froze 8 per-package floors into C:\...\coverage-floors.json
```

`--freeze` records `floor(actual) - 3.0` so a small, honest fluctuation between machines does not fail CI. Floors only ever ratchet **up**, by re-running `--freeze` after coverage improves.

> If Chrome is unavailable on this machine, do **not** freeze from a `-m "not browser"` run — the resulting floors would be near-zero and worthless. Freeze on a machine that can run browsers, or take the `coverage-json` artifact from Task 4's CI browser lane and freeze from that file with `--report <downloaded path>`.

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_coverage_floors.py -v --no-cov`
Expected: PASS, 14 passed.

- [ ] **Step 8: Prove the gate actually bites**

Run: `uv run python scripts/check_coverage.py`
Expected: prints the table then `All coverage floors met.`, exits 0.

Now temporarily raise one floor. Edit `coverage-floors.json` and set `"cli"` to `100.0`, then run: `uv run python scripts/check_coverage.py`
Expected: exits 1 with

```
Coverage floors NOT met:
  - cli: 84.55% < floor 100.00%
```

Restore the frozen value before committing (re-run `uv run python scripts/check_coverage.py --freeze` if you lost it).

- [ ] **Step 9: Lint the new script**

Run: `uv run ruff check src tests scripts`
Expected: `All checks passed!`

- [ ] **Step 10: Commit**

```bash
git add scripts/check_coverage.py coverage-floors.json tests/test_coverage_floors.py .gitignore
git commit -m "chore(coverage): enforce per-package floors on top of the global gate"
```

---

### Task 3: Test the installed console scripts (E4)

**Files:**
- Create: `tests/test_installed_entry_points.py`
- Modify: `pyproject.toml:26-35` (`[dev]` gains `build`, `hatchling`), `pyproject.toml:66-68` (register the `packaging` marker)

**Interfaces:**
- Consumes (from PLAN 1): `visus.web.cli._entry:cli_main`, `visus.web.cli._entry:mcp_main`, the repointed `[project.scripts]`, `src/visus/web/skills/visus-web/SKILL.md` inside the package, and the guard message containing the literal substring `visus-web[cli]`.
- Produces: the `packaging` pytest marker, consumed by Task 4's `ci.yml` (`-m packaging` / `-m "not packaging"`).

**Why the existing "e2e" test does not close this gap.** `tests/test_e2e_cli_session.py:42` reads:

```python
    info = session_client.start_daemon("chrome", headless=True, url=_PAGE, cwd=tmp_path)
```

That is a **library function imported in-process** (`from visus.web.cli import session_client`, line 19). Its own spawn, `session_client.py:165-176`, is:

```python
    subprocess.Popen(
        [sys.executable, "-m", "visus.web.cli.session_server", engine, env["VISUS_WEB_HEADLESS"]]
        + ([url] if url else []),
```

— `python -m`, never the `visus` executable. So the genuinely cross-process e2e test still resolves `typer` from the developer's environment and never touches `[project.scripts]`. Combined with the fact that all 50 CLI commands are driven through `typer.testing.CliRunner` against the imported `app` object, and that `twine check` validates metadata without ever installing the wheel: a broken console-script target, a missing `[cli]` extra, or a wheel that omits the packaged skill are **all invisible to every existing test and workflow**.

- [ ] **Step 1: Write the failing test**

Create `tests/test_installed_entry_points.py`:

```python
"""Proof that the INSTALLED console scripts work — the one thing CliRunner cannot show.

Every other CLI test imports `visus.web.cli.main.app` in-process, so the
`[project.scripts]` entry points are never resolved and never executed. Even the
genuine cross-process test (tests/test_e2e_cli_session.py:42) calls the library
function `session_client.start_daemon()`, which spawns
`python -m visus.web.cli.session_server` — still not the `visus` executable.

These tests build the real wheel, install it into throw-away virtualenvs, and run
the real `visus` binary, including the case where the optional `[cli]` extra is
absent (the CLI must explain itself, not raise ModuleNotFoundError).

Marked `packaging`: they need network (pip resolves selenium/typer from PyPI) and
take minutes, so CI runs them in a dedicated job.
"""

from __future__ import annotations

import subprocess
import sys
import venv
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = [pytest.mark.packaging, pytest.mark.timeout(900)]


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _venv_executables(env_dir: Path) -> tuple[Path, Path]:
    """Return (python, visus) inside *env_dir* for this platform."""
    if sys.platform == "win32":
        bindir = env_dir / "Scripts"
        return bindir / "python.exe", bindir / "visus.exe"
    bindir = env_dir / "bin"
    return bindir / "python", bindir / "visus"


def _install(env_dir: Path, requirement: str) -> Path:
    """Create a fresh venv, pip-install *requirement*, return the `visus` path."""
    venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)
    python, visus = _venv_executables(env_dir)
    proc = _run(
        [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-q", requirement]
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return visus


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the real wheel from this checkout (no build isolation: offline-safe)."""
    outdir = tmp_path_factory.mktemp("dist")
    proc = _run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(outdir),
            str(REPO_ROOT),
        ]
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    wheels = sorted(outdir.glob("visus_web-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {[w.name for w in wheels]}"
    return wheels[0]


@pytest.fixture(scope="module")
def cli_visus(tmp_path_factory: pytest.TempPathFactory, wheel: Path) -> Path:
    """`visus` from a venv where the [cli] extra IS installed."""
    return _install(tmp_path_factory.mktemp("with-cli") / "venv", f"{wheel}[cli]")


@pytest.fixture(scope="module")
def bare_visus(tmp_path_factory: pytest.TempPathFactory, wheel: Path) -> Path:
    """`visus` from a venv where the [cli] extra is ABSENT (base deps only)."""
    return _install(tmp_path_factory.mktemp("no-cli") / "venv", str(wheel))


def test_wheel_ships_the_runtime_data_files(wheel: Path) -> None:
    names = set(zipfile.ZipFile(wheel).namelist())
    for required in (
        "visus/web/py.typed",
        "visus/web/backends/selenium/js/bundle.js",
        "visus/web/skills/visus-web/SKILL.md",
    ):
        assert required in names, f"{required} is missing from {wheel.name}"


def test_wheel_declares_both_console_scripts(wheel: Path) -> None:
    archive = zipfile.ZipFile(wheel)
    entry = next(n for n in archive.namelist() if n.endswith(".dist-info/entry_points.txt"))
    text = archive.read(entry).decode("utf-8")
    assert "visus = visus.web.cli._entry:cli_main" in text
    assert "visus-web-mcp = visus.web.cli._entry:mcp_main" in text


def test_installed_visus_help_runs_through_the_real_entry_point(cli_visus: Path) -> None:
    assert cli_visus.is_file(), f"{cli_visus} was not created by the install"
    proc = _run([str(cli_visus), "--help"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for command in ("session", "list-fields", "translate", "doctor"):
        assert command in proc.stdout, f"{command!r} missing from `visus --help`"


def test_installed_visus_version_matches_the_package(cli_visus: Path) -> None:
    from visus.web import __version__

    proc = _run([str(cli_visus), "version"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == __version__


def test_visus_without_the_cli_extra_explains_itself(bare_visus: Path) -> None:
    assert bare_visus.is_file(), f"{bare_visus} was not created by the install"
    proc = _run([str(bare_visus), "--help"])
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, "a CLI that cannot start must not exit 0"
    assert "visus-web[cli]" in combined, (
        "the guard must name the pip target the user needs to install"
    )
    assert "Traceback" not in combined
    assert "ModuleNotFoundError" not in combined
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_installed_entry_points.py -v --no-cov`
Expected: FAIL — all six tests error during the `wheel` fixture, because `build` is not installed:

```
E       AssertionError: ... No module named build
```

- [ ] **Step 3: Add the build dependencies and register the marker**

In `pyproject.toml`, in the `[dev]` list, add these two entries after `"pre-commit>=3.5.0",`:

```toml
    # tests/test_installed_entry_points.py builds the real wheel with
    # `python -m build --no-isolation`, which needs the backend present locally.
    "build>=1.0.0",
    "hatchling>=1.21.0",
```

Then replace `pyproject.toml:66-68`:

```toml
markers = [
    "browser: integration test that launches a real headless browser",
]
```

with:

```toml
markers = [
    "browser: integration test that launches a real headless browser",
    "packaging: builds the real wheel and installs it into a temp venv (needs network)",
]
```

- [ ] **Step 4: Sync and run the test to verify it passes**

Run: `uv pip install -e ".[dev,vision,mcp,cli]"`
Then run: `uv run pytest tests/test_installed_entry_points.py -v --no-cov`
Expected: PASS, 6 passed. Duration 2-5 minutes (one wheel build, two venvs, two pip installs).

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_installed_entry_points.py
git commit -m "test(packaging): exercise the installed console scripts in real venvs"
```

---

### Task 4: CI workflow that actually runs the tests (E1)

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `tests/test_ci_workflows.py`
- Modify: `pyproject.toml:26-35` (`[dev]` gains `pyyaml`)

**Interfaces:**
- Consumes: `scripts/check_coverage.py` (Task 2), the `packaging` marker (Task 3), `[tool.coverage.report] fail_under` (Task 1).
- Produces: `.github/workflows/ci.yml` with `on: workflow_call`, and jobs named `lint`, `fast-tests`, `packaging-tests`, `browser-tests`. Task 5's `publish.yml` calls it as `./.github/workflows/ci.yml`.

**Lane design — read this before writing the YAML:**

| Job | Runner(s) | Python | Runs | Coverage |
|---|---|---|---|---|
| `lint` | ubuntu-latest | 3.12 | `ruff check src tests scripts`, `mypy` | n/a |
| `fast-tests` | ubuntu-latest **and windows-latest** | 3.10 and 3.12 | `-m "not browser and not packaging"` | `--cov-fail-under=0` |
| `packaging-tests` | ubuntu-latest **and windows-latest** | 3.12 | `-m packaging` | `--cov-fail-under=0` |
| `browser-tests` | **windows-latest** | 3.12 | `visus doctor`, then `-m "not packaging"` (browser + unit) | `--cov-fail-under=90 --cov-report=json` + `scripts/check_coverage.py` |

**Why windows-latest is mandatory, not optional.** `pyproject.toml:15` classifies `Operating System :: Microsoft :: Windows`. `main.py:33-36` shells out to PowerShell for the clipboard:

```python
    cmd = {
        "win32": ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
        "darwin": ["pbpaste"],
    }.get(sys.platform, ["xclip", "-selection", "clipboard", "-o"])
```

and `session_client.py:28-39` probes process liveness with `tasklist`:

```python
    if sys.platform == "win32":
        # tasklist is the dependency-free way to probe a pid on Windows.
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
```

`session_client.py:157-161` also picks Windows-only `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` creation flags. A Linux-only CI would leave every one of those paths untested on the platform this project targets.

**Why the browser lane is the gated one, and how the browser gets there.** Coverage is only meaningful over the whole suite — 299 of the 755 tests need a real browser — so the 90% gate and the per-package floors run in the lane that executes them. GitHub's `windows-latest` image ships Google Chrome, Microsoft Edge and Firefox pre-installed; nothing needs to be downloaded for the browsers themselves. The **driver** is resolved by Selenium Manager at launch time: `backends/browsers/chrome.py:39-41` is

```python
def build_service() -> Service:
    # No executable_path: Selenium Manager (selenium>=4.6) downloads/resolves chromedriver.
    return Service()
```

so the runner needs outbound network on first launch and nothing else. The lane's first step is `visus doctor` (`main.py:97-107`), which launches Chrome headless, navigates a data URL and exits 1 with the exception on failure — a 5-second smoke test that turns "Chrome or chromedriver is missing on this runner" into an unambiguous failure instead of 299 confusing ones. `tests/test_e2e_edge_ie.py:21-22` skips itself under xdist (which is always on here via `-n auto`), and `tests/test_e2e_firefox.py:35-37` runs for real because the runner has Firefox.

- [ ] **Step 1: Add PyYAML to `[dev]`**

In `pyproject.toml`, in the `[dev]` list, add after `"hatchling>=1.21.0",`:

```toml
    # tests/test_ci_workflows.py asserts the workflow contracts structurally.
    "pyyaml>=6.0",
```

Run: `uv pip install -e ".[dev,vision,mcp,cli]"`
Expected: exits 0.

- [ ] **Step 2: Write the failing test**

Create `tests/test_ci_workflows.py`:

```python
"""The GitHub Actions workflows are a contract — assert them structurally.

Same anti-drift pattern as tests/test_mcp_server.py's tool inventory: a workflow
that silently stops running the suite, drops windows-latest, or loses its release
guard is a defect that only shows up when it is too late.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    """GitHub's `on:` key. YAML 1.1 parses a bare `on` as the boolean True."""
    if "on" in workflow:
        triggers: dict[str, Any] = workflow["on"]
        return triggers
    return workflow[True]


def _run_text(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_ci_runs_on_push_and_pull_request_and_is_reusable() -> None:
    triggers = _triggers(_load(CI))
    assert "push" in triggers
    assert "pull_request" in triggers
    assert "workflow_call" in triggers, "publish.yml gates the build on this workflow"


def test_ci_declares_the_four_lanes() -> None:
    jobs = _load(CI)["jobs"]
    assert set(jobs) == {"lint", "fast-tests", "packaging-tests", "browser-tests"}


def test_lint_job_runs_both_static_gates() -> None:
    run = _run_text(_load(CI)["jobs"]["lint"])
    assert "ruff check src tests scripts" in run
    assert "mypy" in run


def test_fast_lane_covers_windows_and_the_declared_python_floor() -> None:
    job = _load(CI)["jobs"]["fast-tests"]
    matrix = job["strategy"]["matrix"]
    assert "windows-latest" in matrix["os"], (
        "Windows-first project: main.py shells to PowerShell, session_client.py "
        "shells to tasklist"
    )
    assert "ubuntu-latest" in matrix["os"]
    assert "3.10" in matrix["python"], 'requires-python = ">=3.10"'
    assert "3.12" in matrix["python"]
    assert job["strategy"]["fail-fast"] is False


def test_fast_lane_waives_the_gate_and_skips_the_slow_markers() -> None:
    run = _run_text(_load(CI)["jobs"]["fast-tests"])
    assert 'not browser and not packaging' in run
    assert "--cov-fail-under=0" in run


def test_packaging_lane_runs_the_installed_console_scripts_on_both_platforms() -> None:
    job = _load(CI)["jobs"]["packaging-tests"]
    assert set(job["strategy"]["matrix"]["os"]) == {"ubuntu-latest", "windows-latest"}
    assert "-m packaging" in _run_text(job)


def test_browser_lane_is_windows_and_carries_both_coverage_gates() -> None:
    job = _load(CI)["jobs"]["browser-tests"]
    assert job["runs-on"] == "windows-latest"
    run = _run_text(job)
    assert "visus doctor" in run, "smoke-test Chrome + Selenium Manager before 299 tests"
    assert "--cov-fail-under=90" in run
    assert "--cov-report=json" in run
    assert "scripts/check_coverage.py" in run
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_ci_workflows.py -v --no-cov`
Expected: FAIL — all eight tests raise `FileNotFoundError: ... .github\workflows\ci.yml`.

- [ ] **Step 4: Write the workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

# Runs the real gates on every push and PR, and is callable from publish.yml so a
# release cannot be built before these jobs go green.
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  workflow_call: {}

permissions:
  contents: read

concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  lint:
    name: Lint + types
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Install (mirrors TESTING.md)
        shell: bash
        run: |
          uv venv --python "3.12"
          uv pip install -e ".[dev,vision,mcp,cli]"
      - name: Put the venv on PATH
        shell: bash
        run: |
          if [ -d .venv/bin ]; then
            echo "$PWD/.venv/bin" >> "$GITHUB_PATH"
          else
            echo "$PWD/.venv/Scripts" >> "$GITHUB_PATH"
          fi
      - name: ruff
        run: ruff check src tests scripts
      - name: mypy --strict
        run: mypy

  fast-tests:
    name: Tests (no browser) ${{ matrix.os }} py${{ matrix.python }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
        python: ["3.10", "3.12"]
    runs-on: ${{ matrix.os }}
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Install (mirrors TESTING.md)
        shell: bash
        run: |
          uv venv --python "${{ matrix.python }}"
          uv pip install -e ".[dev,vision,mcp,cli]"
      - name: Put the venv on PATH
        shell: bash
        run: |
          if [ -d .venv/bin ]; then
            echo "$PWD/.venv/bin" >> "$GITHUB_PATH"
          else
            echo "$PWD/.venv/Scripts" >> "$GITHUB_PATH"
          fi
      - name: pytest (no browser, no packaging)
        run: pytest -q -m "not browser and not packaging" --cov-fail-under=0

  packaging-tests:
    name: Installed console scripts (${{ matrix.os }})
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Install (mirrors TESTING.md)
        shell: bash
        run: |
          uv venv --python "3.12"
          uv pip install -e ".[dev,vision,mcp,cli]"
      - name: Put the venv on PATH
        shell: bash
        run: |
          if [ -d .venv/bin ]; then
            echo "$PWD/.venv/bin" >> "$GITHUB_PATH"
          else
            echo "$PWD/.venv/Scripts" >> "$GITHUB_PATH"
          fi
      - name: pytest -m packaging
        run: pytest -q -m packaging --cov-fail-under=0

  browser-tests:
    name: Full suite + coverage gates (windows-latest)
    runs-on: windows-latest
    timeout-minutes: 75
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true
      - name: Install (mirrors TESTING.md)
        shell: bash
        run: |
          uv venv --python "3.12"
          uv pip install -e ".[dev,vision,mcp,cli]"
      - name: Put the venv on PATH
        shell: bash
        run: |
          if [ -d .venv/bin ]; then
            echo "$PWD/.venv/bin" >> "$GITHUB_PATH"
          else
            echo "$PWD/.venv/Scripts" >> "$GITHUB_PATH"
          fi
      # Chrome ships with the runner image; Selenium Manager resolves chromedriver
      # on first launch (backends/browsers/chrome.py:39-41). Fail loudly here rather
      # than 299 times below.
      - name: Smoke-test browser + driver
        run: visus doctor
      - name: pytest (full suite, real browsers) + global coverage gate
        run: pytest -q -m "not packaging" --cov-fail-under=90 --cov-report=json
      - name: Per-package coverage floors
        run: python scripts/check_coverage.py
      - name: Upload coverage.json
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: coverage-json
          path: coverage.json
          if-no-files-found: warn
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_ci_workflows.py -v --no-cov`
Expected: PASS, 8 passed.

- [ ] **Step 6: Verify the workflow parses the way GitHub will**

Run: `uv run python -c "import yaml,pathlib; d=yaml.safe_load(pathlib.Path('.github/workflows/ci.yml').read_text(encoding='utf-8')); print(sorted(d['jobs']))"`
Expected: `['browser-tests', 'fast-tests', 'lint', 'packaging-tests']`

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/ci.yml tests/test_ci_workflows.py pyproject.toml
git commit -m "devops(ci): run lint, types and the full test suite on every push"
```

---

### Task 5: Guard the release workflow and assert the wheel's contents (E2)

**Files:**
- Modify: `.github/workflows/publish.yml:7-51`
- Modify: `tests/test_ci_workflows.py` (append)

**Interfaces:**
- Consumes: `.github/workflows/ci.yml` (Task 4) as a reusable workflow; `src/visus/web/skills/visus-web/SKILL.md` (PLAN 1).
- Produces: nothing other plans consume.

**The bug, verified.** `publish.yml:7-10` declares both triggers:

```yaml
on:
  release:
    types: [published]
  workflow_dispatch: # allow a manual run from the Actions tab
```

and neither `build` (`:13-32`) nor `publish` (`:34-51`) carries an `if:`. So **a `workflow_dispatch` from any branch builds that branch and pushes it to PyPI**, with no version bump and no test run. The file's own comment at `:4` — "A plain `git push` does NOT publish — only a published Release does" — describes only half the trigger surface. `playwright-cli/.github/workflows/publish.yml:9` guards exactly this with `if: github.event_name == 'release'`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ci_workflows.py`:

```python
PUBLISH = REPO_ROOT / ".github" / "workflows" / "publish.yml"


def test_every_publish_job_is_guarded_to_a_real_release() -> None:
    jobs = _load(PUBLISH)["jobs"]
    assert jobs, "publish.yml declares no jobs"
    for name, job in jobs.items():
        assert job.get("if") == "github.event_name == 'release'", (
            f"job {name!r} has no release guard — a workflow_dispatch from ANY "
            f"branch would publish that branch to PyPI"
        )


def test_workflow_dispatch_is_still_declared_so_the_guard_is_observable() -> None:
    triggers = _triggers(_load(PUBLISH))
    assert "release" in triggers
    assert "workflow_dispatch" in triggers


def test_build_cannot_run_before_the_ci_gates() -> None:
    jobs = _load(PUBLISH)["jobs"]
    assert jobs["test"]["uses"] == "./.github/workflows/ci.yml"
    assert jobs["build"]["needs"] == ["test"]
    assert jobs["publish"]["needs"] == ["build"]


def test_build_asserts_the_wheel_ships_the_agent_skill() -> None:
    run = _run_text(_load(PUBLISH)["jobs"]["build"])
    assert "visus/web/skills/visus-web/SKILL.md" in run
    assert "visus/web/backends/selenium/js/bundle.js" in run
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ci_workflows.py -v --no-cov`
Expected: 8 passed, 4 failed.
- `test_every_publish_job_is_guarded_to_a_real_release` → `AssertionError: job 'build' has no release guard...`
- `test_build_cannot_run_before_the_ci_gates` → `KeyError: 'test'`
- `test_build_asserts_the_wheel_ships_the_agent_skill` → `AssertionError`
- `test_workflow_dispatch_is_still_declared_so_the_guard_is_observable` passes.

(Exact count: 3 failures if the dispatch test passes as expected.)

- [ ] **Step 3: Rewrite `publish.yml`**

Replace the entire contents of `.github/workflows/publish.yml` with:

```yaml
name: Publish to PyPI

# Publishes to PyPI when you cut a GitHub Release (tag vX.Y.Z).
#
# A plain `git push` does NOT publish. Neither does `workflow_dispatch`: EVERY job
# below is guarded by `if: github.event_name == 'release'`, so a manual run from
# the Actions tab — on any branch — builds nothing and publishes nothing. The
# dispatch trigger is kept only so the guard stays visible and testable.
#
# Nothing is built until the full CI matrix (lint, types, unit, packaging and the
# real-browser suite with both coverage gates) is green on the tagged commit.
#
# Auth is via PyPI Trusted Publishing (OIDC): no tokens, no secrets.

on:
  release:
    types: [published]
  workflow_dispatch: # deliberately inert — see the guard on every job

permissions:
  contents: read

jobs:
  test:
    name: CI gates
    if: github.event_name == 'release'
    uses: ./.github/workflows/ci.yml

  build:
    name: Build distribution
    if: github.event_name == 'release'
    needs: [test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Build sdist + wheel and validate metadata
        run: |
          python -m pip install --upgrade pip build twine
          python -m build
          twine check dist/*

      # `twine check` validates metadata and never opens the wheel's payload.
      # The agent skill lives inside the package directory, so a packaging
      # regression would ship a CLI that cannot install its own skill.
      - name: Assert the wheel ships the agent skill and the runtime data files
        run: |
          python - "$(ls dist/*.whl)" <<'PY'
          import sys, zipfile
          wheel = sys.argv[1]
          names = set(zipfile.ZipFile(wheel).namelist())
          required = [
              "visus/web/skills/visus-web/SKILL.md",
              "visus/web/backends/selenium/js/bundle.js",
              "visus/web/py.typed",
          ]
          print(f"{wheel}: {len(names)} entries")
          for item in required:
              print(("  OK   " if item in names else "  MISS ") + item)
          missing = [item for item in required if item not in names]
          if missing:
              sys.exit(f"wheel is missing required files: {missing}")
          PY

      - uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish:
    name: Publish to PyPI
    if: github.event_name == 'release'
    needs: [build]
    runs-on: ubuntu-latest
    # The environment name MUST match what you set on PyPI's trusted publisher.
    environment:
      name: pypi
      url: https://pypi.org/p/visus-web
    permissions:
      id-token: write # required for OIDC / trusted publishing
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/

      - name: Publish to PyPI
        uses: pypa/gh-action-pypi-publish@release/v1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ci_workflows.py -v --no-cov`
Expected: PASS, 12 passed.

- [ ] **Step 5: Prove the wheel assertion catches a real regression**

Run the same check the workflow runs, against a locally built wheel:

```bash
uv run python -m build --wheel --no-isolation --outdir dist
uv run python -c "import glob,zipfile; n=set(zipfile.ZipFile(sorted(glob.glob('dist/*.whl'))[0]).namelist()); print('visus/web/skills/visus-web/SKILL.md' in n)"
```

Expected: `True` (with PLAN 1 landed). If it prints `False`, PLAN 1's packaging change is not in this checkout — stop and land it first.

Clean up: `rm -rf dist build` (`dist/` and `build/` are already gitignored at `.gitignore:20-21`).

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/publish.yml tests/test_ci_workflows.py
git commit -m "devops(release): guard publishing to real releases and gate it on CI"
```

---

### Task 6: Strict markers, fatal pytest warnings, and the forbid-only guards (row 34)

**Files:**
- Modify: `pyproject.toml:64-75` (`addopts` + new `filterwarnings`)
- Modify: `tests/test_pytest_config.py` (append)
- Create: `tests/test_repo_hygiene.py`

**Interfaces:**
- Consumes: the `addopts` string produced by Task 1, the `packaging` marker from Task 3.
- Produces: nothing other plans consume.

**What "forbid-only equivalent" means here.** `playwright.config.ts:22` in the reference repo sets `forbidOnly: !!process.env.CI` — a guard that fails CI when someone commits a narrowed test run. pytest has no `.only`, so the three real analogues are implemented instead:

1. `--strict-markers` — a typo'd marker (`@pytest.mark.browsr`) becomes an error instead of silently registering and de-selecting the test forever.
2. `--strict-config` — an unknown or misspelled ini key errors instead of being ignored.
3. `tests/test_repo_hygiene.py` — CONVENTIONS forbids `skip`/`xfail`; the guard fails on any *new* one, with the two pre-existing conditional skips named explicitly in an allowlist.

Plus `filterwarnings` promoting pytest's **own** warning classes to errors. Only pytest's own classes are promoted: a blanket `error` would turn third-party `DeprecationWarning`s from selenium/urllib3/onnxruntime into 755 failures for reasons this repo cannot fix.

**Verified pre-conditions** (do not re-derive):
- The only markers applied anywhere in `tests/` are `browser` (300 sites), `parametrize` (7), `timeout` (1) and `skipif` (1) — all registered or builtin, so `--strict-markers` is safe today.
- The only `Test*` classes are `TestValueHolder`, `TestDialog`, `TestDownload` (`tests/test_events.py:11,34,50`) and `TestMouseProperty`, `TestKeyboardProperty` (`tests/test_input_wiring.py:164,200`). **None has an `__init__`**, so no `PytestCollectionWarning` fires today.
- No test function returns a value (verified by AST scan over all 61 test modules).
- `tests/test_e2e_network.py` and `tests/test_mcp_server.py` are saved with a UTF-8 BOM — any test that reads test sources must use `encoding="utf-8-sig"`.

- [ ] **Step 1: Write the failing config assertions**

Append to `tests/test_pytest_config.py`:

```python
def test_markers_and_config_are_strict() -> None:
    addopts = _addopts()
    assert "--strict-markers" in addopts, "a typo'd marker must error, not silently register"
    assert "--strict-config" in addopts, "an unknown ini key must error, not be ignored"


def test_the_packaging_marker_is_registered() -> None:
    markers = _pyproject()["tool"]["pytest"]["ini_options"]["markers"]
    assert any(m.startswith("packaging:") for m in markers)


def test_pytests_own_warnings_are_fatal() -> None:
    filters = _pyproject()["tool"]["pytest"]["ini_options"]["filterwarnings"]
    assert "error::pytest.PytestUnknownMarkWarning" in filters
    assert "error::pytest.PytestCollectionWarning" in filters
    assert not any(f.strip() == "error" for f in filters), (
        "a blanket `error` would fail 755 tests on selenium/urllib3/onnxruntime "
        "deprecations this repo cannot fix"
    )
```

- [ ] **Step 2: Write the failing hygiene test**

Create `tests/test_repo_hygiene.py`:

```python
"""Repo hygiene guards — the pytest equivalents of playwright's `forbidOnly`.

CONVENTIONS for this repo forbid `skip`, `xfail` and mock-to-pass. Two
conditional skips predate that rule and are allowlisted by name with the reason;
anything else is a regression. Separately, a test function that `return`s instead
of asserting is silently useless, so that is scanned for structurally.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS = REPO_ROOT / "tests"
SELF = Path(__file__).name

#: Pre-existing conditional skips. Both run for real when the environment allows.
ALLOWED_SKIPS = {
    # IE-mode needs window focus and hangs the worker under xdist (TESTING.md).
    "test_e2e_edge_ie.py",
    # Firefox is optional in this environment; the test runs the moment it exists.
    "test_e2e_firefox.py",
}

_NEEDLES = ("pytest.skip", "pytest.mark." + "skip", "pytest.mark." + "xfail", "pytest." + "xfail")


def _test_modules() -> list[Path]:
    return sorted(p for p in TESTS.glob("test_*.py") if p.name != SELF)


def test_no_new_skips_or_xfails() -> None:
    offenders: list[str] = []
    for path in _test_modules():
        if path.name in ALLOWED_SKIPS:
            continue
        # Two modules carry a UTF-8 BOM; utf-8-sig reads both forms.
        for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if any(needle in line for needle in _NEEDLES):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "skip/xfail is forbidden — prove the behaviour or delete the test:\n"
        + "\n".join(offenders)
    )


def _direct_return_lines(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[int]:
    """Return statements in the function's OWN body (nested defs/lambdas excluded)."""
    lines: list[int] = []
    stack: list[ast.AST] = list(function.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Return) and node.value is not None:
            lines.append(node.lineno)
        stack.extend(ast.iter_child_nodes(node))
    return lines


def test_no_test_function_returns_a_value() -> None:
    offenders: list[str] = []
    for path in _test_modules():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            for lineno in _direct_return_lines(node):
                offenders.append(f"{path.name}:{lineno}: {node.name} returns a value")
    assert not offenders, (
        "a test that returns instead of asserting proves nothing:\n" + "\n".join(offenders)
    )
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_pytest_config.py tests/test_repo_hygiene.py -v --no-cov`
Expected: the two hygiene tests PASS (the repo is already clean — that is the point of a guard). The three new config tests FAIL:
- `test_markers_and_config_are_strict` → `AssertionError: a typo'd marker must error...`
- `test_pytests_own_warnings_are_fatal` → `KeyError: 'filterwarnings'`
- `test_the_packaging_marker_is_registered` passes if Task 3 has landed.

- [ ] **Step 4: Write the config change**

In `pyproject.toml`, replace the `addopts` line written in Task 1:

```toml
addopts = "-p no:visus_web -n auto --dist loadfile --cov=visus.web --cov-report=term-missing"
```

with:

```toml
addopts = "-p no:visus_web -n auto --dist loadfile --strict-markers --strict-config --cov=visus.web --cov-report=term-missing"
```

Then add, immediately after the `addopts` line:

```toml
# pytest's OWN warnings are defects in this repo, so they are fatal. A blanket
# `error` is NOT used: selenium/urllib3/onnxruntime deprecations would fail 755
# tests for reasons this repo cannot fix.
filterwarnings = [
    "error::pytest.PytestUnknownMarkWarning",
    "error::pytest.PytestCollectionWarning",
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_pytest_config.py tests/test_repo_hygiene.py -v --no-cov`
Expected: PASS, 10 passed.

- [ ] **Step 6: Verify strictness across the whole suite without running it**

Run: `uv run pytest --collect-only -q -n 0 --no-cov`
Expected: ends with `755 tests collected` (exact number may drift as other plans land) and **no** `PytestUnknownMarkWarning`, `PytestCollectionWarning` or `ERROR` lines. Collection exercises every one of the 61 modules, so an unregistered marker or an uncollectable `Test*` class would surface here.

- [ ] **Step 7: Verify a filtered run still passes**

Run: `uv run pytest -q -m "not browser and not packaging" --cov-fail-under=0`
Expected: exits 0.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml tests/test_pytest_config.py tests/test_repo_hygiene.py
git commit -m "chore(test): make markers strict and pytest's own warnings fatal"
```

---

### Task 7: The missing `.pre-commit-config.yaml` (row 32)

**Files:**
- Create: `.pre-commit-config.yaml`
- Modify: `tests/test_repo_hygiene.py` (append)

**Interfaces:**
- Consumes: `pre-commit>=3.5.0`, already declared at `pyproject.toml:34`; `pyyaml` from Task 4.
- Produces: nothing other plans consume.

**The gap:** `pyproject.toml:34` declares `pre-commit>=3.5.0` in `[dev]` and there is no `.pre-commit-config.yaml` anywhere in the repo, so `pre-commit install` fails and the declared dependency is dead weight.

**Design:** every hook is `repo: local` with `language: system`. That means no network clone, no second copy of ruff/mypy with its own version, and — most importantly — the hooks cannot drift from the CI gates, because they invoke the exact same commands. No formatting hook is added: `ruff format` is not currently applied to this codebase and a `--check` hook would fail on arrival.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_repo_hygiene.py`:

```python
import yaml

PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"


def _pre_commit_hooks() -> dict[str, dict[str, object]]:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    return {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}


def test_pre_commit_config_exists() -> None:
    assert PRE_COMMIT.is_file(), (
        "pyproject.toml declares pre-commit in [dev]; without this file "
        "`pre-commit install` fails and the dependency is dead weight"
    )


def test_pre_commit_hooks_are_the_ci_gates_verbatim() -> None:
    hooks = _pre_commit_hooks()
    assert {"ruff", "mypy"} <= set(hooks)
    assert str(hooks["ruff"]["entry"]).startswith("uv run ruff check")
    assert str(hooks["mypy"]["entry"]).startswith("uv run mypy")
    assert hooks["mypy"]["pass_filenames"] is False  # [tool.mypy] packages = ["visus.web"]


def test_pre_commit_hooks_are_local_only() -> None:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    assert [repo["repo"] for repo in config["repos"]] == ["local"], (
        "remote hook repos would need a network clone and could pin a different "
        "ruff/mypy than the CI gates"
    )
```

Move the `import yaml` to the top of the module with the other imports (ruff's `I` rule requires it).

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_repo_hygiene.py -v --no-cov`
Expected: FAIL — `test_pre_commit_config_exists` fails its assertion, the other two raise `FileNotFoundError`.

- [ ] **Step 3: Write the config**

Create `.pre-commit-config.yaml`:

```yaml
# Local-only hooks. Every hook shells out to the exact command CI runs, so
# `pre-commit run --all-files` and the `lint` job in .github/workflows/ci.yml
# cannot disagree, and no hook needs a network clone or a second pinned copy of
# ruff/mypy.
#
# Setup (see TESTING.md):
#   uv venv && uv pip install -e ".[dev,vision,mcp,cli]"
#   uv run pre-commit install
#
# Requires `uv` on PATH.
repos:
  - repo: local
    hooks:
      - id: ruff
        name: ruff check (src, tests, scripts)
        entry: uv run ruff check --force-exclude
        language: system
        types_or: [python, pyi]
        files: ^(src|tests|scripts)/
        require_serial: true

      - id: mypy
        name: mypy --strict (visus.web)
        entry: uv run mypy
        language: system
        types_or: [python, pyi]
        files: ^src/
        # [tool.mypy] packages = ["visus.web"] — mypy selects its own inputs.
        pass_filenames: false
        require_serial: true
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_repo_hygiene.py -v --no-cov`
Expected: PASS, 5 passed.

- [ ] **Step 5: Verify the hooks actually run green**

Run: `uv run pre-commit run --all-files`
Expected:

```
ruff check (src, tests, scripts)..........................................Passed
mypy --strict (visus.web).................................................Passed
```

If `ruff` fails, fix the reported files — the same failure would break the `lint` job in CI.

- [ ] **Step 6: Commit**

```bash
git add .pre-commit-config.yaml tests/test_repo_hygiene.py
git commit -m "chore(dev): add a local-only pre-commit config mirroring the CI gates"
```

---

### Task 8: Dependabot, CONTRIBUTING, SECURITY and the release runbook (row 35)

**Files:**
- Create: `.github/dependabot.yml`
- Create: `CONTRIBUTING.md`
- Create: `SECURITY.md`
- Create: `RELEASING.md`
- Modify: `tests/test_repo_hygiene.py` (append)

**Interfaces:**
- Consumes: the gate commands established in Tasks 1, 2, 4 and 5.
- Produces: nothing other plans consume.

**The gap:** `.github/` contains exactly one file (`workflows/publish.yml`); the repo root has no `CONTRIBUTING.md`, no `SECURITY.md` and no release runbook. `selenium>=4.38,<5` has nothing testing an upgrade. The reference repo carries `.claude/skills/dev/roll.md` (47 lines) and `release.md` (77 lines) for exactly this.

**Placement note:** these files go at the **repo root**, not under `.claude/`. PLAN 1 moves `skills/developing-visus-web/` into `.claude/skills/` and adds `.claude/` to `.gitignore`; putting a runbook there would make it untracked.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_repo_hygiene.py`:

```python
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"

FULL_GATE = (
    "uv run ruff check src tests scripts",
    "uv run mypy",
    "uv run pytest -q --cov-fail-under=90 --cov-report=json",
    "uv run python scripts/check_coverage.py",
)


def test_dependabot_watches_pip_and_github_actions() -> None:
    config = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    assert config["version"] == 2
    ecosystems = {update["package-ecosystem"] for update in config["updates"]}
    assert {"pip", "github-actions"} <= ecosystems


def test_the_repo_hygiene_documents_exist() -> None:
    for name in ("CONTRIBUTING.md", "SECURITY.md", "RELEASING.md"):
        path = REPO_ROOT / name
        assert path.is_file(), f"{name} is missing"
        assert path.read_text(encoding="utf-8").strip(), f"{name} is empty"


def test_contributing_documents_the_full_gate_verbatim() -> None:
    text = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for command in FULL_GATE:
        assert command in text, f"CONTRIBUTING.md does not document `{command}`"


def test_release_runbook_names_both_version_strings() -> None:
    text = (REPO_ROOT / "RELEASING.md").read_text(encoding="utf-8")
    assert "pyproject.toml" in text
    assert "src/visus/web/__init__.py" in text, (
        "the version is duplicated there (line 17) — a release that bumps only "
        "pyproject.toml ships a package whose `visus version` lies"
    )
    assert "workflow_dispatch" in text, "the runbook must state that dispatch does not publish"


def test_security_policy_points_at_a_private_channel() -> None:
    text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "security/advisories/new" in text
    assert "do not open a public issue" in text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_repo_hygiene.py -v --no-cov`
Expected: FAIL — 5 new failures, all `FileNotFoundError` or a missing-file assertion.

- [ ] **Step 3: Create `.github/dependabot.yml`**

```yaml
version: 2

updates:
  # Python dependencies are declared in pyproject.toml (PEP 621 + optional-dependencies).
  # NOTE: `selenium>=4.38,<5` is a range, so Dependabot will only open a PR when a
  # release falls OUTSIDE it. Rolling Selenium within the range is a manual step —
  # see RELEASING.md, "Rolling Selenium".
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
    groups:
      dev-tooling:
        patterns:
          - "pytest*"
          - "ruff"
          - "mypy"
          - "pre-commit"
          - "build"
          - "hatchling"
          - "tomli"
          - "pyyaml"

  # Pinned action majors in ci.yml and publish.yml.
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5
```

- [ ] **Step 4: Create `CONTRIBUTING.md`**

````markdown
# Contributing to visus.web

## Setup

```bash
uv venv && uv pip install -e ".[dev,vision,mcp,cli]"
uv run pre-commit install
```

`[vision]` (RapidOCR + OpenCV) is required for the OCR/image tests; `[mcp]` and `[cli]`
for the MCP/CLI tests. See `TESTING.md` for what the suite covers and how it is split.

## The gate

Everything below must pass before a change is proposed. CI runs the same commands
(`.github/workflows/ci.yml`), so a green local run is a green CI run.

```bash
uv run ruff check src tests scripts
uv run mypy
uv run pytest -q --cov-fail-under=90 --cov-report=json
uv run python scripts/check_coverage.py
```

- The **global** 90% floor lives in `[tool.coverage.report] fail_under` and is passed
  explicitly on the pytest command. It is deliberately *not* in `addopts`: a filtered
  run (`-m "not browser"` selects 456 of 755 tests) can never reach it.
- `scripts/check_coverage.py` adds **per-package** floors from `coverage-floors.json`,
  so `cli/` and `mcp/` — 3,172 of 11,290 lines — cannot rot behind a healthy total.
  Floors ratchet up only: after coverage improves, re-run
  `uv run python scripts/check_coverage.py --freeze` and commit the new numbers.

While iterating on one file, drop the gate but keep the table:

```bash
uv run pytest tests/test_e2e_locators.py -m browser --cov-fail-under=0
```

## How to write a change

**TDD is not optional.** Write the failing test, run it and watch it fail for the right
reason, write the smallest implementation that makes it pass, run it again, commit.

**Real browser, no fakes.** Anything that touches a page is marked `@pytest.mark.browser`
and drives a real headless Chromium against a local fixture page in `tests/fixtures/*.html`,
served by the session-scoped `base_url` fixture in `tests/conftest.py`. A test double may
isolate a unit only when the same behaviour is *also* proven by an integration test.

**No `skip`, no `xfail`, no mock-to-pass.** `tests/test_repo_hygiene.py` enforces this;
the two pre-existing conditional skips are allowlisted there by name with their reason.

**The hidden-engine rule.** No `selenium.*` type may appear in any public signature,
return type, exception or docstring. Selenium imports are allowed only in
`src/visus/web/backends/browsers/*.py`, `src/visus/web/backends/selenium/*.py` and
`src/visus/web/backends/selenium_backend.py`.

## Commits

Small and semantic: `label(scope): description`, where `label` is one of
`fix`, `feat`, `chore`, `docs`, `test`, `devops`.

```
fix(session): invalidate cached field indexes on navigation
```

Never add `Co-Authored-By` trailers.

## Releasing

See `RELEASING.md`.
````

- [ ] **Step 5: Create `SECURITY.md`**

```markdown
# Security Policy

## Supported versions

| Version | Supported |
|---|---|
| 0.2.x   | yes |
| < 0.2   | no  |

## Reporting a vulnerability

Report privately through GitHub Security Advisories:

<https://github.com/botvisus/visus-framework-web/security/advisories/new>

Please **do not open a public issue** for a security problem. Use the
[bug tracker](https://github.com/botvisus/visus-framework-web/issues) only for
non-security defects.

Include: the version, the OS and browser engine, a minimal reproduction, and what an
attacker gains. An acknowledgement is sent within 5 working days.

## Threat model of the session daemon

`visus session start` runs a long-lived daemon that drives a real browser. It is
designed for a single trusted user on one machine:

- The daemon binds **loopback only**, on an ephemeral port.
- Every request must carry a per-session shared token (`secrets.token_hex(16)`),
  written to `.visus/session.json`.
- `.visus/` is in `.gitignore`, so the token is never committed.

Anything that can read `.visus/session.json` can drive the browser: run JavaScript in
the page via `visus eval`, read cookies, take screenshots to an arbitrary path, and
upload local files into a page. Treat that file as a credential. **Never expose the
daemon's port beyond loopback and never run the daemon on a shared or multi-tenant
host.**

Reports about a directory-local token file being readable by the same user are out of
scope; reports about the port being reachable off-host, the token being guessable, or
the token leaking into logs or artifacts are in scope.
```

- [ ] **Step 6: Create `RELEASING.md`**

````markdown
# Releasing visus-web

A release is: bump two version strings, prove the gate is green, tag, and cut a GitHub
Release. `.github/workflows/publish.yml` does the rest through PyPI Trusted Publishing
(OIDC) — there are no tokens and no secrets to manage.

**`workflow_dispatch` does not publish.** Every job in `publish.yml` is guarded by
`if: github.event_name == 'release'`. A manual run from the Actions tab builds nothing.
That guard is the fix for a defect where a dispatch from any branch published that
branch to PyPI, unversioned and untested.

## Steps

1. **Bump the version in BOTH places.** They are duplicated and nothing keeps them in
   sync — a release that bumps only one ships a package whose `visus version` lies.

   - `pyproject.toml` → `[project] version = "X.Y.Z"` (line 7)
   - `src/visus/web/__init__.py` → `__version__ = "X.Y.Z"` (line 17)

   Verify: `uv run python -c "import visus.web; print(visus.web.__version__)"`

2. **Run the full gate locally.** This is the same set CI runs; run it before tagging so
   a red release job is never the first you hear of a problem.

   ```bash
   uv run ruff check src tests scripts
   uv run mypy
   uv run pytest -q --cov-fail-under=90 --cov-report=json
   uv run python scripts/check_coverage.py
   ```

3. **Ratchet the coverage floors if they moved up.** Floors only ever go up.

   ```bash
   uv run python scripts/check_coverage.py --freeze
   git diff coverage-floors.json
   ```

   If nothing improved, discard the diff. If CI's numbers are the authoritative ones,
   download the `coverage-json` artifact from the `browser-tests` job of the latest CI
   run and freeze from it: `uv run python scripts/check_coverage.py --freeze --report <path>`.

4. **Verify the wheel is shippable.** `twine check` only reads metadata; this opens the
   payload, exactly as the `build` job does.

   ```bash
   uv run python -m build --wheel --no-isolation --outdir dist
   uv run python -c "import glob,zipfile; n=set(zipfile.ZipFile(sorted(glob.glob('dist/*.whl'))[0]).namelist()); print([f for f in ('visus/web/skills/visus-web/SKILL.md','visus/web/backends/selenium/js/bundle.js','visus/web/py.typed') if f not in n] or 'OK')"
   ```

   Expected: `OK`. Then remove `dist/` and `build/`.

5. **Commit, tag and push.**

   ```bash
   git add pyproject.toml src/visus/web/__init__.py coverage-floors.json
   git commit -m "chore: mark vX.Y.Z"
   git tag vX.Y.Z
   git push origin main --tags
   ```

6. **Cut the GitHub Release** on tag `vX.Y.Z`. Publishing the Release fires
   `publish.yml`, which runs the whole CI matrix first (`needs: [test]`), then builds,
   asserts the wheel's contents, and uploads to PyPI.

7. **Verify what landed.**

   ```bash
   pip download --no-deps --dest /tmp/vw "visus-web[cli]==X.Y.Z"
   ```

   Then install it into a clean venv and run `visus --help` and `visus version`. The
   `packaging-tests` job already does this against the pre-release wheel on both
   ubuntu-latest and windows-latest.

## Rolling Selenium

`selenium>=4.38,<5` is a range, so Dependabot only files a PR when a release falls
outside it. Rolling *within* the range is manual and worth doing before each release:

1. `uv pip install --upgrade selenium` and note the new version.
2. Run the full gate (step 2 above). The real-browser suite is the actual test of the
   roll — Selenium Manager resolves a matching driver at launch, so a driver-protocol
   regression shows up as browser test failures, not as an import error.
3. Run the Edge IE-mode test serially, since it excludes itself from parallel runs:
   `uv run pytest tests/test_e2e_edge_ie.py -n 0 --no-cov -m browser`
4. If the new version is outside the current cap, widen `dependencies` in
   `pyproject.toml` and say so in the release notes.
5. Commit as `chore: roll selenium to <version>`.
````

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_repo_hygiene.py -v --no-cov`
Expected: PASS, 10 passed.

- [ ] **Step 8: Verify the dependabot file parses**

Run: `uv run python -c "import yaml,pathlib; d=yaml.safe_load(pathlib.Path('.github/dependabot.yml').read_text(encoding='utf-8')); print([u['package-ecosystem'] for u in d['updates']])"`
Expected: `['pip', 'github-actions']`

- [ ] **Step 9: Run the whole non-browser suite one last time**

Run: `uv run pytest -q -m "not browser and not packaging" --cov-fail-under=0`
Expected: exits 0, no failures.

- [ ] **Step 10: Commit**

```bash
git add .github/dependabot.yml CONTRIBUTING.md SECURITY.md RELEASING.md tests/test_repo_hygiene.py
git commit -m "docs(repo): add CONTRIBUTING, SECURITY, RELEASING and dependabot"
```

---

## Done means

- `git push` on a branch triggers `.github/workflows/ci.yml`: ruff + mypy on ubuntu, the
  non-browser suite on 4 OS/Python combinations including `windows-latest` × 3.10, the
  installed-console-script tests on both OSes, and the full 755-test suite with real
  browsers plus both coverage gates on `windows-latest`.
- A `workflow_dispatch` of `publish.yml` from any branch does nothing at all.
- Publishing a GitHub Release runs the whole CI matrix, then builds, then asserts the
  wheel contains `visus/web/skills/visus-web/SKILL.md`, then uploads to PyPI.
- `visus --help` and `visus version` are proven to work from a wheel installed into a
  clean venv on both Linux and Windows, and `visus` without the `[cli]` extra prints a
  message naming `visus-web[cli]` instead of a `ModuleNotFoundError` traceback.
- `uv run pytest -q -m "not browser"` exits 0 instead of failing the coverage gate on
  arrival, and `cli/` or `mcp/` dropping below its frozen floor fails the build even
  when the global total is still above 90%.
