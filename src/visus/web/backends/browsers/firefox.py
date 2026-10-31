"""Firefox plug-in: assembles Selenium options/service. Selenium Manager resolves geckodriver."""

from __future__ import annotations

import subprocess
import sys

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service

from visus.web.errors import UnsupportedEngineError

_MIMES = "application/octet-stream,text/plain,application/pdf,application/zip,image/png,text/csv"


def build_options(
    *,
    headless: bool,
    download_dir: str,
    user_data_dir: str,
    debugger_address: str | None = None,
) -> Options:
    if debugger_address:
        raise UnsupportedEngineError(
            "attaching to a running browser needs chrome or edge — Firefox exposes no "
            "Chrome DevTools Protocol endpoint"
        )
    opts = Options()
    if headless:
        opts.add_argument("-headless")
    opts.set_preference("browser.download.folderList", 2)
    opts.set_preference("browser.download.dir", download_dir)
    opts.set_preference("browser.download.useDownloadDir", True)
    opts.set_preference("browser.helperApps.neverAskSaveToDisk", _MIMES)
    opts.set_preference("pdfjs.disabled", True)
    return opts


def _quiet(service: Service) -> Service:
    """Stop the driver executable opening a console window (Windows only).

    The driver is spawned BY the session daemon, which runs DETACHED and so has
    no console of its own to lend it — Windows then allocates a fresh one, which
    the user sees as a black window flashing on screen. Selenium forwards
    ``creation_flags`` straight to ``subprocess.Popen``.

    It also stops the driver inheriting this process's handles: Selenium passes
    ``close_fds=False`` on Windows, so the driver would hold open every pipe our
    parent reads us through, and a supervisor of a process that died (a timeout,
    a crash) would wait for an EOF that never comes while the driver lives on.
    """
    if sys.platform == "win32":
        service.creation_flags = subprocess.CREATE_NO_WINDOW
        service.popen_kw["close_fds"] = True
    return service


def build_service() -> Service:
    # No executable_path: Selenium Manager (selenium>=4.6) downloads/resolves geckodriver.
    return _quiet(Service())


def build_driver(*, options: Options, service: Service) -> webdriver.Firefox:
    return webdriver.Firefox(options=options, service=service)
