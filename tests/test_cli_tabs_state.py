"""Tab handle targeting, tab-follow mode, storage state, and session-start options."""

from __future__ import annotations

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
