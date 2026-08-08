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
COMMANDS_MD = SKILL_DIR / "references" / "cli-commands.md"

DEV_SKILL = (
    Path(__file__).resolve().parents[1]
    / ".claude"
    / "skills"
    / "developing-visus-web"
    / "SKILL.md"
)


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


def _cli_command_names() -> list[str]:
    """Every invocable command name, e.g. 'list-fields' and 'session start'."""
    from typer.main import get_command_name

    from visus.web.cli.main import app

    names: list[str] = []
    for info in app.registered_commands:
        names.append(info.name or get_command_name(info.callback.__name__))
    for group in app.registered_groups:
        prefix = group.name or ""
        for info in group.typer_instance.registered_commands:
            sub = info.name or get_command_name(info.callback.__name__)
            names.append(f"{prefix} {sub}".strip())
    return names


def test_every_cli_command_is_documented() -> None:
    """Adding a command without a doc row must fail here, not in the field."""
    text = COMMANDS_MD.read_text(encoding="utf-8")
    missing = [
        name
        for name in _cli_command_names()
        # `(?![\w-])` stops `visus clear-input` from satisfying `visus clear`.
        if not re.search(rf"`visus {re.escape(name)}(?![\w-])", text)
    ]
    assert not missing, (
        f"{len(missing)} command(s) missing from {COMMANDS_MD.name}: {sorted(missing)}"
    )


def test_command_reference_is_linked_from_the_skill() -> None:
    assert "references/cli-commands.md" in SKILL_MD.read_text(encoding="utf-8")


def test_targeting_reference_states_the_name_only_rule() -> None:
    """`--name` alone is rejected by main.py's `_target_args` — the README never says so."""
    text = (SKILL_DIR / "references" / "cli-targeting.md").read_text(encoding="utf-8")
    assert "`--name` alone is not a target" in text
    # The doc must quote the message the CLI really prints, line for line — an
    # agent that hits it looks the literal up here.
    for line in (
        "error: no target. Use one of:",
        "--name alone is NOT a target; it only qualifies --role.",
        "Run `visus list-fields` to see what is on the page.",
    ):
        assert line in text, f"cli-targeting.md no longer quotes {line!r}"


def test_troubleshooting_reference_carries_the_literal_daemon_errors() -> None:
    """Symptom lookup only works if the strings match the daemon byte for byte."""
    text = (SKILL_DIR / "references" / "troubleshooting.md").read_text(encoding="utf-8")
    for literal in (
        "no live session — run `visus session start` first",
        "a session is already running (pid",
        "daemon did not come up within",
        "daemon closed the connection without responding",
        "unauthorized: bad token",
        "out of range (have",
    ):
        assert literal in text, f"missing the literal error {literal!r}"


_REFERENCES = (
    "cli-session.md",
    "cli-targeting.md",
    "cli-commands.md",
    "cli-json-and-piping.md",
    "cli-repl.md",
    "windows-shell.md",
    "mcp-tools.md",
    "vision.md",
    "tracing-reports.md",
    "pytest-plugin.md",
    "troubleshooting.md",
    "library-api.md",
)


def test_every_reference_exists_and_is_linked() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    linked = set(re.findall(r"\]\(references/([A-Za-z0-9._-]+)\)", text))
    on_disk = {p.name for p in (SKILL_DIR / "references").glob("*.md")}
    assert on_disk == set(_REFERENCES), f"unexpected reference files: {on_disk}"
    assert linked == set(_REFERENCES), f"unlinked: {sorted(set(_REFERENCES) - linked)}"


def test_no_reference_link_is_dead() -> None:
    for path in (SKILL_DIR / "references").glob("*.md"):
        for target in re.findall(r"\]\(([A-Za-z0-9._-]+\.md)\)", path.read_text(encoding="utf-8")):
            assert (SKILL_DIR / "references" / target).is_file(), f"{path.name} -> {target}"


def test_skill_has_a_specific_tasks_index() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "## Specific tasks" in text
    tail = text.split("## Specific tasks", 1)[1]
    assert tail.count("](references/") >= 9


def test_contributor_recipe_names_every_place_a_session_command_touches() -> None:
    text = DEV_SKILL.read_text(encoding="utf-8")
    for fragment in (
        "session_server.py",
        "_op_",
        "console.py",
        "README.md",
        "references/cli-commands.md",
    ):
        assert fragment in text, f"the CLI recipe never mentions {fragment!r}"


def test_contributor_recipe_names_the_real_locator_helper() -> None:
    text = DEV_SKILL.read_text(encoding="utf-8")
    assert "make_locator" in text
    assert "locator(page, role=" not in text, "that helper does not exist"


def test_contributor_skill_declares_the_full_cli_extra() -> None:
    assert "[cli]` (typer + rich + click)" in DEV_SKILL.read_text(encoding="utf-8")
