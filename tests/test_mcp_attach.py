"""One dispatcher, two frontends: structure, routing and refusals."""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any

import pytest

os.environ["VISUS_WEB_HEADLESS"] = "1"


def _tool_sources() -> dict[str, str]:
    """{function name: its source text} for every top-level def in mcp/server.py."""
    from visus.web.mcp import server

    src = Path(server.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    out: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            segment = ast.get_source_segment(src, node)
            if segment is not None:
                out[node.name] = segment
    return out


def test_every_daemon_backed_tool_dispatches_through_the_seam() -> None:
    """Totality: no tool may quietly keep its own private implementation.

    Without this, `browser_attach_session` would be half-true — some tools would
    cross to the shell's browser and others would silently keep driving a second,
    invisible one. Two browsers that look like one is the bug being removed.
    """
    from visus.web.ops import registry

    sources = _tool_sources()
    problems: list[str] = []
    for tool, op in sorted(registry.TOOL_OPS.items()):
        body = sources.get(tool)
        if body is None:
            problems.append(f"{tool}: not a top-level function in mcp/server.py")
            continue
        if f'_run("{op}"' not in body:
            problems.append(f'{tool}: does not dispatch through _run("{op}", ...)')
    assert not problems, problems


def test_local_only_tools_do_not_dispatch() -> None:
    """The declared exemptions must really be exempt, not accidentally routed."""
    from visus.web.ops import registry

    sources = _tool_sources()
    for tool in sorted(registry.LOCAL_ONLY_TOOLS | registry.SESSIONLESS_TOOLS):
        body = sources.get(tool, "")
        assert "_run(" not in body, f"{tool} is declared exempt but dispatches through _run"


def test_run_raises_the_daemon_error_when_attached(monkeypatch: pytest.MonkeyPatch) -> None:
    from visus.web.mcp import server

    class _Fake:
        def handle(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
            return {"ok": False, "error": "IndexError: field index 9 out of range"}

    monkeypatch.setattr(server, "_remote", _Fake())
    with pytest.raises(RuntimeError, match="field index 9 out of range"):
        server._run("click", {"index": 9}, lambda: pytest.fail("local path ran while attached"))


def test_run_returns_the_daemon_envelope_when_attached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from visus.web.mcp import server

    env = {"ok": True, "result": "clicked", "page": {"url": "http://x/", "title": "X"}}

    class _Fake:
        def handle(self, op: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
            return env

    monkeypatch.setattr(server, "_remote", _Fake())
    assert server._run("click", {}, lambda: pytest.fail("local path ran")) == env
