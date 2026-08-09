"""`.visus/cli.json` discovery, parsing, precedence and error messages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.cli import config as cliconfig
from visus.web.cli import session_client
from visus.web.cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_active() -> Any:
    cliconfig.set_active(cliconfig.CliConfig())
    session_client.set_session_name(None)
    yield
    cliconfig.set_active(cliconfig.CliConfig())
    session_client.set_session_name(None)


def _write_config(dir_: Path, data: dict[str, Any]) -> Path:
    visus = dir_ / ".visus"
    visus.mkdir(parents=True, exist_ok=True)
    path = visus / "cli.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_find_config_walks_upward(tmp_path: Path) -> None:
    path = _write_config(tmp_path, {"engine": "edge"})
    deep = tmp_path / "a" / "b"
    deep.mkdir(parents=True)
    assert cliconfig.find_config(deep) == path


def test_find_config_returns_none_when_absent(tmp_path: Path) -> None:
    assert cliconfig.find_config(tmp_path) is None


def test_load_config_maps_every_key(tmp_path: Path) -> None:
    path = _write_config(
        tmp_path,
        {
            "session": "auth",
            "engine": "edge",
            "headless": True,
            "url": "https://example.com",
            "device": "Pixel 7",
            "persistent": True,
            "remoteUrl": "http://grid:4444/wd/hub",
            "slowMo": 120,
            "idleTimeout": 600,
            "allowRunCode": True,
            "outputDir": "artifacts",
        },
    )
    cfg = cliconfig.load_config(path)
    assert cfg.session == "auth"
    assert cfg.engine == "edge"
    assert cfg.headless is True
    assert cfg.url == "https://example.com"
    assert cfg.device == "Pixel 7"
    assert cfg.persistent is True
    assert cfg.remote_url == "http://grid:4444/wd/hub"
    assert cfg.slow_mo == 120
    assert cfg.idle_timeout == 600.0
    assert cfg.allow_run_code is True
    assert Path(cfg.output_dir or "") == (tmp_path / "artifacts")
    assert cfg.path == path


def test_relative_paths_resolve_against_the_config_file(tmp_path: Path) -> None:
    """A config in repo/.visus must not mean "relative to wherever you ran the command"."""
    path = _write_config(tmp_path, {"userDataDir": "./profiles/main"})
    cfg = cliconfig.load_config(path)
    assert Path(cfg.user_data_dir or "") == (tmp_path / "profiles" / "main")


def test_absolute_paths_are_left_alone(tmp_path: Path) -> None:
    absolute = str((tmp_path / "elsewhere").resolve())
    path = _write_config(tmp_path, {"userDataDir": absolute})
    assert cliconfig.load_config(path).user_data_dir == absolute


def test_unknown_key_is_an_error_that_names_it(tmp_path: Path) -> None:
    path = _write_config(tmp_path, {"engien": "edge"})
    with pytest.raises(cliconfig.ConfigError) as excinfo:
        cliconfig.load_config(path)
    message = str(excinfo.value)
    assert "engien" in message
    assert "engine" in message  # the valid keys are listed


def test_malformed_json_is_an_error_that_names_the_file(tmp_path: Path) -> None:
    visus = tmp_path / ".visus"
    visus.mkdir(parents=True)
    path = visus / "cli.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(cliconfig.ConfigError, match="cli.json"):
        cliconfig.load_config(path)


def test_non_object_config_is_an_error(tmp_path: Path) -> None:
    visus = tmp_path / ".visus"
    visus.mkdir(parents=True)
    path = visus / "cli.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(cliconfig.ConfigError, match="JSON object"):
        cliconfig.load_config(path)


def test_wrong_value_type_is_an_error(tmp_path: Path) -> None:
    path = _write_config(tmp_path, {"slowMo": "fast"})
    with pytest.raises(cliconfig.ConfigError, match="slowMo"):
        cliconfig.load_config(path)


def test_cli_loads_the_config_from_the_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"session": "auth", "engine": "edge"})
    captured: dict[str, Any] = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(engine=e, headless=h, **kw)
        or {"pid": 1, "port": 2},
    )
    r = runner.invoke(app, ["session", "start"])
    assert r.exit_code == 0, r.output
    assert captured["engine"] == "edge"
    assert session_client.session_name() == "auth"


def test_an_explicit_flag_always_beats_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"engine": "edge", "headless": True})
    captured: dict[str, Any] = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(engine=e, headless=h) or {"pid": 1, "port": 2},
    )
    r = runner.invoke(app, ["session", "start", "--engine", "chrome"])
    assert r.exit_code == 0, r.output
    assert captured["engine"] == "chrome"
    assert captured["headless"] is True  # not passed, so the config still applies


def test_explicit_session_flag_beats_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"session": "auth"})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: "T")
    assert runner.invoke(app, ["-S", "public", "title"]).exit_code == 0
    assert session_client.session_name() == "public"


def test_explicit_config_path_wins_over_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"engine": "edge"})
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"engine": "firefox"}), encoding="utf-8")
    captured: dict[str, Any] = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(engine=e) or {"pid": 1, "port": 2},
    )
    r = runner.invoke(app, ["--config", str(other), "session", "start"])
    assert r.exit_code == 0, r.output
    assert captured["engine"] == "firefox"


def test_missing_explicit_config_is_an_error(tmp_path: Path) -> None:
    r = runner.invoke(app, ["--config", str(tmp_path / "nope.json"), "version"])
    assert r.exit_code == 1


def test_a_broken_discovered_config_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A typo in a config nobody asked for must not be swallowed either."""
    _write_config(tmp_path, {"engien": "edge"})
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["version"])
    assert r.exit_code == 1


def test_config_persistent_uses_the_managed_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_config(tmp_path, {"persistent": True, "session": "auth"})
    captured: dict[str, Any] = {}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        session_client,
        "start_daemon",
        lambda e, h, u, **kw: captured.update(kw) or {"pid": 1, "port": 2},
    )
    r = runner.invoke(app, ["session", "start"])
    assert r.exit_code == 0, r.output
    assert Path(captured["user_data_dir"]) == session_client.profile_dir(tmp_path, "auth")


def test_config_output_dir_reaches_the_output_funnel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from visus.web.cli import output

    _write_config(tmp_path, {"outputDir": "artifacts"})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: "T")
    assert runner.invoke(app, ["title"]).exit_code == 0
    assert Path(output.resolve_out("shot.png")).parent == (tmp_path / "artifacts")
