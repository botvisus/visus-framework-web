"""Attaching to a browser visus did not launch, and releasing it again."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web import errors, launch
from visus.web.backends.browsers import chrome, edge, edge_ie, firefox
from visus.web.cli import session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


def test_chrome_options_attach_and_drop_launch_arguments(tmp_path: Path) -> None:
    """Chrome ignores launch flags when attaching, and chromedriver rejects some."""
    opts = chrome.build_options(
        headless=True,
        download_dir=str(tmp_path),
        user_data_dir=str(tmp_path / "p"),
        debugger_address="127.0.0.1:9222",
    )
    assert opts.experimental_options["debuggerAddress"] == "127.0.0.1:9222"
    assert opts.arguments == []
    assert "prefs" not in opts.experimental_options


def test_edge_options_attach(tmp_path: Path) -> None:
    opts = edge.build_options(
        headless=False,
        download_dir=str(tmp_path),
        user_data_dir=str(tmp_path / "p"),
        debugger_address="localhost:9333",
    )
    assert opts.experimental_options["debuggerAddress"] == "localhost:9333"
    assert opts.arguments == []


def test_chrome_options_unchanged_without_a_debugger_address(tmp_path: Path) -> None:
    opts = chrome.build_options(
        headless=True, download_dir=str(tmp_path), user_data_dir=str(tmp_path / "p")
    )
    assert "--headless=new" in opts.arguments
    assert any(a.startswith("--user-data-dir=") for a in opts.arguments)
    assert "debuggerAddress" not in opts.experimental_options


@pytest.mark.parametrize("module", [firefox, edge_ie])
def test_non_chromium_option_builders_refuse_to_attach(module: Any, tmp_path: Path) -> None:
    with pytest.raises(errors.UnsupportedEngineError, match="chrome or edge"):
        module.build_options(
            headless=True,
            download_dir=str(tmp_path),
            user_data_dir=str(tmp_path / "p"),
            debugger_address="127.0.0.1:9222",
        )


def test_launch_refuses_a_debugger_address_on_a_non_chromium_engine() -> None:
    """Fail before spawning anything, with the engine named."""
    with pytest.raises(errors.UnsupportedEngineError, match="chrome or edge"):
        launch("firefox", debugger_address="127.0.0.1:9222")


class _FakeService:
    def __init__(self) -> None:
        self.stopped = 0

    def stop(self) -> None:
        self.stopped += 1


class _FakeDriver:
    def __init__(self) -> None:
        self.quit_calls = 0
        self.service = _FakeService()

    @property
    def current_window_handle(self) -> str:
        return "CDwindow-1"

    def quit(self) -> None:
        self.quit_calls += 1


def _delegate(tmp_path: Path, driver: _FakeDriver) -> Any:
    from visus.web.backends.base import BrowserConfig
    from visus.web.backends.selenium_backend import SeleniumBrowserDelegate
    from visus.web.engine import Engine

    config = BrowserConfig(
        engine=Engine.CHROME,
        options_factory=lambda **k: None,
        service_factory=lambda: None,
        driver_factory=lambda **k: driver,
    )
    profile = tmp_path / "profile"
    downloads = tmp_path / "downloads"
    profile.mkdir()
    downloads.mkdir()
    return SeleniumBrowserDelegate(
        driver,
        str(profile),
        str(downloads),
        config=config,
        headless=True,
    )


def test_detach_stops_the_driver_process_and_never_quits(tmp_path: Path) -> None:
    """quit() may close a browser visus only attached to — stop the driver instead."""
    driver = _FakeDriver()
    delegate = _delegate(tmp_path, driver)
    delegate.detach()
    assert driver.quit_calls == 0, "detach() closed the user's browser"
    assert driver.service.stopped == 1
    assert not (tmp_path / "downloads").exists()


def test_detach_is_idempotent_and_disables_dispose(tmp_path: Path) -> None:
    driver = _FakeDriver()
    delegate = _delegate(tmp_path, driver)
    delegate.detach()
    delegate.detach()
    delegate.dispose()
    assert driver.quit_calls == 0
    assert driver.service.stopped == 1


def test_dispose_still_quits_a_browser_visus_launched(tmp_path: Path) -> None:
    driver = _FakeDriver()
    delegate = _delegate(tmp_path, driver)
    delegate.dispose()
    assert driver.quit_calls == 1


def test_browser_detach_delegates(tmp_path: Path) -> None:
    from visus.web.api.browser import Browser
    from visus.web.config import Defaults

    calls: list[str] = []

    class _Delegate:
        def new_context(self) -> Any: ...

        def contexts(self) -> list[Any]:
            return []

        def dispose(self) -> None:
            calls.append("dispose")

        def detach(self) -> None:
            calls.append("detach")

    Browser(_Delegate(), Defaults()).detach()  # type: ignore[arg-type]
    assert calls == ["detach"]


def test_handler_forwards_the_debugger_address(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class _Page:
        def goto(self, url: str) -> None: ...

    class _Browser:
        def new_page(self) -> _Page:
            return _Page()

        def close(self) -> None: ...

        def detach(self) -> None: ...

    def fake_launch(engine: Any, **kwargs: Any) -> _Browser:
        seen.update(kwargs)
        return _Browser()

    monkeypatch.setattr(session_server, "launch", fake_launch)
    h = session_server.SessionHandler(
        engine="chrome", headless=False, debugger_address="127.0.0.1:9222"
    )
    h._ensure()
    assert seen["debugger_address"] == "127.0.0.1:9222"
    assert h._attached is True


def test_handler_is_not_attached_by_default() -> None:
    h = session_server.SessionHandler(engine="chrome", headless=True)
    assert h._attached is False
    assert h.detached() is False


def test_status_reports_attached() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    h._attached = True
    assert h.handle("status", {})["result"]["attached"] is True


def test_op_detach_refuses_on_a_launched_session() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    resp = h.handle("detach", {})
    assert resp["ok"] is False
    assert "session attach" in resp["error"] and "session stop" in resp["error"]
    assert h.detached() is False


def test_op_detach_flags_the_session_and_sets_the_stop_event() -> None:
    import threading as _threading

    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    h._attached = True
    stop = _threading.Event()
    h.bind_stop(stop)
    resp = h.handle("detach", {})
    assert resp["ok"] is True
    assert "stays open" in resp["result"]
    assert h.detached() is True
    assert stop.is_set()


def test_release_detaches_the_browser_instead_of_closing_it() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    calls: list[str] = []

    class _Browser:
        @property
        def contexts(self) -> list[Any]:
            return []

        def close(self) -> None:
            calls.append("close")

        def detach(self) -> None:
            calls.append("detach")

    h = _handler_with_fake_page(_FakePage())
    h._browser = _Browser()  # type: ignore[assignment]
    h.release()
    assert calls == ["detach"]
    assert h._browser is None and h._page is None
    assert h._fields == [] and h._fields_url is None


def test_serve_releases_instead_of_closing_a_detached_session(tmp_path: Path) -> None:
    """The brief's contract: serve()'s finally must SKIP handler.close()."""
    import json as _json
    import socket as _socket
    import threading as _threading
    import time as _time

    from test_cli_session import _FakePage, _handler_with_fake_page

    calls: list[str] = []
    handler = _handler_with_fake_page(_FakePage())
    handler._attached = True

    class _Browser:
        @property
        def contexts(self) -> list[Any]:
            return []

        def close(self) -> None:
            calls.append("close")

        def detach(self) -> None:
            calls.append("detach")

    handler._browser = _Browser()  # type: ignore[assignment]

    t = _threading.Thread(
        target=session_server.serve,
        kwargs={"handler": handler, "token": "tok", "cwd": tmp_path},
        daemon=True,
    )
    t.start()
    sf = session_server.session_file(tmp_path)
    for _ in range(200):
        if sf.is_file():
            break
        _time.sleep(0.02)
    port = int(_json.loads(sf.read_text(encoding="utf-8"))["port"])

    with _socket.create_connection(("127.0.0.1", port), timeout=10) as sock:
        f = sock.makefile("rwb")
        f.write((_json.dumps({"token": "tok", "op": "detach"}) + "\n").encode("utf-8"))
        f.flush()
        assert _json.loads(f.readline().decode("utf-8"))["ok"] is True

    t.join(timeout=20)
    assert not t.is_alive(), "detach did not stop the daemon"
    assert calls == ["detach"], f"the browser was closed on detach: {calls}"
    assert not sf.is_file()


def test_daemon_main_reads_the_debugger_address_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: dict[str, Any] = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VISUS_WEB_DEBUGGER_ADDRESS", "127.0.0.1:9222")
    monkeypatch.setattr(session_server, "SessionHandler", lambda **kw: built.update(kw))
    monkeypatch.setattr(session_server, "serve", lambda handler, **kw: None)
    session_server.main(["chrome", "0", ""])
    assert built["debugger_address"] == "127.0.0.1:9222"


def test_start_daemon_exports_the_debugger_address(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class _FakePopen:
        def poll(self) -> None:  # o daemon de mentira não sai
            return None

        def __init__(self, *a: Any, **kw: Any) -> None:
            captured["env"] = kw["env"]

    monkeypatch.setattr(session_client, "find_session", lambda base, name=None: None)
    monkeypatch.setattr(session_client.subprocess, "Popen", _FakePopen)
    with pytest.raises(session_client.SessionError):
        session_client.start_daemon(
            "chrome", False, None, cwd=tmp_path, timeout=0.2, debugger_address="h:9222"
        )
    assert captured["env"]["VISUS_WEB_DEBUGGER_ADDRESS"] == "h:9222"


def test_cli_session_attach(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_start(engine: str, headless: bool, url: str | None, **kwargs: Any) -> dict[str, Any]:
        captured.update(engine=engine, headless=headless, url=url, **kwargs)
        return {"pid": 3, "port": 4}

    monkeypatch.setattr(session_client, "start_daemon", fake_start)
    r = runner.invoke(app, ["session", "attach", "--cdp", "127.0.0.1:9222"])
    assert r.exit_code == 0, r.output
    assert captured["debugger_address"] == "127.0.0.1:9222"
    assert captured["headless"] is False
    assert "attached" in r.output


def test_cli_session_attach_accepts_a_url_form(monkeypatch: pytest.MonkeyPatch) -> None:
    """`--cdp http://localhost:9222` is what a container prints — accept it."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(kw) or {"pid": 1, "port": 2},
    )
    r = runner.invoke(app, ["session", "attach", "--cdp", "http://localhost:9222"])
    assert r.exit_code == 0, r.output
    assert captured["debugger_address"] == "localhost:9222"


def test_cli_session_attach_refuses_a_non_chromium_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(session_client, "start_daemon", lambda *a, **kw: {"pid": 1, "port": 2})
    r = runner.invoke(
        app, ["session", "attach", "--cdp", "127.0.0.1:9222", "--engine", "firefox"]
    )
    assert r.exit_code == 1


def test_cli_session_detach(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(op=op) or "detached — the browser stays open",
    )
    r = runner.invoke(app, ["session", "detach"])
    assert r.exit_code == 0, r.output
    assert captured["op"] == "detach"
    assert "stays open" in r.output
