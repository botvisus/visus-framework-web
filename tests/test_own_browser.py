"""O navegador da pessoa (Chrome, senão Edge) sem driver abrindo o navegador."""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from visus.web import own_browser as ob


def test_chrome_first_then_edge() -> None:
    assert ob.pick(find=lambda b: "x" if b == "edge" else None) == "edge"
    assert ob.pick(find=lambda b: "x") == "chrome"
    assert ob.pick(find=lambda b: None) is None


def test_the_installed_browser_on_windows(tmp_path: Path) -> None:
    exe = tmp_path / "Microsoft/Edge/Application/msedge.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")
    env = {"PROGRAMFILES(X86)": str(tmp_path)}
    assert ob.executable("edge", platform="win32", env=env) == str(exe)
    assert ob.executable("chrome", platform="win32", env=env) is None


def test_the_profile_folder_of_each_system() -> None:
    win = ob.profile_dir("chrome", platform="win32", env={"LOCALAPPDATA": "C:/L"})
    assert win == Path("C:/L/Google/Chrome/User Data")
    mac = ob.profile_dir("edge", platform="darwin", env={"HOME": "/h"})
    assert mac == Path("/h/Library/Application Support/Microsoft Edge")
    assert ob.profile_dir("chrome", platform="linux", env={"HOME": "/h"}) == Path(
        "/h/.config/google-chrome"
    )


def test_the_endpoint_only_while_the_browser_listens(tmp_path: Path) -> None:
    assert ob.endpoint(tmp_path) is None
    (tmp_path / "DevToolsActivePort").write_text("9222\n/devtools/browser/abc")
    assert ob.endpoint(tmp_path, listening=lambda port: True) == (9222, "/devtools/browser/abc")
    assert ob.endpoint(tmp_path, listening=lambda port: False) is None, "o arquivo fica"


def _state(folder: Path, data: dict[str, Any]) -> None:
    (folder / "Local State").write_text(json.dumps(data), encoding="utf-8")


def test_the_switch_is_turned_on_only_with_the_browser_closed(tmp_path: Path) -> None:
    assert ob.enable_remote_debugging("chrome", user_data_dir=tmp_path) == "missing"
    _state(tmp_path, {"browser": {"x": 1}})
    opened = ob.enable_remote_debugging("chrome", user_data_dir=tmp_path, running=lambda b: True)
    assert opened == "running", "aberto, ele regravaria o arquivo ao fechar"
    assert not ob.remote_debugging_enabled(tmp_path)
    closed = ob.enable_remote_debugging("chrome", user_data_dir=tmp_path, running=lambda b: False)
    assert closed == "enabled" and ob.remote_debugging_enabled(tmp_path)
    state = json.loads((tmp_path / "Local State").read_text(encoding="utf-8"))
    assert state["browser"] == {"x": 1}, "o resto do arquivo fica igual"
    again = ob.enable_remote_debugging("chrome", user_data_dir=tmp_path, running=lambda b: True)
    assert again == "already"


def test_the_visus_browser_is_launched_without_a_driver(tmp_path: Path) -> None:
    started: list[list[str]] = []

    def popen(argv: list[str], **kw: Any) -> None:
        started.append(argv)
        (tmp_path / "DevToolsActivePort").write_text("5555\n/devtools/browser/x")

    import socket

    with socket.socket() as srv:  # um "navegador" escutando na porta
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]

        def popen_port(argv: list[str], **kw: Any) -> None:
            started.append(argv)
            (tmp_path / "DevToolsActivePort").write_text(f"{port}\n/devtools/browser/x")

        address = ob.launch("chrome", tmp_path, find=lambda b: "chrome.exe", popen=popen_port)
        assert address == f"127.0.0.1:{port}"
        (argv,) = started
        assert argv[0] == "chrome.exe" and "--remote-debugging-port=0" in argv
        assert f"--user-data-dir={tmp_path}" in argv
        assert not any("enable-automation" in a for a in argv)
        again = ob.launch("chrome", tmp_path, find=lambda b: "chrome.exe", popen=popen)
        assert again == address and len(started) == 1, "o que já está aberto é reaproveitado"


def test_no_browser_installed_says_so(tmp_path: Path) -> None:
    with pytest.raises(ob.OwnBrowserError, match="not installed"):
        ob.launch("edge", tmp_path, find=lambda b: None)


class _Ws:
    """O WebSocket do navegador, de mentira: responde o que o shim pergunta."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self._replies: list[str] = []
        self.closed = False

    def settimeout(self, t: float) -> None:
        pass

    def send(self, raw: str) -> None:
        msg = json.loads(raw)
        self.sent.append(msg)
        result: dict[str, Any] = {}
        if msg["method"] == "Browser.getVersion":
            result = {
                "product": "Chrome/157.0",
                "protocolVersion": "1.3",
                "userAgent": "UA",
                "jsVersion": "13",
                "revision": "@abc123",
            }
        elif msg["method"] == "Target.getTargets":
            result = {
                "targetInfos": [
                    {"targetId": "A", "type": "page", "title": "da pessoa", "url": "u"},
                    {"targetId": "B", "type": "page", "url": "v", "openerId": "A"},
                ]
            }
        self._replies.append(json.dumps({"id": msg["id"], "result": result}))

    def recv(self) -> str:
        return self._replies.pop(0)

    def close(self) -> None:
        self.closed = True


def test_the_shim_gives_chromedriver_what_it_asks() -> None:
    ws = _Ws()
    seen: dict[str, Any] = {}

    def connect(url: str, **kw: Any) -> _Ws:
        seen.update(url=url, **kw)
        return ws

    shim = ob.DevToolsShim(9222, "/devtools/browser/abc", connect=connect)
    address = shim.start()
    try:
        assert seen["url"] == "ws://127.0.0.1:9222/devtools/browser/abc"
        assert seen["suppress_origin"] is True
        with urllib.request.urlopen(f"http://{address}/json/version") as r:  # noqa: S310
            version = json.load(r)
        assert version["webSocketDebuggerUrl"] == "ws://127.0.0.1:9222/devtools/browser/abc"
        assert version["WebKit-Version"] == "537.36 (@abc123)", "o formato que o ChromeDriver lê"
        with urllib.request.urlopen(f"http://{address}/json/list") as r:  # noqa: S310
            pages = json.load(r)
        assert [p["id"] for p in pages] == ["A", "B"]
        assert pages[0]["webSocketDebuggerUrl"] == "ws://127.0.0.1:9222/devtools/page/A"
        assert shim.opener("B") == "A" and shim.opener("A") is None
    finally:
        shim.close()
    assert ws.closed


def test_a_refused_connection_says_to_allow_it() -> None:
    def refuse(url: str, **kw: Any) -> Any:
        raise ConnectionError("403 Connection rejected")

    with pytest.raises(ob.OwnBrowserError, match="Allow"):
        ob.DevToolsShim(9222, "/x", connect=refuse).start()


def test_mine_is_the_open_browser_with_debugging_allowed(tmp_path: Path) -> None:
    folders = {"chrome": tmp_path / "c", "edge": tmp_path / "e"}
    live = {folders["edge"]: (60263, "/devtools/browser/e")}
    found = ob.find_open(folder=lambda b: folders[b], live=lambda f: live.get(f))
    assert found == ("edge", 60263, "/devtools/browser/e")
    live[folders["chrome"]] = (9222, "/devtools/browser/c")
    found = ob.find_open(folder=lambda b: folders[b], live=lambda f: live.get(f))
    assert found is not None and found[0] == "chrome", "o Chrome primeiro"


def test_in_the_persons_browser_the_agent_never_takes_their_tab() -> None:
    """Só a aba aberta POR uma aba do agente é seguida; a que a pessoa abriu, nunca."""
    from visus.web.cli.session_server import SessionHandler

    class _Shim:
        def opener(self, handle: str) -> str | None:
            return {"POPUP": "AGENT"}.get(handle)

    handler = SessionHandler(engine="chrome", headless=False, debugger_address="mine")
    handler._shim = _Shim()
    handler._own_tabs = {"AGENT"}
    handler._known_handles = ["PERSON", "AGENT"]
    handler._active_handle = "AGENT"
    assert handler._resolve_active(["PERSON", "AGENT", "NEWTAB"]) == "AGENT", "a da pessoa"
    assert handler._resolve_active(["PERSON", "AGENT", "NEWTAB", "POPUP"]) == "POPUP"
    assert handler.attached, "conectada: soltar, nunca fechar"
