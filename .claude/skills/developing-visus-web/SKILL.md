---
name: developing-visus-web
description: Use when extending or contributing to the visus.web library itself — adding a get_by_* locator, an action, an assertion matcher, a browser plug-in, an MCP tool, or a CLI command. Covers the engine-hidden architecture (api wrappers over delegate Protocols, Selenium confined to the backend), the clean-room injected JS bundle, the actionability / expect / frame-aware resolver internals, and the real-browser test conventions (no fakes, xdist, mypy --strict, coverage gate).
---

# Developing visus.web

## Architecture in one picture

```
visus.web (public)        api/ wrappers hold a *Delegate Protocol — NEVER a selenium object
  launch()  ─► Browser ─► Context ─► Page ─► Locator / FrameLocator
                              │                 expect(locator) ─► LocatorAssertions
                              ▼
                         backends/base.py     Protocols: Backend, BrowserDelegate,
                                              ContextDelegate, PageDelegate + BrowserConfig
                              ▼
                         backends/selenium_backend.py     driver lifecycle (launch/dispose)
                         backends/selenium/
                            driver_delegate.py   SeleniumPage/ContextDelegate (the only place
                                                 selenium WebElements live)
                            resolver.py          frame-aware element resolution (shared)
                            actionability.py     deadline+backoff auto-wait loop (actions)
                            expect_engine.py     auto-retry assertion poll loop
                            js/bundle.js         OUR clean-room injected engine (window.__visus)
                         backends/browsers/      per-browser option/service/driver factories
```

**THE HIDDEN-ENGINE RULE (inviolable):** no `selenium.*` type may appear in any public signature, return, exception, or docstring. "Public" = `src/visus/web/__init__.py` and everything under `src/visus/web/api/`. Selenium imports are allowed ONLY in `backends/browsers/*.py`, `backends/selenium/*.py`, and `backends/selenium_backend.py`. Selenium exceptions are translated to `visus.web.errors` via `driver_delegate.translate_exc`. Verify with: no `selenium` import resolves inside `api/` or `__init__.py`.

## How resolution works

A `Locator` is `{delegate, steps, defaults}` where `steps` is an immutable tuple of JSON-able dicts (`{"kind":"role"|"text"|"css"|"xpath"|"label"|"placeholder"|"testid"|"alt"|"title"|"filter_has_text"|"nth"|"frame", ...}`). Builders append a step and return a NEW Locator. To act/read, the Locator JSON-encodes its steps and calls a delegate method; `resolver.resolve_elements(driver, ensure_bundle, selector_json)` runs `window.__visus.queryAll(steps)` in JS — re-injecting the bundle and `switch_to.frame`-ing for any `frame` steps (idempotent: it restarts from `default_content`; `_activate()` resets the frame context each op). Strict single-element ops use `resolver.resolve_strict`.

The clean-room `bundle.js` (`window.__visus`) is OUR code (NOT Playwright). It computes ARIA `role`, `accessibleName` (a subset of the W3C ACCNAME algorithm), normalized-text matching, `elementState` (visible/hidden/enabled/disabled/editable/checked), `checkStable` (RAF), `hitTarget`, `clickablePoint`, and `snapshot`. Extend it for new selector kinds / states.

## Recipes

### Add a `get_by_*` locator
1. `bundle.js`: add a matcher + a `queryAll` branch for the new `{"kind": ...}` step (see the `label`/`placeholder` branches).
2. `api/locator.py`: add a builder returning `self._child({"kind": ..., ...})`. Add a `Page` entry point mirroring `get_by_role`. Add to `FrameLocator` too.
3. Add a real-browser test against a fixture in `tests/`.

### Add an action (auto-waited)
1. `actionability.py`: add the action name to `_ACTION_STATES` (its required states) and, if it's pointer-like, to `_POINTER_ACTIONS`.
2. `backends/base.py`: add `locator_<action>` to `PageDelegate`. `driver_delegate.py`: implement it — call `run_action(self._driver, selector, "<name>", timeout_ms=..., force=..., dispatch=<callback>, ensure_bundle=self._ensure_bundle)`; the dispatch performs the real Selenium op (`ActionChains`, `Select`, `send_keys`, JS).
3. `api/locator.py`: add the public method (use `self._t(timeout)` for the default).
4. Update fake delegates in `tests/test_backend_protocols.py`. Add a real-browser behavior test (assert a real DOM effect; use a 250–700ms `setTimeout` in the fixture to prove the auto-wait path).

### Add an assertion matcher
1. `expect_engine.py` `_evaluate`: add a branch returning `(matches, received)`.
2. `api/assertions.py`: add `to_*` on `LocatorAssertions` calling `self._poll("<matcher>", arg, timeout)`. Negation via `.not_` is automatic (`matches != is_not`).
3. Add a real-browser test where the condition flips after a delay (proves auto-retry) + a failure case asserting `AssertionError`.

### Add a browser plug-in (Firefox/Edge/…)
1. `backends/browsers/<engine>.py`: `build_options/build_service/build_driver` (mirror `chrome.py`).
2. `registry.py`: map the `Engine` member to a `BrowserConfig`.
3. Real-browser smoke test under that engine if available in CI.

### Add an MCP tool
`src/visus/web/mcp/server.py`: a `@mcp.tool()` thin wrapper over the public API, targeting via the shared `make_locator(page, *, selector=, role=, name=, text=, exact=, frame=)` helper (`mcp/session.py:142-160`; **keyword-only** after `page`). Add the name to `_EXPECTED_TOOLS` in `tests/test_mcp_server.py` and drive the tool in `tests/test_e2e_mcp.py`.

### Add a CLI command

There are two kinds of command, and only the first is a one-file change.

**Daemon-free command** — 11 of the 54 registered commands: `version`, `translate`,
`doctor`, `install`, `install-skills`, `screenshot`, `pdf`, `open`, `run`, `mcp`,
`codegen`. These launch (at most) their own throwaway browser and never talk to the
session daemon. For these, `src/visus/web/cli/main.py` really is the whole change:
an `@app.command()` Typer function over the public API. Test with
`typer.testing.CliRunner` (real browser for the browser-touching ones).

**Session command** — the other 43. It drives the running daemon (started by
`visus session start`) instead of launching its own browser. Following only the
one-file recipe above for one of these ships a command that always fails at
runtime with `error: ValueError: unknown op '<name>'`, because nothing ever
answers the dispatch in step 1. Places to touch, in the order you'll hit them:

1. **`src/visus/web/cli/session_server.py`** — a `_op_<name>(self, args)` method.
   `SessionHandler.handle()` dispatches with `getattr(self, f"_op_{op}", None)`
   and raises `unknown op '<name>'` if it's missing — this is the one contributors
   skip, and it's the only one that fails silently at authoring time (ruff/mypy
   are clean; it only breaks when someone runs the command). Required.
2. **`src/visus/web/cli/main.py`** — an `@app.command()` that sends the op via
   `_send("<name>", args)`, never talking to the daemon directly. Required (this
   is the one place the old recipe named).
3. **`src/visus/web/skills/visus-web/references/cli-commands.md`** — a row in the
   matching table. `tests/test_skill_docs.py::test_every_cli_command_is_documented`
   walks `app.registered_commands` and fails, listing anything undocumented here.
   Required to pass the build.
4. **`README.md`**'s CLI command tables — a row in the matching table. Not
   test-gated (no test reads `README.md`), but it's the first thing a human
   reads; keep it in sync by hand.
5. **`src/visus/web/cli/console.py`** — a `dispatch()` branch plus a line in
   `_HELP`, so the interactive REPL can reach it too. Nice-to-have, not
   required: the REPL is a convenience wrapper over the same `_send`, and it is
   currently *incomplete* on purpose/by-omission — `drag`, `upload`,
   `add-cookies`, `clear-cookies`, `read-text`, `solve-captcha`, and
   `find-image` all ship as working CLI commands with no `console.py` branch at
   all. Add one when it's cheap; don't treat its absence as broken.

Test the `_op_*` handler with a real-browser test, and the CLI command with
`typer.testing.CliRunner` asserting the exact op name and payload sent to the
daemon (pattern: `tests/test_cli_session.py:1152-1642`).

## Test conventions (enforced)

- **Real browser, no fakes.** Coverage is driven by real-browser integration tests (`@pytest.mark.browser`) against local fixture pages in `tests/fixtures/`, served by the session-scoped `base_url` fixture (an ephemeral `http.server`). Pure-logic units (errors/enum/config/exception-translation/step-encoding/vision-on-generated-images) are the only non-browser tests. Test doubles isolate a unit ONLY when its real behavior is also covered by an integration test — never as the sole proof of a feature. No `skip`/`xfail`/mock-to-pass.
- **Parallel:** the suite runs under `pytest-xdist` (`-n auto`, `--dist loadfile`). Run a subset with `--no-cov` (the `--cov-fail-under=90` gate only makes sense on the full run).
- **Gates:** `uv run ruff check src tests`, `uv run mypy` (`--strict`, no weakening — cast `execute_script`/CDP `Any` returns; selenium types only inside backend files), `uv run pytest -q` (≥90% coverage on `visus.web`).
- **Commits:** small, TDD (failing test → minimal impl → green → commit).

### Change the shipped agent skill

The skill lives at `src/visus/web/skills/visus-web/` and ships inside the wheel.
Its frontmatter `version` must equal `visus.web.__version__` — bump both together.
`tests/test_skill_docs.py` gates command coverage, the MCP tool count, and link
integrity. The contributor guide you are reading is **not** shipped; it lives in
`.claude/skills/developing-visus-web/`.

## Layout & build
`src/`-layout namespace package (`visus.web`; no `src/visus/__init__.py`). Build: `uv` + `hatchling`. Optional extras: `[dev]`, `[vision]` (rapidocr/opencv/pillow/numpy), `[mcp]` (mcp), `[cli]` (typer + rich + click). Entry points: `visus`, `visus-web-mcp`.
