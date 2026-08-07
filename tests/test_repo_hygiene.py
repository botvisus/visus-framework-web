"""Repo hygiene guards — the pytest equivalents of playwright's `forbidOnly`.

CONVENTIONS for this repo forbid `skip`, `xfail` and mock-to-pass. Two
conditional skips predate that rule and are allowlisted by name with the reason;
anything else is a regression. Separately, a test function that `return`s instead
of asserting is silently useless, so that is scanned for structurally.
"""

from __future__ import annotations

import ast
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS = REPO_ROOT / "tests"
SELF = Path(__file__).name
PRE_COMMIT = REPO_ROOT / ".pre-commit-config.yaml"

#: Pre-existing conditional skips. Both run for real when the environment allows.
ALLOWED_SKIPS = {
    # IE-mode needs window focus and hangs the worker under xdist (TESTING.md).
    "test_e2e_edge_ie.py",
    # Firefox is optional in this environment; the test runs the moment it exists.
    "test_e2e_firefox.py",
}

_NEEDLES = ("pytest.skip", "pytest.mark." + "skip", "pytest.mark." + "xfail", "pytest." + "xfail")


def _test_modules() -> list[Path]:
    return sorted(p for p in TESTS.glob("test_*.py") if p.name != SELF)


def test_no_new_skips_or_xfails() -> None:
    offenders: list[str] = []
    for path in _test_modules():
        if path.name in ALLOWED_SKIPS:
            continue
        # Two modules carry a UTF-8 BOM; utf-8-sig reads both forms.
        for lineno, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            if any(needle in line for needle in _NEEDLES):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "skip/xfail is forbidden — prove the behaviour or delete the test:\n"
        + "\n".join(offenders)
    )


def _direct_return_lines(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[int]:
    """Return statements in the function's OWN body (nested defs/lambdas excluded)."""
    lines: list[int] = []
    stack: list[ast.AST] = list(function.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(node, ast.Return) and node.value is not None:
            lines.append(node.lineno)
        stack.extend(ast.iter_child_nodes(node))
    return lines


def test_no_test_function_returns_a_value() -> None:
    offenders: list[str] = []
    for path in _test_modules():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test_"):
                continue
            for lineno in _direct_return_lines(node):
                offenders.append(f"{path.name}:{lineno}: {node.name} returns a value")
    assert not offenders, (
        "a test that returns instead of asserting proves nothing:\n" + "\n".join(offenders)
    )


def _pre_commit_hooks() -> dict[str, dict[str, object]]:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    return {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}


def test_pre_commit_config_exists() -> None:
    assert PRE_COMMIT.is_file(), (
        "pyproject.toml declares pre-commit in [dev]; without this file "
        "`pre-commit install` fails and the dependency is dead weight"
    )


def test_pre_commit_hooks_are_the_ci_gates_verbatim() -> None:
    hooks = _pre_commit_hooks()
    assert {"ruff", "mypy"} <= set(hooks)
    assert str(hooks["ruff"]["entry"]).startswith("uv run ruff check")
    assert str(hooks["mypy"]["entry"]).startswith("uv run mypy")
    assert hooks["mypy"]["pass_filenames"] is False  # [tool.mypy] packages = ["visus.web"]


def test_pre_commit_hooks_are_local_only() -> None:
    config = yaml.safe_load(PRE_COMMIT.read_text(encoding="utf-8"))
    assert [repo["repo"] for repo in config["repos"]] == ["local"], (
        "remote hook repos would need a network clone and could pin a different "
        "ruff/mypy than the CI gates"
    )


DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"

FULL_GATE = (
    "uv run ruff check src tests scripts",
    "uv run mypy",
    "uv run pytest -q --cov-fail-under=90 --cov-report=json",
    "uv run python scripts/check_coverage.py",
)


def test_dependabot_watches_pip_and_github_actions() -> None:
    config = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    assert config["version"] == 2
    ecosystems = {update["package-ecosystem"] for update in config["updates"]}
    assert {"pip", "github-actions"} <= ecosystems


def test_the_repo_hygiene_documents_exist() -> None:
    for name in ("CONTRIBUTING.md", "SECURITY.md", "RELEASING.md"):
        path = REPO_ROOT / name
        assert path.is_file(), f"{name} is missing"
        assert path.read_text(encoding="utf-8").strip(), f"{name} is empty"


def test_contributing_documents_the_full_gate_verbatim() -> None:
    text = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    for command in FULL_GATE:
        assert command in text, f"CONTRIBUTING.md does not document `{command}`"


def test_release_runbook_names_both_version_strings() -> None:
    text = (REPO_ROOT / "RELEASING.md").read_text(encoding="utf-8")
    assert "pyproject.toml" in text
    assert "src/visus/web/__init__.py" in text, (
        "the version is duplicated there (line 17) — a release that bumps only "
        "pyproject.toml ships a package whose `visus version` lies"
    )
    assert "workflow_dispatch" in text, "the runbook must state that dispatch does not publish"


def test_security_policy_points_at_a_private_channel() -> None:
    text = (REPO_ROOT / "SECURITY.md").read_text(encoding="utf-8")
    assert "security/advisories/new" in text
    assert "do not open a public issue" in text.lower()
