"""Repo-metadata guards.

These tests read ``pyproject.toml`` rather than any importable code: they exist to
catch packaging mistakes that no unit test would notice because they only bite on a
*fresh install*, in CI, or in a user's environment.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on the 3.10 floor
    import tomli as tomllib

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"
ROOT = PYPROJECT.parent

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


def test_the_license_is_stated_consistently_everywhere() -> None:
    """LICENSE, PyPI metadata and README must not disagree about the licence.

    They did: LICENSE and pyproject.toml said Apache-2.0 while README carried a
    "Proprietary — all rights reserved" badge and prose. Both render on the same
    PyPI project page, so a reader had no way to tell which one bound them, and
    the packaged metadata is the legally operative one.
    """
    declared = _pyproject()["project"]["license"]
    assert declared == "Apache-2.0", declared

    license_text = (PYPROJECT.parent / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in license_text
    assert "Version 2.0" in license_text

    readme = (PYPROJECT.parent / "README.md").read_text(encoding="utf-8")
    lowered = readme.lower()
    assert "proprietary" not in lowered, (
        "README still claims a proprietary licence while LICENSE and pyproject.toml "
        "say Apache-2.0 — the two render on the same PyPI page"
    )
    assert "all rights reserved" not in lowered
    assert "Apache" in readme


def test_gitignore_ignores_the_installed_self_skill_but_keeps_the_contributor_one() -> None:
    """`visus install --skills` writes build artifacts; the contributor skill is source.

    The installed copy under ``.claude/skills/visus-web/`` (and its ``.agents/``
    twin) must stay untracked, while ``.claude/skills/developing-visus-web/`` — the
    skill for people contributing to this repo — must remain tracked.
    """
    lines = [ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert ".claude/skills/visus-web/" in lines
    assert ".agents/" in lines
    assert ".claude/" not in lines, "that would untrack the contributor skill"
    assert (ROOT / ".claude" / "skills" / "developing-visus-web" / "SKILL.md").is_file()


def test_gitignore_still_hides_planning_docs_but_allows_the_docs_page() -> None:
    """`/docs/` is local-only planning material except the one page the site needs.

    Git cannot un-ignore a file whose parent directory is excluded, so the rule has
    to be ``/docs/*`` plus a negated re-include rather than a blanket ``/docs/``.
    """
    lines = [ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert "/docs/*" in lines
    assert "!/docs/agent-skill.md" in lines


def test_readme_clone_url_matches_the_package_repository_url() -> None:
    """The README's `git clone` instructions must name the same org as PyPI does."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r'^Repository = "([^"]+)"', pyproject, re.M)
    assert match, "pyproject.toml has no Repository URL"
    assert f"git clone {match.group(1)}" in readme


def test_pypi_metadata_is_not_thin() -> None:
    """PyPI search and filtering rely on keywords and a full classifier set."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "keywords = [" in pyproject
    for version in ("3.10", "3.11", "3.12", "3.13"):
        assert f'"Programming Language :: Python :: {version}"' in pyproject
    for classifier in (
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Testing",
        "Typing :: Typed",
    ):
        assert classifier in pyproject, f"missing classifier {classifier!r}"


def test_docs_site_carries_the_agent_skill() -> None:
    """The mkdocs nav must reach the agent-skill page, and the page must exist."""
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert "agent-skill.md" in mkdocs, "the mkdocs nav does not reach the skill"
    page = ROOT / "docs" / "agent-skill.md"
    assert page.is_file()
    text = page.read_text(encoding="utf-8")
    assert "visus install --skills" in text
    assert "visus session start" in text
