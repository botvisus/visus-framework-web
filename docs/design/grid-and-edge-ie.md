# Design — `edge_ie` and Selenium Grid as the enterprise wedge

> Status: **designed, spike landed**. The spike is `visus doctor --engine
> --remote-url --headed/--headless` (`src/visus/web/cli/main.py`), covered by
> four tests in `tests/test_cli.py`. The CI Grid lane, the enterprise skill page
> and the README engine row are **not** implemented.

## Why this is the wedge

Playwright's engine list is chromium / firefox / webkit / chrome / msedge. There
is **no IE mode among them**, so a Playwright-based competitor cannot bid on an
IE-mode application at any price. visus can: `Engine.EDGE_IE` drives Edge's
Trident engine through IEDriverServer with `attach_to_edge_chrome`, pins the
driver to 4.0.0 because 4.8+ hangs forever on modern Edge, aligns the Windows
registry itself where it can, and turns a hang into an actionable message with a
45-second watchdog.

Combined with the single-file HTML report (Task 8), the offer becomes concrete:
*we run your legacy app on your Grid and hand you an auditable artifact per run.*

## What the spike settled

The open question was **what a Grid or IE-mode failure looks like to the person
hitting it** — because a wedge nobody can debug is not a wedge.

Before: an unreachable Grid surfaced as a raw Selenium connection error through
`main.py`'s `_send` funnel, and an IE-mode misconfiguration took 45 seconds to
say anything at all.

After: `doctor` names the engine, the endpoint and up to three likely causes, and
never emits a traceback. Two specifics worth keeping:

- **`--engine edge_ie --headless` fails in milliseconds**, not after the launch
  watchdog. IE mode has no headless driver, so waiting 45 seconds to discover a
  statically-knowable fact is pure waste.
- **The IE-mode branch asks the registry first.** If `ie_mode_enabled()` is
  false, the message is the preflight's own `admin_hint()`; if it is true, the
  advice is different (close every Edge window, pin the driver version). One
  generic "IE mode failed" would have been useless in both cases.

## Command surface

- `visus session start --engine edge_ie --remote-url <grid>` — the flags are
  PLAN 5's; this design covers the **combination**.
- `visus doctor --engine <e> [--remote-url <url>] [--headed]` — this task's spike.
- `visus install --engine edge_ie` — pre-fetch the pinned IEDriverServer.

## The IE-mode contract

Extracted from the code so it stops living only in comments:

| Fact | Where it comes from |
|---|---|
| IE mode is **always headed** and ignores `headless` / `download_dir` / `user_data_dir`. | `backends/browsers/edge_ie.py`, `build_options` |
| IEDriverServer is pinned to **4.0.0**; 4.8+ hangs at "Finding window handle for IE Mode on Edge". | `edge_ie.py`, resolved in `build_service` |
| `VISUS_WEB_IE_DRIVER` overrides the driver path (air-gapped machines). | `edge_ie.py` |
| `VISUS_WEB_IE_DRIVER_VERSION` overrides the pin. | `edge_ie.py` |
| `VISUS_WEB_EDGE_BINARY` overrides the Edge path. | `edge_ie.py` |
| `VISUS_WEB_IE_TIMEOUT` overrides the 45 s watchdog. | `edge_ie.py` |
| The preflight equalises IE zone `2500` across zones 0–4 under **HKCU, no admin**. | `_ie_preflight._equalize_protected_mode` |
| Only the Edge **policy** needs elevation. | `_ie_preflight._try_enable_ie_mode` |

## Grid node preparation

`_ie_preflight.ensure()` writes the **local** registry, and a Grid node is not
local. The node must be:

- Windows,
- **headed** — a real interactive session, not a service,
- have the Edge IE-mode policy enabled,
- expose `edge_ie` capabilities.

The consequence, stated once: **on a Grid, IE-mode preflight is an operator task,
not something visus can do for you** — and `visus doctor --remote-url --engine
edge_ie` must say exactly that rather than implying it can fix it remotely.

## Test strategy

`tests/test_e2e_edge_ie.py` already documents the constraint: IE mode opens a
real headed window, is focus- and zone-sensitive, and reliably hangs an xdist
worker — so it runs standalone with `-n 0`.

Proposal:

1. **Keep that test as the local gate**, unchanged.
2. **A `VISUS_WEB_GRID_URL`-driven Grid lane in CI** running the *chrome* engine
   against a `selenium/standalone-chrome` service container. A real,
   always-available Grid — no conditional skipping, because a lane that skips
   itself proves nothing.
3. **An `edge_ie` lane on a self-hosted Windows runner** — out of scope for this
   repository's CI until such a runner exists. Saying so is better than a
   permanently-skipped job.

## Documentation gap

`edge_ie` appears in **no** README command table and in **no** skill file, while
the packaged skill already promises "broad browser/Grid/IE-mode compatibility".
The fix: one row in the engines table, plus a new
`src/visus/web/skills/visus-web/references/enterprise.md` page in the packaged
skill.

## Acceptance criteria

- `visus doctor --remote-url <unreachable>` exits 1 with the URL, no traceback
  and three named causes.
- `visus doctor --engine edge_ie --headless` fails in under a second.
- `visus session start --remote-url <grid> --engine chrome` against a
  `selenium/standalone-chrome` container drives `goto` / `list-fields` / `click` /
  `expect-text` end to end in CI.
- `visus session start --remote-url <grid> --engine edge_ie` against a prepared
  Windows node reaches `page.title()`, and against an unprepared one fails within
  the watchdog naming the node-preparation step.
- `README.md` and the packaged skill both name `edge_ie`.

## Not in scope

- Provisioning Grid nodes.
- Selenium Grid's own configuration.
- BrowserStack / SauceLabs endpoints — they are `remote_url` values and need no
  code.
