"""The driver executable must not inherit its parent's handles.

On Windows Selenium spawns the driver with ``close_fds=False``, so chromedriver /
geckodriver inherit EVERY inheritable handle of the process that launched them —
including the pipes a supervisor reads that process's output through. When that
process dies (killed by pytest-timeout, a crash, an agent's own timeout) the
still-running driver holds the pipe open: the supervisor never sees EOF and waits
forever. That is how one slow test wedged the CI browser job for 49 minutes until
the 75-minute job limit cancelled it.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

WINDOWS = sys.platform == "win32"


@pytest.mark.parametrize("module_name", ["chrome", "edge", "firefox", "edge_ie"])
def test_driver_service_closes_inherited_handles(module_name: str) -> None:
    import importlib

    module = importlib.import_module(f"visus.web.backends.browsers.{module_name}")
    service = module.build_service()
    # Selenium reads close_fds from popen_kw, defaulting to False on Windows only
    assert service.popen_kw.get("close_fds", not WINDOWS) is True, (
        f"{module_name}.build_service() lets the driver inherit its parent's handles"
    )


_ORPHAN_A_DRIVER = textwrap.dedent(
    """
    import os, sys
    from pathlib import Path
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.driver_finder import DriverFinder
    from visus.web.backends.browsers import chrome

    service = chrome.build_service()
    # webdriver.Chrome() resolves the path via Selenium Manager; do it by hand here
    service.path = DriverFinder(service, Options()).get_driver_path()
    service.start()
    Path(sys.argv[1]).write_text(str(service.process.pid))
    print("driver up", flush=True)
    os._exit(0)  # die WITHOUT stopping the driver, as pytest-timeout does
    """
)


def _kill(pid: int) -> None:
    if WINDOWS:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass


@pytest.mark.browser
def test_a_dead_parent_does_not_leave_its_pipe_held_by_the_driver(tmp_path: Path) -> None:
    pid_file = tmp_path / "driver.pid"
    proc = subprocess.Popen(
        [sys.executable, "-c", _ORPHAN_A_DRIVER, str(pid_file)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        # communicate() returns on EOF: with the driver holding the pipe it never does
        out, _ = proc.communicate(timeout=45)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("the orphaned driver kept the dead parent's stdout pipe open")
    finally:
        # the driver was deliberately orphaned: end it here, by its exact pid
        if pid_file.is_file():
            _kill(int(pid_file.read_text()))
        if proc.stdout is not None:
            proc.stdout.close()
    assert b"driver up" in out
