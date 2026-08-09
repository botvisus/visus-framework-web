"""Warn when a repo's installed copy of the agent skill has drifted from the bundle.

Port of ``playwright-cli/skillCheck.js``. Three properties are load-bearing:

* line endings are normalised before comparing — a CRLF checkout on Windows is
  not drift (``skillCheck.js:41``);
* the warning goes to **stderr**, so it never contaminates a piped stdout;
* the whole check is wrapped in ``except Exception: pass`` — a broken or missing
  skill must never break the CLI.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from visus.web.cli.skills import bundled_skill_dir, installed_skill_targets

_BOX_UNICODE = ("╔", "═", "╗", "║", "╚", "╝")
_BOX_ASCII = ("+", "-", "+", "|", "+", "+")


def read_skill(file: Path) -> str | None:
    """Read + normalise CRLF->LF. None when missing."""
    try:
        raw = file.read_bytes()
    except OSError:
        return None
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n")


def _box_chars() -> tuple[str, str, str, str, str, str]:
    """Box-drawing characters, downgraded to ASCII on a console that cannot encode them."""
    encoding = getattr(sys.stderr, "encoding", None) or "utf-8"
    try:
        "".join(_BOX_UNICODE).encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return _BOX_ASCII
    return _BOX_UNICODE


def frame(lines: list[str]) -> str:
    """Box-drawing frame, port of playwright-cli/skillCheck.js:48-54."""
    top_left, horizontal, top_right, vertical, bottom_left, bottom_right = _box_chars()
    width = max((len(line) for line in lines), default=0)
    top = top_left + horizontal * (width + 2) + top_right
    bottom = bottom_left + horizontal * (width + 2) + bottom_right
    body = [f"{vertical} {line.ljust(width)} {vertical}" for line in lines]
    return "\n".join([top, *body, bottom]) + "\n"


def normalise_cli_name(text: str) -> str:
    """Fold the ``visus-web`` command spelling back to ``visus`` for comparison.

    An installer may rewrite the skill to name the binary that actually works in
    its environment: ``visus`` is not ours alone (visus-desktop declares the same
    console script), so a mixed install has to say ``visus-web``. That rewrite is
    NOT staleness, and treating it as such is worse than useless — the warning
    fires on every command and tells the user to reinstall, which would replace
    the corrected copy with one naming a binary that runs another program.

    Only the whole token is folded: ``visus-web-mcp`` and ``visus.web`` keep their
    names.
    """
    return re.sub(r"(?<![\w.-])visus-web(?![\w.-])", "visus", text)


def check_installed_skills(cwd: Path | None = None) -> None:
    """Compare installed vs bundled; write a framed warning to STDERR on drift."""
    try:
        base = Path.cwd() if cwd is None else cwd
        bundled = read_skill(bundled_skill_dir() / "SKILL.md")
        if bundled is None:
            return
        bundled_key = normalise_cli_name(bundled)
        for target in installed_skill_targets(base):
            installed = read_skill(target.dir / "SKILL.md")
            if installed is None or normalise_cli_name(installed) == bundled_key:
                continue
            try:
                shown: Path | str = target.dir.relative_to(base)
            except ValueError:
                shown = target.dir
            sys.stderr.write(
                frame(
                    [
                        f"The visus-web skill at '{shown}'",
                        "does not match the tool version.",
                        "",
                        f"Run `{target.command}`",
                        "to install the up-to-date skill.",
                    ]
                )
            )
    except Exception:  # noqa: BLE001 — a skill check must never break the CLI
        pass
