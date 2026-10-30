"""Proof that the INSTALLED console scripts work — the one thing CliRunner cannot show.

Every other CLI test imports `visus.web.cli.main.app` in-process, so the
`[project.scripts]` entry points are never resolved and never executed. Even the
genuine cross-process test (tests/test_e2e_cli_session.py:42) calls the library
function `session_client.start_daemon()`, which spawns
`python -m visus.web.cli.session_server` — still not the `visus` executable.

These tests build the real wheel, install it into throw-away virtualenvs, and run
the real `visus` binary, including the case where the optional `[cli]` extra is
absent (the CLI must explain itself, not raise ModuleNotFoundError).

Marked `packaging`: they need network (pip resolves selenium/typer from PyPI) and
take minutes, so CI runs them in a dedicated job.
"""

from __future__ import annotations

import subprocess
import sys
import venv
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

pytestmark = [pytest.mark.packaging, pytest.mark.timeout(900)]


# A stalled download (a TLS read that never gets data) is NOT covered by pip's own
# retries: without a cap the install hung for an hour until pytest-timeout os._exit'ed
# the whole xdist worker ("node down: Not properly terminated"). Fail it, clearly.
INSTALL_TIMEOUT = 600


def _run(command: list[str], *, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    # Decode as UTF-8 explicitly: `text=True` alone picks the locale encoding, and on
    # Windows that is cp1252, which cannot decode the box-drawing characters Rich puts
    # in `visus --help`. The decode then fails inside subprocess' reader thread and
    # `stdout` silently arrives as None.
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(f"{command[2:5]} did not finish in {timeout:g}s -- is PyPI reachable?")


def _venv_executables(env_dir: Path) -> tuple[Path, Path]:
    """Return (python, visus) inside *env_dir* for this platform."""
    if sys.platform == "win32":
        bindir = env_dir / "Scripts"
        return bindir / "python.exe", bindir / "visus.exe"
    bindir = env_dir / "bin"
    return bindir / "python", bindir / "visus"


def _install(env_dir: Path, requirement: str) -> Path:
    """Create a fresh venv, pip-install *requirement*, return the `visus` path."""
    venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)
    python, visus = _venv_executables(env_dir)
    proc = _run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "-q",
            "--timeout",
            "30",
            "--retries",
            "3",
            requirement,
        ],
        timeout=INSTALL_TIMEOUT,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return visus


@pytest.fixture(scope="module")
def wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the real wheel from this checkout (no build isolation: offline-safe)."""
    outdir = tmp_path_factory.mktemp("dist")
    proc = _run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(outdir),
            str(REPO_ROOT),
        ]
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    wheels = sorted(outdir.glob("visus_web-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {[w.name for w in wheels]}"
    return wheels[0]


@pytest.fixture(scope="module")
def cli_visus(tmp_path_factory: pytest.TempPathFactory, wheel: Path) -> Path:
    """`visus` from a venv where the [cli] extra IS installed."""
    return _install(tmp_path_factory.mktemp("with-cli") / "venv", f"{wheel}[cli]")


@pytest.fixture(scope="module")
def bare_visus(tmp_path_factory: pytest.TempPathFactory, wheel: Path) -> Path:
    """`visus` from a venv where the [cli] extra is ABSENT (base deps only)."""
    return _install(tmp_path_factory.mktemp("no-cli") / "venv", str(wheel))


def test_wheel_ships_the_runtime_data_files(wheel: Path) -> None:
    names = set(zipfile.ZipFile(wheel).namelist())
    for required in (
        "visus/web/py.typed",
        "visus/web/backends/selenium/js/bundle.js",
        "visus/web/skills/visus-web/SKILL.md",
    ):
        assert required in names, f"{required} is missing from {wheel.name}"


def test_wheel_declares_both_console_scripts(wheel: Path) -> None:
    archive = zipfile.ZipFile(wheel)
    entry = next(n for n in archive.namelist() if n.endswith(".dist-info/entry_points.txt"))
    text = archive.read(entry).decode("utf-8")
    assert "visus = visus.web.cli._entry:cli_main" in text
    assert "visus-web-mcp = visus.web.cli._entry:mcp_main" in text


def test_installed_visus_help_runs_through_the_real_entry_point(cli_visus: Path) -> None:
    assert cli_visus.is_file(), f"{cli_visus} was not created by the install"
    proc = _run([str(cli_visus), "--help"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for command in ("session", "list-fields", "translate", "doctor"):
        assert command in proc.stdout, f"{command!r} missing from `visus --help`"


def test_installed_visus_version_matches_the_package(cli_visus: Path) -> None:
    from visus.web import __version__

    proc = _run([str(cli_visus), "version"])
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == __version__


def test_visus_without_the_cli_extra_explains_itself(bare_visus: Path) -> None:
    assert bare_visus.is_file(), f"{bare_visus} was not created by the install"
    proc = _run([str(bare_visus), "--help"])
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, "a CLI that cannot start must not exit 0"
    assert "visus-web[cli]" in combined, (
        "the guard must name the pip target the user needs to install"
    )
    assert "Traceback" not in combined
    assert "ModuleNotFoundError" not in combined
