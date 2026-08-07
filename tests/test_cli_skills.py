"""Packaging, installation and drift detection for the bundled agent skill.

Every test that touches a target directory chdir's into ``tmp_path`` first —
nothing in this module may write ``.claude`` or ``.agents`` into the repo.
"""

from __future__ import annotations

from pathlib import Path

from visus.web.cli.skills import (
    SKILL_NAME,
    SkillTarget,
    bundled_skill_dir,
    installed_skill_targets,
)


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
