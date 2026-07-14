"""visus.web — Playwright-style web automation on a Selenium engine."""

from __future__ import annotations

from visus.web import errors, tracing
from visus.web.api.assertions import expect
from visus.web.api.browser import Browser
from visus.web.api.context import Context
from visus.web.api.fields import Field
from visus.web.api.page import Page
from visus.web.backends.selenium_backend import SeleniumBackend
from visus.web.config import Defaults
from visus.web.engine import Engine
from visus.web.registry import get_browser_config
from visus.web.rpa import rpa

__version__ = "0.2.0"

__all__ = [
    "launch",
    "rpa",
    "expect",
    "Engine",
    "Browser",
    "Context",
    "Page",
    "Field",
    "errors",
    "tracing",
    "is_active",
    "save_screenshot",
]


def is_active() -> bool:
    """True while an ``rpa()`` session holds a live page.

    The runpilot SDK screenshot fallback calls this to prefer the *browser* shot for
    a web bot over a desktop grab when both ``visus.web`` and ``visus.desktop`` are
    installed.
    """
    return tracing.active_page() is not None


def save_screenshot(path: str) -> str:
    """Write a PNG screenshot of the active ``rpa()`` page to *path*.

    Exposed as a module-level hook for the runpilot SDK's screenshot fallback
    (``bot.error(screenshot=True)``). Raises ``RuntimeError`` if no session is active
    so the SDK can fall through to another driver.
    """
    page = tracing.active_page()
    if page is None:
        raise RuntimeError("visus.web.save_screenshot: no active page/session")
    page.screenshot(path=path)
    return path


def launch(
    engine: Engine | str = Engine.CHROME,
    *,
    headless: bool = False,
    slow_mo: int = 0,
    user_data_dir: str | None = None,
    remote_url: str | None = None,
) -> Browser:
    """Launch a browser and return a Browser handle.

    *slow_mo* delays every action/navigation by the given milliseconds — handy
    to watch a script drive the page in real time.

    *user_data_dir* reuses (or creates) a persistent browser profile instead of
    a throwaway temp profile — cookies, localStorage and logins survive across
    runs. The directory is never deleted by visus.

    *remote_url* opens the session on a Selenium Grid / Remote WebDriver
    (e.g. ``"http://grid:4444/wd/hub"``) instead of spawning a local browser.

    Usage:
        with launch(headless=True) as browser:
            page = browser.new_page()
            page.goto("https://example.com")
    """
    resolved = Engine.from_str(engine)
    config = get_browser_config(resolved)
    backend = SeleniumBackend()
    delegate = backend.launch(
        config, headless=headless, user_data_dir=user_data_dir, remote_url=remote_url
    )
    return Browser(delegate, Defaults(slow_mo_ms=slow_mo))
