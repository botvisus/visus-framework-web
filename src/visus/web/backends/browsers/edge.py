"""Edge plug-in: assembles Selenium options/service. Selenium Manager resolves the driver."""

from __future__ import annotations

import subprocess
import sys

from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service


def build_options(
    *,
    headless: bool,
    download_dir: str,
    user_data_dir: str,
    debugger_address: str | None = None,
) -> Options:
    opts = Options()
    if debugger_address:
        # Same as chrome: Edge ignores launch arguments when attaching, and
        # msedgedriver rejects a session that mixes them with debuggerAddress.
        # The logging capabilities below are launch-time only, so an attached
        # session has no performance/console history to drain.
        opts.add_experimental_option("debuggerAddress", debugger_address)
        return opts
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument(f"--user-data-dir={user_data_dir}")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-gpu")
    opts.add_experimental_option(
        "prefs",
        {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
        },
    )
    # Performance log feeds page.network_requests(); browser log feeds
    # page.console_messages(). Negligible overhead when never drained.
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    # msedgedriver (a Chromium fork) reads the vendor-prefixed ms:loggingPrefs for
    # the DevTools performance log NetworkCapture drains; both capabilities coexist.
    # perfLoggingPrefs enables CDP Network.* events. Must be set at session creation.
    opts.set_capability("ms:loggingPrefs", {"performance": "ALL"})
    opts.add_experimental_option(
        "perfLoggingPrefs",
        {"enableNetwork": True, "enablePage": False},
    )
    return opts


def _quiet(service: Service) -> Service:
    """Stop the driver executable opening a console window (Windows only).

    The driver is spawned BY the session daemon, which runs DETACHED and so has
    no console of its own to lend it — Windows then allocates a fresh one, which
    the user sees as a black window flashing on screen. Selenium forwards
    ``creation_flags`` straight to ``subprocess.Popen``.
    """
    if sys.platform == "win32":
        service.creation_flags = subprocess.CREATE_NO_WINDOW
    return service


def build_service() -> Service:
    # No executable_path: Selenium Manager (selenium>=4.6) downloads/resolves msedgedriver.
    return _quiet(Service())


def build_driver(*, options: Options, service: Service) -> webdriver.Edge:
    return webdriver.Edge(options=options, service=service)
