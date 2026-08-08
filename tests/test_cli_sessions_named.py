"""Named sessions, the cross-project registry, and fleet management.

Every test is isolated: session state under ``tmp_path``, the global registry
under ``VISUS_WEB_HOME``. Nothing ever writes into the developer's real
``~/.visus`` or into the repo root.

The shared fakes are imported as ``from test_cli_session import ...`` (no
``tests.`` prefix): ``tests/`` has no ``__init__.py``, so pytest's default
prepend import mode puts ``tests/`` itself on ``sys.path`` and every test module
is a top-level module. The same spelling is used throughout this plan.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the global session registry at tmp_path and clear any pinned name."""
    monkeypatch.setenv("VISUS_WEB_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("VISUS_WEB_SESSION", raising=False)
    session_client.set_session_name(None)


def test_session_file_defaults_to_the_default_name(tmp_path: Path) -> None:
    sf = session_server.session_file(tmp_path)
    assert sf == tmp_path / ".visus" / "sessions" / "default.json"
    assert session_server.sessions_dir(tmp_path) == tmp_path / ".visus" / "sessions"


def test_session_file_is_namespaced(tmp_path: Path) -> None:
    assert (
        session_server.session_file(tmp_path, "auth")
        == tmp_path / ".visus" / "sessions" / "auth.json"
    )


def test_lock_name_follows_the_session_name(tmp_path: Path) -> None:
    """PLAN 3's _claim_lock is unchanged — the lock name falls out of the path."""
    sf = session_server.session_file(tmp_path, "auth")
    sf.parent.mkdir(parents=True, exist_ok=True)
    lock = session_server._claim_lock(sf)
    assert lock.name == "auth.json.lock"
    lock.unlink()


@pytest.mark.parametrize(
    "bad", ["", "../escape", "a/b", "a\\b", ".hidden", "x" * 65, "with space", "sess:1"]
)
def test_invalid_session_names_are_refused(bad: str) -> None:
    with pytest.raises(session_client.SessionError, match="invalid session name"):
        session_client.validate_session_name(bad)


@pytest.mark.parametrize("good", ["default", "auth", "a", "site-1", "v1.2_x", "A9"])
def test_valid_session_names_are_accepted(good: str) -> None:
    assert session_client.validate_session_name(good) == good


def test_session_name_resolution_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """explicit argument > `-S` (set_session_name) > VISUS_WEB_SESSION > "default"."""
    assert session_client.session_name() == "default"

    monkeypatch.setenv("VISUS_WEB_SESSION", "from-env")
    assert session_client.session_name() == "from-env"

    session_client.set_session_name("from-flag")
    assert session_client.session_name() == "from-flag"
    assert session_client.session_name("explicit") == "explicit"

    session_client.set_session_name(None)
    assert session_client.session_name() == "from-env"


def test_find_session_is_namespaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two names in one directory are two independent sessions."""
    import socket as _socket

    srv = _socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        sessions = tmp_path / ".visus" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "auth.json").write_text(
            json.dumps({"pid": 1, "port": port, "token": "t-auth"}), encoding="utf-8"
        )
        monkeypatch.setattr(session_client, "_pid_alive", lambda pid: True)
        assert session_client.find_session(tmp_path, "auth")["token"] == "t-auth"
        assert session_client.find_session(tmp_path, "public") is None
        assert session_client.find_session(tmp_path) is None  # "default" is a third name
    finally:
        srv.close()


def test_start_daemon_refusal_names_the_file_it_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old message never said WHERE — so a parent-directory session looked silent."""
    sf = tmp_path / ".visus" / "sessions" / "default.json"
    monkeypatch.setattr(
        session_client,
        "find_session",
        lambda base, name=None: {"pid": 7, "port": 8, "token": "t", "_file": str(sf)},
    )
    with pytest.raises(session_client.SessionError) as excinfo:
        session_client.start_daemon("chrome", True, None, cwd=tmp_path)
    message = str(excinfo.value)
    assert "already running" in message
    assert str(sf) in message, message
    assert "--session" in message, message


def test_start_daemon_exports_the_session_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class _FakePopen:
        def __init__(self, *a: Any, **kw: Any) -> None:
            captured["env"] = kw["env"]

    monkeypatch.setattr(session_client, "find_session", lambda base, name=None: None)
    monkeypatch.setattr(session_client.subprocess, "Popen", _FakePopen)
    with pytest.raises(session_client.SessionError):
        session_client.start_daemon("chrome", True, None, cwd=tmp_path, timeout=0.2, name="auth")
    assert captured["env"]["VISUS_WEB_SESSION"] == "auth"


def test_serve_writes_the_named_session_file(tmp_path: Path) -> None:
    import threading as _threading
    import time as _time

    from test_cli_session import _FakePage, _handler_with_fake_page, _shutdown_thread

    handler = _handler_with_fake_page(_FakePage())
    t = _threading.Thread(
        target=session_server.serve,
        kwargs={"handler": handler, "token": "tok", "cwd": tmp_path, "name": "auth"},
        daemon=True,
    )
    t.start()
    sf = session_server.session_file(tmp_path, "auth")
    port = 0
    for _ in range(200):
        if sf.is_file():
            break
        _time.sleep(0.02)
    try:
        assert sf.is_file()
        info = json.loads(sf.read_text(encoding="utf-8"))
        assert info["name"] == "auth"
        assert Path(info["cwd"]) == tmp_path.resolve()
        port = int(info["port"])
    finally:
        _shutdown_thread(t, port, "tok")
    assert not sf.is_file()
    assert not sf.with_name("auth.json.lock").exists()


def test_daemon_main_reads_the_session_name_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served: dict[str, Any] = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VISUS_WEB_SESSION", "auth")
    monkeypatch.setattr(session_server, "SessionHandler", lambda **kw: object())
    monkeypatch.setattr(session_server, "serve", lambda handler, **kw: served.update(kw))
    session_server.main(["chrome", "1", ""])
    assert served["name"] == "auth"


def test_cli_root_accepts_the_session_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str | None] = []
    monkeypatch.setattr(session_client, "set_session_name", seen.append)
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: "Dashboard")
    r = runner.invoke(app, ["-S", "auth", "title"])
    assert r.exit_code == 0, r.output
    assert seen == ["auth"]


def test_cli_session_flag_is_capital_s_only() -> None:
    """`-s` must stay `--selector`: 21 commands already bind it."""
    r = runner.invoke(app, ["--help"])
    assert r.exit_code == 0
    assert "-S" in r.output and "--session" in r.output
    r2 = runner.invoke(app, ["click", "--help"])
    assert r2.exit_code == 0
    assert "-s" in r2.output and "--selector" in r2.output
