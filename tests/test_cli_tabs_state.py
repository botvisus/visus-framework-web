"""Tab handle targeting, tab-follow mode, storage state, and session-start options."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


@pytest.mark.browser
def test_tab_follow_off_keeps_the_context_on_the_current_tab() -> None:
    """With follow off, a newly-opened window must NOT steal the session context."""
    h = session_server.SessionHandler(
        engine="chrome",
        headless=True,
        url="data:text/html,<button id=firstbtn>First</button>",
    )
    try:
        first = h.handle("list_fields", {"highlight": False})
        assert "#firstbtn" in {f["locator"] for f in first["result"]["fields"]}

        assert h.handle("tab_follow", {"enabled": False})["result"] == {"follow": False}

        driver = h._page._delegate._driver  # type: ignore[attr-defined]
        driver.switch_to.new_window("tab")
        driver.get("data:text/html,<button id=secondbtn>Second</button>")

        stayed = h.handle("list_fields", {"highlight": False})
        assert "#firstbtn" in {f["locator"] for f in stayed["result"]["fields"]}

        # Re-enabling follow adopts the newest tab again.
        assert h.handle("tab_follow", {"enabled": True})["result"] == {"follow": True}
        driver.switch_to.new_window("tab")
        driver.get("data:text/html,<button id=thirdbtn>Third</button>")
        followed = h.handle("list_fields", {"highlight": False})
        assert "#thirdbtn" in {f["locator"] for f in followed["result"]["fields"]}
    finally:
        h.close()


@pytest.mark.browser
def test_tab_activate_by_handle_survives_index_shift() -> None:
    h = session_server.SessionHandler(
        engine="chrome",
        headless=True,
        url="data:text/html,<button id=firstbtn>First</button>",
    )
    try:
        h.handle("list_fields", {"highlight": False})
        tabs = h.handle("tabs", {})["result"]["tabs"]
        first_handle = tabs[0]["handle"]

        driver = h._page._delegate._driver  # type: ignore[attr-defined]
        driver.switch_to.new_window("tab")
        driver.get("data:text/html,<button id=secondbtn>Second</button>")
        h.handle("list_fields", {"highlight": False})  # auto-follows tab 1

        back = h.handle("tab_activate", {"handle": first_handle})
        assert back["ok"] is True, back
        assert back["result"]["handle"] == first_handle
        fields = h.handle("list_fields", {"highlight": False})["result"]["fields"]
        assert "#firstbtn" in {f["locator"] for f in fields}

        bad = h.handle("tab_activate", {"handle": "no-such-handle"})
        assert bad["ok"] is False and "no open tab" in bad["error"]
    finally:
        h.close()


def test_cli_tab_activate_and_tab_follow(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        if op == "tab_activate":
            return {"active": 0, "handle": "H1", "title": "First"}
        return {"follow": args["enabled"] if args else True}

    monkeypatch.setattr(session_client, "send", fake_send)
    r1 = runner.invoke(app, ["tab-activate", "H1"])
    assert r1.exit_code == 0 and "H1" in r1.output
    r2 = runner.invoke(app, ["tab-follow", "--off"])
    assert r2.exit_code == 0 and "manual" in r2.output
    r3 = runner.invoke(app, ["tab-follow", "--on"])
    assert r3.exit_code == 0 and "auto" in r3.output
    assert calls[0] == ("tab_activate", {"handle": "H1"})
    assert calls[1] == ("tab_follow", {"enabled": False})
    assert calls[2] == ("tab_follow", {"enabled": True})


def test_repl_tab_activate_and_tab_follow() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "tab_activate":
            return {"active": 1, "handle": "H2", "title": "T"}
        return {"follow": args["enabled"]}

    console.dispatch("tab-activate H2", send)
    console.dispatch("tab-follow off", send)
    console.dispatch("tab-follow on", send)
    assert calls[0] == ("tab_activate", {"handle": "H2"})
    assert calls[1] == ("tab_follow", {"enabled": False})
    assert calls[2] == ("tab_follow", {"enabled": True})
    assert "tab-follow" in console.dispatch("help", send)


# ---------------------------------------------------------------------------
# storage state save / load
# ---------------------------------------------------------------------------


@pytest.mark.browser
def test_state_save_then_load_round_trips_local_storage(
    base_url: str, tmp_path: Path
) -> None:
    """A saved snapshot restores localStorage into a fresh session — the login-reuse flow."""
    state_file = tmp_path / "state.json"
    first = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/storage.html"
    )
    try:
        first.handle(
            "eval", {"expression": "() => localStorage.setItem('token', 'saved-value')"}
        )
        saved = first.handle("state_save", {"path": str(state_file)})
        assert saved["ok"] is True, saved
        assert saved["result"]["path"] == str(state_file.resolve())
        assert saved["result"]["origins"] >= 1
    finally:
        first.close()

    doc = json.loads(state_file.read_text(encoding="utf-8"))
    assert any(
        any(item["name"] == "token" and item["value"] == "saved-value"
            for item in origin.get("localStorage", []))
        for origin in doc.get("origins", [])
    ), doc

    second = session_server.SessionHandler(
        engine="chrome", headless=True, url=f"{base_url}/storage.html"
    )
    try:
        # The fixture re-seeds 'seed-local' on every load; restoring overwrites it.
        loaded = second.handle("state_load", {"path": str(state_file)})
        assert loaded["ok"] is True, loaded
        value = second.handle(
            "eval", {"expression": "() => localStorage.getItem('token')"}
        )["result"]["result"]
        assert value == "saved-value"
    finally:
        second.close()


def test_cli_state_save_and_load_resolve_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_send(op: str, args: dict[str, Any] | None = None) -> Any:
        calls.append((op, args or {}))
        if op == "state_save":
            return {"path": (args or {}).get("path"), "cookies": 2, "origins": 1}
        return "restored storage state"

    monkeypatch.setattr(session_client, "send", fake_send)
    target = tmp_path / "auth.json"
    r1 = runner.invoke(app, ["state-save", str(target)])
    assert r1.exit_code == 0, r1.output
    r2 = runner.invoke(app, ["state-load", str(target)])
    assert r2.exit_code == 0
    assert calls[0] == ("state_save", {"path": str(target.resolve())})
    assert calls[1] == ("state_load", {"path": str(target.resolve())})


def test_cli_state_save_defaults_to_storage_state_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None: calls.append((op, args or {}))
        or {"path": (args or {}).get("path"), "cookies": 0, "origins": 0},
    )
    r = runner.invoke(app, ["state-save"])
    assert r.exit_code == 0
    assert calls[0][1]["path"].endswith("storage-state.json")


def test_repl_state_commands() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        return {"path": args.get("path"), "cookies": 1, "origins": 1}

    console.dispatch("state-save auth.json", send)
    console.dispatch("state-load auth.json", send)
    assert calls[0][0] == "state_save"
    assert calls[0][1]["path"] == str(Path("auth.json").resolve())
    assert calls[1][0] == "state_load"
    assert "state-save" in console.dispatch("help", send)
