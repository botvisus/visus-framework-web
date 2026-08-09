"""The fleet renderer — a pure function, so it is testable independently of collection."""

from __future__ import annotations

from typing import Any

from visus.web.cli.fleet import render_fleet


def _session(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "default",
        "pid": 4242,
        "port": 51234,
        "engine": "chrome",
        "headless": False,
        "url": "https://example.com/dashboard",
        "title": "Dashboard",
        "cwd": "/proj/a",
        "alive": True,
    }
    base.update(over)
    return base


def test_no_sessions_says_so_and_names_the_fix() -> None:
    out = render_fleet([])
    assert "no visus sessions" in out
    assert "visus session start" in out


def test_one_session_renders_every_column() -> None:
    out = render_fleet([_session()])
    for fragment in ("default", "4242", "51234", "chrome", "headed", "Dashboard", "/proj/a"):
        assert fragment in out, f"missing column value {fragment!r}"


def test_a_dead_session_is_marked_and_names_the_fix() -> None:
    out = render_fleet([_session(alive=False)])
    assert "dead" in out
    assert "visus session kill" in out


def test_headless_and_headed_are_distinguishable() -> None:
    out = render_fleet([_session(name="a", headless=True), _session(name="b", headless=False)])
    assert "headless" in out and "headed" in out


def test_rows_are_sorted_by_name_so_the_view_is_stable() -> None:
    out = render_fleet([_session(name="zeta"), _session(name="alpha")])
    assert out.index("alpha") < out.index("zeta")


def test_a_missing_field_never_raises() -> None:
    """Session files are written by other processes; a partial one must still render."""
    out = render_fleet([{"name": "partial"}])
    assert "partial" in out
