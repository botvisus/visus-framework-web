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

__version__ = "0.3.6"

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
    debugger_address: str | None = None,
    keep_dialogs: bool = False,
) -> Browser:
    """Launch a browser and return a Browser handle.

    *slow_mo* delays every action/navigation by the given milliseconds — handy
    to watch a script drive the page in real time.

    *user_data_dir* reuses (or creates) a persistent browser profile instead of
    a throwaway temp profile — cookies, localStorage and logins survive across
    runs. The directory is never deleted by visus.

    *remote_url* opens the session on a Selenium Grid / Remote WebDriver
    (e.g. ``"http://grid:4444/wd/hub"``) instead of spawning a local browser.

    *debugger_address* (``"host:port"``, chrome/edge only) ATTACHES to a browser
    that is already running with remote debugging enabled instead of launching
    one — the user's own logged-in window, or a container exposing CDP. Release
    it with :meth:`Browser.detach`; :meth:`Browser.close` would end the browser
    along with the session.

    *keep_dialogs* leaves an ``alert``/``confirm``/``prompt`` open until it is
    handled explicitly (``page.expect_dialog``) instead of letting the driver
    dismiss it as soon as any other command runs — what an agent that must SEE
    the dialog needs. Off by default.

    Usage:
        with launch(headless=True) as browser:
            page = browser.new_page()
            page.goto("https://example.com")
    """
    resolved = Engine.from_str(engine)
    if debugger_address is not None and resolved not in (Engine.CHROME, Engine.EDGE):
        raise errors.UnsupportedEngineError(
            f"attaching to a running browser needs chrome or edge, not {resolved.value!r}"
        )
    config = get_browser_config(resolved)
    backend = SeleniumBackend()
    delegate = backend.launch(
        config,
        headless=headless,
        user_data_dir=user_data_dir,
        remote_url=remote_url,
        debugger_address=debugger_address,
        keep_dialogs=keep_dialogs,
    )
    return Browser(delegate, Defaults(slow_mo_ms=slow_mo, action_timeout_ms=_action_timeout_ms()))


def _action_timeout_ms() -> int:
    """``VISUS_ACTION_TIMEOUT_MS`` overrides the 30 s an action waits for its element: an
    agent driving the CLI wants a wrong guess to fail in seconds, not in half a minute."""
    import os

    raw = os.environ.get("VISUS_ACTION_TIMEOUT_MS", "").strip()
    try:
        value = int(raw) if raw else Defaults.action_timeout_ms
    except ValueError:
        return Defaults.action_timeout_ms
    return value if value > 0 else Defaults.action_timeout_ms
