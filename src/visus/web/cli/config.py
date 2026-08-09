"""Project config file for the `visus` CLI (``.visus/cli.json``).

Discovered with the same upward walk sessions use, so a config in the repo root
applies to a command run in ``repo/src``. Every value is a DEFAULT: an option the
user actually typed always wins, which is what :func:`is_default` decides.

Unknown keys are an error rather than a shrug — a typo in a config file is the
classic way this feature silently does nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

CONFIG_RELPATH = Path(".visus") / "cli.json"


class ConfigError(RuntimeError):
    """Raised when a config file is missing, malformed, or has an unknown key."""


@dataclass(frozen=True)
class CliConfig:
    """Defaults read from ``.visus/cli.json``. ``None`` means "not configured"."""

    path: Path | None = None
    session: str | None = None
    engine: str | None = None
    headless: bool | None = None
    url: str | None = None
    device: str | None = None
    persistent: bool | None = None
    user_data_dir: str | None = None
    remote_url: str | None = None
    slow_mo: int | None = None
    idle_timeout: float | None = None
    allow_run_code: bool | None = None
    output_dir: str | None = None


# JSON key -> (dataclass field, python type, is it a path?)
_SCHEMA: dict[str, tuple[str, type, bool]] = {
    "session": ("session", str, False),
    "engine": ("engine", str, False),
    "headless": ("headless", bool, False),
    "url": ("url", str, False),
    "device": ("device", str, False),
    "persistent": ("persistent", bool, False),
    "userDataDir": ("user_data_dir", str, True),
    "remoteUrl": ("remote_url", str, False),
    "slowMo": ("slow_mo", int, False),
    "idleTimeout": ("idle_timeout", float, False),
    "allowRunCode": ("allow_run_code", bool, False),
    "outputDir": ("output_dir", str, True),
}

_active = CliConfig()


def set_active(cfg: CliConfig) -> None:
    """Install the config the root callback resolved for this invocation."""
    global _active
    _active = cfg


def active() -> CliConfig:
    """The config in force for this invocation (empty when none was found)."""
    return _active


def find_config(start_dir: str | Path | None = None) -> Path | None:
    """Search upward from *start_dir* for ``.visus/cli.json`` (git-style)."""
    cur = Path(start_dir) if start_dir is not None else Path.cwd()
    cur = cur.resolve()
    for d in [cur, *cur.parents]:
        candidate = d / CONFIG_RELPATH
        if candidate.is_file():
            return candidate
    return None


def load_config(path: Path) -> CliConfig:
    """Parse *path* into a :class:`CliConfig`, or raise :class:`ConfigError`.

    Relative ``userDataDir`` / ``outputDir`` values resolve against the config
    file's PROJECT directory, never the caller's cwd — a config in ``repo/.visus``
    must mean the same thing from every subdirectory. For a discovered config that
    project directory is the parent of ``.visus``, not ``.visus`` itself:
    ``"outputDir": "artifacts"`` means ``repo/artifacts``, because ``.visus/`` is
    visus's own state directory and nobody writing that line means to nest inside
    it. A config named with ``--config`` resolves against wherever it lives.
    """
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a JSON object, not {type(raw).__name__}")

    values: dict[str, Any] = {"path": path}
    base = path.parent
    if base.name == ".visus":
        base = base.parent
    for key, value in raw.items():
        entry = _SCHEMA.get(str(key))
        if entry is None:
            known = ", ".join(sorted(_SCHEMA))
            raise ConfigError(f"unknown key {key!r} in {path} — valid keys: {known}")
        field, expected, is_path = entry
        if expected is bool:
            if not isinstance(value, bool):
                raise ConfigError(f"{key!r} in {path} must be true or false")
        elif expected is float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{key!r} in {path} must be a number")
            value = float(value)
        elif expected is int:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ConfigError(f"{key!r} in {path} must be a whole number")
        elif not isinstance(value, str):
            raise ConfigError(f"{key!r} in {path} must be a string")
        if is_path and isinstance(value, str) and value:
            candidate = Path(value)
            value = str(candidate if candidate.is_absolute() else (base / candidate).resolve())
        values[field] = value
    return CliConfig(**values)


def resolve(explicit: str | None, start_dir: str | Path | None = None) -> CliConfig:
    """Load the config named by ``--config``, else the discovered one, else empty."""
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        return load_config(path)
    found = find_config(start_dir)
    return CliConfig() if found is None else load_config(found)


def is_default(ctx: typer.Context, name: str) -> bool:
    """True when *name* was NOT supplied on the command line.

    Click records where each parameter's value came from; anything other than
    ``DEFAULT`` means the user (or an env var) asked for it, and the config must
    step aside.
    """
    source = ctx.get_parameter_source(name)
    return source is None or getattr(source, "name", "") == "DEFAULT"
