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
