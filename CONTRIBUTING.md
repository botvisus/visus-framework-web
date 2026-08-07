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
  run (`-m "not browser"` selects most, but not all, of the suite) can never reach it.
- `scripts/check_coverage.py` adds **per-package** floors from `coverage-floors.json`,
  so `cli/` and `mcp/` — roughly 3,200 of 11,300 lines — cannot rot behind a healthy
  total. Floors ratchet up only: after coverage improves, re-run
  `uv run python scripts/check_coverage.py --freeze` and commit the new numbers.

While iterating on one file, drop the gate but keep the table:

```bash
uv run pytest tests/test_e2e_locators.py -m browser --cov-fail-under=0
```

The suite runs under `pytest-xdist` and takes roughly 15 minutes end to end with the
real-browser lane (currently 965+ collected items — it grows, so treat any specific
count as a snapshot, not a target); markers are `browser` and `packaging`.

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
