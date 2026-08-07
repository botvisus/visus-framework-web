# Testing visus.web

The test suite is **real-browser-first**: nearly every public method is proven by an integration test that drives a real headless Chromium against local fixture pages (served by an ephemeral `http.server` in `tests/conftest.py`). Pure-logic units (errors, enum, config, exception-translation, selector-step encoding) and the vision module (OCR/image on generated images) are the only non-browser tests. The async-facade wiring also has fast mock tests, but its real behaviour is covered by `tests/test_e2e_async*.py`.

## Setup

```bash
uv venv && uv pip install -e ".[dev,vision,mcp,cli]"
```
`[vision]` (RapidOCR + OpenCV) is required for the OCR/image tests; `[mcp]` and `[cli]` for the MCP/CLI tests.

## Run the suite

The full gate is **two commands**: run the suite to produce a machine-readable
report, then enforce both the global floor and the per-package floors against it.

```bash
uv run pytest -q --cov-fail-under=0 --cov-report=json   # writes coverage.json
uv run python scripts/check_coverage.py                 # enforce global + per-package
```
- Runs in **parallel** via `pytest-xdist` (`-n auto`, `--dist loadfile`).
- `scripts/check_coverage.py` re-reads `[tool.coverage.report] fail_under` from
  `pyproject.toml` as the global floor (the same 90% number `pytest-cov` itself
  would enforce), then re-aggregates `coverage.json` per top-level sub-package of
  `visus.web` (`api`, `async_api`, `backends`, `cli`, `mcp`, `observability`,
  `vision`, plus `_root` for top-level modules) and checks each one against
  `coverage-floors.json`. A single global percentage can hide a weak package
  behind a strong one — `cli/` and `mcp/` alone are roughly 3,200 of ~11,300
  statements — so the per-package floors close that gap. See
  `scripts/check_coverage.py`'s module docstring for the full design, and
  `coverage-floors.json` for the freeze command and current status (it ships
  unmeasured — see that file's `_comment`).
- `pytest`'s own `--cov-fail-under` is passed as `0` above because
  `scripts/check_coverage.py` is the thing enforcing floors now, including the
  same global number. Pass `--cov-fail-under=90` instead and skip the script if
  you only want pytest-cov's old single-number gate.
- A filtered lane (e.g. `-m "not browser"`) can never reach 90% coverage — it
  only exercises part of the code — so it waives *both* gates instead of
  enforcing them:
  ```bash
  uv run pytest -q -m "not browser" --cov-fail-under=0 --cov-report=json
  ```
  This keeps coverage **measured** (the term-missing table still prints, and
  `coverage.json` is still written) without throwing the numbers away, unlike
  `--no-cov`. Do not run `scripts/check_coverage.py` against a filtered-lane
  report — its numbers would be misleadingly low.
- Browser tests are marked `@pytest.mark.browser`.

Run a single file fast — drop coverage entirely:
```bash
uv run pytest tests/test_e2e_locators.py -m browser --no-cov
```
…or keep the coverage table and only waive the gate:
```bash
uv run pytest tests/test_e2e_locators.py -m browser --cov-fail-under=0
```

## The Edge IE-mode test (special)

`tests/test_e2e_edge_ie.py` drives **Edge in IE/Trident mode** via a local `IEDriverServer.exe` (gitignored; set `VISUS_WEB_IE_DRIVER` to its path — the test points to the repo-root copy automatically). Two caveats:

1. **It is headed by necessity** — the IE/Trident engine has **no headless mode** (headless is a Chromium-only feature), so a visible Edge-IE window appears during the test.
2. **It hangs under parallel execution** — IE-mode needs window focus, and other headless browsers running in parallel steal it; the session then blocks in a way neither the launch watchdog nor pytest-timeout can interrupt. The test therefore **skips itself automatically under xdist** (it detects `PYTEST_XDIST_WORKER`). **Run it serially**:
   ```bash
   uv run pytest tests/test_e2e_edge_ie.py -n0 --no-cov -m browser
   ```
3. **Only IEDriverServer 4.0.0 works** — 4.8+ (including the 4.14 Selenium Manager picks by default) hangs forever at `BrowserFactory.cpp Finding window handle for IE Mode on Edge`. `edge_ie.py` pins 4.0.0 via Selenium Manager; a repo-root `IEDriverServer.exe` (gitignored) or `VISUS_WEB_IE_DRIVER` overrides it, `VISUS_WEB_IE_DRIVER_VERSION` re-pins.

## Browsers covered

Chrome and Edge (Chromium) run **headless**. Edge IE-mode runs **headed** (see above). Firefox is supported by the architecture but has no plug-in yet (it is not installed in this environment) — install Firefox and a `backends/browsers/firefox.py` plug-in mirroring `chrome.py` is a few minutes' work, with Firefox-native paths for the Chromium-only RPA bits (full-page screenshot, `pdf`, download-dir).

## Quality gates

```bash
uv run ruff check src tests scripts   # lint (and `ruff format` to format)
uv run mypy                           # strict type-check (visus.web only)
```

`scripts/` holds repo tooling — currently `scripts/check_coverage.py`, the per-package
coverage floors. It is linted by ruff but **not** type-checked: `[tool.mypy] packages =
["visus.web"]` selects mypy's own inputs. Write it fully annotated anyway.
