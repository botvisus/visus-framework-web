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
        def poll(self) -> None:  # o daemon de mentira não sai
            return None

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


def _registry_entry(tmp_path: Path, name: str, cwd: Path, port: int, pid: int) -> Path:
    """Write a registry mirror by hand, exactly as serve() would."""
    reg = session_server.registry_file(cwd, name)
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(
        json.dumps(
            {
                "name": name,
                "cwd": str(cwd),
                "file": str(session_server.session_file(cwd, name)),
                "pid": pid,
                "port": port,
                "engine": "chrome",
                "headless": True,
                "url": "http://x",
            }
        ),
        encoding="utf-8",
    )
    return reg


def test_registry_paths_are_keyed_by_cwd_and_name(tmp_path: Path) -> None:
    a = session_server.registry_file(tmp_path / "proj-a", "default")
    b = session_server.registry_file(tmp_path / "proj-b", "default")
    c = session_server.registry_file(tmp_path / "proj-a", "auth")
    assert a.parent == session_server.registry_dir()
    assert a != b, "two projects must not share a registry entry"
    assert a != c, "two names in one project must not share a registry entry"
    assert a.name.endswith("-default.json") and c.name.endswith("-auth.json")


def test_registry_dir_honours_visus_web_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tests (and CI) must never write into the developer's real ~/.visus."""
    monkeypatch.setenv("VISUS_WEB_HOME", str(tmp_path / "custom"))
    assert session_server.registry_dir() == tmp_path / "custom" / "sessions"


def test_registry_never_records_the_token(tmp_path: Path) -> None:
    import threading as _threading
    import time as _time

    from test_cli_session import _FakePage, _handler_with_fake_page, _shutdown_thread

    handler = _handler_with_fake_page(_FakePage())
    t = _threading.Thread(
        target=session_server.serve,
        kwargs={"handler": handler, "token": "super-secret", "cwd": tmp_path},
        daemon=True,
    )
    t.start()
    sf = session_server.session_file(tmp_path)
    for _ in range(200):
        if sf.is_file():
            break
        _time.sleep(0.02)
    port = int(json.loads(sf.read_text(encoding="utf-8"))["port"])
    reg = session_server.registry_file(tmp_path, "default")
    try:
        assert reg.is_file(), "serve() did not mirror the session into the registry"
        entry = json.loads(reg.read_text(encoding="utf-8"))
        assert "token" not in entry
        assert entry["file"] == str(sf)
        assert entry["port"] == port
    finally:
        _shutdown_thread(t, port, "super-secret")
    assert not reg.exists(), "the registry entry outlived the daemon"


def test_list_sessions_merges_local_and_other_projects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket as _socket

    srv = _socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        here = tmp_path / "here"
        elsewhere = tmp_path / "elsewhere"
        sessions = here / ".visus" / "sessions"
        sessions.mkdir(parents=True)
        (sessions / "default.json").write_text(
            json.dumps(
                {
                    "name": "default",
                    "cwd": str(here),
                    "pid": 11,
                    "port": port,
                    "token": "t",
                    "engine": "chrome",
                    "headless": False,
                    "url": "http://here",
                }
            ),
            encoding="utf-8",
        )
        _registry_entry(tmp_path, "default", here, port, 11)
        _registry_entry(tmp_path, "scrape", elsewhere, port, 22)
        monkeypatch.setattr(session_client, "_probe_pid", lambda pid: True)

        rows = session_client.list_sessions(here)
        by_key = {(r["name"], r["scope"]): r for r in rows}
        assert ("default", "local") in by_key
        assert ("scrape", "other") in by_key
        assert by_key[("default", "local")]["live"] is True
        assert by_key[("default", "local")]["url"] == "http://here"
        assert Path(by_key[("scrape", "other")]["cwd"]) == elsewhere
        assert all("token" not in r for r in rows), "list_sessions leaked a token"
    finally:
        srv.close()


def test_the_upward_walk_does_not_mistake_the_registry_for_a_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``~/.visus/sessions`` is the REGISTRY, not some project's local state.

    Every project under the user's home (i.e. nearly all of them) has the visus
    home on its upward path. A project with no ``.visus`` of its own would walk
    straight into it and report every other project's session as this project's
    "local" one — the same walk that binds ``repo/src`` to ``repo``'s daemon.
    """
    home = tmp_path / "home"
    (home / ".visus" / "sessions").mkdir(parents=True)
    (home / ".visus" / "sessions" / "abc123-other.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("VISUS_WEB_HOME", str(home / ".visus"))
    project = home / "code" / "project"
    project.mkdir(parents=True)

    # Asserts the registry is SKIPPED, not that the walk finds nothing: tmp_path
    # lives under the real %TEMP%, and any `.visus` a developer (or an earlier
    # test) left in an ancestor is a legitimate find that says nothing about the
    # rule under test.
    fake_registry = home / ".visus" / "sessions"
    assert session_client._find_sessions_dir(project) != fake_registry
    assert session_client._is_registry(fake_registry)
    # O lookup por NOME EXATO não pula a home: um registro se chama
    # `<sha>-<name>.json`, então `other.json` nunca casaria com ele de qualquer
    # forma — e pular quebraria quem trabalha com cwd == ~.
    assert session_client._find_session_file(project, "other") is None
    # the DEFAULT ~/.visus is a registry too, even with the override pointed away
    assert session_client._is_registry(Path.home() / ".visus" / "sessions")

    # a real project-local directory is still found, including from a subfolder
    (project / ".visus" / "sessions").mkdir(parents=True)
    src = project / "src"
    src.mkdir()
    assert session_client._find_sessions_dir(src) == project / ".visus" / "sessions"


def test_a_session_started_in_the_home_directory_is_still_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`cwd == ~` é incomum, mas legítimo — e foi o que a regra de registro quebrou.

    MEDIDO: `visus session start` rodado no home criava
    `~/.visus/sessions/<name>.json` e o comando SEGUINTE não achava nada, porque
    o lookup pulava a pasta inteira. O nome exato nunca colide com um registro
    (`<sha>-<name>.json`), então não havia o que pular aqui.
    """
    home = tmp_path / "home"
    sessions = home / ".visus" / "sessions"
    sessions.mkdir(parents=True)
    monkeypatch.setenv("VISUS_WEB_HOME", str(home / ".visus"))
    (sessions / "trabalho.json").write_text('{"pid": 1, "port": 2}', encoding="utf-8")

    assert session_client._find_session_file(home, "trabalho") == sessions / "trabalho.json"


def test_list_sessions_marks_a_dead_entry_not_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _registry_entry(tmp_path, "ghost", tmp_path / "gone", 1, 999999)
    monkeypatch.setattr(session_client, "_probe_pid", lambda pid: False)
    rows = session_client.list_sessions(tmp_path)
    assert [(r["name"], r["live"]) for r in rows] == [("ghost", False)]


def test_cli_session_list_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client,
        "list_sessions",
        lambda start_dir=None: [
            {
                "name": "auth",
                "cwd": "/p/a",
                "file": "/p/a/.visus/sessions/auth.json",
                "pid": 4,
                "port": 5,
                "engine": "chrome",
                "headless": False,
                "url": "http://x",
                "live": True,
                "scope": "local",
            }
        ],
    )
    r = runner.invoke(app, ["--json", "session", "list"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)[0]["name"] == "auth"


def test_cli_session_list_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "list_sessions", lambda start_dir=None: [])
    r = runner.invoke(app, ["session", "list"])
    assert r.exit_code == 0
    assert "no sessions" in r.output


def test_cli_session_list_table_shows_scope_and_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        session_client,
        "list_sessions",
        lambda start_dir=None: [
            {
                "name": "auth",
                "cwd": "/p/a",
                "file": "/p/a/.visus/sessions/auth.json",
                "pid": 4,
                "port": 5,
                "engine": "chrome",
                "headless": False,
                "url": "http://x",
                "live": True,
                "scope": "local",
            },
            {
                "name": "ghost",
                "cwd": "/p/b",
                "file": "/p/b/.visus/sessions/ghost.json",
                "pid": 9,
                "port": 0,
                "engine": "chrome",
                "headless": True,
                "url": None,
                "live": False,
                "scope": "other",
            },
        ],
    )
    r = runner.invoke(app, ["session", "list"])
    assert r.exit_code == 0, r.output
    for token in ("auth", "ghost", "local", "other", "live", "dead"):
        assert token in r.output, f"{token!r} missing from the session table"


def test_profile_dir_is_inside_the_project(tmp_path: Path) -> None:
    assert (
        session_client.profile_dir(tmp_path, "auth")
        == tmp_path / ".visus" / "profiles" / "auth"
    )


def test_close_all_shuts_down_every_live_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[int, str, str]] = []

    rows = [
        {
            "name": "auth",
            "cwd": str(tmp_path / "a"),
            "file": str(tmp_path / "a" / ".visus" / "sessions" / "auth.json"),
            "pid": 1,
            "port": 5001,
            "live": True,
            "scope": "local",
        },
        {
            "name": "ghost",
            "cwd": str(tmp_path / "b"),
            "file": str(tmp_path / "b" / ".visus" / "sessions" / "ghost.json"),
            "pid": 2,
            "port": 5002,
            "live": False,
            "scope": "other",
        },
    ]
    sf = Path(rows[0]["file"])
    sf.parent.mkdir(parents=True)
    sf.write_text(json.dumps({"pid": 1, "port": 5001, "token": "tok-a"}), encoding="utf-8")

    monkeypatch.setattr(session_client, "list_sessions", lambda start_dir=None: rows)
    monkeypatch.setattr(
        session_client,
        "_send_raw",
        lambda port, payload, **kw: sent.append((port, payload["token"], payload["op"]))
        or {"ok": True, "result": "shutdown"},
    )
    msg = session_client.close_all(start_dir=tmp_path)
    assert sent == [(5001, "tok-a", "shutdown")], sent
    assert "closed 1" in msg
    assert "ghost" not in msg  # a dead session is not "closed"


def test_close_all_reports_a_session_it_cannot_authenticate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No readable session file means no token — say so, don't pretend it closed."""
    rows = [
        {
            "name": "locked",
            "cwd": str(tmp_path / "x"),
            "file": str(tmp_path / "x" / ".visus" / "sessions" / "locked.json"),
            "pid": 3,
            "port": 5003,
            "live": True,
            "scope": "other",
        }
    ]
    monkeypatch.setattr(session_client, "list_sessions", lambda start_dir=None: rows)
    msg = session_client.close_all(start_dir=tmp_path)
    assert "locked" in msg and "kill-all" in msg


def test_close_all_with_nothing_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(session_client, "list_sessions", lambda start_dir=None: [])
    assert session_client.close_all(start_dir=tmp_path) == "no live sessions"


def test_kill_all_terminates_and_removes_every_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[int] = []
    proj = tmp_path / "proj"
    sessions = proj / ".visus" / "sessions"
    sessions.mkdir(parents=True)
    sf = sessions / "auth.json"
    sf.write_text(json.dumps({"pid": 42, "port": 1, "token": "t"}), encoding="utf-8")
    lock = sessions / "auth.json.lock"
    lock.write_text("42", encoding="utf-8")
    reg = session_server.registry_file(proj, "auth")
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(
        json.dumps({"name": "auth", "cwd": str(proj), "file": str(sf), "pid": 42, "port": 1}),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        session_client,
        "list_sessions",
        lambda start_dir=None: [
            {
                "name": "auth",
                "cwd": str(proj),
                "file": str(sf),
                "pid": 42,
                "port": 1,
                "live": True,
                "scope": "local",
            }
        ],
    )
    monkeypatch.setattr(session_client, "_probe_pid", lambda pid: True)
    monkeypatch.setattr(session_client, "_terminate", killed.append)

    msg = session_client.kill_all(start_dir=tmp_path)
    assert killed == [42]
    assert not sf.exists() and not lock.exists() and not reg.exists()
    assert "auth" in msg and "42" in msg


def test_kill_all_sweeps_a_pre_namespace_session_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A daemon started before named sessions writes .visus/session.json.

    Neither the new client nor `session stop` can find it, so kill-all is the
    only command that can reach it.
    """
    killed: list[int] = []
    visus = tmp_path / ".visus"
    visus.mkdir(parents=True)
    legacy = visus / "session.json"
    legacy.write_text(json.dumps({"pid": 77, "port": 1, "token": "t"}), encoding="utf-8")
    (visus / "session.json.lock").write_text("77", encoding="utf-8")

    monkeypatch.setattr(session_client, "list_sessions", lambda start_dir=None: [])
    monkeypatch.setattr(session_client, "_probe_pid", lambda pid: True)
    monkeypatch.setattr(session_client, "_terminate", killed.append)

    msg = session_client.kill_all(start_dir=tmp_path)
    assert killed == [77]
    assert not legacy.exists()
    assert not (visus / "session.json.lock").exists()
    assert "session.json" in msg


def test_kill_all_with_nothing_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(session_client, "list_sessions", lambda start_dir=None: [])
    assert session_client.kill_all(start_dir=tmp_path) == "no session state to remove"


def test_delete_data_removes_the_managed_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = session_client.profile_dir(tmp_path, "auth")
    profile.mkdir(parents=True)
    (profile / "Cookies").write_text("x", encoding="utf-8")
    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None, name=None: None)
    msg = session_client.delete_data(start_dir=tmp_path, name="auth")
    assert not profile.exists()
    assert str(profile) in msg


def test_delete_data_refuses_while_the_session_is_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = session_client.profile_dir(tmp_path, "auth")
    profile.mkdir(parents=True)
    monkeypatch.setattr(
        session_client,
        "find_session",
        lambda start_dir=None, name=None: {"pid": 9, "port": 8, "token": "t"},
    )
    with pytest.raises(session_client.SessionError, match="still running"):
        session_client.delete_data(start_dir=tmp_path, name="auth")
    assert profile.exists(), "a live session's profile must not be deleted"


def test_delete_data_never_touches_a_user_chosen_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--profile <dir> points at a directory the USER owns; never rmtree it."""
    outside = tmp_path / "my-chrome-profile"
    outside.mkdir()
    sessions = tmp_path / ".visus" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "auth.json").write_text(
        json.dumps({"pid": 1, "port": 1, "user_data_dir": str(outside)}), encoding="utf-8"
    )
    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None, name=None: None)
    msg = session_client.delete_data(start_dir=tmp_path, name="auth")
    assert outside.is_dir(), "delete-data deleted a directory it does not manage"
    assert str(outside) in msg and "not managed by visus" in msg


def test_delete_data_with_nothing_to_delete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(session_client, "find_session", lambda start_dir=None, name=None: None)
    msg = session_client.delete_data(start_dir=tmp_path, name="auth")
    assert "no profile data" in msg


def test_cli_fleet_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    """All three commands call their client function with NO arguments.

    `delete_data` resolves the session name itself (via `session_name()`), so the
    fake must too — asserting `deleted auth` proves the root callback's `-S auth`
    reached `set_session_name` before the subcommand ran.
    """
    monkeypatch.setattr(session_client, "close_all", lambda **kw: "closed 2 session(s)")
    monkeypatch.setattr(session_client, "kill_all", lambda **kw: "killed pid 1")
    monkeypatch.setattr(
        session_client,
        "delete_data",
        lambda **kw: f"deleted {session_client.session_name(kw.get('name'))}",
    )

    assert "closed 2" in runner.invoke(app, ["session", "close-all"]).output
    assert "killed pid 1" in runner.invoke(app, ["session", "kill-all"]).output
    r = runner.invoke(app, ["-S", "auth", "session", "delete-data"])
    assert r.exit_code == 0 and "deleted auth" in r.output
