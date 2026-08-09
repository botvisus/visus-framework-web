# Design — run video

> Status: **designed, spike landed**. The spike is
> `visus.web.observability.video` (`capture_frames`, `cdp_screencast_available`),
> covered by two browser tests in `tests/test_e2e_observability.py`, plus the
> `[video]` extra in `pyproject.toml`. The commands, chapters and assembly below
> are **not** implemented.

## Priority

This is the **lowest-priority** Tier 3 item and is explicitly sequenced after
items 1–3 (the unified dispatcher, index targeting on MCP, observability). The
reason is not scheduling convenience: the single-file HTML report already embeds
a screenshot **per step**, so video adds *continuity*, not *evidence*. The report
is what wins deals; video without it wins nothing. Build it when items 1–3 are
paying for themselves, not before.

## The spike's finding

**`cdp_screencast_available()` returns `False` on this machine's Chrome, and v1
therefore uses screenshot polling.**

The reason in one sentence: CDP's `Page.startScreencast` delivers frames as
`Page.screencastFrame` **events**, and the synchronous CDP bridge this project
uses everywhere (`driver.execute_cdp_cmd`) issues a command and reads its return
value — it has **no event subscription**, so the command is accepted and the
frames go nowhere.

This mattered before anything was designed on top: if frames could not arrive at
all, the whole feature had to be built on polling, and that changes the cost
model, the API and the fps ceiling. Now it is a recorded fact rather than an
assumption.

**What would change the decision:** a Selenium release exposing a CDP event
queue, or moving to a websocket CDP client under `backends/selenium/` — which
already exists in this repo for a different purpose (`cdp_fetch.py`, PLAN 6
Task 5, drives `Fetch.requestPaused` over its own DevTools socket). That is the
strongest argument that the migration is feasible: the hard part is already
written and proven.

A second finding, from making the spike test honest: a `data:` URL
percent-**decodes**, so a JS modulo written as `%240` silently becomes `$0` and
the script never runs. The first version of the test captured six identical
frames and would have "passed" a weaker assertion. `len(set(frames)) >= 2` is
what caught it.

## Command surface

```
visus video start [--fps 5]
visus video chapter "<label>"
visus video stop -o run.webm
```

Daemon ops `video_start` / `video_chapter` / `video_stop`, the REPL twins, and
README rows. Chapters and action overlays reuse the `window.__visus` injection
channel — the same exported object literal the field overlay uses — rather than
inventing a second drawing mechanism.

## Assembly

- `imageio-ffmpeg` behind the `[video]` extra supplies the encoder.
- Frames are written to `.visus/video/<run>/NNNN.png` **as they are captured**,
  never accumulated in memory: a ten-minute run at 5 fps is 3000 full-page PNGs.
- The extra is guarded exactly as `[vision]` is today, so a missing extra is a
  clean error naming `pip install "visus-web[video]"` and not an `ImportError`
  traceback.

## Cost

Screenshot polling costs **one WebDriver round-trip per frame** — far more than a
screencast, which streams frames the browser is compositing anyway. At 5 fps on
the spike's page each frame cost roughly 40–60 ms of round-trip, so capture
occupies a meaningful fraction of the interval and the practical ceiling is
around 10 fps before frames start arriving late.

Consequences for the default: cap the default duration, default `--fps 5` rather
than something cinematic, and document that video is a diagnostic aid, not a
recording of exact timing.

## Acceptance criteria

- `visus video start` then `visus video stop -o run.webm` on a headed session
  writes a playable file.
- Frames differ — the spike's assertion, promoted to the feature test.
- A `visus video chapter` marker appears in the output at the right timestamp.
- Without the `[video]` extra, every video command exits 1 with
  `pip install "visus-web[video]"`.
- Video capture running concurrently with `visus click` does not serialise behind
  it for more than one frame interval. **The daemon's `RLock` around `handle()`
  makes this a real question, not a hypothetical** — answer it, or move capture
  to its own thread with its own driver handle.

## Not in scope

- Audio.
- Live streaming.
- Per-element video.
