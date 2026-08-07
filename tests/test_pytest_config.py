"""The pytest + coverage configuration is a contract — assert it directly.

``--cov-fail-under=90`` used to sit unconditionally in ``addopts``, which made a
filtered lane (``-m "not browser"`` selects 623 of 921 tests) fail the coverage
gate on arrival. The gate now lives in ``[tool.coverage.report]`` and is passed
explicitly by whichever invocation is supposed to enforce it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on the 3.10 floor
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent


def _pyproject() -> dict[str, Any]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        data: dict[str, Any] = tomllib.load(fh)
    return data


def _addopts() -> str:
    opts: str = _pyproject()["tool"]["pytest"]["ini_options"]["addopts"]
    return opts


def test_coverage_gate_is_not_baked_into_addopts() -> None:
    assert "--cov-fail-under" not in _addopts(), (
        "the 90% gate must not be unconditional: a `-m 'not browser'` lane can "
        "never reach it (298 of 921 tests need a real browser) and would fail on "
        "arrival. Pass the gate explicitly on the invocation that enforces it."
    )


def test_coverage_measurement_stays_on_by_default() -> None:
    addopts = _addopts()
    assert "--cov=visus.web" in addopts
    assert "--cov-report=term-missing" in addopts


def test_the_global_gate_lives_in_the_coverage_config() -> None:
    report = _pyproject()["tool"]["coverage"]["report"]
    assert report["fail_under"] == 90, (
        "one number, one place: pytest-cov, `coverage report` and "
        "scripts/check_coverage.py all read this value"
    )


def test_coverage_measures_the_source_tree() -> None:
    run = _pyproject()["tool"]["coverage"]["run"]
    assert run["source"] == ["visus.web"]


@pytest.mark.timeout(600)
def test_partial_run_waives_the_gate_but_keeps_measuring(tmp_path: Path) -> None:
    """A filtered run needs ONE flag to waive the gate, and still prints coverage.

    Runs the real pytest against the real pyproject in a subprocess with its own
    COVERAGE_FILE so it cannot clobber the outer run's ``.coverage``. Targets
    ``tests/test_engine.py``, a small non-browser file, to keep this fast.
    """
    env = dict(os.environ)
    env["COVERAGE_FILE"] = str(tmp_path / ".coverage.inner")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_engine.py",
            "-q",
            "-n",
            "0",
            "-p",
            "no:cacheprovider",
            "--cov-fail-under=0",
        ],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        env=env,
        timeout=540,
        check=False,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "Required test coverage" not in combined
    assert "visus" in proc.stdout, "the term-missing table should still be printed"


def test_markers_and_config_are_strict() -> None:
    addopts = _addopts()
    assert "--strict-markers" in addopts, "a typo'd marker must error, not silently register"
    assert "--strict-config" in addopts, "an unknown ini key must error, not be ignored"


def test_the_packaging_marker_is_registered() -> None:
    markers = _pyproject()["tool"]["pytest"]["ini_options"]["markers"]
    assert any(m.startswith("packaging:") for m in markers)


def test_pytests_own_warnings_are_fatal() -> None:
    filters = _pyproject()["tool"]["pytest"]["ini_options"]["filterwarnings"]
    assert "error::pytest.PytestUnknownMarkWarning" in filters
    assert "error::pytest.PytestCollectionWarning" in filters
    assert not any(f.strip() == "error" for f in filters), (
        "a blanket `error` would fail 775 tests on selenium/urllib3/onnxruntime "
        "deprecations this repo cannot fix"
    )
