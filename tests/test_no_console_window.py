"""No console window may flash on Windows when the CLI runs.

Every helper visus spawns is a CONSOLE application (`tasklist`, `taskkill`,
`powershell`, the driver), and the session daemon runs DETACHED — with no console
of its own to lend them, Windows allocates a NEW one per spawn, which the user
sees as a black window. `capture_output=True` pipes their output but does not
stop the window.

Nothing here is skipped off-Windows: each test asserts what the code does on the
platform it is running on, because "POSIX takes a path where the problem cannot
arise" is itself a claim worth holding.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest

WINDOWS = sys.platform == "win32"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _capture_run(monkeypatch: pytest.MonkeyPatch, module: Any) -> list[dict[str, Any]]:
    """Record the kwargs of every subprocess.run made through *module*."""
    seen: list[dict[str, Any]] = []

    class _Completed:
        stdout = ""
        returncode = 0

    def fake_run(cmd: Any, **kw: Any) -> Any:
        seen.append({"cmd": cmd, **kw})
        return _Completed()

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    return seen


def test_pid_probe_does_not_open_a_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """`tasklist` runs on EVERY command via find_session — the worst offender."""
    from visus.web.cli import session_client

    seen = _capture_run(monkeypatch, session_client)
    session_client._probe_pid(4242)
    if not WINDOWS:
        assert seen == [], "POSIX probes with os.kill — no process, no console to open"
        return
    assert seen and seen[0]["cmd"][0] == "tasklist"
    assert seen[0].get("creationflags", 0) & NO_WINDOW, seen[0]


def test_terminate_does_not_open_a_console(monkeypatch: pytest.MonkeyPatch) -> None:
    from visus.web.cli import session_client

    seen = _capture_run(monkeypatch, session_client)
    session_client._terminate(4242)
    if not WINDOWS:
        assert seen == [], "POSIX terminates with SIGTERM"
        return
    assert seen and seen[0]["cmd"][0] == "taskkill"
    assert seen[0].get("creationflags", 0) & NO_WINDOW, seen[0]


def test_clipboard_read_does_not_open_a_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """`visus translate` with no argument shells out to powershell / pbpaste / xclip.

    `_read_clipboard` imports subprocess INSIDE the function, so the real module is
    patched rather than a module attribute that does not exist.
    """
    import subprocess as real_subprocess

    from visus.web.cli import main

    seen: list[dict[str, Any]] = []

    class _Completed:
        stdout = ""

    def fake_run(cmd: Any, **kw: Any) -> Any:
        seen.append({"cmd": cmd, **kw})
        return _Completed()

    monkeypatch.setattr(real_subprocess, "run", fake_run)
    main._read_clipboard()
    assert seen, "expected a clipboard shell-out"
    # creationflags is always passed; it is 0 off-Windows, which subprocess accepts.
    flags = seen[0].get("creationflags", None)
    assert flags is not None, seen[0]
    assert bool(flags & NO_WINDOW) is WINDOWS, seen[0]


def test_the_daemon_spawn_stays_detached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """Detachment is what outlives the shell; it is orthogonal to the window."""
    from visus.web.cli import session_client

    captured: dict[str, Any] = {}

    class _FakePopen:
        def poll(self) -> None:  # o daemon de mentira não sai
            return None

        def __init__(self, argv: list[str], **kw: Any) -> None:
            captured["argv"] = argv
            captured.update(kw)

    monkeypatch.setattr(session_client, "find_session", lambda base, name=None: None)
    monkeypatch.setattr(session_client.subprocess, "Popen", _FakePopen)
    # cwd=tmp_path, because after Popen the wait loop reads
    # `<cwd>/.visus/sessions/<name>.json` DIRECTLY — patching find_session is not
    # enough, and a real `visus session start` in this repo would satisfy the
    # loop and make the spawn look successful.
    with pytest.raises(session_client.SessionError):
        session_client.start_daemon("chrome", True, None, cwd=tmp_path, timeout=0.2)

    if WINDOWS:
        assert captured["creationflags"] & getattr(subprocess, "DETACHED_PROCESS", 0x8)
    else:
        assert captured["start_new_session"] is True


def test_the_daemon_runs_under_pythonw_so_it_allocates_no_console(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """The daemon itself was the window.

    MEASURED: `session start` created a conhost.exe whose PARENT was the daemon's
    own python.exe — the daemon allocated a console for itself. DETACHED_PROCESS
    does not prevent that, and Windows documents CREATE_NO_WINDOW as IGNORED when
    combined with it, so no flag combination fixes it. pythonw.exe is the
    GUI-subsystem interpreter and cannot allocate a console at all.
    """
    from visus.web.cli import session_client

    captured: dict[str, Any] = {}

    class _FakePopen:
        def poll(self) -> None:  # o daemon de mentira não sai
            return None

        def __init__(self, argv: list[str], **kw: Any) -> None:
            captured["argv"] = argv

    monkeypatch.setattr(session_client, "find_session", lambda base, name=None: None)
    monkeypatch.setattr(session_client.subprocess, "Popen", _FakePopen)
    with pytest.raises(session_client.SessionError):
        session_client.start_daemon("chrome", True, None, cwd=tmp_path, timeout=0.2)

    exe = captured["argv"][0]
    if WINDOWS:
        assert exe.lower().endswith("pythonw.exe"), exe
    else:
        assert exe == sys.executable, exe


def test_daemon_interpreter_falls_back_when_pythonw_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A python build with no pythonw.exe must still start a daemon."""
    from visus.web.cli import session_client

    lonely = tmp_path / "python.exe"
    lonely.write_bytes(b"")
    monkeypatch.setattr(session_client.sys, "executable", str(lonely))
    assert session_client._daemon_interpreter() == str(lonely)


@pytest.mark.parametrize("module_name", ["chrome", "edge", "firefox", "edge_ie"])
def test_driver_service_suppresses_its_console(module_name: str) -> None:
    """The driver is spawned BY the detached daemon, so it would get a fresh console."""
    import importlib

    module = importlib.import_module(f"visus.web.backends.browsers.{module_name}")
    service = module.build_service()
    if WINDOWS:
        assert service.creation_flags & NO_WINDOW, (
            f"{module_name}.build_service() lets the driver open a console window"
        )
    else:
        assert service.creation_flags == 0, "no Windows flag may leak onto POSIX"
