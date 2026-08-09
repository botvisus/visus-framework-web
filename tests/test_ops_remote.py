"""RemoteDispatcher: SessionHandler's contract, another process's browser."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from visus.web.cli import session_client
from visus.web.ops.remote import NoSessionError, RemoteDispatcher

_PAGE = "data:text/html,<title>remote</title><h1 id=h>hello</h1>"


def test_handle_returns_the_daemon_envelope_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The envelope is passed through untouched — `page`/`code` included."""
    calls: list[tuple[str, Any, Any]] = []
    env = {
        "ok": True,
        "result": "clicked",
        "page": {"url": "http://x/dash", "title": "Dash", "fields_stale": False},
        "code": 'page.get_by_role("button", name="Submit").click()',
    }

    def fake_send_envelope(op: str, args: Any = None, *, start_dir: Any = None) -> dict[str, Any]:
        calls.append((op, args, start_dir))
        return env

    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None: {"pid": 1})
    monkeypatch.setattr(session_client, "send_envelope", fake_send_envelope)

    d = RemoteDispatcher(start_dir="/proj")
    assert d.handle("click", {"index": 3}) == env
    assert calls == [("click", {"index": 3}, "/proj")]


def test_handle_turns_a_daemon_failure_back_into_an_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`SessionHandler.handle` never raises; neither may this."""

    def boom(op: str, args: Any = None, *, start_dir: Any = None) -> dict[str, Any]:
        raise session_client.SessionError("IndexError: field index 9 out of range")

    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None: {"pid": 1})
    monkeypatch.setattr(session_client, "send_envelope", boom)

    resp = RemoteDispatcher().handle("click", {"index": 9})
    assert resp["ok"] is False
    assert "field index 9 out of range" in resp["error"]


def test_is_live_and_session_are_false_when_nothing_is_running(tmp_path: Path) -> None:
    d = RemoteDispatcher(start_dir=tmp_path)
    assert d.session() is None
    assert d.is_live() is False


def test_result_raises_no_session_error_when_nothing_is_running(tmp_path: Path) -> None:
    d = RemoteDispatcher(start_dir=tmp_path)
    with pytest.raises(NoSessionError, match="visus session start"):
        d.result("title")


def test_result_raises_on_a_failed_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None: {"pid": 1})
    monkeypatch.setattr(
        session_client,
        "send_envelope",
        lambda op, args=None, **_: (_ for _ in ()).throw(session_client.SessionError("nope")),
    )
    with pytest.raises(RuntimeError, match="nope"):
        RemoteDispatcher().result("title")


@pytest.mark.browser
def test_remote_dispatcher_drives_a_real_daemon(tmp_path: Path) -> None:
    """The integration proof: a second process's browser, the same envelope."""
    session_client.start_daemon("chrome", headless=True, url=_PAGE, cwd=tmp_path)
    try:
        d = RemoteDispatcher(start_dir=tmp_path)
        assert d.is_live() is True
        assert d.handle("title")["result"] == "remote"
        assert d.result("get_text", {"selector": "#h"})["value"] == "hello"

        # A mutating op comes back with PLAN 4's page footer, unchanged.
        env = d.handle("goto", {"url": "data:text/html,<title>second</title>"})
        assert env["ok"] is True
        assert env["page"]["title"] == "second"

        # A failing op is an envelope, not an exception.
        bad = d.handle("click", {"index": 42})
        assert bad["ok"] is False and "out of range" in bad["error"]
    finally:
        session_client.stop(start_dir=tmp_path)
