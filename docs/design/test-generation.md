# Design — test generation as a first-class flow

> Status: **designed, spike landed**. The spike is `codegen.generate_test`
> (`src/visus/web/cli/codegen.py`), covered by five tests in
> `tests/test_codegen.py`. The `--as-test` flag, the spec format, `visus attach`
> and the heal loop are **not** implemented.

## Problem

`codegen.py` emitted `from visus.web import launch` followed by
`with launch(headless=False)` — no test function, no fixtures, no assertions.
That is D14/D15.

The sting is that `pytest_plugin.py` has been shipping a ready `visus_page`
fixture — isolated context, on-failure screenshots, `--visus-engine` /
`--visus-headed` options — to **every installed user** through the `pytest11`
entry point the whole time. The generator and the test harness had simply never
been introduced to each other.

The opportunity is bigger than parity. Combined with the single-file HTML report
(Task 8), visus gets something the prior art does not have: test generation
**with a report of the heal run**, attachable to the PR that fixes the test.

## What the spike settled

**Yes — the recorded event stream is enough.** `generate_test` emits a valid,
collectable pytest test from the events `generate_line` already produces, with
no new browser-side capture. Three findings worth recording:

- The `launch()` scaffolding is not merely unnecessary, it is **wrong** in a
  test: the fixture owns the browser lifetime, and a generated `launch()` would
  quietly opt out of the isolation and the failure screenshots the user already
  paid for. The test asserts `"launch(" not in code`.
- Assertions cannot be generated. The recorder knows what happened; only the
  author knows what was supposed to be *proved*. So `expectations` are pasted
  verbatim, and the spec file (below) is where they come from.
- Every generated file is `compile()`d in the tests. A generator whose output is
  merely plausible is worthless — the free syntax check is the cheapest possible
  guard against a quoting bug in the emitter.

## Plan → generate → heal

| Phase | playwright-cli | visus |
|---|---|---|
| Explore | `attach tw-XXXX`, `snapshot`, `click e5` | `visus session start`, `visus list-fields`, `visus click 3` |
| Capture code | `# Ran Playwright code:` blocks | PLAN 4's `### Code` block after every action |
| Capture assertion | `--raw snapshot [ref]`, `--raw eval` | `visus --raw snapshot [TARGET]`, `visus --raw get-text` |
| Emit test | copy TypeScript into a `.spec.ts` | `visus codegen --as-test -o tests/test_login.py` |
| Diagnose | `snapshot` + `console` + `requests` | `visus snapshot` + `visus logs` + `visus requests` |
| Report | *(none)* | `visus tracing-stop --report heal.html` |

## Spec file format

`specs/<feature>.plan.md`, mirroring the prior art:

```markdown
# <Feature>

## Application Overview
<what the app does, in two sentences>

### 1. <Scenario group>

**Seed:** <the state every scenario in this group starts from>
**File:** tests/test_<kebab-case-scenario>.py

**Steps:**
- navigate to /login
- fill Username with "student"
- click Submit
- expect: page URL matches *dashboard*
- expect: heading contains "Welcome"
```

Four rules that matter:

1. **One test per file.** A heal loop reruns one test; a file with five tests
   reruns five.
2. **Kebab-case scenario names matching the file name**, so a failure names its
   own file.
3. **Scenarios independent from the seed state** — each must pass when run alone.
4. **`- expect:` bullets become the `expectations` argument** of
   `generate_test`, verbatim. That is the whole reason the parameter takes raw
   source lines rather than a structure.

## Seed

The visus equivalent of `tests/seed.spec.ts` is a `conftest.py` fixture wrapping
the packaged one:

```python
import pytest

@pytest.fixture()
def seeded_page(visus_page):
    visus_page.goto("https://app.example.com/login")
    visus_page.get_by_role("textbox", name="Username").fill("student")
    visus_page.get_by_role("button", name="Sign in").click()
    return visus_page
```

Generated tests then take `fixture="seeded_page"` and start from a known state.

## `visus attach <test-id>` — the honest finding

**visus has no `--debug=cli` equivalent, and this design does not pretend
otherwise.** `pytest_plugin.py` calls `launch()` directly and never registers
with the session daemon, so there is nothing to attach *to*. The prior art's
whole mechanism (`playwright test --debug=cli` → `attach tw-XXXX` → `resume`)
has no counterpart here today.

Proposal, in dependency order:

1. A `visus_paused_page` fixture that writes `.visus/sessions/<test-id>.json`
   describing its live driver, then blocks on a file/socket signal.
2. `visus attach <test-id>` pointing the CLI client at that session.
3. `visus resume` releasing the block.

**Recorded risk:** reaching another process's WebDriver session means
reconnecting to the driver's HTTP endpoint by session id. That is engine-level
work under `backends/selenium/`, and it must not leak a `selenium.*` type past
that boundary — the hidden-engine rule is inviolable, and this is exactly the
kind of feature that tempts an exception.

## Heal loop

The diagnostic triad: `visus snapshot` (what is on the page), `visus logs` (what
the page complained about), `visus requests` (what the API actually returned).

**Fix one thing at a time and rerun after each.** Batched fixes make it
impossible to say which one worked.

Spec reconciliation, as a decision tree:

- **Purely technical** (a selector moved, a timing race) → fix the test, leave
  the spec alone.
- **User-visible change** (a step disappeared, a label changed) → update the
  spec too; it is now wrong.
- **Unclear** → **stop and ask**, quoting the scenario id, the stale spec lines,
  and the observed behaviour. Guessing here silently rewrites the requirement.

Escalation: the visus equivalent of `test.fixme` is
`@pytest.mark.xfail(strict=True, reason="<link to the user's decision>")` in the
**generated user test suite**. That does not relax this repository's own
no-`xfail` rule — different codebase, different contract. `strict=True` matters:
a non-strict xfail that starts passing stays silent.

## Acceptance criteria

- `visus codegen --as-test -o tests/test_x.py <url>` writes a file that
  `pytest --collect-only` collects as exactly one test.
- The generated file imports `expect` and takes `visus_page`, and contains no
  `launch(`.
- Running the generated test against the recorded app passes.
- `visus tracing-start` before a heal run and `visus tracing-stop --report
  heal.html` after produce a report whose timeline contains the failing step and
  its ARIA snapshot.
- A **new** skill reference
  `src/visus/web/skills/visus-web/references/test-generation.md` ships inside the
  packaged skill and names the six commands in the table above. (Basename
  collision warning: that is a file to be created in **this** repo, not the
  `playwright-cli` reference of the same name.)

## Not in scope

- Generating async tests.
- Generating page objects.
- Multi-scenario parallel generation.
