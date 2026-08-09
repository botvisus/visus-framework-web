# Design — `visus annotate`, human in the loop

> Status: **designed, spike landed**. The spike is `Page.fields_in_box`
> (`src/visus/web/api/page.py`), covered by three browser tests in
> `tests/test_e2e_fields.py`. Nothing else here is implemented yet.

## Problem

An agent that cannot see the screen has to guess which of nine "Submit"-ish
controls the human meant. Every disambiguation channel it has is expensive:
enumerate the fields again, screenshot and describe, ask a question in prose and
hope the reply is unambiguous. The cheapest correction channel is the one that
needs no vocabulary at all — the human points at it.

`playwright-cli` answers this with `show --annotate`
(`playwright-cli/skills/playwright-cli/SKILL.md:401-408`, in the sibling
checkout — prior art, not a file in this repo). The difference is what it costs:
that design needs a dashboard process to host the annotation UI. visus already
owns a **live headed page** and already injects drawing code into it —
`bundle.js` renders the numbered field overlay through
`window.__visus.highlightFields`, positions boxes absolutely at
`z-index:2147483646`, repositions them on scroll and resize, and tears them down
in `clearHighlights`. An annotation canvas is that same channel with the arrow
reversed: instead of visus drawing boxes for the human to read, the human draws
boxes for visus to read.

## Command surface

```
visus annotate [--timeout 120] [--output annotate.png]
```

Blocks until the user presses **Done** or the timeout expires, then returns:

```json
{"screenshot_path": "...",
 "boxes": [{"x": 0, "y": 0, "width": 0, "height": 0, "note": ""}],
 "notes": ["..."],
 "region_snapshot": [{"index": 3, "kind": "button", "name": "Submit"}]}
```

Plus the REPL twin `annotate` and a `README.md` row, per the repo's three-part
mirror rule. Daemon op: `annotate`. It is **not** in `_MUTATING_OPS` — it
observes the page, it does not act on it, so it gets no `### Page` footer.

## Mechanism

A new `window.__visus.annotate(opts)` in `bundle.js`, beside `highlightFields`
and exported from the same `window.__visus` object literal, reusing the existing
absolute-positioning and scroll-reposition code rather than growing a second
copy of it. Two companions: `readAnnotations()` and `endAnnotate()`.

The daemon **polls** `readAnnotations()` until the user is done. Polling rather
than a callback because the daemon speaks JSON-lines request/response over a
socket and has no push channel — a browser-initiated callback has nowhere to
arrive. Poll interval and the `--timeout` ceiling are the only tuning knobs.

## Region snapshot

`Page.fields_in_box(box, *, contained=False)` — **this task's spike, and now
real code**. Called once per drawn rectangle.

What the spike settled, which prose could not:

- A bounding box **can** be turned into a set of elements, cheaply, with no new
  browser primitive: `Field.box` (PLAN 5) already carries viewport geometry for
  every enumerated field, so the mapping is arithmetic, not a DOM query.
- **Intersect is the right default for a hand-drawn box.** A human dragging a
  rectangle around a control routinely clips it by a few pixels; requiring
  containment would silently return nothing, which reads as "visus did not
  understand" rather than "you missed".
- `contained=True` is the quieter answer for a **machine**-drawn box, where the
  coordinates are exact and neighbours are noise.
- Fields with no measurable box (`display:none`, zero-size) are never returned,
  so the answer cannot contain something the human could not have been pointing
  at.

## Risks

| Risk | Mitigation |
|---|---|
| A headless session has nothing to draw on. | `annotate` fails fast, and the message names the fix: start the session **without** `--headless`. |
| The overlay injects nodes into `body`, exactly as `list-fields` does — so a screenshot taken *while* annotating is polluted with visus's own UI. | Take the screenshot **before** injecting the overlay. The returned `screenshot_path` is then the page as the human saw it, not as visus decorated it. |
| There is no human in CI, so the feature looks untestable. | `page.mouse.move/down/up` synthesises the drag. The acceptance test drives the real event path, so what CI exercises is what a human triggers. |
| A navigation during annotation destroys the overlay. | Detect via the page URL and return what was collected so far, rather than failing or hanging until the timeout. |

## Acceptance criteria

- `visus annotate` on a headed session returns within the timeout with a JSON
  payload containing all four keys.
- A synthesised `page.mouse` drag over a known field produces one box whose
  `region_snapshot` contains that field's index.
- `visus annotate` against a headless session exits 1 naming the fix.
- The overlay leaves the DOM byte-identical after `endAnnotate()` — assert
  `document.querySelectorAll('[data-visus-annotate]').length == 0`.
- `visus list-fields` immediately afterwards returns the same indexes it
  returned before.

## Not in scope

- The multi-session dashboard — see `docs/design/session-dashboard.md`.
- Freehand drawing. Rectangles are enough to name a region.
- Annotating a video frame — see `docs/design/video-screencast.md`.
