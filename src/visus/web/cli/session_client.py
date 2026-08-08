"""Client for the persistent CLI session daemon.

Discovers ``.visus/session.json`` (searching upward git-style), checks liveness
(pid alive + socket connectable) and cleans stale files, sends JSON-lines ops to
the daemon, and spawns a detached daemon when none is running.
"""

from __future__ import annotations

import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class SessionError(RuntimeError):
    """Raised when no live session is found or a daemon op fails."""


DEFAULT_SESSION_NAME = "default"

# The name becomes a FILE name under .visus/sessions/, so path separators, `..`
# and a leading dot are all refused rather than escaped.
_SESSION_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

_session_name: str | None = None


def validate_session_name(name: str) -> str:
    """Return *name* when it is a safe session name, else raise :class:`SessionError`."""
    if not _SESSION_NAME_RE.match(name or ""):
        raise SessionError(
            f"invalid session name {name!r} — start with a letter or digit and use only "
            "letters, digits, '.', '_' or '-' (max 64 chars); the name becomes a file "
            "name under .visus/sessions/"
        )
    return name


def set_session_name(name: str | None) -> None:
    """Pin the session name for this process (the CLI's ``--session`` / ``-S``)."""
    global _session_name
    _session_name = validate_session_name(name) if name else None


def session_name(name: str | None = None) -> str:
    """Resolve the session name: explicit arg > ``-S`` > ``VISUS_WEB_SESSION`` > default."""
    if name:
        return validate_session_name(name)
    if _session_name:
        return _session_name
    env = os.environ.get("VISUS_WEB_SESSION")
    if env:
        return validate_session_name(env)
    return DEFAULT_SESSION_NAME


# How long a liveness answer may be reused. Short enough that a dying daemon is
# noticed almost immediately, long enough to collapse the repeat probes a single
# CLI invocation makes.
PID_ALIVE_TTL = 1.0
_pid_alive_cache: dict[int, tuple[float, bool]] = {}


def _probe_pid(pid: int) -> bool:
    """Ask the OS whether a process with *pid* exists (uncached)."""
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


def _pid_alive(pid: int) -> bool:
    """True if a process with *pid* exists, memoised for :data:`PID_ALIVE_TTL`.

    On Windows every probe spawns ``tasklist`` with a 5 s timeout, and a single
    command probes the same pid more than once (discovery, then the op). The memo
    removes the duplicate cost without ever hiding a death for longer than the TTL.
    Liveness-critical callers use :func:`_probe_pid` directly.
    """
    now = time.monotonic()
    hit = _pid_alive_cache.get(pid)
    if hit is not None and now - hit[0] < PID_ALIVE_TTL:
        return hit[1]
    alive = _probe_pid(pid)
    _pid_alive_cache[pid] = (now, alive)
    return alive


def _socket_open(port: int, *, host: str = "127.0.0.1", timeout: float = 1.0) -> bool:
    """True if a TCP connection to *port* is accepted."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _find_session_file(
    start_dir: str | Path | None = None, name: str | None = None
) -> Path | None:
    """Search upward from *start_dir* for ``.visus/sessions/<name>.json`` (git-style).

    The upward walk is deliberate: a command run in ``repo/src`` must reach the
    session started in ``repo``. It is also why every "already running" message
    prints the file it resolved — the same walk used to bind a subfolder to its
    parent's daemon without ever saying so.
    """
    cur = Path(start_dir) if start_dir is not None else Path.cwd()
    cur = cur.resolve()
    filename = f"{session_name(name)}.json"
    for d in [cur, *cur.parents]:
        candidate = d / ".visus" / "sessions" / filename
        if candidate.is_file():
            return candidate
    return None


def find_session(
    start_dir: str | Path | None = None, name: str | None = None
) -> dict[str, Any] | None:
    """Return the live session dict for *name*, or ``None``. Cleans stale files.

    A session is live when its pid is alive AND its socket accepts. A session
    file that fails either check is treated as stale and deleted.
    """
    sf = _find_session_file(start_dir, name)
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


def send_envelope(
    op: str,
    args: dict[str, Any] | None = None,
    *,
    start_dir: str | Path | None = None,
    name: str | None = None,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Send an op to the named session and return the daemon's FULL reply envelope.

    The envelope carries ``result`` plus, for a mutating op, ``page`` state, the
    generated ``code`` line, and the ``snapshot`` file path — everything the CLI
    needs to print the perception half of the loop. Raises on ``ok: False``.

    The socket deadline defaults to :func:`socket_timeout_for` so a long
    ``--timeout`` on the op is not cut short by the transport.
    """
    info = find_session(start_dir, name)
    if info is None:
        raise SessionError(
            f"no live session {session_name(name)!r} — run `visus session start` first "
            "(`visus session list` shows every session)"
        )
    resp = _send_raw(
        int(info["port"]),
        {"token": info["token"], "op": op, "args": args or {}},
        timeout=socket_timeout_for(args) if timeout is None else timeout,
    )
    if not resp.get("ok"):
        raise SessionError(str(resp.get("error", "unknown error")))
    return resp


def send(
    op: str,
    args: dict[str, Any] | None = None,
    *,
    start_dir: str | Path | None = None,
    name: str | None = None,
    timeout: float | None = None,
) -> Any:
    """Send an op to the named session and return its ``result`` (raises on failure)."""
    return send_envelope(op, args, start_dir=start_dir, name=name, timeout=timeout).get(
        "result"
    )


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
    name: str | None = None,
    user_data_dir: str | None = None,
    remote_url: str | None = None,
    slow_mo: int = 0,
    cwd: str | Path | None = None,
    timeout: float = 20.0,
    idle_timeout: float | None = None,
) -> dict[str, Any]:
    """Spawn a detached daemon for session *name* and block until its socket accepts.

    Sessions are namespaced: ``.visus/sessions/<name>.json``. Discovery walks
    upward, so a second session in the same tree needs its own ``--session`` name.

    ``user_data_dir`` reuses a persistent browser profile (cookies/logins survive
    across runs), ``remote_url`` targets a Selenium Grid instead of a local
    browser, and ``slow_mo`` delays every action by that many milliseconds.

    Returns the session dict. Raises :class:`SessionError` if a live session of the
    same name is already present or the daemon does not come up in time.
    """
    resolved = session_name(name)
    base = Path(cwd) if cwd is not None else Path.cwd()
    existing = find_session(base, resolved)
    if existing is not None:
        raise SessionError(
            f"session {resolved!r} is already running "
            f"(pid {existing['pid']}, port {existing['port']}, "
            f"state {existing.get('_file', '?')}) — stop it, or start another one "
            "with `--session <name>`"
        )

    env = dict(os.environ)
    env["VISUS_WEB_ENGINE"] = engine
    env["VISUS_WEB_HEADLESS"] = "1" if headless else "0"
    env["VISUS_WEB_SESSION"] = resolved
    if url:
        env["VISUS_WEB_URL"] = url
    if user_data_dir:
        # Resolve against the CLIENT's cwd — the daemon is spawned elsewhere.
        env["VISUS_WEB_USER_DATA_DIR"] = str(Path(user_data_dir).resolve())
    if remote_url:
        env["VISUS_WEB_REMOTE_URL"] = remote_url
    if slow_mo:
        env["VISUS_WEB_SLOW_MO"] = str(slow_mo)
    if idle_timeout is not None:
        env["VISUS_WEB_IDLE_TIMEOUT"] = str(idle_timeout)

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

    sf = base / ".visus" / "sessions" / f"{resolved}.json"
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


def stop(*, start_dir: str | Path | None = None, name: str | None = None) -> str:
    """Shut down the named session's daemon. Returns a status message."""
    info = find_session(start_dir, name)
    if info is None:
        return f"no session {session_name(name)!r} running"
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


def status(
    *, start_dir: str | Path | None = None, name: str | None = None
) -> dict[str, Any] | None:
    """Return the named session's status dict, or ``None`` when it is not running.

    Sends on the connection info from the SINGLE ``find_session`` call above —
    routing through :func:`send` would re-run discovery and pay a second liveness
    probe (on Windows: a second ``tasklist`` with a 5 s timeout).
    """
    info = find_session(start_dir, name)
    if info is None:
        return None
    resp = _send_raw(int(info["port"]), {"token": info["token"], "op": "status", "args": {}})
    if not resp.get("ok"):
        raise SessionError(str(resp.get("error", "unknown error")))
    result = resp.get("result")
    merged: dict[str, Any] = {
        "name": session_name(name),
        "pid": info["pid"],
        "port": info["port"],
        "engine": info.get("engine"),
        "headless": info.get("headless"),
    }
    if isinstance(result, dict):
        merged.update(result)
    return merged


def _find_lock_file(
    start_dir: str | Path | None = None, name: str | None = None
) -> Path | None:
    """Search upward for ``.visus/sessions/<name>.json.lock`` (git-style).

    A wedged project has the LOCK but no session file, so the lock needs its own
    discovery walk — :func:`_find_session_file` would return ``None``.
    """
    cur = Path(start_dir) if start_dir is not None else Path.cwd()
    cur = cur.resolve()
    filename = f"{session_name(name)}.json.lock"
    for d in [cur, *cur.parents]:
        candidate = d / ".visus" / "sessions" / filename
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


def kill(*, start_dir: str | Path | None = None, name: str | None = None) -> str:
    """Force-clear this project's session state. Returns a status message.

    The escape hatch for a wedged daemon: ``stop()`` needs a reachable socket and
    ``start()`` refuses while a lock exists, so neither can recover a process that
    was killed mid-flight. ``kill`` terminates the recorded pid when it is still
    alive and deletes ``session.json`` and ``session.json.lock`` unconditionally.
    """
    removed: list[str] = []
    pid = -1

    sf = _find_session_file(start_dir, name)
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

    lock = _find_lock_file(start_dir, name)
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

    if pid > 0 and _probe_pid(pid):
        _terminate(pid)
        return f"killed daemon pid {pid}; removed {', '.join(removed) or 'nothing'}"
    if not removed:
        return "no session state to remove"
    return f"removed {', '.join(removed)}"


def _find_sessions_dir(start_dir: str | Path | None = None) -> Path | None:
    """Search upward for a ``.visus/sessions`` directory (git-style). First hit wins."""
    cur = Path(start_dir) if start_dir is not None else Path.cwd()
    cur = cur.resolve()
    for d in [cur, *cur.parents]:
        candidate = d / ".visus" / "sessions"
        if candidate.is_dir():
            return candidate
    return None


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _entry(info: dict[str, Any], *, sf: Path, scope: str) -> dict[str, Any]:
    """Shape one session record for :func:`list_sessions` — never carries the token."""
    pid = int(info.get("pid", -1) or -1)
    port = int(info.get("port", -1) or -1)
    return {
        "name": str(info.get("name") or sf.stem),
        "cwd": str(info.get("cwd") or sf.parent.parent.parent),
        "file": str(info.get("file") or sf),
        "pid": pid,
        "port": port,
        "engine": info.get("engine"),
        "headless": info.get("headless"),
        "url": info.get("url"),
        "live": bool(pid > 0 and _probe_pid(pid) and _socket_open(port)),
        "scope": scope,
    }


def list_sessions(start_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """Every session visus knows about: this project's, plus every other project's.

    Two sources are merged on ``(cwd, name)``: the project's own
    ``.visus/sessions/*.json`` (found with the same upward walk commands use) and
    the cross-project registry under ``~/.visus/sessions``. Local records win —
    they are the authoritative file the daemon writes. Liveness is probed with
    the UNCACHED :func:`_probe_pid`, because a stale "alive" here would hide a
    dead daemon from ``kill-all``.
    """
    from visus.web.cli import session_server

    merged: dict[tuple[str, str], dict[str, Any]] = {}

    local_dir = _find_sessions_dir(start_dir)
    if local_dir is not None:
        for sf in sorted(local_dir.glob("*.json")):
            info = _read_json(sf)
            if info is None:
                continue
            row = _entry(info, sf=sf, scope="local")
            merged[(str(Path(row["cwd"]).resolve()), row["name"])] = row

    try:
        registry = sorted(session_server.registry_dir().glob("*.json"))
    except OSError:
        registry = []
    for entry_file in registry:
        info = _read_json(entry_file)
        if info is None:
            continue
        row = _entry(info, sf=entry_file, scope="other")
        key = (str(Path(row["cwd"]).resolve()), row["name"])
        if key not in merged:
            merged[key] = row

    return sorted(
        merged.values(), key=lambda r: (r["scope"] != "local", r["name"], r["cwd"])
    )
