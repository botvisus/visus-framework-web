"""Frame capture for run video (behind the ``[video]`` extra).

Deliberately mechanism-agnostic. CDP's ``Page.startScreencast`` delivers frames
as ``Page.screencastFrame`` EVENTS, and the synchronous CDP bridge this project
uses everywhere (see ``network.py``'s ``execute_cdp_cmd`` calls) issues commands
and reads their return value — it has no event subscription. Until that is
resolved, :func:`capture_frames` polls screenshots at a fixed rate, which works
on every engine including Firefox and needs no CDP at all.
"""

from __future__ import annotations

import time
from typing import Any


def cdp_screencast_available(page: Any) -> bool:
    """True when ``Page.startScreencast`` can be issued AND frames can be drained.

    Reports, never assumes: a Chromium page accepts the command happily and then
    delivers nothing through a synchronous bridge, so "the command worked" is not
    the same question as "frames arrive".
    """
    delegate = getattr(page, "_delegate", None)
    driver = getattr(delegate, "_driver", None)
    if driver is None or not hasattr(driver, "execute_cdp_cmd"):
        return False
    try:
        driver.execute_cdp_cmd("Page.startScreencast", {"format": "png", "everyNthFrame": 1})
    except Exception:  # noqa: BLE001 — a non-Chromium engine simply has no screencast
        return False
    try:
        # The command is accepted and the frames go nowhere: a synchronous bridge
        # exposes no event queue to drain them from. If a future Selenium grows
        # one, this is the line that changes — until then the honest answer is
        # False, which is exactly what this spike exists to record.
        return False
    finally:
        try:
            driver.execute_cdp_cmd("Page.stopScreencast", {})
        except Exception:  # noqa: BLE001
            pass


def capture_frames(page: Any, *, fps: int = 5, duration_ms: int = 1000) -> list[bytes]:
    """Capture PNG frames of *page* for *duration_ms* at roughly *fps*.

    Screenshot polling: engine-independent, no CDP, and accurate enough for a
    run video whose purpose is "show me what happened", not broadcast. Returns
    the frames in capture order; assembling them into a container is the caller's
    job (see ``docs/design/video-screencast.md``).
    """
    if fps <= 0:
        raise ValueError("fps must be positive")
    interval = 1.0 / fps
    deadline = time.monotonic() + duration_ms / 1000.0
    frames: list[bytes] = []
    while True:
        started = time.monotonic()
        frames.append(page.screenshot())
        if time.monotonic() >= deadline:
            return frames
        remaining = interval - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(min(remaining, max(0.0, deadline - time.monotonic())))
