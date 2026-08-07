"""Drift gates for the shipped agent skill.

These read the skill out of the repo source tree (not through
``bundled_skill_dir()``) so they fail on an edit regardless of how the package
is installed.
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "visus" / "web" / "skills" / "visus-web"
)
SKILL_MD = SKILL_DIR / "SKILL.md"


def _frontmatter() -> dict[str, str]:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must open with YAML frontmatter"
    block = text.split("---\n", 2)[1]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip().strip('"')
    return out


def test_frontmatter_declares_name_and_allowed_tools() -> None:
    fm = _frontmatter()
    assert fm["name"] == "visus-web"
    assert "Bash(visus:*)" in fm["allowed-tools"]
    assert "Bash(visus-web-mcp:*)" in fm["allowed-tools"]
    assert len(fm["description"]) > 80, "the description is what an agent routes on"


def test_frontmatter_version_tracks_the_package_version() -> None:
    """The skill carries provenance; a release bump must bump the skill too."""
    from visus.web import __version__

    assert _frontmatter()["version"] == __version__


def test_skill_teaches_the_session_loop() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    for fragment in (
        "visus session start",
        "visus list-fields",
        "visus fill 1 student",
        "visus click --role button --name Submit",
        "visus expect-text",
        "visus session stop",
    ):
        assert fragment in text, f"the session loop is missing {fragment!r}"


def test_skill_claims_the_real_mcp_tool_count() -> None:
    """`~38 tools` was wrong; the count must be derived, never guessed."""
    import importlib

    server = importlib.import_module("visus.web.mcp.server")
    real = len(server.mcp._tool_manager.list_tools())
    claimed = re.findall(r"\*\*(\d+) tools\*\*", SKILL_MD.read_text(encoding="utf-8"))
    assert claimed, "SKILL.md must state the MCP tool count as `**N tools**`"
    assert {int(c) for c in claimed} == {real}, f"claimed {claimed}, registered {real}"


def test_skill_covers_every_subsystem() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    for fragment in (
        "rpa(",
        "async_api",
        "tracing",
        "pytest",
        "NetworkCapture",
        "edge_ie",
        "remote_url",
        "python -m visus.web.cli",
    ):
        assert fragment in text, f"the skill never mentions {fragment!r}"


def test_skill_has_a_decision_guide_and_a_skills_less_prompt() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "## Which interface" in text
    assert "## Skills-less operation" in text
    assert "visus --help" in text
