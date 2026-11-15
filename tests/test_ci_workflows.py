"""The GitHub Actions workflows are a contract — assert them structurally.

Same anti-drift pattern as tests/test_mcp_server.py's tool inventory: a workflow
that silently stops running the suite, drops windows-latest, or loses its release
guard is a defect that only shows up when it is too late.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CI = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    """GitHub's `on:` key. YAML 1.1 parses a bare `on` as the boolean True."""
    if "on" in workflow:
        triggers: dict[str, Any] = workflow["on"]
        return triggers
    return workflow[True]


def _run_text(job: dict[str, Any]) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_ci_runs_on_push_and_pull_request_and_is_reusable() -> None:
    triggers = _triggers(_load(CI))
    assert "push" in triggers
    assert "pull_request" in triggers
    assert "workflow_call" in triggers, "publish.yml gates the build on this workflow"


def test_ci_declares_the_four_lanes() -> None:
    jobs = _load(CI)["jobs"]
    assert set(jobs) == {"lint", "fast-tests", "packaging-tests", "browser-tests"}


def test_lint_job_runs_both_static_gates() -> None:
    run = _run_text(_load(CI)["jobs"]["lint"])
    assert "ruff check src tests scripts" in run
    assert "mypy" in run


def test_fast_lane_covers_windows_and_the_declared_python_floor() -> None:
    job = _load(CI)["jobs"]["fast-tests"]
    matrix = job["strategy"]["matrix"]
    assert "windows-latest" in matrix["os"], (
        "Windows-first project: main.py shells to PowerShell, session_client.py shells to tasklist"
    )
    assert "ubuntu-latest" in matrix["os"]
    assert "3.10" in matrix["python"], 'requires-python = ">=3.10"'
    assert "3.12" in matrix["python"]
    assert job["strategy"]["fail-fast"] is False


def test_fast_lane_waives_the_gate_and_skips_the_slow_markers() -> None:
    run = _run_text(_load(CI)["jobs"]["fast-tests"])
    assert "not browser and not packaging" in run
    assert "--cov-fail-under=0" in run


def test_packaging_lane_runs_the_installed_console_scripts_on_both_platforms() -> None:
    job = _load(CI)["jobs"]["packaging-tests"]
    assert set(job["strategy"]["matrix"]["os"]) == {"ubuntu-latest", "windows-latest"}
    assert "-m packaging" in _run_text(job)


def test_browser_lane_is_windows_and_carries_both_coverage_gates() -> None:
    job = _load(CI)["jobs"]["browser-tests"]
    assert job["runs-on"] == "windows-latest"
    run = _run_text(job)
    assert "visus doctor" in run, "smoke-test Chrome + Selenium Manager before 298 browser tests"
    assert "--cov-fail-under=90" in run
    assert "--cov-report=json" in run
    assert "scripts/check_coverage.py" in run


def test_browser_lane_pins_xdist_parallelism_instead_of_auto() -> None:
    """`-n auto` exhausts memory on many-core machines: each xdist worker loads its
    own ONNX model for the vision tests (test_e2e_vision.py runs under the
    `browser` marker) and workers die with `_ArrayMemoryError`. A real full-suite
    run measured `-n 4` as safe (935 passed, 7 skipped, 0 failed, 14m52s); relying
    on the bare `-n auto` baked into `[tool.pytest.ini_options] addopts` would let
    a wide GitHub-hosted runner rediscover that crash. Then `-n 3`: on the 4-core
    windows runners, 4 browsers plus the fixture servers flaked (renderer timeouts,
    "session not created") in the v0.3.4 and v0.3.6 release runs.
    """
    run = _run_text(_load(CI)["jobs"]["browser-tests"])
    assert "-n 3" in run, "pin xdist workers explicitly rather than trust -n auto's default"


def test_workflow_files_are_well_formed_yaml() -> None:
    for path in (CI, REPO_ROOT / ".github" / "workflows" / "publish.yml"):
        assert _load(path)["jobs"], f"{path} has no jobs"


PUBLISH = REPO_ROOT / ".github" / "workflows" / "publish.yml"


GUARD = "github.event_name == 'release' && github.event.release.target_commitish == 'main'"


def test_every_publish_job_is_guarded_to_a_real_release() -> None:
    jobs = _load(PUBLISH)["jobs"]
    assert jobs, "publish.yml declares no jobs"
    for name, job in jobs.items():
        assert job.get("if") == GUARD, (
            f"job {name!r} has no release guard — without it a workflow_dispatch "
            f"from ANY branch, or a Release cut from ANY branch, publishes to PyPI"
        )


def test_the_branch_half_of_the_guard_uses_target_commitish_not_github_ref() -> None:
    """On a `release` event GITHUB_REF is the TAG ref, never a branch ref.

    So `github.ref == 'refs/heads/main'` — the obvious-looking way to write "only
    from main" — is never true on a release, and would silently block every
    publish while looking like a working guard. The branch a Release was cut from
    lives in `github.event.release.target_commitish`.
    """
    for job in _load(PUBLISH)["jobs"].values():
        condition = job.get("if", "")
        assert "target_commitish" in condition
        assert "github.ref" not in condition, (
            "github.ref is the tag ref on a release event — this guard would "
            "never pass and no release would ever publish"
        )


def test_workflow_dispatch_is_still_declared_so_the_guard_is_observable() -> None:
    triggers = _triggers(_load(PUBLISH))
    assert "release" in triggers
    assert "workflow_dispatch" in triggers


def test_build_cannot_run_before_the_ci_gates() -> None:
    jobs = _load(PUBLISH)["jobs"]
    assert jobs["test"]["uses"] == "./.github/workflows/ci.yml"
    assert jobs["build"]["needs"] == ["test"]
    assert jobs["publish"]["needs"] == ["build"]


def test_build_asserts_the_wheel_ships_the_agent_skill() -> None:
    run = _run_text(_load(PUBLISH)["jobs"]["build"])
    assert "visus/web/skills/visus-web/SKILL.md" in run
    assert "visus/web/backends/selenium/js/bundle.js" in run
