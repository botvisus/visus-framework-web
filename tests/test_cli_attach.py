"""Attaching to a browser visus did not launch, and releasing it again."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from visus.web import errors, launch
from visus.web.backends.browsers import chrome, edge, edge_ie, firefox


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
