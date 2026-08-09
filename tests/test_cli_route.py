"""`visus route` / `unroute` / `route-list`: payload plumbing and REPL twins.

The daemon ops are driven against a fake page that records the calls; their real
behaviour against a live browser is covered by tests/test_route.py.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from visus.web.api.route import RouteRule
from visus.web.cli import console, session_client, session_server
from visus.web.cli.main import app

runner = CliRunner()


class _RoutingPage:
    """A page that records route calls and answers `routes()` from its own store."""

    def __init__(self) -> None:
        self.rules: list[RouteRule] = []
        self.url = "http://x.test/"

    def route(
        self,
        pattern: str,
        *,
        status: int | None = None,
        body: str | None = None,
        content_type: str | None = None,
        headers: dict[str, str] | None = None,
        abort: bool = False,
    ) -> RouteRule:
        rule = RouteRule(pattern, status, body, content_type, dict(headers or {}), abort)
        self.rules = [r for r in self.rules if r.pattern != pattern]
        self.rules.append(rule)
        return rule

    def unroute(self, pattern: str | None = None) -> int:
        before = len(self.rules)
        self.rules = [] if pattern is None else [r for r in self.rules if r.pattern != pattern]
        return before - len(self.rules)

    def routes(self) -> list[RouteRule]:
        return list(self.rules)


def _handler_with_routing_page() -> session_server.SessionHandler:
    from test_cli_session import _FakeBrowser

    h = session_server.SessionHandler(engine="chrome", headless=True)
    h._browser = _FakeBrowser()  # type: ignore[assignment]
    h._page = _RoutingPage()  # type: ignore[assignment]
    return h


def test_op_route_returns_the_installed_rule() -> None:
    h = _handler_with_routing_page()
    resp = h.handle(
        "route",
        {
            "pattern": "**/api/*",
            "status": 503,
            "body": '{"error":"down"}',
            "content_type": "application/json",
            "headers": {"X-Mock": "1"},
        },
    )
    assert resp["ok"] is True
    rule = resp["result"]["route"]
    assert rule["pattern"] == "**/api/*" and rule["status"] == 503
    assert rule["headers"] == {"X-Mock": "1"}
    assert rule["abort"] is False


def test_op_route_list_redacts_secret_headers() -> None:
    h = _handler_with_routing_page()
    h.handle("route", {"pattern": "**/a", "headers": {"Authorization": "Bearer s3cret"}})
    listed = h.handle("route_list", {})["result"]["routes"]
    assert listed[0]["headers"] == {"Authorization": "REDACTED"}


def test_op_unroute_counts_removals() -> None:
    h = _handler_with_routing_page()
    h.handle("route", {"pattern": "**/a"})
    h.handle("route", {"pattern": "**/b", "abort": True})
    assert h.handle("unroute", {"pattern": "**/a"})["result"] == {"removed": 1}
    assert h.handle("unroute", {})["result"] == {"removed": 1}
    assert h.handle("route_list", {})["result"] == {"routes": []}


def test_op_route_requires_a_pattern() -> None:
    h = _handler_with_routing_page()
    resp = h.handle("route", {})
    assert resp["ok"] is False and "pattern" in resp["error"]


def test_cli_route_builds_the_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(op=op, args=args)
        or {"route": {"pattern": "**/api/*", "status": 404, "abort": False}},
    )
    r = runner.invoke(
        app,
        [
            "route", "**/api/*",
            "--status", "404",
            "--body", '{"x":1}',
            "--content-type", "application/json",
            "--header", "X-A: 1",
            "--header", "X-B: 2",
        ],
    )
    assert r.exit_code == 0, r.output
    assert captured["op"] == "route"
    assert captured["args"] == {
        "pattern": "**/api/*",
        "status": 404,
        "body": '{"x":1}',
        "content_type": "application/json",
        "headers": {"X-A": "1", "X-B": "2"},
        "abort": False,
    }


def test_cli_route_abort(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(args=args)
        or {"route": {"pattern": "**/*.png", "abort": True}},
    )
    r = runner.invoke(app, ["route", "**/*.png", "--abort"])
    assert r.exit_code == 0, r.output
    assert captured["args"]["abort"] is True


def test_cli_route_body_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    payload = tmp_path / "items.json"
    payload.write_text('[{"id":1}]', encoding="utf-8")
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(args=args) or {"route": {}},
    )
    r = runner.invoke(app, ["route", "**/api/*", "--body-file", str(payload)])
    assert r.exit_code == 0, r.output
    assert captured["args"]["body"] == '[{"id":1}]'


def test_cli_route_rejects_a_malformed_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: {"route": {}})
    r = runner.invoke(app, ["route", "**/api/*", "--header", "no-colon-here"])
    assert r.exit_code == 1
    assert "K: V" in r.output or "K: V" in (r.stderr or "")


def test_cli_route_rejects_abort_with_a_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """--abort fails the request; a body would silently be thrown away."""
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: {"route": {}})
    r = runner.invoke(app, ["route", "**/api/*", "--abort", "--body", "x"])
    assert r.exit_code == 1


def test_cli_route_list_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: {
            "routes": [
                {
                    "pattern": "**/api/*",
                    "status": 503,
                    "body": "{}",
                    "content_type": "application/json",
                    "headers": {},
                    "abort": False,
                }
            ]
        },
    )
    r = runner.invoke(app, ["--json", "route-list"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)[0]["pattern"] == "**/api/*"


def test_cli_route_list_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_client, "send", lambda op, args=None, **kw: {"routes": []})
    r = runner.invoke(app, ["route-list"])
    assert r.exit_code == 0 and "no routes" in r.output


def test_cli_unroute(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        session_client,
        "send",
        lambda op, args=None, **kw: captured.update(op=op, args=args) or {"removed": 2},
    )
    assert "2" in runner.invoke(app, ["unroute"]).output
    assert captured["args"] == {"pattern": None}
    runner.invoke(app, ["unroute", "**/api/*"])
    assert captured["args"] == {"pattern": "**/api/*"}


def test_repl_route_twins() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def send(op: str, args: dict[str, Any]) -> Any:
        calls.append((op, args))
        if op == "route_list":
            return {"routes": [{"pattern": "**/a", "status": 500, "abort": False}]}
        if op == "unroute":
            return {"removed": 1}
        return {"route": {"pattern": args.get("pattern"), "status": 500, "abort": False}}

    assert "**/a" in console.dispatch("route **/a 500", send)
    assert calls[0] == ("route", {"pattern": "**/a", "status": 500})
    assert "**/a" in console.dispatch("routes", send)
    assert "1" in console.dispatch("unroute **/a", send)
    assert calls[-1] == ("unroute", {"pattern": "**/a"})


def test_repl_help_lists_the_route_commands() -> None:
    out = console.dispatch("help", lambda op, args: None)
    for line in ("route ", "unroute", "routes"):
        assert line in out, f"{line!r} missing from the REPL help"


def test_every_command_this_plan_added_has_a_repl_twin_and_a_readme_row() -> None:
    from pathlib import Path as _Path

    readme = _Path("README.md").read_text(encoding="utf-8")
    repl_source = _Path("src/visus/web/cli/console.py").read_text(encoding="utf-8")

    for name in ("devices", "drop", "route", "route-list", "run-code", "unroute", "upload"):
        assert f"visus {name}" in readme, f"`visus {name}` has no README row"

    # Session-lifecycle commands intentionally have NO repl twin: the REPL runs
    # inside a session, and each of these either ends it or reports on others.
    for name in ("session list", "session close-all", "session kill-all",
                 "session delete-data", "session attach", "session detach"):
        assert f"visus {name}" in readme, f"`visus {name}` has no README row"

    for repl in ("drop", "route", "unroute", "routes", "run-code", "upload"):
        assert f'cmd == "{repl}"' in repl_source, f"{repl!r} missing from console.dispatch"
        assert repl in console._HELP, f"{repl!r} missing from the REPL help text"
