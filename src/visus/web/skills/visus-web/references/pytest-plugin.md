# The pytest plugin

Installing `visus-web` registers a pytest plugin automatically — no `conftest.py`
wiring needed.

```python
from visus.web import expect

def test_login(visus_page):
    visus_page.goto("https://example.com/login")
    visus_page.get_by_label("Email").fill("ada@example.com")
    visus_page.get_by_role("button", name="Sign in").click()
    expect(visus_page.get_by_text("Welcome")).to_be_visible()
```

| Fixture | Scope | What you get |
|---|---|---|
| `visus_browser` | session | a launched browser |
| `visus_context` | function | a fresh context |
| `visus_page` | function | a fresh page, screenshotted on failure |

```bash
pytest --visus-engine edge --visus-headed --visus-output ./artifacts
```

## How it registers

`pyproject.toml` declares it as a `pytest11` entry point
(`visus_web = "visus.web.pytest_plugin"`) — any project that installs
`visus-web` gets `visus_browser` / `visus_context` / `visus_page` for free the
moment `pytest` runs, no import or fixture wiring required.

## What each fixture does

- `visus_browser` (session-scoped) — one browser launched with
  `--visus-engine` (default `chrome`) and headless unless `--visus-headed` is
  passed; closed once at the end of the session.
- `visus_context` (function-scoped) — a fresh, isolated `Context` per test
  (own cookies/storage), closed after the test.
- `visus_page` (function-scoped) — a fresh `Page` on that context. If the test
  fails, a screenshot is saved to `--visus-output` (default `visus-results/`)
  as `<sanitized-nodeid>.png`; a screenshot failure (e.g. a dead page) is
  swallowed so it never masks the real test failure.

Soft assertions (`expect.soft(...)`) are verified automatically at the end of
each test's call phase — `verify_soft()` runs in a `pytest_runtest_call`
hookwrapper, so a collected soft failure fails the test itself (not just
teardown), and any leftovers are drained silently if the test already failed
on its own.

## Why this repo's own suite disables it

`visus-framework-web`'s own `pyproject.toml` sets
`addopts = "-p no:visus_web ..."`. That is a coverage-measurement detail
specific to *this* repository — its own `pytest11` entry point would import
`visus.web` before `pytest-cov` starts measuring, zeroing out import-time
coverage of the library it ships. It does not apply to a project that merely
*depends on* `visus-web`; there the plugin should stay enabled.
