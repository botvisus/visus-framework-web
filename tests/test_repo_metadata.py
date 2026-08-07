"""Repo-metadata guards.

These tests read ``pyproject.toml`` rather than any importable code: they exist to
catch packaging mistakes that no unit test would notice because they only bite on a
*fresh install*, in CI, or in a user's environment.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on the 3.10 floor
    import tomli as tomllib

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"

# `docs` never reaches a user's environment and is not installed in CI, so a new
# major there cannot break anything we ship.
_UNGUARDED_EXTRAS = frozenset({"docs"})


def _pyproject() -> dict[str, Any]:
    with PYPROJECT.open("rb") as fh:
        return tomllib.load(fh)


def _declared_requirements() -> list[tuple[str, str]]:
    """Every (extra, requirement) pair we promise to keep installable."""
    data = _pyproject()
    pairs = [("<runtime>", spec) for spec in data["project"]["dependencies"]]
    for extra, specs in data["project"]["optional-dependencies"].items():
        if extra in _UNGUARDED_EXTRAS:
            continue
        pairs.extend((extra, spec) for spec in specs)
    return pairs


def test_every_dependency_declares_an_upper_bound() -> None:
    """An unbounded floor lets a new major silently break a published extra.

    This is not hypothetical. ``mcp>=1.2.0`` admitted mcp 2.0.0, which removed
    ``mcp.server.fastmcp``; since that release every ``visus.web.mcp.server`` import
    has raised ``ModuleNotFoundError`` on a fresh install, so ``pip install
    "visus-web[mcp]"`` shipped a dead server without a single change to this repo.
    """
    unbounded = [
        f"{extra}: {spec}"
        for extra, spec in _declared_requirements()
        if not any(op in spec for op in ("<", "==", "~="))
    ]
    assert unbounded == [], (
        "these requirements have no upper bound, so a new major release can break "
        f"an install with no change to this repo: {unbounded}"
    )


def test_mcp_extra_excludes_the_release_that_removed_fastmcp() -> None:
    """`mcp` 2.0.0 deleted `mcp.server.fastmcp`, which `mcp/server.py` imports.

    Pinned explicitly rather than left to the generic bound above, so that relaxing
    the ceiling is a deliberate act that has to delete this test.
    """
    (spec,) = _pyproject()["project"]["optional-dependencies"]["mcp"]
    assert "<2" in spec, (
        f"the mcp extra must exclude 2.x while src/visus/web/mcp/server.py imports "
        f"mcp.server.fastmcp; got {spec!r}"
    )


def test_numpy_bound_keeps_mypy_able_to_parse_its_stubs() -> None:
    """numpy 2.5's stubs use PEP 695 `type` statements.

    Under ``python_version = "3.10"`` mypy rejects them as a *syntax* error at
    ``numpy/__init__.pyi`` and stops before checking any of our code — so the gate
    passes vacuously. numpy 2.4 and earlier parse fine.
    """
    vision = _pyproject()["project"]["optional-dependencies"]["vision"]
    (numpy_spec,) = [s for s in vision if s.startswith("numpy")]
    assert "<2.5" in numpy_spec, (
        "numpy must stay below 2.5 while [tool.mypy] targets python_version 3.10, "
        f"otherwise mypy silently checks nothing; got {numpy_spec!r}"
    )


def test_runtime_imports_are_declared() -> None:
    """`rich` is imported at runtime by the CLI, not merely by Typer.

    ``src/visus/web/cli/main.py`` and ``console.py`` both ``import rich`` directly.
    Today Typer happens to pull it in, but that is a transitive accident: if Typer
    ever drops it, the CLI breaks with no change here.
    """
    cli = _pyproject()["project"]["optional-dependencies"]["cli"]
    assert any(s.startswith("rich") for s in cli), (
        f"the cli extra must declare rich (imported directly by the CLI); got {cli}"
    )
