"""The person's own browser (Chrome, else Edge), driven without launching it through a driver.

Two ways, both through ``visus session attach``:

``--cdp visus``
    visus starts the INSTALLED Chrome/Edge itself, on a profile of its own, with remote
    debugging on (``--remote-debugging-port``). No driver launches the browser, so there is
    no automation flag (``navigator.webdriver`` stays false) and no "allow remote debugging"
    question; logins made in that profile are kept for next time.

``--cdp mine``
    The browser the person already has open, with their profile, logins and extensions.
    Chrome/Edge 144+ only allow this after the person turns it on in
    ``chrome://inspect/#remote-debugging`` (:func:`enable_remote_debugging` turns it on while
    the browser is closed), and then ask "Allow remote debugging?" for each new connection.
    In that mode the browser no longer serves ``/json/version``, which ChromeDriver needs
    before it attaches -- :class:`DevToolsShim` serves it locally, from the address the
    browser writes to ``DevToolsActivePort``, and keeps one connection open for the whole
    session so the question comes once.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "BROWSERS",
    "DevToolsShim",
    "OwnBrowserError",
    "enable_remote_debugging",
    "endpoint",
    "executable",
    "is_running",
    "launch",
    "pick",
    "profile_dir",
    "remote_debugging_enabled",
]

Browser = Literal["chrome", "edge"]
#: the order the person asked for: Chrome, and Edge when there is no Chrome
BROWSERS: tuple[Browser, ...] = ("chrome", "edge")
#: how long the person has to click "Allow" on the browser's question
CONSENT_TIMEOUT_S = 120.0

_WIN_EXE = {
    "chrome": (r"Google\Chrome\Application\chrome.exe",),
    "edge": (r"Microsoft\Edge\Application\msedge.exe",),
}
_MAC_EXE = {
    "chrome": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "edge": "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
}
_LINUX_EXE = {
    "chrome": ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"),
    "edge": ("microsoft-edge", "microsoft-edge-stable"),
}
_PROCESS = {"chrome": "chrome.exe", "edge": "msedge.exe"}


class OwnBrowserError(RuntimeError):
    """The person's browser is not there, not reachable, or did not allow the connection."""


# --- where the browser is ---------------------------------------------------------------


def executable(
    browser: Browser, *, platform: str = sys.platform, env: Mapping[str, str] = os.environ
) -> str | None:
    """The installed Chrome/Edge, or ``None``."""
    if platform == "win32":
        roots = [env.get(k, "") for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for root in filter(None, roots):
            for rel in _WIN_EXE[browser]:
                path = Path(root) / rel
                if path.is_file():
                    return str(path)
        return None
    if platform == "darwin":
        return _MAC_EXE[browser] if Path(_MAC_EXE[browser]).is_file() else None
    for name in _LINUX_EXE[browser]:
        found = shutil.which(name)
        if found:
            return found
    return None


def pick(
    order: tuple[Browser, ...] = BROWSERS, *, find: Callable[[Browser], str | None] = executable
) -> Browser | None:
    """The first installed browser of *order* (Chrome, then Edge)."""
    return next((b for b in order if find(b)), None)


def profile_dir(
    browser: Browser, *, platform: str = sys.platform, env: Mapping[str, str] = os.environ
) -> Path:
    """The person's own browser data folder (where ``Local State`` and
    ``DevToolsActivePort`` live)."""
    if platform == "win32":
        base = Path(env.get("LOCALAPPDATA", ""))
        return base / ("Google/Chrome" if browser == "chrome" else "Microsoft/Edge") / "User Data"
    home = Path(env.get("HOME", str(Path.home())))
    if platform == "darwin":
        name = "Google/Chrome" if browser == "chrome" else "Microsoft Edge"
        return home / "Library/Application Support" / name
    return home / ".config" / ("google-chrome" if browser == "chrome" else "microsoft-edge")


def _listening(port: int, *, host: str = "127.0.0.1", timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def endpoint(
    user_data_dir: Path, *, listening: Callable[[int], bool] = _listening
) -> tuple[int, str] | None:
    """``(port, browser path)`` from ``DevToolsActivePort`` when the browser is listening
    there; ``None`` when remote debugging is off or the browser is closed (the file stays
    behind after the browser exits)."""
    try:
        lines = (user_data_dir / "DevToolsActivePort").read_text(encoding="utf-8").split("\n")
        port, path = int(lines[0].strip()), lines[1].strip()
    except (OSError, ValueError, IndexError):
        return None
    return (port, path) if path and listening(port) else None


def is_running(browser: Browser, *, platform: str = sys.platform) -> bool:
    """Is any window of this browser open (its ``Local State`` would be rewritten on exit)?"""
    if platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {_PROCESS[browser]}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        return _PROCESS[browser] in out.lower()
    names = _LINUX_EXE[browser] if platform != "darwin" else (Path(_MAC_EXE[browser]).name,)
    return any(
        subprocess.run(["pgrep", "-x", name], capture_output=True).returncode == 0 for name in names
    )


# --- the person's switch (chrome://inspect/#remote-debugging) ------------------------------

_SWITCH = ("devtools", "remote_debugging", "user-enabled")


def remote_debugging_enabled(user_data_dir: Path) -> bool:
    try:
        state = json.loads((user_data_dir / "Local State").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    node: Any = state
    for key in _SWITCH:
        node = node.get(key) if isinstance(node, dict) else None
    return node is True


def enable_remote_debugging(
    browser: Browser,
    *,
    user_data_dir: Path | None = None,
    running: Callable[[Browser], bool] = is_running,
) -> Literal["enabled", "already", "running", "missing"]:
    """Turn on "Allow remote debugging for this browser instance" -- the switch of
    ``chrome://inspect/#remote-debugging``, kept in ``Local State``. Only with the browser
    closed: an open browser rewrites that file when it exits and the change is lost
    (``"running"``: ask the person to close it, or to turn it on there)."""
    folder = user_data_dir or profile_dir(browser)
    state_file = folder / "Local State"
    if not state_file.is_file():
        return "missing"
    if remote_debugging_enabled(folder):
        return "already"
    if running(browser):
        return "running"
    state = json.loads(state_file.read_text(encoding="utf-8"))
    node = state
    for key in _SWITCH[:-1]:
        child = node.get(key)
        node[key] = child if isinstance(child, dict) else {}
        node = node[key]
    node[_SWITCH[-1]] = True
    tmp = state_file.with_suffix(".visus-tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, state_file)
    return "enabled"


# --- "visus": the installed browser on a profile of visus ----------------------------------


def launch(
    browser: Browser,
    user_data_dir: Path,
    *,
    find: Callable[[Browser], str | None] = executable,
    popen: Callable[..., Any] = subprocess.Popen,
    wait_s: float = 30.0,
) -> str:
    """The installed browser on *user_data_dir* with remote debugging on; returns
    ``"127.0.0.1:<port>"``. Reuses the one already open on that profile. The browser is
    started on its own (not as a child of this process): it stays open when the session
    ends, like a browser the person opened."""
    user_data_dir.mkdir(parents=True, exist_ok=True)
    live = endpoint(user_data_dir)
    if live:
        return f"127.0.0.1:{live[0]}"
    exe = find(browser)
    if exe is None:
        raise OwnBrowserError(f"{browser} is not installed on this computer")
    try:
        (user_data_dir / "DevToolsActivePort").unlink()
    except OSError:
        pass
    flags: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL}
    flags["stderr"] = subprocess.DEVNULL
    if sys.platform == "win32":
        flags["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        flags["close_fds"] = True
    else:
        flags["start_new_session"] = True
    popen(
        [
            exe,
            "--remote-debugging-port=0",  # the browser picks a free port and writes it
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        **flags,
    )
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        live = endpoint(user_data_dir)
        if live:
            return f"127.0.0.1:{live[0]}"
        time.sleep(0.2)
    raise OwnBrowserError(f"{browser} did not open its debugging port in {wait_s:.0f} s")


# --- "mine": the browser the person has open -----------------------------------------------


class DevToolsShim:
    """Serves the ``/json/version`` and ``/json/list`` ChromeDriver asks for before it
    attaches, for a browser that only exposes its WebSocket (``chrome://inspect`` mode).

    Holds ONE connection to the browser for its whole life: the browser asks "Allow?" when
    a client connects with none open, so while the shim lives, ChromeDriver reconnecting
    does not ask again. Also answers who opened a tab (:meth:`opener`).
    """

    def __init__(
        self,
        port: int,
        path: str,
        *,
        connect: Callable[..., Any] | None = None,
        consent_timeout: float = CONSENT_TIMEOUT_S,
    ) -> None:
        self.browser_url = f"ws://127.0.0.1:{port}{path}"
        self._port = port
        self._connect = connect
        self._timeout = consent_timeout
        self._ws: Any = None
        self._server: ThreadingHTTPServer | None = None
        self._lock = threading.Lock()
        self._next = 0

    def start(self) -> str:
        """Connect (the person allows it on the browser) and serve; returns the address
        to give ChromeDriver as ``debuggerAddress``."""
        connect = self._connect
        if connect is None:
            import websocket

            connect = websocket.create_connection
        try:
            # no Origin header: the browser refuses a WebSocket that has an unknown one
            self._ws = connect(self.browser_url, timeout=self._timeout, suppress_origin=True)
        except Exception as exc:  # noqa: BLE001 -- refused, timed out or closed
            raise OwnBrowserError(
                "the browser did not allow the connection (click Allow when it asks)"
            ) from exc
        self._ws.settimeout(30)
        shim = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, body: Any) -> None:
                data = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:  # noqa: N802
                try:
                    if self.path.startswith("/json/version"):
                        return self._send(shim.version())
                    if self.path.startswith("/json"):
                        return self._send(shim.targets())
                except Exception:  # noqa: BLE001 -- the browser went away
                    self.send_response(502)
                    self.end_headers()
                    return None
                self.send_response(404)
                self.end_headers()
                return None

            do_PUT = do_GET

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(
            target=self._server.serve_forever, name="devtools-shim", daemon=True
        ).start()
        return f"127.0.0.1:{self._server.server_address[1]}"

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._next += 1
            ident = self._next
            self._ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
            while True:
                message = json.loads(self._ws.recv())
                if message.get("id") == ident:
                    if "error" in message:
                        raise OwnBrowserError(str(message["error"]))
                    result: dict[str, Any] = message.get("result") or {}
                    return result

    def version(self) -> dict[str, str]:
        v = self.call("Browser.getVersion")
        revision = str(v.get("revision", "")).lstrip("@")
        return {
            "Browser": v.get("product", ""),
            "Protocol-Version": v.get("protocolVersion", ""),
            "User-Agent": v.get("userAgent", ""),
            "V8-Version": v.get("jsVersion", ""),
            # ChromeDriver parses this one: "537.36 (@<revision>)"
            "WebKit-Version": f"537.36 (@{revision})",
            "webSocketDebuggerUrl": self.browser_url,
        }

    def targets(self) -> list[dict[str, str]]:
        infos = self.call("Target.getTargets").get("targetInfos") or []
        return [
            {
                "id": t["targetId"],
                "type": t["type"],
                "title": t.get("title", ""),
                "url": t.get("url", ""),
                "webSocketDebuggerUrl": (
                    f"ws://127.0.0.1:{self._port}/devtools/{t['type']}/{t['targetId']}"
                ),
            }
            for t in infos
            if t.get("type") in ("page", "iframe", "service_worker", "worker", "other")
        ]

    def opener(self, target_id: str) -> str | None:
        """The tab that opened *target_id* (``None``: the person opened it)."""
        try:
            infos = self.call("Target.getTargets").get("targetInfos") or []
        except Exception:  # noqa: BLE001
            return None
        for t in infos:
            if t.get("targetId") == target_id:
                return t.get("openerId") or None
        return None

    def close(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None


def find_open(
    order: tuple[Browser, ...] = BROWSERS,
    *,
    folder: Callable[[Browser], Path] = profile_dir,
    live: Callable[[Path], tuple[int, str] | None] = endpoint,
) -> tuple[Browser, int, str] | None:
    """The first of *order* that is open with remote debugging allowed."""
    for browser in order:
        found = live(folder(browser))
        if found:
            return browser, found[0], found[1]
    return None


def mine_engine(order: tuple[Browser, ...] = BROWSERS) -> Browser:
    """Which browser ``--cdp mine`` will use: the open one with debugging allowed, else
    the first installed (the error then says how to turn it on)."""
    found = find_open(order)
    if found:
        return found[0]
    return pick(order) or order[0]


def connect_mine(engine: Browser) -> tuple[str, DevToolsShim]:
    """The person's open *engine*: starts the shim; ``(debuggerAddress, shim)``."""
    found = endpoint(profile_dir(engine))
    if found is None:
        page = (
            "chrome://inspect/#remote-debugging"
            if engine == "chrome"
            else ("edge://inspect/#remote-debugging")
        )
        raise OwnBrowserError(
            f"{engine} is not open with remote debugging allowed: open it and turn on "
            f"'Allow remote debugging' in {page}"
        )
    shim = DevToolsShim(*found)
    return shim.start(), shim
