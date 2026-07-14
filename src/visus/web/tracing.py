"""Global tracing toggle + session manager for visus.web observability."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from visus.web.observability.recorder import Recorder


def _env_on() -> bool:
    return os.environ.get("VISUS_WEB_TRACING", "0").lower() not in ("0", "", "false", "no")


class _Tracing:
    def __init__(self) -> None:
        self.enabled: bool = _env_on()
        self.screenshot_each_action: bool = True  # per-action shots ON by default
        self.screenshot_on_failure: bool = True
        self.recorder: Recorder | None = None
        self.active_page: Any = None  # live page for module-level save_screenshot()
        self.step_sink: Any = None  # per-action reporter (streams steps to the SaaS)


_STATE = _Tracing()


def enable(**opts: Any) -> None:
    """Enable tracing, optionally setting options (screenshot_each_action, screenshot_on_failure)."""
    _STATE.enabled = True
    for k, v in opts.items():
        setattr(_STATE, k, v)


def disable() -> None:
    """Disable tracing globally."""
    _STATE.enabled = False


def is_enabled() -> bool:
    """Return True if tracing is currently enabled."""
    return _STATE.enabled


def current_recorder() -> Recorder | None:
    """Return the active Recorder, or None if not inside a ``record()`` session."""
    return _STATE.recorder


def set_active_page(page: Any) -> None:
    """Register the live page so ``visus.web.save_screenshot`` (the runpilot SDK's
    screenshot fallback for web bots) can grab the browser. Pass ``None`` to clear."""
    _STATE.active_page = page


def active_page() -> Any:
    """Return the live page of an active ``rpa()`` session, or ``None``."""
    return _STATE.active_page


def set_step_sink(sink: Any) -> None:
    """Install a per-action sink ``sink(event: dict, png: bytes | None)`` called for
    every recorded action (used to stream steps to an orchestrator). ``None`` clears."""
    _STATE.step_sink = sink


def current_sink() -> Any:
    """Return the active per-action sink, or ``None``."""
    return _STATE.step_sink


def options() -> _Tracing:
    """Return the mutable options object."""
    return _STATE


@contextmanager
def record(
    zip_path: str | None, report: str | None = None, *, sink: Any = None, **opts: Any
) -> Iterator[Recorder]:
    """Context manager: enable tracing, collect events/screenshots, write zip on exit.

    If *report* is given, the HTML report is rendered to that path on the way out —
    **even when the body raises** — so a failed run is always debuggable without any
    try/finally boilerplate. A render error never masks the original failure.

    Pass ``zip_path=None`` to skip writing the local zip/report entirely (e.g. when
    steps are streamed live to an orchestrator via *sink*); resources are still
    released. *sink* — see :func:`set_step_sink` — receives every recorded action.

    Usage::

        with tracing.record("run.zip", report="report.html"):
            page.goto(url)
            page.get_by_label("Name").fill("Ada")
            page.get_by_role("button", name="Save").click()  # if this raises,
            # run.zip AND report.html are still written before the error propagates.
    """
    from visus.web.observability.recorder import Recorder

    prev_enabled, prev_rec, prev_sink = _STATE.enabled, _STATE.recorder, _STATE.step_sink
    enable(**opts)
    rec = Recorder()
    _STATE.recorder = rec
    _STATE.step_sink = sink
    try:
        yield rec
    finally:
        _STATE.recorder = prev_rec
        _STATE.enabled = prev_enabled
        _STATE.step_sink = prev_sink
        if zip_path is None:
            rec.close()  # release the log handler without writing a local zip
        else:
            rec.write_zip(zip_path)
            if report:
                # On a clean exit, surface render errors. While unwinding an exception,
                # render best-effort so a report bug can't mask the real failure.
                if sys.exc_info()[0] is None:
                    render_report(zip_path, report)
                else:
                    try:
                        render_report(zip_path, report)
                    except Exception:
                        pass


def render_report(zip_path: str, output: str = "report.html") -> str:
    """Render a self-contained HTML report from a tracing zip.

    Returns the path of the written HTML file.
    """
    from visus.web.observability.report import render_report as _render

    return _render(zip_path, output)
