"""Locate the agent skill that ships inside the package, and install copies of it.

``pip install visus-web`` must deliver the skill, so the skill tree lives at
``src/visus/web/skills/visus-web`` (hatchling ships non-``.py`` files found inside
a packaged directory) and is resolved through :mod:`importlib.resources`.

This module is imported by the MCP server as well as the CLI, so it must stay
free of ``typer`` / ``rich`` / ``mcp`` imports.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

#: Dotted name of the packaged data directory, for documentation and error text.
#: ``visus/web/skills`` has no ``__init__.py`` — it is package *data*, so the
#: importlib anchor is ``visus.web`` and the rest is a path walk.
BUNDLED_SKILL_PACKAGE = "visus.web.skills"

#: Directory name of the skill, both inside the package and inside a target repo.
SKILL_NAME = "visus-web"


@dataclass(frozen=True)
class SkillTarget:
    """One place a consuming repo can hold an installed copy of the skill."""

    dir: Path
    command: str
    flavor: str


def bundled_skill_dir() -> Path:
    """Directory of the packaged skill, via importlib.resources."""
    return Path(str(files("visus.web") / "skills" / SKILL_NAME))


def installed_skill_targets(cwd: Path) -> list[SkillTarget]:
    """[(dir, remediation_command)] for .claude and .agents."""
    return [
        SkillTarget(
            dir=cwd / ".claude" / "skills" / SKILL_NAME,
            command="visus install --skills",
            flavor="claude",
        ),
        SkillTarget(
            dir=cwd / ".agents" / "skills" / SKILL_NAME,
            command="visus install --skills=agents",
            flavor="agents",
        ),
    ]


def install_skills(cwd: Path, *, flavor: str = "claude", force: bool = False) -> list[Path]:
    """Copy the bundled skill tree into the target(s). Returns written paths.

    ``flavor`` is ``"claude"``, ``"agents"`` or ``"both"``. Without ``force`` the
    copy overwrites the files it ships and leaves anything else in place; with
    ``force`` the target directory is removed first, so the result mirrors the
    bundle exactly.
    """
    src = bundled_skill_dir()
    written: list[Path] = []
    for target in installed_skill_targets(cwd):
        if flavor != "both" and target.flavor != flavor:
            continue
        if force and target.dir.exists():
            shutil.rmtree(target.dir)
        target.dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, target.dir, dirs_exist_ok=True)
        written.extend(sorted(p for p in target.dir.rglob("*") if p.is_file()))
    return written
