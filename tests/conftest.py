from __future__ import annotations

import http.server
import json
import pathlib
import socketserver
import threading

import pytest

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def _visus_home_root(tmp_path_factory):  # type: ignore[no-untyped-def]
    return tmp_path_factory.mktemp("visus-home")


@pytest.fixture(autouse=True)
def _isolate_visus_home(_visus_home_root, monkeypatch):  # type: ignore[no-untyped-def]
    """Point the cross-project session registry at a tmp dir for EVERY test.

    ``serve()`` mirrors each live session into ``visus_home()/sessions``, which
    defaults to the real ``~/.visus`` — so without this any test that starts a
    daemon writes into the developer's (or CI's) home directory. Registry entries
    are keyed by a hash of the project cwd, and every test gets its own
    ``tmp_path``, so one shared root cannot collide. A test wanting a registry of
    its own just sets ``VISUS_WEB_HOME`` again — a module-level autouse fixture
    runs after this one and wins.
    """
    monkeypatch.setenv("VISUS_WEB_HOME", str(_visus_home_root))


class _FixtureHandler(http.server.SimpleHTTPRequestHandler):
    """Serve fixture files, with a /echo-headers endpoint for header tests."""

    def __init__(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(*args, directory=str(FIXTURE_DIR), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/echo-headers":
            # Return all request headers as a JSON object.
            headers_dict = dict(self.headers)
            body = json.dumps(headers_dict).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            super().do_GET()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        # Keep the default logging behaviour (writes to stderr).
        super().log_message(format, *args)


@pytest.fixture(scope="session")
def base_url():
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _FixtureHandler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()


@pytest.fixture
def browser():
    from visus.web import launch

    with launch(headless=True) as b:
        yield b


@pytest.fixture
def live_session(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Um daemon de sessão REAL (Chrome headless) servindo numa thread, achado pela
    CLI pelo cwd — o caminho que um agente percorre, sem subprocesso nem mock.

    Devolve ``ops``: a lista de ops que a CLI mandou ao daemon, para os testes
    provarem o que um comando faz por baixo (ex.: que ``text`` nunca usa ``eval``).
    """
    import socket
    import time

    from visus.web.cli import session_client, session_server

    handler = session_server.SessionHandler(engine="chrome", headless=True, url="about:blank")
    token = "live-test"
    thread = threading.Thread(
        target=session_server.serve,
        kwargs={"handler": handler, "token": token, "cwd": tmp_path},
        daemon=True,
    )
    thread.start()
    sf = session_server.session_file(tmp_path)
    for _ in range(500):
        if sf.is_file():
            break
        time.sleep(0.02)
    port = int(json.loads(sf.read_text(encoding="utf-8"))["port"])
    monkeypatch.chdir(tmp_path)

    ops: list[str] = []
    real_send, real_env = session_client.send, session_client.send_envelope

    def spy_send(op, args=None, *a, **k):  # type: ignore[no-untyped-def]
        ops.append(op)
        return real_send(op, args, *a, **k)

    def spy_env(op, args=None, *a, **k):  # type: ignore[no-untyped-def]
        ops.append(op)
        return real_env(op, args, *a, **k)

    monkeypatch.setattr(session_client, "send", spy_send)
    monkeypatch.setattr(session_client, "send_envelope", spy_env)
    try:
        yield ops
    finally:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
                f = sock.makefile("rwb")
                f.write((json.dumps({"token": token, "op": "shutdown"}) + "\n").encode("utf-8"))
                f.flush()
                f.readline()
        except OSError:
            pass
        thread.join(timeout=15)
        handler.close()
