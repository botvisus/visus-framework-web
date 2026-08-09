"""Profile and device emulation on `session start`, and `visus devices`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.api.devices import DEFAULT_MOBILE, DEVICES, get_device
from visus.web.cli import session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


def test_device_table_is_non_empty_and_well_formed() -> None:
    assert DEVICES, "the device table must not be empty"
    for key, device in DEVICES.items():
        assert key == key.lower(), f"{key!r} must be lower-case for lookup"
        assert device.width > 0 and device.height > 0
        assert device.device_scale_factor > 0
        assert isinstance(device.mobile, bool)


def test_get_device_is_case_and_space_insensitive() -> None:
    assert get_device("iPhone 15").mobile is True
    assert get_device("  iphone 15 ") == get_device("iPhone 15")


def test_default_mobile_device_exists_and_is_mobile() -> None:
    assert get_device(DEFAULT_MOBILE).mobile is True


def test_unknown_device_lists_the_known_ones() -> None:
    with pytest.raises(ValueError) as excinfo:
        get_device("Nokia 3310")
    message = str(excinfo.value)
    assert "Nokia 3310" in message
    assert get_device(DEFAULT_MOBILE).name in message


def test_handler_applies_device_metrics_before_the_initial_goto(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first load must already see the mobile viewport."""
    order: list[str] = []

    class _Page:
        def set_device_metrics(
            self, width: int, height: int, *, device_scale_factor: float, mobile: bool
        ) -> None:
            order.append(f"metrics:{width}x{height}@{device_scale_factor}:{mobile}")

        def goto(self, url: str) -> None:
            order.append(f"goto:{url}")

    class _Browser:
        def new_page(self) -> _Page:
            return _Page()

        def close(self) -> None: ...

    monkeypatch.setattr(session_server, "launch", lambda engine, **kw: _Browser())
    device = get_device("iPhone 15")
    h = session_server.SessionHandler(
        engine="chrome", headless=True, url="http://x", device="iPhone 15"
    )
    h._ensure()
    assert order == [
        f"metrics:{device.width}x{device.height}@{device.device_scale_factor}:True",
        "goto:http://x",
    ]


def test_handler_without_a_device_never_touches_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _Page:
        def set_device_metrics(self, *a: Any, **kw: Any) -> None:
            calls.append("metrics")

        def goto(self, url: str) -> None: ...

    class _Browser:
        def new_page(self) -> _Page:
            return _Page()

        def close(self) -> None: ...

    monkeypatch.setattr(session_server, "launch", lambda engine, **kw: _Browser())
    session_server.SessionHandler(engine="chrome", headless=True, url="http://x")._ensure()
    assert calls == []


def test_status_reports_the_device() -> None:
    from test_cli_session import _FakePage, _handler_with_fake_page

    h = _handler_with_fake_page(_FakePage())
    h._device = "iPhone 15"
    assert h.handle("status", {})["result"]["device"] == "iPhone 15"


def test_daemon_main_reads_the_device_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built: dict[str, Any] = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VISUS_WEB_DEVICE", "Pixel 7")
    monkeypatch.setattr(session_server, "SessionHandler", lambda **kw: built.update(kw))
    monkeypatch.setattr(session_server, "serve", lambda handler, **kw: None)
    session_server.main(["chrome", "1", ""])
    assert built["device"] == "Pixel 7"


def test_cli_persistent_uses_the_managed_profile_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(kw) or {"pid": 1, "port": 2},
    )
    r = runner.invoke(app, ["-S", "auth", "session", "start", "--persistent"])
    assert r.exit_code == 0, r.output
    assert Path(captured["user_data_dir"]) == session_client.profile_dir(tmp_path, "auth")


def test_cli_profile_is_a_spelling_of_user_data_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(kw) or {"pid": 1, "port": 2},
    )
    assert runner.invoke(app, ["session", "start", "--profile", "/p/x"]).exit_code == 0
    assert captured["user_data_dir"] == "/p/x"
    assert runner.invoke(app, ["session", "start", "--user-data-dir", "/p/y"]).exit_code == 0
    assert captured["user_data_dir"] == "/p/y"


def test_cli_persistent_and_profile_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "start_daemon", lambda *a, **kw: {"pid": 1, "port": 2})
    r = runner.invoke(app, ["session", "start", "--persistent", "--profile", "/p/x"])
    assert r.exit_code == 1


def test_cli_browser_is_a_spelling_of_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(engine=e) or {"pid": 1, "port": 2},
    )
    assert runner.invoke(app, ["session", "start", "--browser", "edge"]).exit_code == 0
    assert captured["engine"] == "edge"


def test_cli_mobile_selects_the_default_device(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(kw) or {"pid": 1, "port": 2},
    )
    assert runner.invoke(app, ["session", "start", "--mobile"]).exit_code == 0
    assert captured["device"] == DEFAULT_MOBILE


def test_cli_device_wins_over_mobile(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(kw) or {"pid": 1, "port": 2},
    )
    r = runner.invoke(app, ["session", "start", "--mobile", "--device", "Pixel 7"])
    assert r.exit_code == 0, r.output
    assert captured["device"] == "Pixel 7"


def test_cli_rejects_an_unknown_device(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "start_daemon", lambda *a, **kw: {"pid": 1, "port": 2})
    r = runner.invoke(app, ["session", "start", "--device", "Nokia 3310"])
    assert r.exit_code == 1


def test_cli_rejects_a_device_on_a_non_chromium_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """set_device_metrics is a CDP call — fail at start, not on the first action."""
    monkeypatch.setattr(session_client, "start_daemon", lambda *a, **kw: {"pid": 1, "port": 2})
    r = runner.invoke(app, ["session", "start", "--engine", "firefox", "--mobile"])
    assert r.exit_code == 1


def test_cli_devices_lists_the_table() -> None:
    r = runner.invoke(app, ["devices"])
    assert r.exit_code == 0, r.output
    for device in DEVICES.values():
        assert device.name in r.output


def test_cli_devices_json() -> None:
    r = runner.invoke(app, ["--json", "devices"])
    assert r.exit_code == 0, r.output
    names = {row["name"] for row in json.loads(r.output)}
    assert {d.name for d in DEVICES.values()} == names
