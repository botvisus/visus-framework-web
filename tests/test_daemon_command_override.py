"""O daemon pode ser hospedado por outro executável que não o Python.

`start_daemon` roda `python -m visus.web.cli.session_server`. Num app CONGELADO
(Nuitka/PyInstaller) não existe python: `sys.executable` aponta para um
interpretador embarcado que some entre versões, e o spawn morre com
`FileNotFoundError [WinError 2]` — MEDIDO no Visus Studio compilado, onde
`visus-web session start` quebrava enquanto `visus-web screenshot <url>` (que não
usa daemon) funcionava.

O host declara como se hospeda pelo `VISUS_WEB_DAEMON_CMD`: uma lista JSON que
substitui o prefixo `[interpretador, -m, módulo]`. Os argumentos do daemon
(engine, headless, url) continuam sendo anexados por `start_daemon`, então o
contrato de `session_server.main` não muda.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from visus.web.cli import session_client


def test_without_the_override_it_runs_python_dash_m() -> None:
    argv = session_client._daemon_argv()
    assert argv[1:] == ["-m", "visus.web.cli.session_server"], argv
    assert argv[0], "sem interpretador não há daemon"


def test_the_override_replaces_the_whole_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "VISUS_WEB_DAEMON_CMD", json.dumps([r"C:\app\visus-studio.exe", "__daemon", "web"])
    )
    assert session_client._daemon_argv() == [r"C:\app\visus-studio.exe", "__daemon", "web"]


def test_a_broken_override_falls_back_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JSON inválido não pode derrubar `session start` — volta ao caminho normal."""
    monkeypatch.setenv("VISUS_WEB_DAEMON_CMD", "isto não é json")
    argv = session_client._daemon_argv()
    assert argv[1:] == ["-m", "visus.web.cli.session_server"], argv


def test_start_daemon_spawns_the_override_with_the_daemon_args(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """O prefixo é do host; engine/headless/url continuam vindo do start_daemon."""
    captured: dict[str, Any] = {}

    class _FakePopen:
        def poll(self) -> None:  # o daemon de mentira não sai
            return None

        def __init__(self, argv: list[str], **kw: Any) -> None:
            captured["argv"] = argv

    monkeypatch.setenv("VISUS_WEB_DAEMON_CMD", json.dumps(["HOST.exe", "__daemon", "web"]))
    monkeypatch.setattr(session_client, "find_session", lambda base, name=None: None)
    monkeypatch.setattr(session_client.subprocess, "Popen", _FakePopen)

    with pytest.raises(session_client.SessionError):
        session_client.start_daemon(
            "chrome", True, "https://x/", cwd=tmp_path, timeout=0.2
        )

    assert captured["argv"] == ["HOST.exe", "__daemon", "web", "chrome", "1", "https://x/"]
