"""Output funnel for the visus CLI — the one place that decides HOW a value prints.

Three modes, selected once by the root ``@app.callback()``:

* ``TEXT`` (default) — human/agent readable: the primary value (or a pre-rendered
  table), then the ``### Code`` and ``### Page`` sections an agent needs in order
  to choose its next command without spending one.
* ``JSON`` (``--json``) — exactly one JSON document per invocation, undecorated.
* ``RAW`` (``--raw``) — the value only: no ``###`` sections, so
  ``TOKEN=$(visus --raw get-attribute value 5)`` captures a token and nothing else.

Errors ALWAYS go to stderr, never stdout: a shell capturing stdout must never
capture an error message as if it were a value.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, NoReturn

import typer


class Mode(str, Enum):
    """How the current invocation prints its result."""

    TEXT = "text"
    JSON = "json"
    RAW = "raw"


_MODE: Mode = Mode.TEXT
_OUTPUT_DIR: Path | None = None
_SNAPSHOT_SINK: bool = False


def set_mode(*, as_json: bool = False, raw: bool = False) -> None:
    """Select the output mode. ``--json`` wins when both flags are given."""
    global _MODE
    if as_json:
        _MODE = Mode.JSON
    elif raw:
        _MODE = Mode.RAW
    else:
        _MODE = Mode.TEXT


def mode() -> Mode:
    """The active output mode."""
    return _MODE


def set_output_dir(path: str | None) -> None:
    """Directory that relative artifact paths resolve against (``None`` = the cwd)."""
    global _OUTPUT_DIR
    _OUTPUT_DIR = Path(path) if path else None


def resolve_out(path: str) -> str:
    """Absolute path for an artifact the CLIENT writes (screenshot/snapshot/script)."""
    p = Path(path)
    if not p.is_absolute() and _OUTPUT_DIR is not None:
        p = _OUTPUT_DIR / p
    return str(p.resolve())


def set_snapshot_sink(enabled: bool) -> None:
    """When True, mutating commands ask the daemon to write a snapshot file."""
    global _SNAPSHOT_SINK
    _SNAPSHOT_SINK = enabled


def snapshot_sink() -> bool:
    """True when ``--snapshot`` asked for a snapshot file after every action."""
    return _SNAPSHOT_SINK


def _dumps(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, default=str)


def _renders_itself(value: Any) -> bool:
    """True when ``str(value)`` is already an honest rendering of *value*.

    A scalar prints as itself; a list/dict prints as a Python repr, which is useless
    to a human and to a shell. This is the whole difference between a ``table`` that
    is the value's RENDERING (keep it under ``--raw``) and one that is DECORATION
    around a value that can speak for itself (drop it under ``--raw``).
    """
    return value is None or isinstance(value, (str, int, float, bool))


def emit(value: Any, *, table: str | None = None) -> None:
    """Print the primary value.

    ``table`` is the pre-rendered text form (a rich table, a formatted line).

    * TEXT — always prefer ``table``; it is what a human should read.
    * JSON — ignore ``table`` and dump ``value``.
    * RAW  — ``--raw`` strips the ``###`` sections (which ``emit`` never writes) and
      any decoration, but never a structure's own rendering. So the table survives
      for a list/dict and is dropped for a scalar: ``visus --raw list-fields`` prints
      the table, ``visus --raw session-screenshot -o s.png`` prints just the path.
    """
    if _MODE is Mode.JSON:
        typer.echo(_dumps(value))
        return
    if table is not None and not (_MODE is Mode.RAW and _renders_itself(value)):
        typer.echo(table)
        return
    typer.echo("" if value is None else str(value))


def emit_error(message: str, *, code: int = 1) -> NoReturn:
    """Write an error to STDERR (never stdout) and exit with ``code``."""
    if _MODE is Mode.JSON:
        typer.echo(_dumps({"ok": False, "error": message}), err=True)
    else:
        typer.echo(message, err=True)
    raise typer.Exit(code)


def emit_envelope(env: dict[str, Any], *, table: str | None = None) -> None:
    """Render a full daemon envelope: the value, then ``### Code``, then ``### Page``."""
    if _MODE is Mode.JSON:
        typer.echo(_dumps(env))
        return
    result = env.get("result")
    if _MODE is Mode.RAW:
        typer.echo("" if result is None else str(result))
        return
    typer.echo(table if table is not None else ("" if result is None else str(result)))
    code = env.get("code")
    if code:
        typer.echo("")
        typer.echo("### Code")
        typer.echo(str(code))
    page = env.get("page") or {}
    if page:
        typer.echo("")
        typer.echo("### Page")
        typer.echo(f"- URL: {page.get('url', '')}")
        typer.echo(f"- Title: {page.get('title', '')}")
        snap = env.get("snapshot")
        if snap:
            typer.echo(f"- Snapshot: {snap}")
        if page.get("fields_stale"):
            typer.echo("- Fields: stale — run `visus list-fields` again before using an index")
