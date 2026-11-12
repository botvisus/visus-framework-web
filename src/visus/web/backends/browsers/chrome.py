"""Chrome plug-in: assembles Selenium options/service. Selenium Manager resolves the driver."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

# http:// continua http:// (intranet de empresa é http puro). Sem isto o Chromium tenta
# https antes — lento num host sem TLS — e então barra a página ou mostra o aviso de site
# não seguro; o driver.get volta sem erro e a aba fica na Nova guia. Precisa dos DOIS
# primeiros juntos (medido no Chrome 157); os demais cobrem variações de versão.
DISABLED_FEATURES = (
    "HttpsUpgrades",
    "HttpsFirstBalancedModeAutoEnable",
    "HttpsFirstModeV2ForTypicallySecureUsers",
    "HttpsFirstModeIncognito",
)
# a opção "Sempre usar conexões seguras" de um perfil persistente (user_data_dir)
HTTP_PREFS = {"https_only_mode_enabled": False}


def in_container() -> bool:
    """Linux dentro de um container (Docker, CI): o seccomp barra o sandbox do próprio
    Chrome e o /dev/shm é pequeno. ``VISUS_CHROME_NO_SANDBOX=1`` força; ``=0`` desliga."""
    forced = os.environ.get("VISUS_CHROME_NO_SANDBOX", "").strip()
    if forced:
        return forced not in ("0", "false", "False", "no")
    return sys.platform.startswith("linux") and Path("/.dockerenv").exists()


def build_options(
    *,
    headless: bool,
    download_dir: str,
    user_data_dir: str,
    debugger_address: str | None = None,
) -> Options:
    opts = Options()
    if debugger_address:
        # Attaching to a browser somebody else launched: Chrome ignores every
        # launch argument in this mode (profile, headless, download prefs), and
        # chromedriver rejects a session that mixes them with debuggerAddress.
        # Log capture is also a launch-time capability, so an attached session
        # has no performance/console history — page.network_requests() and
        # page.console_messages() simply stay empty.
        opts.add_experimental_option("debuggerAddress", debugger_address)
        return opts
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument(f"--user-data-dir={user_data_dir}")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-features=" + ",".join(DISABLED_FEATURES))
    if in_container():
        # o container é o sandbox; e o /dev/shm de 64 MB derrubaria as abas pesadas
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
    opts.add_experimental_option(
        "prefs",
        {
            "download.default_directory": download_dir,
            "download.prompt_for_download": False,
            **HTTP_PREFS,
        },
    )
    # Performance log feeds page.network_requests(); browser log feeds
    # page.console_messages(). Negligible overhead when never drained.
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})
    # perfLoggingPrefs enables CDP Network.* events (requestWillBeSent/
    # responseReceived/loadingFinished) so NetworkCapture(use_cdp=True) captures
    # JSONP <script>, sendBeacon, images and document navigations beyond the
    # fetch/XHR JS hook. Must be set at session creation — cannot be turned on later.
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
    # No executable_path: Selenium Manager (selenium>=4.6) downloads/resolves chromedriver.
    return _quiet(Service())


def build_driver(*, options: Options, service: Service) -> webdriver.Chrome:
    return webdriver.Chrome(options=options, service=service)
