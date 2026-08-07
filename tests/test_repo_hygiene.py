"""Repo hygiene guards — the pytest equivalents of playwright's `forbidOnly`.

CONVENTIONS for this repo forbid `skip`, `xfail` and mock-to-pass. Two
conditional skips predate that rule and are allowlisted by name with the reason;
anything else is a regression. Separately, a test function that `return`s instead
of asserting is silently useless, so that is scanned for structurally.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TESTS = REPO_ROOT / "tests"
SELF = Path(__file__).name

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
