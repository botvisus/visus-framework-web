"""Packaging, installation and drift detection for the bundled agent skill.

Every test that touches a target directory chdir's into ``tmp_path`` first —
nothing in this module may write ``.claude`` or ``.agents`` into the repo.
"""

from __future__ import annotations

import io
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from visus.web.cli import skill_check
from visus.web.cli._entry import cli_main, mcp_main
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


def test_read_skill_normalises_crlf(tmp_path: Path) -> None:
    f = tmp_path / "SKILL.md"
    f.write_bytes(b"# title\r\nbody\r\n")
    assert skill_check.read_skill(f) == "# title\nbody\n"


def test_read_skill_returns_none_when_missing(tmp_path: Path) -> None:
    assert skill_check.read_skill(tmp_path / "nope.md") is None


def test_frame_pads_every_line_to_the_widest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_check.sys, "stderr", io.StringIO())  # utf-8 capable
    out = skill_check.frame(["ab", "cdefg"])
    assert out == ("╔═══════╗\n║ ab    ║\n║ cdefg ║\n╚═══════╝\n")


def test_frame_falls_back_to_ascii_on_a_cp1252_console(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(skill_check.sys, "stderr", stream)
    out = skill_check.frame(["hi"])
    assert out == "+----+\n| hi |\n+----+\n"
    out.encode("cp1252")  # must not raise


def test_frame_handles_no_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_check.sys, "stderr", io.StringIO())
    assert skill_check.frame([]) == "╔══╗\n╚══╝\n"


def test_check_is_silent_when_nothing_is_installed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    skill_check.check_installed_skills(tmp_path)
    assert capsys.readouterr().err == ""


def test_check_is_silent_when_the_copy_matches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    install_skills(tmp_path, flavor="claude")
    capsys.readouterr()
    skill_check.check_installed_skills(tmp_path)
    assert capsys.readouterr().err == ""


def test_check_warns_on_stderr_when_the_copy_diverges(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    install_skills(tmp_path, flavor="claude")
    installed = tmp_path / ".claude" / "skills" / "visus-web" / "SKILL.md"
    with installed.open("a", encoding="utf-8") as fh:
        fh.write("x")
    capsys.readouterr()
    skill_check.check_installed_skills(tmp_path)
    captured = capsys.readouterr()
    assert "does not match the tool version" in captured.err
    assert "visus install --skills" in captured.err
    assert captured.out == "", "the warning must never reach stdout"


def test_check_ignores_a_crlf_only_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Regression: a CRLF checkout must not look like drift (Windows-first repo)."""
    install_skills(tmp_path, flavor="claude")
    installed = tmp_path / ".claude" / "skills" / "visus-web" / "SKILL.md"
    installed.write_bytes(installed.read_text(encoding="utf-8").replace("\n", "\r\n").encode())
    capsys.readouterr()
    skill_check.check_installed_skills(tmp_path)
    assert capsys.readouterr().err == ""


def test_check_never_raises_when_the_bundle_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom() -> Path:
        raise RuntimeError("resource resolution exploded")

    monkeypatch.setattr(skill_check, "bundled_skill_dir", _boom)
    skill_check.check_installed_skills(tmp_path)  # must not raise


def test_cli_warns_after_the_skill_is_edited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Port of playwright-cli tests/integration.spec.ts:75-86."""
    monkeypatch.delenv("VISUS_WEB_NO_SKILL_CHECK")  # this test IS the check (conftest)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["install", "--skills=claude"]).exit_code == 0
    installed = tmp_path / ".claude" / "skills" / "visus-web" / "SKILL.md"
    with installed.open("a", encoding="utf-8") as fh:
        fh.write("x")

    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert "does not match the tool version" in r.stderr
    assert "visus install --skills" in r.stderr
    assert "does not match the tool version" not in r.stdout


def test_cli_does_not_warn_on_a_line_ending_only_difference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Port of playwright-cli tests/integration.spec.ts:88-99 — the CRLF regression."""
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["install", "--skills=claude"]).exit_code == 0
    installed = tmp_path / ".claude" / "skills" / "visus-web" / "SKILL.md"
    installed.write_bytes(installed.read_text(encoding="utf-8").replace("\n", "\r\n").encode())

    r = runner.invoke(app, ["version"])
    assert r.exit_code == 0
    assert "does not match the tool version" not in r.stderr


def test_install_commands_never_emit_the_drift_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["install", "--skills=claude"]).exit_code == 0
    installed = tmp_path / ".claude" / "skills" / "visus-web" / "SKILL.md"
    with installed.open("a", encoding="utf-8") as fh:
        fh.write("x")

    for argv in (["install", "--skills=claude"], ["install-skills", "--target", "claude"]):
        r = runner.invoke(app, argv)
        assert r.exit_code == 0, r.output
        assert "does not match the tool version" not in r.stderr, argv


def test_cli_main_accepts_a_bare_skills_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`visus install --skills` — the playwright-cli spelling — must work end to end."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["visus", "install", "--skills"])
    with pytest.raises(SystemExit) as exc:
        cli_main()
    assert exc.value.code == 0
    assert (tmp_path / ".claude" / "skills" / "visus-web" / "SKILL.md").is_file()


def test_cli_main_reports_a_missing_cli_extra(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "typer", None)
    with pytest.raises(SystemExit) as exc:
        cli_main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "visus-web[cli]" in err
    assert "pip install" in err


def test_mcp_main_reports_a_missing_mcp_extra(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "mcp", None)
    with pytest.raises(SystemExit) as exc:
        mcp_main()
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "visus-web[mcp]" in err


def test_mcp_main_delegates_to_the_server(monkeypatch: pytest.MonkeyPatch) -> None:
    import visus.web.mcp.server as server

    calls: list[str] = []
    monkeypatch.setattr(server, "main", lambda: calls.append("ran"))
    mcp_main()
    assert calls == ["ran"]


def test_python_dash_m_runs_the_cli() -> None:
    """`python -m visus.web.cli` is the fallback when the console script is off PATH."""
    from visus.web import __version__

    proc = subprocess.run(
        [sys.executable, "-m", "visus.web.cli", "version"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert __version__ in proc.stdout


def test_help_advertises_the_skill_install() -> None:
    """`visus --help` must tell the user the agent skill exists.

    The skill ships inside the wheel but is inert until a repo installs a copy,
    and the command list alone never explains why anyone would want one. Mirrors
    the epilog `playwright-cli --help` prints for the same reason.
    """
    from typer.testing import CliRunner

    from visus.web.cli.main import app

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    assert "Installing skills" in result.output
    assert "visus install --skills" in result.output


def test_the_skill_check_can_be_turned_off(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """VISUS_WEB_NO_SKILL_CHECK=1: the CLI skips the check (an automation that reads the
    output); unset, it runs."""
    from typer.testing import CliRunner

    from visus.web.cli.main import app

    calls: list[str] = []
    monkeypatch.setattr(skill_check, "check_installed_skills", lambda: calls.append("x"))
    monkeypatch.setenv("VISUS_WEB_NO_SKILL_CHECK", "1")
    CliRunner().invoke(app, ["version"])
    assert calls == []
    monkeypatch.delenv("VISUS_WEB_NO_SKILL_CHECK")
    CliRunner().invoke(app, ["version"])
    assert calls == ["x"]
