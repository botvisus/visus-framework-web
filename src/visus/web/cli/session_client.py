"""Client for the persistent CLI session daemon.

Discovers ``.visus/session.json`` (searching upward git-style), checks liveness
(pid alive + socket connectable) and cleans stale files, sends JSON-lines ops to
the daemon, and spawns a detached daemon when none is running.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class SessionError(RuntimeError):
    """Raised when no live session is found or a daemon op fails."""


def _pid_alive(pid: int) -> bool:
    """True if a process with *pid* exists."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # tasklist is the dependency-free way to probe a pid on Windows.
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout
        except Exception:
            return False
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _socket_open(port: int, *, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """True if a TCP connection to *port* is accepted."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _find_session_file(start_dir: str | Path | None = None) -> Path | None:
    """Search upward from *start_dir* for ``.visus/session.json`` (git-style)."""
    cur = Path(start_dir) if start_dir is not None else Path.cwd()
    cur = cur.resolve()
    for d in [cur, *cur.parents]:
        candidate = d / ".visus" / "session.json"
        if candidate.is_file():
            return candidate
    return None


def find_session(start_dir: str | Path | None = None) -> dict[str, Any] | None:
    """Return the live session dict, or ``None``. Cleans up stale session files.

    A session is live when its pid is alive AND its socket accepts. A session
    file that fails either check is treated as stale and deleted.
    """
    sf = _find_session_file(start_dir)
    if sf is None:
        return None
    try:
        info: dict[str, Any] = json.loads(sf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _cleanup(sf)
        return None
    pid = int(info.get("pid", -1))
    port = int(info.get("port", -1))
    if not _pid_alive(pid) or not _socket_open(port):
        _cleanup(sf)
        return None
    info["_file"] = str(sf)
    return info


def _cleanup(sf: Path) -> None:
    """Remove a dead session's state: the session file AND its ownership lock.

    Deleting only ``session.json`` leaves ``session.json.lock`` behind, and the
    daemon claims that lock BEFORE binding — so the next ``session start`` aborts
    on a lock nobody owns and the user only sees a 20 s timeout.
    """
    for path in (sf, sf.with_name(sf.name + ".lock")):
        try:
            path.unlink()
        except OSError:
            pass


# The client's socket deadline when an op carries no timeout of its own.
DEFAULT_SOCKET_TIMEOUT = 60.0
# Slack added on top of an op's own deadline, covering the daemon's reply hop.
SOCKET_TIMEOUT_MARGIN = 10.0


def socket_timeout_for(args: dict[str, Any] | None) -> float:
    """Socket deadline for one op: its own ``timeout`` (ms) plus slack.

    ``visus wait``/``visus expect-text`` expose an uncapped ``--timeout`` in
    milliseconds that the daemon honours literally, so a fixed 60 s socket
    deadline would abort a perfectly healthy long wait mid-flight.
    """
    ms = (args or {}).get("timeout")
    if ms is None:
        return DEFAULT_SOCKET_TIMEOUT
    try:
        seconds = float(ms) / 1000.0
    except (TypeError, ValueError):
        return DEFAULT_SOCKET_TIMEOUT
    return max(DEFAULT_SOCKET_TIMEOUT, seconds + SOCKET_TIMEOUT_MARGIN)


def _send_raw(
    port: int, payload: dict[str, Any], *, timeout: float = DEFAULT_SOCKET_TIMEOUT
) -> dict[str, Any]:
    """Send one JSON request line, read one JSON response line."""
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        f = sock.makefile("rwb")
        f.write((json.dumps(payload) + "\n").encode("utf-8"))
        f.flush()
        line = f.readline()
        if not line:
            raise SessionError("daemon closed the connection without responding")
        resp: dict[str, Any] = json.loads(line.decode("utf-8"))
        return resp


def send(
    op: str,
    args: dict[str, Any] | None = None,
    *,
    start_dir: str | Path | None = None,
    timeout: float | None = None,
) -> Any:
    """Send an op to the live daemon and return its ``result`` (raises on failure).

    The socket deadline defaults to :func:`socket_timeout_for` so a long
    ``--timeout`` on the op is not cut short by the transport.
    """
    info = find_session(start_dir)
    if info is None:
        raise SessionError("no live session — run `visus session start` first")
    resp = _send_raw(
        int(info["port"]),
        {"token": info["token"], "op": op, "args": args or {}},
        timeout=socket_timeout_for(args) if timeout is None else timeout,
    )
    if not resp.get("ok"):
        raise SessionError(str(resp.get("error", "unknown error")))
    return resp.get("result")


def _log_tail(base: Path, *, lines: int = 20) -> str:
    """The last *lines* of ``<base>/.visus/daemon.log``, or ``""`` when unreadable."""
    log = base / ".visus" / "daemon.log"
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])


def start_daemon(
    engine: str = "chrome",
    headless: bool = False,
    url: str | None = None,
    *,
    cwd: str | Path | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """Spawn a detached daemon and block until its socket accepts.

    Returns the session dict. Raises :class:`SessionError` if an existing live
    session is already present or the daemon does not come up in time.
    """
    base = Path(cwd) if cwd is not None else Path.cwd()
    existing = find_session(base)
    if existing is not None:
        raise SessionError(
            f"a session is already running (pid {existing['pid']}, port {existing['port']})"
        )

    env = dict(os.environ)
    env["VISUS_WEB_ENGINE"] = engine
    env["VISUS_WEB_HEADLESS"] = "1" if headless else "0"
    if url:
        env["VISUS_WEB_URL"] = url

    creationflags = 0
    start_new_session = False
    if sys.platform == "win32":
        # These flags only exist on Windows; getattr keeps mypy happy on every platform.
        detached = getattr(subprocess, "DETACHED_PROCESS", 0)
        new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags = detached | new_group
    else:
        start_new_session = True

    subprocess.Popen(
        [sys.executable, "-m", "visus.web.cli.session_server", engine, env["VISUS_WEB_HEADLESS"]]
        + ([url] if url else []),
        cwd=str(base),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        start_new_session=start_new_session,
        close_fds=True,
    )

    sf = base / ".visus" / "session.json"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if sf.is_file():
            try:
                info: dict[str, Any] = json.loads(sf.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                time.sleep(0.1)
                continue
            if _socket_open(int(info.get("port", -1))):
                info["_file"] = str(sf)
                return info
        time.sleep(0.1)
    log_path = base / ".visus" / "daemon.log"
    tail = _log_tail(base)
    if tail:
        detail = f"\n--- last lines of {log_path} ---\n{tail}"
    else:
        detail = f" (no output in {log_path})"
    raise SessionError(f"daemon did not come up within {timeout:.0f}s{detail}")


def stop(*, start_dir: str | Path | None = None) -> str:
    """Shut down the live daemon. Returns a status message."""
    info = find_session(start_dir)
    if info is None:
        return "no session running"
    try:
        _send_raw(int(info["port"]), {"token": info["token"], "op": "shutdown", "args": {}})
    except (OSError, SessionError):
        pass
    # Wait briefly for the session file to be removed by the daemon.
    sf = Path(info["_file"])
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if not sf.is_file():
            break
        time.sleep(0.1)
    _cleanup(sf)
    return "session stopped"


def status(*, start_dir: str | Path | None = None) -> dict[str, Any] | None:
    """Return the live daemon's status dict, or ``None`` if no session is running."""
    info = find_session(start_dir)
    if info is None:
        return None
    result = send("status", start_dir=start_dir)
    merged: dict[str, Any] = {
        "pid": info["pid"],
        "port": info["port"],
        "engine": info.get("engine"),
        "headless": info.get("headless"),
    }
    if isinstance(result, dict):
        merged.update(result)
    return merged


def _find_lock_file(start_dir: str | Path | None = None) -> Path | None:
    """Search upward from *start_dir* for ``.visus/session.json.lock`` (git-style).

    A wedged project has the LOCK but no session file, so the lock needs its own
    discovery walk — :func:`_find_session_file` would return ``None``.
    """
    cur = Path(start_dir) if start_dir is not None else Path.cwd()
    cur = cur.resolve()
    for d in [cur, *cur.parents]:
        candidate = d / ".visus" / "session.json.lock"
        if candidate.is_file():
            return candidate
    return None


def _terminate(pid: int) -> None:
    """Best-effort terminate of a daemon process (``taskkill`` / ``SIGTERM``)."""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)], capture_output=True, timeout=10
            )
        except Exception:
            pass
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass


def kill(*, start_dir: str | Path | None = None) -> str:
    """Force-clear this project's session state. Returns a status message.

    The escape hatch for a wedged daemon: ``stop()`` needs a reachable socket and
    ``start()`` refuses while a lock exists, so neither can recover a process that
    was killed mid-flight. ``kill`` terminates the recorded pid when it is still
    alive and deletes ``session.json`` and ``session.json.lock`` unconditionally.
    """
    removed: list[str] = []
    pid = -1

    sf = _find_session_file(start_dir)
    if sf is not None:
        try:
            info: dict[str, Any] = json.loads(sf.read_text(encoding="utf-8"))
            pid = int(info.get("pid", -1))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pid = -1
        lock_beside = sf.with_name(sf.name + ".lock")
        had_lock = lock_beside.is_file()
        _cleanup(sf)  # removes the session file AND the lock beside it
        removed.append(sf.name)
        if had_lock:
            removed.append(lock_beside.name)

    lock = _find_lock_file(start_dir)
    if lock is not None:
        if pid <= 0:
            try:
                pid = int(lock.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                pid = -1
        try:
            lock.unlink()
            removed.append(lock.name)
        except OSError:
            pass

    if pid > 0 and _pid_alive(pid):
        _terminate(pid)
        return f"killed daemon pid {pid}; removed {', '.join(removed) or 'nothing'}"
    if not removed:
        return "no session state to remove"
    return f"removed {', '.join(removed)}"
