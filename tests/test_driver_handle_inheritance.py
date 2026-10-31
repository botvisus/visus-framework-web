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
import signal
import subprocess
import sys
import textwrap

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
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.driver_finder import DriverFinder
    from visus.web.backends.browsers import chrome

    service = chrome.build_service()
    # webdriver.Chrome() resolves the path via Selenium Manager; do it by hand here
    service.path = DriverFinder(service, Options()).get_driver_path()
    service.start()
    print(service.process.pid, flush=True)
    sys.stdin.readline()  # the parent now holds a handle on the driver
    os._exit(0)  # die WITHOUT stopping the driver, as pytest-timeout does
    """
)


class _Pinned:
    """A process held by HANDLE, never by pid number.

    Windows reuses pids fast: a ``taskkill /F /PID`` on a pid whose process already
    exited kills whatever got the number next — an xdist worker ("node down: Not
    properly terminated"). An open handle keeps the pid from being reused, and
    TerminateProcess on it can only ever hit the process it was opened on.

    POSIX hands pids out in sequence, so there the number itself is safe enough.
    """

    def __init__(self, pid: int) -> None:
        self._pid: int | None = pid
        self._handle = None
        if WINDOWS:
            import ctypes

            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            process_terminate, synchronize = 0x0001, 0x00100000
            self._handle = self._kernel32.OpenProcess(process_terminate | synchronize, False, pid)

    def terminate(self) -> None:
        if WINDOWS:
            if self._handle:
                self._kernel32.TerminateProcess(self._handle, 1)
                self._kernel32.CloseHandle(self._handle)
                self._handle = None
        elif self._pid is not None:
            try:
                os.kill(self._pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            self._pid = None


@pytest.mark.browser
def test_a_dead_parent_does_not_leave_its_pipe_held_by_the_driver() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", _ORPHAN_A_DRIVER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert proc.stdin is not None and proc.stdout is not None
    driver = None
    try:
        driver = _Pinned(int(proc.stdout.readline()))
        # communicate() returns on EOF: with the driver holding the pipe it never does
        proc.communicate(input=b"go\n", timeout=45)
    except subprocess.TimeoutExpired:
        proc.kill()
        pytest.fail("the orphaned driver kept the dead parent's stdout pipe open")
    finally:
        # the driver was deliberately orphaned: end it through the handle
        if driver is not None:
            driver.terminate()
        proc.stdout.close()
