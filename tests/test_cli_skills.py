"""Packaging, installation and drift detection for the bundled agent skill.

Every test that touches a target directory chdir's into ``tmp_path`` first —
nothing in this module may write ``.claude`` or ``.agents`` into the repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from visus.web.cli.main import app
from visus.web.cli.skills import (
    SKILL_NAME,
    SkillTarget,
    bundled_skill_dir,
    install_skills,
    installed_skill_targets,
    normalize_skills_argv,
)

runner = CliRunner()


def test_bundled_skill_dir_contains_skill_md() -> None:
    """The skill ships inside the package and is resolvable at runtime."""
    d = bundled_skill_dir()
    assert d.is_dir(), f"{d} is not a directory"
    assert d.name == SKILL_NAME
    assert (d / "SKILL.md").is_file(), f"{d / 'SKILL.md'} is missing"


def test_bundled_skill_dir_lives_inside_the_package() -> None:
    """Resolution goes through the installed package, not the repo root."""
    import visus.web

    package_root = Path(str(visus.web.__file__)).parent
    assert bundled_skill_dir().parent.parent == package_root


def test_installed_skill_targets_names_both_flavors(tmp_path: Path) -> None:
    """Two targets, each carrying its own remediation command."""
    targets = installed_skill_targets(tmp_path)
    assert [t.flavor for t in targets] == ["claude", "agents"]
    assert targets[0] == SkillTarget(
        dir=tmp_path / ".claude" / "skills" / "visus-web",
        command="visus install --skills",
        flavor="claude",
    )
    assert targets[1] == SkillTarget(
        dir=tmp_path / ".agents" / "skills" / "visus-web",
        command="visus install --skills=agents",
        flavor="agents",
    )


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["install", "--skills"], ["install", "--skills=claude"]),
        (["install", "--skills", "--force"], ["install", "--skills=claude", "--force"]),
        (["install", "--skills", "agents"], ["install", "--skills", "agents"]),
        (["install", "--skills=agents"], ["install", "--skills=agents"]),
        (["version"], ["version"]),
        ([], []),
    ],
)
def test_normalize_skills_argv(argv: list[str], expected: list[str]) -> None:
    """A bare ``--skills`` becomes ``--skills=claude``; every other form is untouched."""
    assert normalize_skills_argv(argv) == expected


def test_install_skills_writes_the_claude_target(tmp_path: Path) -> None:
    written = install_skills(tmp_path, flavor="claude")
    skill = tmp_path / ".claude" / "skills" / "visus-web" / "SKILL.md"
    assert skill.is_file()
    assert skill in written
    assert not (tmp_path / ".agents").exists()
    assert skill.read_bytes() == (bundled_skill_dir() / "SKILL.md").read_bytes()


def test_install_skills_both_flavors(tmp_path: Path) -> None:
    install_skills(tmp_path, flavor="both")
    assert (tmp_path / ".claude" / "skills" / "visus-web" / "SKILL.md").is_file()
    assert (tmp_path / ".agents" / "skills" / "visus-web" / "SKILL.md").is_file()


def test_install_skills_force_removes_stale_files(tmp_path: Path) -> None:
    install_skills(tmp_path, flavor="claude")
    stale = tmp_path / ".claude" / "skills" / "visus-web" / "stale.md"
    stale.write_text("gone", encoding="utf-8")
    install_skills(tmp_path, flavor="claude")
    assert stale.is_file(), "without --force an unknown file must survive"
    install_skills(tmp_path, flavor="claude", force=True)
    assert not stale.exists(), "with --force the target must mirror the bundle"


def test_cli_install_skills_equals_agents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["install", "--skills=agents"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / ".agents" / "skills" / "visus-web" / "SKILL.md").is_file()
    assert not (tmp_path / ".claude").exists()


def test_cli_install_skills_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["install-skills", "--target", "both"])
    assert r.exit_code == 0, r.output
    assert (tmp_path / ".claude" / "skills" / "visus-web" / "SKILL.md").is_file()
    assert (tmp_path / ".agents" / "skills" / "visus-web" / "SKILL.md").is_file()
    assert "installed the visus-web skill" in r.stdout


def test_cli_install_skills_rejects_unknown_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    r = runner.invoke(app, ["install-skills", "--target", "cursor"])
    assert r.exit_code == 2
    assert "unknown skill target" in r.output
