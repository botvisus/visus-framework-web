# Design — ARIA-snapshot assertions

> Status: **designed, spike landed**. The spike is
> `PageAssertions.to_match_aria_snapshot` (`src/visus/web/api/assertions.py`),
> covered by four browser tests in `tests/test_e2e_expect.py`. The locator-level
> matcher and the CLI surface below are **not** implemented.

## Problem

`LocatorAssertions` lists 21 matchers and none of them is
`to_match_aria_snapshot`; `PageAssertions` had exactly two, `to_have_url` and
`to_have_title`. That is D13.

What makes it sharp is that the **capture side already exists twice**: the
`Recorder` captures an ARIA snapshot on every failure
(`observability/recorder.py`) and the report renders it
(`observability/report.py`). The data was already flowing, and there was no way
to assert on it — so a broken accessibility tree was *observable after the fact*
and not *preventable*.

It also broke the loop the prior art prescribes: capture the expected snapshot,
then assert it
(`playwright-cli/skills/playwright-cli/references/test-generation.md:110-116`,
sibling checkout — not this repo). visus could capture (PLAN 4's scoped
`visus snapshot <target>`) and could not assert.

## Semantics chosen

**Subsequence match over the flat `[{role, name, depth}]` list — not tree
equality.** This was the open question, and the spike settled it. Three reasons,
in order of weight:

1. **`page.snapshot()` is flat.** The bundle emits a list with a `depth` integer,
   not a nested tree. Tree equality would require inventing a nesting model the
   browser side does not produce — a large, speculative change made *before*
   anyone had used the matcher.
2. **Partial matching is what the workflow needs.** The prior art states it
   directly: the snapshot to be matched "does not have to contain all the
   information". An assertion listing every row on the page is unreadable and
   breaks on any unrelated addition.
3. **Order carries real signal; completeness does not.** A reordered navigation
   bar is a regression worth failing on. An extra footer link is not. A
   subsequence match encodes exactly that asymmetry.

`name` accepts a compiled regex, because the values that break these assertions
in practice are counts and timestamps.

## Locator scope

The spike implements the **page-level** matcher only, and that is deliberate.

`LocatorAssertions._poll` routes through the delegate's `expect_poll` matcher
engine, so a locator-level matcher is not a Python-side addition: it means a new
matcher name inside that engine, on both the sync and the async paths. That is a
bigger change than the question being answered here justified.

**Recommendation for implementation:** add `"aria_snapshot"` to `expect_poll` and
have `LocatorAssertions.to_match_aria_snapshot` delegate to it. Until then,
`PageAssertions`' `selector=` form is the answer for a region, and the spike
proves it works.

## Capture-to-assertion loop

```bash
visus --json snapshot > expected.json          # whole page
visus --json snapshot "#main" > region.json    # one region
```

`--json` only, not `--raw --json`. PLAN 4's `set_mode` makes `--json` win when
both are given, so `--raw --json` would be a confusing no-op on `--raw`. `--json`
is the machine-readable form; `--raw` is the shell-capture form.

The generated assertion:

```python
expect(page).to_match_aria_snapshot(json.load(open("region.json")), selector="#main")
```

## CLI surface

```
visus expect-snapshot <file.json> [TARGET] [--timeout]
```

Returns `PASSED` / `FAILED: <detail>` exactly like `visus expect-text`, which is
already the repo's convention for an assertion command: it reports a verdict and
never raises to the shell, so a script can branch on the text without trapping an
exit code. Daemon op `expect_snapshot`, the REPL twin, and a `README.md` row.

## Acceptance criteria

- `expect(page).to_match_aria_snapshot(rows)` passes on a matching page and
  raises with `last received` on a mismatch.
- A regex `name` matches an unstable value.
- Reordering the expected rows fails.
- `selector=` excludes everything outside the region.
- `visus expect-snapshot` prints `PASSED` / `FAILED: …` and never raises to the
  shell.
- The async mirror exposes the same matcher — the README calls `async_api` "a
  100% mirror of the sync surface", and `test_async_surface_covers_sync` enforces
  it.

## Not in scope

- YAML snapshot files. JSON is what `visus snapshot` already emits.
- `toMatchAriaSnapshot`'s auto-update-on-failure behaviour. A matcher that
  rewrites the expectation it just failed is a footgun in a review-based
  workflow.
