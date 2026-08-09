"""Render a fleet of `visus` sessions as a table.

A pure function over already-collected session dicts, deliberately separate from
the collection so the two can be tested and evolved apart. See
``docs/design/session-dashboard.md`` — including its note that PLAN 6 has since
shipped both the collector (``session_client.list_sessions``) and a first
renderer (``visus session list``), so the remaining work is reconciliation rather
than construction.
"""

from __future__ import annotations

from typing import Any


def render_fleet(sessions: list[dict[str, Any]]) -> str:
    """A table of sessions: name, pid, port, engine, mode, page, directory.

    Each dict may carry ``name``, ``pid``, ``port``, ``engine``, ``headless``,
    ``url``, ``title``, ``cwd`` and ``alive``. Missing keys render blank rather
    than raising — the dicts come from files other processes wrote, and a fleet
    view that crashes on one bad row is worse than no fleet view.
    """
    if not sessions:
        return "no visus sessions running — start one with `visus session start <url>`"

    from rich import box
    from rich.console import Console
    from rich.table import Table

    table = Table(box=box.ASCII, header_style="bold", pad_edge=False)
    table.add_column("NAME", no_wrap=True)
    table.add_column("STATE", no_wrap=True)
    table.add_column("PID", justify="right", no_wrap=True)
    table.add_column("PORT", justify="right", no_wrap=True)
    table.add_column("ENGINE", no_wrap=True)
    table.add_column("MODE", no_wrap=True)
    table.add_column("PAGE", overflow="fold")
    table.add_column("DIRECTORY", overflow="fold")

    dead = False
    for s in sorted(sessions, key=lambda s: str(s.get("name", ""))):
        alive = bool(s.get("alive", True))
        dead = dead or not alive
        page = str(s.get("title") or "") or str(s.get("url") or "")
        table.add_row(
            str(s.get("name", "")),
            "live" if alive else "dead",
            str(s.get("pid", "")),
            str(s.get("port", "")),
            str(s.get("engine", "")),
            "" if s.get("headless") is None else ("headless" if s.get("headless") else "headed"),
            page,
            str(s.get("cwd", "")),
        )

    console = Console()
    with console.capture() as cap:
        console.print(table)
    out = cap.get().rstrip("\n")
    if dead:
        out += "\n\nsome sessions are dead — clear them with `visus session kill`"
    return out
