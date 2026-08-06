# Tier 1 — Skill Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** make `pip install visus-web` ship the agent skill, make one command install it into a consuming repo, make drift detectable, and make the skill actually teach the 54-command CLI instead of the Python library.

**Architecture:** The skill tree moves from the untracked-by-the-wheel `skills/` sibling of `src/` into `src/visus/web/skills/visus-web/`, where hatchling's existing `packages = ["src/visus"]` picks it up as package data; runtime code resolves it through `importlib.resources.files("visus.web")`. Two new leaf modules — `cli/skills.py` (locate + copy) and `cli/skill_check.py` (read + compare + warn) — are wired into the project's **first** `@app.callback()`, which becomes the extension point PLAN 4 hangs its global flags on. Console scripts are repointed at a new `cli/_entry.py` that guards the optional extras before importing them. The skill itself is rewritten around the session daemon and split into twelve progressive-disclosure reference files, with a pytest drift test that fails when a CLI command or an MCP tool is added without a doc row.

**Tech Stack:** Python 3.10+, Typer, Rich, Selenium 4.38, pytest + pytest-xdist, hatchling, mypy --strict, ruff

## Global Constraints

- Repo root is `C:/Users/matheus.pereira/Documents/Visus/visus-framework-web`; `src/`-layout namespace package `visus.web` (there is **no** `src/visus/__init__.py`).
- Build is `uv` + `hatchling`. `pyproject.toml:61-62` stays `packages = ["src/visus"]` — do not add `force-include`, `artifacts`, `shared-data` or a `MANIFEST.in`.
- Gates, all three must pass before any commit: `uv run ruff check src tests`, `uv run mypy` (strict), `uv run pytest -q` (≥90 % coverage on `visus.web`).
- Ruff: line-length 100, `select = ["E","F","I","UP","B"]`. Keep every added line ≤100 characters.
- mypy: `strict = true`, `python_version = "3.10"`. Every new function is fully annotated; no `Any` leaks into a public signature.
- **THE HIDDEN-ENGINE RULE (inviolable):** no `selenium.*` type may appear in any public signature, return, exception or docstring. Selenium imports are allowed ONLY in `backends/browsers/*.py`, `backends/selenium/*.py`, `backends/selenium_backend.py`. Nothing in this plan touches those files.
- **Real browser, no fakes.** Browser-touching tests use `@pytest.mark.browser` and a fixture page under `tests/fixtures/*.html` served by the session-scoped `base_url` fixture in `tests/conftest.py`. Test doubles isolate a unit ONLY when its real behaviour is also covered by an integration test. No `skip`, no `xfail`, no mock-to-pass. *(This plan is packaging + docs; only Task 5's `python -m` test spawns a subprocess, and no task needs a browser.)*
- Single-test runs use `--no-cov` — the `--cov-fail-under=90` gate in `pyproject.toml:74` only makes sense on a full run.
- Commits: small, TDD (failing test → minimal impl → green → commit), semantic messages `label(scope): description` with labels `fix`, `feat`, `chore`, `docs`, `test`, `devops`. **Never** add a `Co-Authored-By` line.

## Prerequisites

**None.** This is PLAN 1 of 7; it lands first and consumes no symbol from any other plan.

What this plan **produces** for its neighbours:

| Symbol | Consumed by |
|---|---|
| `visus.web.cli.skills.bundled_skill_dir() -> Path` | PLAN 2 (wheel assertion), PLAN 7 (MCP/CLI unification) |
| `visus.web.cli.skills.SkillTarget` / `installed_skill_targets(cwd)` / `install_skills(cwd, *, flavor, force)` | PLAN 2 |
| `visus.web.cli.skill_check.frame(lines) -> str` | PLAN 4 (framed warnings), PLAN 6 |
| `visus.web.cli.skill_check.check_installed_skills(cwd=None) -> None` | — |
| `visus.web.cli._entry.cli_main()` / `mcp_main()` | PLAN 2 (subprocess entry-point tests) |
| **`visus.web.cli.main._root` — the `@app.callback()`** | **PLAN 4 — this is where `--json` / `--raw` / `--session` / `--config` attach. The exact contract is spelled out in Task 4's Interfaces block.** |
| `src/visus/web/skills/visus-web/references/*.md` | PLANS 3–7 add rows/sections here when they add commands |

## File Structure

**Created**

| Path | Single responsibility |
|---|---|
| `src/visus/web/skills/visus-web/SKILL.md` | The shipped agent skill (moved, then rewritten) |
| `src/visus/web/skills/visus-web/references/cli-session.md` | Daemon lifecycle, `.visus/`, index semantics |
| `src/visus/web/skills/visus-web/references/cli-targeting.md` | The target model — worked exemplar, written in full below |
| `src/visus/web/skills/visus-web/references/cli-commands.md` | The complete 54-command reference (ported from README) |
| `src/visus/web/skills/visus-web/references/cli-json-and-piping.md` | `--json`, exit codes, shell capture |
| `src/visus/web/skills/visus-web/references/cli-repl.md` | `visus console` REPL vocabulary and its 5 divergences |
| `src/visus/web/skills/visus-web/references/windows-shell.md` | PowerShell/cmd quoting, `visus translate` as the escape hatch |
| `src/visus/web/skills/visus-web/references/mcp-tools.md` | The 45 MCP tools and when to prefer them |
| `src/visus/web/skills/visus-web/references/vision.md` | OCR / captcha / template matching |
| `src/visus/web/skills/visus-web/references/tracing-reports.md` | `rpa()`, `tracing.record()`, HTML reports |
| `src/visus/web/skills/visus-web/references/pytest-plugin.md` | `visus_page` fixtures, CLI options |
| `src/visus/web/skills/visus-web/references/troubleshooting.md` | Symptom→cause→fix — worked exemplar, written in full below |
| `src/visus/web/skills/visus-web/references/library-api.md` | The Python API, async mirror, `NetworkCapture`, `edge_ie` |
| `.claude/skills/developing-visus-web/SKILL.md` | Contributor guide (moved out of the shipped package) |
| `src/visus/web/cli/skills.py` | Locate the bundled skill, enumerate targets, copy it |
| `src/visus/web/cli/skill_check.py` | Read + CRLF-normalise + compare + framed stderr warning |
| `src/visus/web/cli/_entry.py` | Console-script entry points that guard the optional extras |
| `src/visus/web/cli/__main__.py` | Makes `python -m visus.web.cli` work |
| `docs/agent-skill.md` | The mkdocs page that carries the skill |
| `tests/test_cli_skills.py` | Install / drift / CRLF / entry-point behaviour |
| `tests/test_skill_docs.py` | Doc-drift gate: commands and tool count must be documented |
| `tests/test_repo_metadata.py` | License, URL, `.gitignore`, PyPI-metadata consistency |

**Modified**

| Path | Change |
|---|---|
| `src/visus/web/cli/main.py:14-17` | Add the first `@app.callback()` |
| `src/visus/web/cli/main.py:110-114` | `install` grows `--skills`; new `install-skills` command |
| `src/visus/web/cli/main.py:162-168` | `visus mcp` routes through the guarded `_entry.mcp_main` |
| `src/visus/web/mcp/server.py` | Two skill resources + one prompt (tool count stays 45) |
| `pyproject.toml:45-47`, `:54-56`, `:14-17` | `[cli]` extra, repointed scripts, richer metadata |
| `README.md:9`, `:151`, `:367-376`, `:932`, `:944`, `:953`, `:960` | Skill install section, tooling rows, layout, clone URL, license |
| `mkdocs.yml:32-36` | Nav carries the skill |
| `.gitignore` | Ignore the installed self-skill, keep the contributor skill tracked |
| `tests/test_cli.py:20-24` | `--help` assertion covers `install-skills` |

**Scoping decision, stated up front so it does not read as an omission:** of the twelve reference files, `cli-targeting.md` and `troubleshooting.md` are written **in full** inside this plan (Task 8) because they encode non-obvious behaviour that cannot be re-derived — that `--name` alone is not a valid target (`main.py:232`), and the literal daemon error strings from `session_client.py:108,122,145,191` and `session_server.py:638`. `cli-commands.md` (Task 7) is a **mechanical port** of `README.md:286-376`, so the plan gives the exact line range plus every edit to apply rather than duplicating 90 lines of tables. The remaining nine files (Task 9) get a precise content outline, their opening content verbatim, and the exact source lines to port from — they are transcription work over material that already exists and is already correct.

---

### Task 1: Move the skill into the wheel and resolve it at runtime

**Files:**
- Move: `skills/using-visus-web/SKILL.md` → `src/visus/web/skills/visus-web/SKILL.md`
- Move: `skills/developing-visus-web/SKILL.md` → `.claude/skills/developing-visus-web/SKILL.md`
- Create: `src/visus/web/cli/skills.py`
- Modify: `README.md:932`, `README.md:953`
- Test: `tests/test_cli_skills.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  ```python
  BUNDLED_SKILL_PACKAGE = "visus.web.skills"
  SKILL_NAME = "visus-web"

  @dataclass(frozen=True)
  class SkillTarget:
      dir: Path
      command: str          # e.g. "visus install --skills"
      flavor: str           # "claude" | "agents"

  def bundled_skill_dir() -> Path: ...
  def installed_skill_targets(cwd: Path) -> list[SkillTarget]: ...
  ```
- `skills.py` must **not** import `typer`, `rich` or `mcp` at module level — `visus.web.mcp.server` imports it in Task 10 and the `[cli]` extra may be absent there.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_skills.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_skills.py -v --no-cov`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'visus.web.cli.skills'`

- [ ] **Step 3: Move both skill trees with git**

```bash
mkdir -p src/visus/web/skills
git mv skills/using-visus-web src/visus/web/skills/visus-web
mkdir -p .claude/skills
git mv skills/developing-visus-web .claude/skills/developing-visus-web
```

Confirm `skills/` is now gone (git removes an emptied tracked directory):

Run: `git status --short && ls src/visus/web/skills/visus-web && ls .claude/skills/developing-visus-web`
Expected: renames listed for both `SKILL.md` files, `skills/` absent from the working tree, `SKILL.md` present under each new location.

- [ ] **Step 4: Write minimal implementation**

Create `src/visus/web/cli/skills.py`:

```python
"""Locate the agent skill that ships inside the package, and install copies of it.

``pip install visus-web`` must deliver the skill, so the skill tree lives at
``src/visus/web/skills/visus-web`` (hatchling ships non-``.py`` files found inside
a packaged directory) and is resolved through :mod:`importlib.resources`.

This module is imported by the MCP server as well as the CLI, so it must stay
free of ``typer`` / ``rich`` / ``mcp`` imports.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

#: Dotted name of the packaged data directory, for documentation and error text.
#: ``visus/web/skills`` has no ``__init__.py`` — it is package *data*, so the
#: importlib anchor is ``visus.web`` and the rest is a path walk.
BUNDLED_SKILL_PACKAGE = "visus.web.skills"

#: Directory name of the skill, both inside the package and inside a target repo.
SKILL_NAME = "visus-web"


@dataclass(frozen=True)
class SkillTarget:
    """One place a consuming repo can hold an installed copy of the skill."""

    dir: Path
    command: str
    flavor: str


def bundled_skill_dir() -> Path:
    """Directory of the packaged skill, via importlib.resources."""
    return Path(str(files("visus.web") / "skills" / SKILL_NAME))


def installed_skill_targets(cwd: Path) -> list[SkillTarget]:
    """[(dir, remediation_command)] for .claude and .agents."""
    return [
        SkillTarget(
            dir=cwd / ".claude" / "skills" / SKILL_NAME,
            command="visus install --skills",
            flavor="claude",
        ),
        SkillTarget(
            dir=cwd / ".agents" / "skills" / SKILL_NAME,
            command="visus install --skills=agents",
            flavor="agents",
        ),
    ]


def install_skills(cwd: Path, *, flavor: str = "claude", force: bool = False) -> list[Path]:
    """Copy the bundled skill tree into the target(s). Returns written paths.

    ``flavor`` is ``"claude"``, ``"agents"`` or ``"both"``. Without ``force`` the
    copy overwrites the files it ships and leaves anything else in place; with
    ``force`` the target directory is removed first, so the result mirrors the
    bundle exactly.
    """
    src = bundled_skill_dir()
    written: list[Path] = []
    for target in installed_skill_targets(cwd):
        if flavor != "both" and target.flavor != flavor:
            continue
        if force and target.dir.exists():
            shutil.rmtree(target.dir)
        target.dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, target.dir, dirs_exist_ok=True)
        written.extend(sorted(p for p in target.dir.rglob("*") if p.is_file()))
    return written
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_skills.py -v --no-cov`
Expected: PASS — 3 passed

- [ ] **Step 6: Prove the built wheel actually contains the skill**

```bash
rm -rf dist
uv build --wheel
python -c "import glob,sys,zipfile; w=sorted(glob.glob('dist/*.whl'))[-1]; n=[f for f in zipfile.ZipFile(w).namelist() if f.endswith('SKILL.md')]; print(w); print(n); sys.exit(0 if n else 1)"
```

Expected: prints `dist/visus_web-0.2.0-py3-none-any.whl` then `['visus/web/skills/visus-web/SKILL.md']`, exit code 0.
If the list is empty, the move landed in the wrong directory — `SKILL.md` must be at `src/visus/web/skills/visus-web/SKILL.md`, not one level up.

```bash
rm -rf dist
```

*(PLAN 2 turns this same one-liner into a release-workflow assertion in `publish.yml`.)*

- [ ] **Step 7: Update the two README references to the old location**

In `README.md`, replace line 932:

```
├── skills/                     # using-visus-web, developing-visus-web (agent/contributor guides)
```

with:

```
├── .claude/skills/             # developing-visus-web (contributor guide, not shipped)
```

and add, directly under the `│   ├── cli/` line (currently `README.md:928`), a new line:

```
│   ├── skills/visus-web/       # the shipped agent skill (installed by `visus install --skills`)
```

Then replace `README.md:952-954`:

```
See [`TESTING.md`](TESTING.md) for the test matrix (including the Edge IE-mode end-to-end tests) and
the `skills/` directory for the agent-facing usage playbook (`using-visus-web`) and contributor guide
(`developing-visus-web`).
```

with:

```
See [`TESTING.md`](TESTING.md) for the test matrix (including the Edge IE-mode end-to-end tests),
`.claude/skills/developing-visus-web/` for the contributor guide, and
`src/visus/web/skills/visus-web/` for the agent-facing playbook that
`visus install --skills` copies into your repo.
```

- [ ] **Step 8: Run the gates**

Run: `uv run ruff check src tests && uv run mypy && uv run pytest -q`
Expected: ruff clean, mypy `Success: no issues found`, pytest all green with coverage ≥90 %.

- [ ] **Step 9: Commit**

```bash
git add src/visus/web/skills .claude/skills src/visus/web/cli/skills.py tests/test_cli_skills.py README.md
git commit -m "feat(cli): ship the agent skill inside the wheel and resolve it at runtime"
```

---

### Task 2: `visus install --skills` and `visus install-skills`

**Files:**
- Modify: `src/visus/web/cli/skills.py` (add `normalize_skills_argv`)
- Modify: `src/visus/web/cli/main.py:110-114`
- Modify: `README.md:151`, `README.md:367-376`
- Modify: `tests/test_cli.py:20-24`
- Test: `tests/test_cli_skills.py`

**Interfaces:**
- Consumes: `install_skills(cwd, *, flavor, force)`, `installed_skill_targets(cwd)` from Task 1.
- Produces:
  ```python
  # visus/web/cli/skills.py
  def normalize_skills_argv(argv: list[str]) -> list[str]: ...
  # visus/web/cli/main.py
  def _install_skills(flavor: str, *, force: bool) -> None: ...
  @app.command("install-skills")
  def install_skills_cmd(target: str = ..., force: bool = ...) -> None: ...
  ```
- **Why `normalize_skills_argv` exists:** click supports "optional value" options (`--skills` bare *or* `--skills=agents`) via `is_flag=False, flag_value=...`, but Typer's `get_click_param` never forwards `flag_value` to the click option it builds — verified against typer 0.26.7. So a bare `--skills` would die with `Option '--skills' requires an argument.` The fix is to rewrite argv once, in the console-script entry point (Task 5). `--skills=agents` and `--skills agents` work through plain Typer with no rewrite.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_skills.py`:

```python
import pytest
from typer.testing import CliRunner

from visus.web.cli.main import app
from visus.web.cli.skills import install_skills, normalize_skills_argv

runner = CliRunner()


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_skills.py -v --no-cov`
Expected: FAIL at collection with `ImportError: cannot import name 'normalize_skills_argv' from 'visus.web.cli.skills'`

- [ ] **Step 3: Add `normalize_skills_argv` to `src/visus/web/cli/skills.py`**

Append at the end of the module:

```python
#: The spelling playwright-cli users type. Kept in one place so Task 5's entry
#: point and this module cannot drift apart.
SKILLS_FLAG = "--skills"


def normalize_skills_argv(argv: list[str]) -> list[str]:
    """Rewrite a bare ``--skills`` into ``--skills=claude``.

    Typer cannot express click's "optional value" option: it builds the click
    option itself and never forwards ``flag_value``. Rewriting argv once, in the
    console-script entry point, keeps ``--skills`` declared as an ordinary value
    option while still accepting the bare spelling users bring from
    playwright-cli. ``--skills=agents`` and ``--skills agents`` pass through
    untouched.
    """
    out: list[str] = []
    for i, token in enumerate(argv):
        if token != SKILLS_FLAG:
            out.append(token)
            continue
        nxt = argv[i + 1] if i + 1 < len(argv) else None
        out.append(f"{SKILLS_FLAG}=claude" if nxt is None or nxt.startswith("-") else token)
    return out
```

- [ ] **Step 4: Wire the commands into `src/visus/web/cli/main.py`**

Replace `main.py:110-114`:

```python
@app.command()
def install(engine: str = "chrome") -> None:
    """Resolve/download the driver via Selenium Manager (by launching once)."""
    with launch(Engine.from_str(engine), headless=True):
        typer.echo(f"{engine} driver is ready (Selenium Manager).")
```

with:

```python
def _install_skills(flavor: str, *, force: bool) -> None:
    """Copy the bundled agent skill into the current repo and report the paths."""
    from visus.web.cli.skills import install_skills

    if flavor not in ("claude", "agents", "both"):
        typer.echo(f"error: unknown skill target {flavor!r} — use claude, agents, or both")
        raise typer.Exit(2)
    written = install_skills(Path.cwd(), flavor=flavor, force=force)
    for path in written:
        typer.echo(f"wrote {path}")
    typer.echo(f"installed the visus-web skill ({len(written)} files)")


@app.command()
def install(
    engine: str = typer.Option("chrome", "--engine", help="Engine to resolve a driver for."),
    skills: str = typer.Option(
        None,
        "--skills",
        help="Install the agent skill instead of a driver: --skills or --skills=agents.",
    ),
    force: bool = typer.Option(
        False, "--force", help="With --skills: wipe the target directory before copying."
    ),
) -> None:
    """Resolve/download the driver via Selenium Manager, or install the agent skill."""
    if skills is not None:
        _install_skills(skills, force=force)
        return
    with launch(Engine.from_str(engine), headless=True):
        typer.echo(f"{engine} driver is ready (Selenium Manager).")


@app.command("install-skills")
def install_skills_cmd(
    target: str = typer.Option("claude", "--target", help="claude | agents | both"),
    force: bool = typer.Option(
        False, "--force", help="Wipe the target directory before copying."
    ),
) -> None:
    """Install the bundled `visus-web` agent skill into this repository."""
    _install_skills(target, force=force)
```

`Path` is already imported at `main.py:7`; nothing else needs adding.

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_skills.py -v --no-cov`
Expected: PASS — 16 passed

- [ ] **Step 6: Extend the existing `--help` assertion**

In `tests/test_cli.py`, replace line 23:

```python
    for cmd in ("doctor", "screenshot", "pdf", "codegen", "mcp", "open", "run", "translate"):
```

with:

```python
    for cmd in (
        "doctor",
        "screenshot",
        "pdf",
        "codegen",
        "mcp",
        "open",
        "run",
        "translate",
        "install-skills",
    ):
```

Run: `uv run pytest tests/test_cli.py -v --no-cov`
Expected: PASS — all existing CLI tests still green, including `test_install_command`.

- [ ] **Step 7: Document it in the README**

After `README.md:158` (the `visus doctor --engine chrome` block) insert:

```markdown
### Installing the agent skill

`visus-web` ships an agent skill (Claude Code, Copilot, and any agent that reads
`.claude/skills/`). One command copies it into the repository you are working in:

```bash
visus install --skills            # -> ./.claude/skills/visus-web/
visus install --skills=agents     # -> ./.agents/skills/visus-web/
visus install-skills --target both --force   # both, mirroring the bundle exactly
```

Every later `visus` invocation compares the installed copy against the one inside
the package and prints a framed warning **to stderr** if they diverge, naming the
command that fixes it. Line endings are normalised, so a CRLF checkout never
triggers a false alarm.
```

Then in the Tooling table, replace `README.md:373`:

```
| `visus install --engine <e>` | Resolve/download the driver via Selenium Manager. |
```

with:

```
| `visus install --engine <e>` | Resolve/download the browser driver via Selenium Manager. |
| `visus install --skills` / `--skills=agents` | Install the bundled agent skill into `./.claude/` or `./.agents/`. |
| `visus install-skills --target <claude\|agents\|both> --force` | Same, with an explicit target. |
```

- [ ] **Step 8: Run the gates**

Run: `uv run ruff check src tests && uv run mypy && uv run pytest -q`
Expected: all three clean.

- [ ] **Step 9: Commit**

```bash
git add src/visus/web/cli/skills.py src/visus/web/cli/main.py tests/test_cli_skills.py tests/test_cli.py README.md
git commit -m "feat(cli): add visus install --skills and visus install-skills"
```

---

### Task 3: Drift detection — `cli/skill_check.py`

**Files:**
- Create: `src/visus/web/cli/skill_check.py`
- Test: `tests/test_cli_skills.py`

**Interfaces:**
- Consumes: `bundled_skill_dir()`, `installed_skill_targets(cwd)`, `SkillTarget` from Task 1.
- Produces:
  ```python
  def read_skill(file: Path) -> str | None: ...
  def frame(lines: list[str]) -> str: ...
  def check_installed_skills(cwd: Path | None = None) -> None: ...
  ```
- Port of `playwright-cli/skillCheck.js:39-42` (CRLF normalisation), `:48-54` (the box frame) and `:56-77` (byte compare + stderr warning).
- Two deviations from the JS original, both deliberate:
  1. `frame()` falls back to ASCII `+ - |` when `sys.stderr.encoding` cannot encode the box-drawing characters. On a legacy Windows console (cp1252) the Unicode write raises `UnicodeEncodeError`, which the outer `except Exception: pass` would swallow — making the warning invisible on exactly the platform `pyproject.toml:15` targets.
  2. `frame([])` returns an empty-bodied box instead of raising, because `max()` on an empty sequence raises `ValueError`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_skills.py`:

```python
import io

from visus.web.cli import skill_check


def test_read_skill_normalises_crlf(tmp_path: Path) -> None:
    f = tmp_path / "SKILL.md"
    f.write_bytes(b"# title\r\nbody\r\n")
    assert skill_check.read_skill(f) == "# title\nbody\n"


def test_read_skill_returns_none_when_missing(tmp_path: Path) -> None:
    assert skill_check.read_skill(tmp_path / "nope.md") is None


def test_frame_pads_every_line_to_the_widest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(skill_check.sys, "stderr", io.StringIO())  # utf-8 capable
    out = skill_check.frame(["ab", "cdefg"])
    assert out == (
        "\u2554\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2557\n"
        "\u2551 ab    \u2551\n"
        "\u2551 cdefg \u2551\n"
        "\u255a\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u255d\n"
    )


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
    assert skill_check.frame([]) == "\u2554\u2550\u2550\u2557\n\u255a\u2550\u2550\u255d\n"


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_skills.py -v --no-cov`
Expected: FAIL at collection with `ImportError: cannot import name 'skill_check' from 'visus.web.cli'`

- [ ] **Step 3: Write minimal implementation**

Create `src/visus/web/cli/skill_check.py`:

```python
"""Warn when a repo's installed copy of the agent skill has drifted from the bundle.

Port of ``playwright-cli/skillCheck.js``. Three properties are load-bearing:

* line endings are normalised before comparing — a CRLF checkout on Windows is
  not drift (``skillCheck.js:41``);
* the warning goes to **stderr**, so it never contaminates a piped stdout;
* the whole check is wrapped in ``except Exception: pass`` — a broken or missing
  skill must never break the CLI.
"""

from __future__ import annotations

import sys
from pathlib import Path

from visus.web.cli.skills import bundled_skill_dir, installed_skill_targets

_BOX_UNICODE = ("\u2554", "\u2550", "\u2557", "\u2551", "\u255a", "\u255d")
_BOX_ASCII = ("+", "-", "+", "|", "+", "+")


def read_skill(file: Path) -> str | None:
    """Read + normalise CRLF->LF. None when missing."""
    try:
        raw = file.read_bytes()
    except OSError:
        return None
    return raw.decode("utf-8", errors="replace").replace("\r\n", "\n")


def _box_chars() -> tuple[str, str, str, str, str, str]:
    """Box-drawing characters, downgraded to ASCII on a console that cannot encode them."""
    encoding = getattr(sys.stderr, "encoding", None) or "utf-8"
    try:
        "".join(_BOX_UNICODE).encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return _BOX_ASCII
    return _BOX_UNICODE


def frame(lines: list[str]) -> str:
    """Box-drawing frame, port of playwright-cli/skillCheck.js:48-54."""
    top_left, horizontal, top_right, vertical, bottom_left, bottom_right = _box_chars()
    width = max((len(line) for line in lines), default=0)
    top = top_left + horizontal * (width + 2) + top_right
    bottom = bottom_left + horizontal * (width + 2) + bottom_right
    body = [f"{vertical} {line.ljust(width)} {vertical}" for line in lines]
    return "\n".join([top, *body, bottom]) + "\n"


def check_installed_skills(cwd: Path | None = None) -> None:
    """Compare installed vs bundled; write a framed warning to STDERR on drift."""
    try:
        base = Path.cwd() if cwd is None else cwd
        bundled = read_skill(bundled_skill_dir() / "SKILL.md")
        if bundled is None:
            return
        for target in installed_skill_targets(base):
            installed = read_skill(target.dir / "SKILL.md")
            if installed is None or installed == bundled:
                continue
            try:
                shown: Path | str = target.dir.relative_to(base)
            except ValueError:
                shown = target.dir
            sys.stderr.write(
                frame(
                    [
                        f"The visus-web skill at '{shown}'",
                        "does not match the tool version.",
                        "",
                        f"Run `{target.command}`",
                        "to install the up-to-date skill.",
                    ]
                )
            )
    except Exception:  # noqa: BLE001 — a skill check must never break the CLI
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_skills.py -v --no-cov`
Expected: PASS — 26 passed

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests && uv run mypy && uv run pytest -q`
Expected: all three clean.

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/cli/skill_check.py tests/test_cli_skills.py
git commit -m "feat(cli): detect agent-skill drift with a CRLF-safe stderr warning"
```

---

### Task 4: The project's first `@app.callback()` — and PLAN 4's extension point

**Files:**
- Modify: `src/visus/web/cli/main.py:14-17`
- Test: `tests/test_cli_skills.py`

**Interfaces:**
- Consumes: `check_installed_skills()` from Task 3.
- Produces:
  ```python
  # src/visus/web/cli/main.py
  _SKILL_INSTALL_COMMANDS: tuple[str, ...] = ("install", "install-skills")

  @app.callback()
  def _root(ctx: typer.Context) -> None: ...
  ```

**Extension contract — read this before PLAN 4 touches `_root`:**

1. `_root` is the **only** place global flags may live. PLAN 4 adds `--json`, `--raw`, `--session` / `-S` (capital S; `-s` is `--selector` in 29 places) and `--config` as **parameters of `_root`**, e.g.
   ```python
   @app.callback()
   def _root(
       ctx: typer.Context,
       as_json: bool = typer.Option(False, "--json", help="Emit the daemon envelope verbatim."),
       raw: bool = typer.Option(False, "--raw", help="Print only the primary value."),
       session: str = typer.Option(
           None, "--session", "-S", envvar="VISUS_WEB_SESSION", help="Named session."
       ),
       config: str = typer.Option(None, "--config", help="Path to a visus config file."),
   ) -> None:
   ```
2. Being group options, they are **pre-subcommand**: `visus --json get-text 3`, never `visus get-text 3 --json`. PLAN 4 keeps the existing per-command `--json` flags working (`main.py:51`, `:265`, `:288`, `:456`, `:521`, `:771`, `:816`, `:871`) so no user script breaks.
3. PLAN 4's `output.set_mode(as_json=as_json, raw=raw)` must be the **first** statement in the body, before the skill check — a drift warning must never be emitted before the output mode is decided.
4. The skill check stays **last** in the body and stays inside the `ctx.invoked_subcommand` guard. `_SKILL_INSTALL_COMMANDS` may grow but must never shrink: warning a user while they are running the very command that fixes the warning is the bug this guard exists to prevent.
5. Click's `--help` is an eager option that exits during `parse_args`, **before** the group callback runs. So `visus --help` and bare `visus` (which `no_args_is_help=True` turns into help) do **not** execute `_root`. Nothing load-bearing for `--help` may be placed here. This is why the drift regression tests below drive `visus version` rather than `--help` (playwright-cli's `tests/integration.spec.ts:83` can use `--help` only because its check runs before argument parsing, at `playwright-cli.js:35-37`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_skills.py`:

```python
def test_cli_warns_after_the_skill_is_edited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Port of playwright-cli tests/integration.spec.ts:75-86."""
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_skills.py -k "warns_after or line_ending or never_emit" -v --no-cov`
Expected: FAIL — `test_cli_warns_after_the_skill_is_edited` asserts `"does not match the tool version" in r.stderr` and `r.stderr` is empty, because no callback exists yet.

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/cli/main.py`, replace lines 14-17:

```python
app = typer.Typer(
    help="visus.web — Playwright-style web automation on Selenium.",
    no_args_is_help=True,
)
```

with:

```python
app = typer.Typer(
    help="visus.web — Playwright-style web automation on Selenium.",
    no_args_is_help=True,
)

#: Subcommands that install the skill — they must never be nagged about it.
#: May grow, must never shrink.
_SKILL_INSTALL_COMMANDS: tuple[str, ...] = ("install", "install-skills")


@app.callback()
def _root(ctx: typer.Context) -> None:
    """Global entry point for every `visus` subcommand.

    This is the project's only group-level callback and therefore the single hook
    for global flags (`--json` / `--raw` / `--session` / `--config` attach here).
    Note that click's eager `--help` exits before a group callback runs, so this
    body does not execute for `visus --help` or bare `visus`.
    """
    from visus.web.cli.skill_check import check_installed_skills

    if ctx.invoked_subcommand not in _SKILL_INSTALL_COMMANDS:
        check_installed_skills()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_skills.py -v --no-cov`
Expected: PASS — 29 passed

- [ ] **Step 5: Verify no existing CLI test regressed**

Run: `uv run pytest tests/test_cli.py tests/test_cli_session.py -q --no-cov`
Expected: PASS — the group help text, `no_args_is_help`, and all 53 CliRunner command tests are unchanged.

- [ ] **Step 6: Run the gates**

Run: `uv run ruff check src tests && uv run mypy && uv run pytest -q`
Expected: all three clean.

- [ ] **Step 7: Commit**

```bash
git add src/visus/web/cli/main.py tests/test_cli_skills.py
git commit -m "feat(cli): add the root callback and run the skill drift check from it"
```

---

### Task 5: Guarded entry points, `python -m visus.web.cli`, and the `[cli]` extra

**Files:**
- Create: `src/visus/web/cli/_entry.py`
- Create: `src/visus/web/cli/__main__.py`
- Modify: `src/visus/web/cli/main.py:162-168`
- Modify: `pyproject.toml:45-47`, `pyproject.toml:54-56`
- Test: `tests/test_cli_skills.py`

**Interfaces:**
- Consumes: `normalize_skills_argv(argv)` from Task 2; `visus.web.cli.main.app`; `visus.web.mcp.server.main`.
- Produces:
  ```python
  def cli_main() -> None: ...      # guards the [cli] extra, then runs main.app()
  def mcp_main() -> None: ...      # guards the [mcp] extra, then runs mcp.server.main()
  ```
- `pyproject.toml` repoints `visus = "visus.web.cli._entry:cli_main"` and `visus-web-mcp = "visus.web.cli._entry:mcp_main"`.
- `[cli]` gains `rich>=13.0.0` (used at runtime in `main.py:531-533` and `console.py:66-68` but undeclared) and `click>=8.2.0` (the version from which click separates `CliRunner` stdout from stderr — Task 4's tests assert on `result.stderr`, and `--skills=agents` parsing depends on click's long-option `=` handling).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli_skills.py`:

```python
import subprocess
import sys

from visus.web.cli._entry import cli_main, mcp_main


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_skills.py -k "cli_main or mcp_main or dash_m" -v --no-cov`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'visus.web.cli._entry'`

- [ ] **Step 3: Write minimal implementation**

Create `src/visus/web/cli/_entry.py`:

```python
"""Console-script entry points that guard the optional extras.

``pyproject.toml`` declares ``visus`` and ``visus-web-mcp`` unconditionally, but
``typer`` lives in the ``[cli]`` extra and ``mcp`` in ``[mcp]``. Pointing the
scripts straight at ``visus.web.cli.main:app`` / ``visus.web.mcp.server:main``
means a plain ``pip install visus-web`` produces commands that die with a raw
``ModuleNotFoundError`` traceback — while ``README.md:154-158`` tells the user to
run ``visus doctor`` right after that install. These wrappers turn that into one
actionable line on stderr and exit code 2.
"""

from __future__ import annotations

import sys

_MISSING_CLI = (
    'The `visus` CLI needs the [cli] extra:  pip install "visus-web[cli]"\n'
)
_MISSING_MCP = (
    'The visus-web MCP server needs the [mcp] extra:  pip install "visus-web[mcp]"\n'
)


def cli_main() -> None:
    """Entry point for the ``visus`` console script."""
    try:
        import typer  # noqa: F401
    except ModuleNotFoundError as exc:
        sys.stderr.write(_MISSING_CLI)
        raise SystemExit(2) from exc

    from visus.web.cli.main import app
    from visus.web.cli.skills import normalize_skills_argv

    app(args=normalize_skills_argv(sys.argv[1:]), prog_name="visus")


def mcp_main() -> None:
    """Entry point for the ``visus-web-mcp`` console script (and ``visus mcp``)."""
    try:
        import mcp  # noqa: F401
    except ModuleNotFoundError as exc:
        sys.stderr.write(_MISSING_MCP)
        raise SystemExit(2) from exc

    from visus.web.mcp import server

    server.main()
```

Create `src/visus/web/cli/__main__.py`:

```python
"""``python -m visus.web.cli`` — same entry point as the ``visus`` console script."""

from visus.web.cli._entry import cli_main

if __name__ == "__main__":
    cli_main()
```

- [ ] **Step 4: Route `visus mcp` through the same guard**

In `src/visus/web/cli/main.py`, replace lines 162-168:

```python
@app.command()
def mcp() -> None:
    """Start the visus.web MCP server (stdio)."""
    from visus.web.mcp.server import main as mcp_main

    mcp_main()
```

with:

```python
@app.command()
def mcp() -> None:
    """Start the visus.web MCP server (stdio)."""
    from visus.web.cli._entry import mcp_main

    mcp_main()
```

- [ ] **Step 5: Repoint the scripts and complete the `[cli]` extra**

In `pyproject.toml`, replace lines 45-47:

```toml
cli = [
    "typer>=0.12.0",
]
```

with:

```toml
cli = [
    "typer>=0.12.0",
    # Imported at runtime by main.py:531-533 and console.py:66-68. typer already
    # pulls it in, but the dependency is ours and must be declared.
    "rich>=13.0.0",
    # 8.2 is the first click that keeps CliRunner's stderr separate from stdout
    # (the drift-warning tests assert on result.stderr) and the version whose
    # long-option parsing `--skills=agents` is pinned against.
    "click>=8.2.0",
]
```

and replace lines 54-56:

```toml
[project.scripts]
visus = "visus.web.cli.main:app"
visus-web-mcp = "visus.web.mcp.server:main"
```

with:

```toml
[project.scripts]
visus = "visus.web.cli._entry:cli_main"
visus-web-mcp = "visus.web.cli._entry:mcp_main"
```

- [ ] **Step 6: Reinstall so the new console scripts exist, then run the tests**

```bash
uv pip install -e ".[dev,vision,mcp,cli]"
```

Run: `uv run pytest tests/test_cli_skills.py -v --no-cov`
Expected: PASS — 34 passed

- [ ] **Step 7: Verify the console script itself**

Run: `uv run visus version`
Expected: prints `0.2.0`

Run: `uv run python -m visus.web.cli --help`
Expected: the group help listing `install-skills` among the commands.

- [ ] **Step 8: Run the gates**

Run: `uv run ruff check src tests && uv run mypy && uv run pytest -q`
Expected: all three clean. *(`__main__.py`'s `cli_main()` line is not measured — it only runs in the subprocess test. Two unmeasured lines out of ~11 300 does not move the 90 % gate.)*

- [ ] **Step 9: Commit**

```bash
git add src/visus/web/cli/_entry.py src/visus/web/cli/__main__.py src/visus/web/cli/main.py pyproject.toml tests/test_cli_skills.py
git commit -m "fix(cli): guard the [cli]/[mcp] extras and support python -m visus.web.cli"
```

---

### Task 6: Rewrite `SKILL.md` around the CLI

**Files:**
- Modify: `src/visus/web/skills/visus-web/SKILL.md` (full rewrite)
- Test: `tests/test_skill_docs.py`

**Interfaces:**
- Consumes: `bundled_skill_dir()` (indirectly — the test reads the source tree directly, see below).
- Produces: the shipped skill's frontmatter contract — `name: visus-web`, `allowed-tools`, and a `version` that must equal `visus.web.__version__`.
- The test reads `src/visus/web/skills/visus-web/` **from the repo source tree**, not through `bundled_skill_dir()`. This is a source-tree drift gate: it must fail on an edit even if the developer's checkout is not installed editable.

**What is wrong today** (`skills/using-visus-web/SKILL.md`, now moved): it documents 8 of 54 CLI commands (`:142-151`), never mentions `session`, `list-fields`, `click` or `fill`, has no `allowed-tools`, no version, no cross-references, no decision guide, and claims "~38 tools" (`:155`) where `tests/test_mcp_server.py:27-84` pins 45.

- [ ] **Step 1: Write the failing test**

Create `tests/test_skill_docs.py`:

```python
"""Drift gates for the shipped agent skill.

These read the skill out of the repo source tree (not through
``bundled_skill_dir()``) so they fail on an edit regardless of how the package
is installed.
"""

from __future__ import annotations

import re
from pathlib import Path

SKILL_DIR = (
    Path(__file__).resolve().parents[1] / "src" / "visus" / "web" / "skills" / "visus-web"
)
SKILL_MD = SKILL_DIR / "SKILL.md"


def _frontmatter() -> dict[str, str]:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must open with YAML frontmatter"
    block = text.split("---\n", 2)[1]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip().strip('"')
    return out


def test_frontmatter_declares_name_and_allowed_tools() -> None:
    fm = _frontmatter()
    assert fm["name"] == "visus-web"
    assert "Bash(visus:*)" in fm["allowed-tools"]
    assert "Bash(visus-web-mcp:*)" in fm["allowed-tools"]
    assert len(fm["description"]) > 80, "the description is what an agent routes on"


def test_frontmatter_version_tracks_the_package_version() -> None:
    """The skill carries provenance; a release bump must bump the skill too."""
    from visus.web import __version__

    assert _frontmatter()["version"] == __version__


def test_skill_teaches_the_session_loop() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    for fragment in (
        "visus session start",
        "visus list-fields",
        "visus fill 1 student",
        "visus click --role button --name Submit",
        "visus expect-text",
        "visus session stop",
    ):
        assert fragment in text, f"the session loop is missing {fragment!r}"


def test_skill_claims_the_real_mcp_tool_count() -> None:
    """`~38 tools` was wrong; the count must be derived, never guessed."""
    import importlib

    server = importlib.import_module("visus.web.mcp.server")
    real = len(server.mcp._tool_manager.list_tools())
    claimed = re.findall(r"\*\*(\d+) tools\*\*", SKILL_MD.read_text(encoding="utf-8"))
    assert claimed, "SKILL.md must state the MCP tool count as `**N tools**`"
    assert {int(c) for c in claimed} == {real}, f"claimed {claimed}, registered {real}"


def test_skill_covers_every_subsystem() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    for fragment in (
        "rpa(",
        "async_api",
        "tracing",
        "pytest",
        "NetworkCapture",
        "edge_ie",
        "remote_url",
        "python -m visus.web.cli",
    ):
        assert fragment in text, f"the skill never mentions {fragment!r}"


def test_skill_has_a_decision_guide_and_a_skills_less_prompt() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "## Which interface" in text
    assert "## Skills-less operation" in text
    assert "visus --help" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_skill_docs.py -v --no-cov`
Expected: FAIL — `test_frontmatter_declares_name_and_allowed_tools` fails with `KeyError: 'allowed-tools'`, and every other test fails on missing content.

- [ ] **Step 3: Write the new `src/visus/web/skills/visus-web/SKILL.md` (replace the whole file)**

````markdown
---
name: visus-web
description: Drive a real browser from the shell with the `visus` CLI — session daemon, list-fields/act-by-index, role/name targeting, expect-text, codegen, vision. Use when automating or testing a web page.
allowed-tools: Bash(visus:*) Bash(visus-web-mcp:*) Bash(pip:*) Bash(uvx:*)
version: "0.2.0"
---

# visus-web

Drive a **real browser** from the shell. `visus` keeps a browser alive in a
background daemon, so every command lands on the same live page — no re-launch,
no lost login.

## Install

```bash
pip install "visus-web[cli]"   # the `visus` CLI
visus install --skills         # (re)install this skill into ./.claude/skills/
visus doctor                   # prove a browser + driver really launch
```

No install rights? `uvx --from "visus-web[cli]" visus doctor`.
Console script not on PATH? `python -m visus.web.cli doctor`.

Extras: `[cli]` the CLI · `[mcp]` the MCP server · `[vision]` OCR + image matching.

## The session loop — start here

```bash
visus session start https://practicetestautomation.com/practice-test-login/
visus list-fields                        # numbered table + numbered overlay on the page
visus fill 1 student                     # act by index
visus fill 2 Password123
visus click --role button --name Submit  # or target by role/name/selector/text
visus expect-text --role heading "Logged In Successfully"   # PASSED / FAILED
visus session stop                       # closes the browser
```

`visus session status` shows pid, port, engine, url, title and `fields_cached`.
Full reference: **[references/cli-session.md](references/cli-session.md)**.

## Rules that will bite you

- **Field indexes belong to the page you listed.** After `goto` / `back` /
  `forward` / `reload` / a form submit, run `list-fields` again before acting by
  index.
- **`--name` alone is not a target.** It only qualifies `--role`. A command with
  no index and no `--selector` / `--role` / `--text` exits 1 with
  `error: provide an index, or --selector / --role / --text`.
- **Timeouts are milliseconds.** `--timeout 5000`, not `5`.
- **Never sleep.** Every action auto-waits; `visus wait --state visible` and
  `visus expect-text` are the synchronisation primitives.
- **`visus clear` removes the highlight overlay. `visus clear-input` clears an
  input's value.** They are different commands.
- **`visus screenshot <URL>` launches a throwaway browser.** The session's
  screenshot command is `visus session-screenshot`.

Targeting in depth: **[references/cli-targeting.md](references/cli-targeting.md)**.
When something goes wrong: **[references/troubleshooting.md](references/troubleshooting.md)**.

## Which interface

| You are | Use | Why |
|---|---|---|
| A coding agent with shell access | **the `visus` CLI** | Cheapest tokens: no tool schemas, one line per action, numbered indexes instead of an accessibility dump. This is the default. |
| An MCP client without shell access | **`visus-web-mcp`** | **45 tools** over the same browser surface. Its browser is a *separate* process from the CLI daemon — the two never share a session. |
| Writing a durable script or a test | **the Python library** | `from visus.web import launch, rpa, expect`. Auto-waiting actions, auto-retrying assertions, HTML run reports. |

The CLI daemon and the MCP server hold **independent** browsers with opposite
defaults (CLI: headed, auto-follows new tabs; MCP: headless, manual tab
follow). Pick one per task.

## Commands

53 commands over a 41-op daemon, plus `install-skills`. The complete reference —
targeting rules, every flag, grouped by task — is
**[references/cli-commands.md](references/cli-commands.md)**.

The ones you will use most:

```bash
visus goto <URL> | back | forward | reload
visus list-fields [--kind input,button] [--all] [--no-highlight] [--json]
visus snapshot [--json]                  # role/name table of interactive elements
visus click|dblclick|hover|focus|check|uncheck [idx] [target]
visus fill <idx> <text>                  # or: -s "#user" --value text
visus select <idx> <value> | visus press <idx> Enter | visus clear-input <idx>
visus get-text|get-attribute <attr>|count [idx] [target]
visus title | visus url | visus tabs | visus tab <idx>
visus wait [idx] --state visible|hidden|attached|detached --timeout <ms>
visus expect-text [idx] <text> --timeout <ms>
visus session-screenshot -o shot.png [--full-page] [idx]
visus eval "() => document.title" [--json]
visus cookies [--json] | visus add-cookies '<json>' | visus clear-cookies
```

`--json` is available on `translate`, `session status`, `list-fields`, `tabs`,
`snapshot`, `cookies`, `eval` and `find-image`. Piping, exit codes and shell
capture: **[references/cli-json-and-piping.md](references/cli-json-and-piping.md)**.

On Windows, the shell mangles `<`, `>` and `"` — `visus translate` exists
precisely for that. Read **[references/windows-shell.md](references/windows-shell.md)**
before quoting a selector in PowerShell.

`visus console` opens a REPL attached to the live session with a shorter
vocabulary: **[references/cli-repl.md](references/cli-repl.md)**.

## MCP server

`visus-web-mcp` (or `visus mcp`) exposes **45 tools** — navigation, ARIA
snapshot, `browser_list_fields`, every action, tabs, dialogs, cookies,
network/console capture, screenshot, evaluate, and the vision tools. Configure
with `VISUS_WEB_ENGINE` (chrome | edge | firefox | edge_ie) and
`VISUS_WEB_HEADLESS` (0/1). Tool list and target parameters:
**[references/mcp-tools.md](references/mcp-tools.md)**.

The server also serves this skill: read the resource `visus://skill/SKILL.md`
and `visus://skill/references/<file>.md`, or call the `visus_web_quickstart`
prompt.

## Beyond the CLI

- **Vision** (`[vision]`): `visus read-text`, `visus solve-captcha`,
  `visus find-image tmpl.png -c 0.8 --json` — OCR and OpenCV template matching.
  **[references/vision.md](references/vision.md)**
- **Tracing & HTML reports**: `rpa("login")` records the run and writes a
  single-file `report.html` **even when a step raises**;
  `tracing.record()` does the same around any block.
  **[references/tracing-reports.md](references/tracing-reports.md)**
- **pytest plugin**: loads automatically, gives you `visus_page` /
  `visus_context` / `visus_browser` with screenshot-on-failure.
  **[references/pytest-plugin.md](references/pytest-plugin.md)**
- **Python API**: `launch()` / `rpa()` / `expect()`, `Field`, `is_active`,
  `save_screenshot`, the 100 %-mirror `visus.web.async_api`, `NetworkCapture`
  for reverse-engineering an API, `launch(remote_url=...)` for Selenium Grid,
  and the `edge_ie` engine for IE-mode legacy apps.
  **[references/library-api.md](references/library-api.md)**

## Errors

`visus.web.errors`: `VisusWebError` (base), `VisusTimeoutError`,
`NavigationError`, `TargetClosedError`, `StrictModeViolation`,
`ElementNotFoundError`, `UnsupportedEngineError`. A failed `expect()` raises
`AssertionError`. From the shell, a failed command exits **1** and prints
`error: <type>: <message>`; a usage error exits **2**.

## Skills-less operation

If this skill is not installed, point the agent at the CLI and let it read its
own help:

```
Automate <task> on <url> using the `visus` CLI.
Run `visus --help` and `visus <command> --help` for the available commands.
Start with `visus session start <url>`, then `visus list-fields`.
```
````

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_skill_docs.py -v --no-cov`
Expected: PASS — 6 passed

- [ ] **Step 5: Confirm the drift check now fires against a stale install**

Run: `uv run pytest tests/test_cli_skills.py -v --no-cov`
Expected: PASS — the install/drift tests reinstall from the bundle each time, so the rewrite does not disturb them.

- [ ] **Step 6: Run the gates**

Run: `uv run ruff check src tests && uv run mypy && uv run pytest -q`
Expected: all three clean.

- [ ] **Step 7: Commit**

```bash
git add src/visus/web/skills/visus-web/SKILL.md tests/test_skill_docs.py
git commit -m "docs(skill): rewrite the agent skill around the CLI session loop"
```

---

### Task 7: `references/cli-commands.md` and the command-coverage drift gate

**Files:**
- Create: `src/visus/web/skills/visus-web/references/cli-commands.md`
- Modify: `tests/test_skill_docs.py`

**Interfaces:**
- Consumes: `visus.web.cli.main.app` (`registered_commands`, `registered_groups`), `typer.main.get_command_name`.
- Produces: the doc-drift gate every later plan must satisfy — **adding a CLI command without a row in `cli-commands.md` fails the suite**.
- Verified against typer 0.26.7: `app.registered_commands` is a list of objects with `.name` (`None` when auto-derived) and `.callback`; `app.registered_groups` is a list with `.name` and `.typer_instance`; `typer.main.get_command_name("list_fields") == "list-fields"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skill_docs.py`:

```python
COMMANDS_MD = SKILL_DIR / "references" / "cli-commands.md"


def _cli_command_names() -> list[str]:
    """Every invocable command name, e.g. 'list-fields' and 'session start'."""
    from typer.main import get_command_name

    from visus.web.cli.main import app

    names: list[str] = []
    for info in app.registered_commands:
        names.append(info.name or get_command_name(info.callback.__name__))
    for group in app.registered_groups:
        prefix = group.name or ""
        for info in group.typer_instance.registered_commands:
            sub = info.name or get_command_name(info.callback.__name__)
            names.append(f"{prefix} {sub}".strip())
    return names


def test_every_cli_command_is_documented() -> None:
    """Adding a command without a doc row must fail here, not in the field."""
    text = COMMANDS_MD.read_text(encoding="utf-8")
    missing = [
        name
        for name in _cli_command_names()
        # `(?![\w-])` stops `visus clear-input` from satisfying `visus clear`.
        if not re.search(rf"`visus {re.escape(name)}(?![\w-])", text)
    ]
    assert not missing, (
        f"{len(missing)} command(s) missing from {COMMANDS_MD.name}: {sorted(missing)}"
    )


def test_command_reference_is_linked_from_the_skill() -> None:
    assert "references/cli-commands.md" in SKILL_MD.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_skill_docs.py -k documented -v --no-cov`
Expected: FAIL with `FileNotFoundError: ... references/cli-commands.md`

- [ ] **Step 3: Create the reference by porting the README tables**

```bash
mkdir -p src/visus/web/skills/visus-web/references
```

Create `src/visus/web/skills/visus-web/references/cli-commands.md` starting with this header, verbatim:

```markdown
# `visus` command reference

Every command below drives the **live session daemon** unless it is marked
*one-off browser*. Start the daemon first: `visus session start [URL]`.

Targeting: most commands accept a positional **field index** (from the last
`list-fields`) **or** `--selector` / `-s`, `--role`, `--name`, `--text`.
`--name` on its own is not a target — see
[cli-targeting.md](cli-targeting.md). Nearly every read command accepts `--json`.

Timeouts are milliseconds. Exit code 1 = the command failed; 2 = usage error.
```

Then append `README.md` **lines 286 through 376 inclusive**, verbatim — that is
the nine `###` sections from `### Session & lifecycle` down to and including the
`| \`visus version\` |` row. Extract them mechanically so nothing is retyped:

```bash
python - <<'PY'
from pathlib import Path
readme = Path("README.md").read_text(encoding="utf-8").splitlines()
block = "\n".join(readme[285:376])  # 1-based lines 286..376
out = Path("src/visus/web/skills/visus-web/references/cli-commands.md")
out.write_text(out.read_text(encoding="utf-8") + "\n" + block + "\n", encoding="utf-8")
print(block.splitlines()[0])
print(block.splitlines()[-1])
PY
```

Expected output:
```
### Session & lifecycle
| `visus version` | Print the `visus.web` version. |
```

Then apply exactly two edits to the file you just wrote:

1. In the **Tooling** table, replace the single install row
   `| \`visus install --engine <e>\` | Resolve/download the driver via Selenium Manager. |`
   with the three rows added to the README in Task 2:
   ```markdown
   | `visus install --engine <e>` | Resolve/download the browser driver via Selenium Manager. |
   | `visus install --skills` / `--skills=agents` | Install the bundled agent skill into `./.claude/` or `./.agents/`. |
   | `visus install-skills --target <claude\|agents\|both> --force` | Same, with an explicit target. |
   ```
2. Append this closing section:
   ```markdown

   ### Not in the CLI (yet)

   These exist in the Python library and/or the MCP server but have no shell
   command: network request log, browser console log, storage state save/load,
   standalone keyboard/mouse, network mocking, tracing start/stop, named
   sessions, `attach`/`detach`. Reach them with `visus eval`, the MCP server, or
   the library — see [library-api.md](library-api.md) and [mcp-tools.md](mcp-tools.md).
   ```

- [ ] **Step 4: Add the link to `SKILL.md`**

`SKILL.md` already carries `**[references/cli-commands.md](references/cli-commands.md)**` in its `## Commands` section (Task 6). Confirm with:

Run: `grep -c "references/cli-commands.md" src/visus/web/skills/visus-web/SKILL.md`
Expected: `1`

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_skill_docs.py -v --no-cov`
Expected: PASS — 8 passed. If `test_every_cli_command_is_documented` reports missing names, add the missing rows to `cli-commands.md`; the assertion message lists them exactly.

- [ ] **Step 6: Run the gates**

Run: `uv run ruff check src tests && uv run mypy && uv run pytest -q`
Expected: all three clean.

- [ ] **Step 7: Commit**

```bash
git add src/visus/web/skills/visus-web/references/cli-commands.md tests/test_skill_docs.py
git commit -m "docs(skill): add the full CLI command reference and a coverage gate"
```

---

### Task 8: The two worked reference exemplars

**Files:**
- Create: `src/visus/web/skills/visus-web/references/cli-targeting.md`
- Create: `src/visus/web/skills/visus-web/references/troubleshooting.md`
- Modify: `tests/test_skill_docs.py`

**Interfaces:**
- Consumes: nothing at runtime; the content is pinned against `main.py:222-235`, `session_server.py:185-221`, `session_client.py:108,122,145,191` and `session_server.py:638`.
- Produces: reference files that Task 9's link-integrity test counts.
- These two are written in full because their content cannot be re-derived from the README: the README never states that `--name` alone is rejected, and it contains none of the daemon's literal error strings.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skill_docs.py`:

```python
def test_targeting_reference_states_the_name_only_rule() -> None:
    """`--name` alone is rejected by main.py:232 — the README never says so."""
    text = (SKILL_DIR / "references" / "cli-targeting.md").read_text(encoding="utf-8")
    assert "`--name` alone is not a target" in text
    assert "error: provide an index, or --selector / --role / --text" in text


def test_troubleshooting_reference_carries_the_literal_daemon_errors() -> None:
    """Symptom lookup only works if the strings match the daemon byte for byte."""
    text = (SKILL_DIR / "references" / "troubleshooting.md").read_text(encoding="utf-8")
    for literal in (
        "no live session — run `visus session start` first",
        "a session is already running (pid",
        "daemon did not come up within",
        "daemon closed the connection without responding",
        "unauthorized: bad token",
        "out of range (have",
    ):
        assert literal in text, f"missing the literal error {literal!r}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_skill_docs.py -k "targeting or troubleshooting" -v --no-cov`
Expected: FAIL with `FileNotFoundError: ... references/cli-targeting.md`

- [ ] **Step 3: Create `src/visus/web/skills/visus-web/references/cli-targeting.md`**

````markdown
# Targeting an element from the shell

Every action, read, wait and assertion command takes the **same** target
grammar. There are exactly two ways to name an element.

## 1. By index (preferred)

```bash
visus list-fields          # prints a numbered table AND draws numbered boxes on the page
visus fill 2 ada@example.com
visus click 7
```

`list-fields` emits six columns: `#`, `KIND`, `NAME`, `VISUS (copy-paste)`,
`CSS`, `XPATH`. The `VISUS` column is a ready Python expression, generated
**frame-aware** — if the element sits inside an iframe it is already wrapped in
`frame_locator(...)`, so pasting it into a script works.

Index targeting is the only form that transparently reaches **through iframes
and open shadow roots**: the daemon stores the frame chain with the field and
re-walks it on every action, then re-resolves with `deep=` for shadow DOM. There
is no extra syntax — `visus click 3` reaches an element three iframes deep.

**Indexes belong to the page you listed them on.** They are a cache, refreshed
only by `list-fields`. After `goto`, `back`, `forward`, `reload`, a form submit,
or a click that navigates, run `list-fields` again. Acting on a stale index is
the single most common way to click the wrong element.

Out-of-range indexes are rejected loudly:

```
error: IndexError: field index 9 out of range (have 4; run list_fields first)
```

Filter a long page instead of paging through it:

```bash
visus list-fields --kind input,button        # kinds: input textarea editable button
visus list-fields --kind link,checkbox       #        link checkbox radio select dropdown
visus list-fields --all                      # include hidden/disabled fields
visus list-fields --no-highlight             # skip the overlay (keeps screenshots clean)
visus clear                                  # remove the overlay afterwards
```

The overlay injects marker elements into the page. Take screenshots, run OCR or
run `find-image` **before** listing, or list with `--no-highlight`.

## 2. By selector / role / text

```bash
visus click --role button --name "Sign in"
visus click --text "Add to cart"
visus click -s "#submit"
visus click -s "//button[@type='submit']"          # xpath is auto-detected
visus fill  -s "#username" --value student         # note: --value, not a positional
```

| Flag | Meaning |
|---|---|
| `--selector` / `-s` | CSS, XPath, or a pasted DevTools element (`<input …>`) |
| `--role` | ARIA role: `button`, `link`, `heading`, `textbox`, `checkbox`, … |
| `--name` | Accessible name — **a qualifier for `--role`, not a target on its own** |
| `--text` | Visible text (substring, case-insensitive) |

**`--name` alone is not a target.** The guard only accepts an index, `--selector`,
`--role` or `--text`; a command carrying just `--name` exits 1 with:

```
error: provide an index, or --selector / --role / --text
```

So `visus click --name Submit` fails, while `visus click --role button --name Submit`
works. This is the most common CLI mistake.

## Precedence and the `--text` collision

- A positional index **wins** over every flag. `visus click 3 --role button`
  clicks field 3.
- Order of resolution among the flags: `--role` (with `--name`), then `--text`,
  then `--selector`.
- On `fill`, `select`, `press` and `expect-text` the **positional** second
  argument is the *value*, and `--text` is the *target*. When you target by
  role/selector/text you must pass the value through its own flag:

```bash
visus fill 2 hunter2                          # index + positional value
visus fill -s "#pwd" --value hunter2          # selector + --value
visus select 5 US                             # index + positional value
visus select --role combobox --name Country --value US
visus press 2 Enter                           # index + positional key
visus press -s "#pwd" --key Enter
visus expect-text 0 "Welcome"                 # index + positional expectation
visus expect-text --role heading --expected "Welcome"
```

Passing no value at all exits 1, e.g.:

```
error: no text to fill — use `visus fill <index> <text>` or `--value`
```

## Strict matching and iframes

The daemon supports `exact` matching and an explicit `frame` selector, but **no
CLI flag sets them today** — from the shell, reach an element inside an iframe
by its `list-fields` index, or use the MCP server's `exact` / `frame`
parameters. `--role` name matching and `--text` are substring, case-insensitive.

If a selector matches more than one element, single-element operations raise
`StrictModeViolation`. Narrow with `--role` + `--name`, or list the fields and
use an index.

## Getting a selector out of DevTools

Right-click the element → *Copy* → *Copy element*, then:

```bash
visus translate                # reads the clipboard, prints tag/id/name/css/xpath
visus translate --file el.html
visus translate '<input name="email" class="…">' --json
```

`visus translate` is the only command that needs no running browser. It also
prints the ordered candidate list the smart locator will try, so you can see
which selector will actually win.
````

- [ ] **Step 4: Create `src/visus/web/skills/visus-web/references/troubleshooting.md`**

````markdown
# Troubleshooting

Errors are keyed to the literal strings the CLI and daemon print. A failed
command exits **1**; a usage error exits **2**.

## Session lifecycle

| Message | Cause | Fix |
|---|---|---|
| `` `error: no live session — run `visus session start` first` `` | No `.visus/session.json` was found walking up from the current directory, or the recorded pid/port failed the liveness probe (the stale file is deleted for you). | `visus session start [URL]`. If you started the session in a *sibling* directory, `cd` into it or into a shared parent — discovery only walks **upward**. |
| `error: a session is already running (pid 1234, port 51234)` | A live daemon was found at or above the current directory. | Reuse it (just run commands), or `visus session stop` first. There are no named sessions — one daemon per directory tree. |
| `error: daemon did not come up within 20s (see .visus/daemon.log)` | The daemon process started but never bound its socket: the browser failed to launch, the driver is missing, or a stale `.visus/session.json.lock` blocked it. | Read the tail of `.visus/daemon.log` — the real exception is there. Then `visus doctor` to prove the browser launches. If the log says `daemon aborting: another daemon already holds …`, delete `.visus/session.json.lock` by hand and retry. |
| `error: daemon closed the connection without responding` | The daemon died mid-request (browser crash, machine sleep, OOM). | `visus session stop` (it cleans up), then `visus session start` again. |
| `error: unauthorized: bad token` | The `.visus/session.json` you are reading belongs to a different daemon than the one listening on that port — usually a half-cleaned crash. | Delete `.visus/` and start a fresh session. |
| `visus session stop` prints `no session running` but a browser window is still open | The daemon died without cleaning up, or the window belongs to a `visus open` / `visus codegen` one-off browser. | Close the window manually; those two commands run their own browser and are not part of the session. |
| `closed the last tab — session stopped` but later commands still work | Closing the last tab tears down the browser without stopping the daemon; the next command relaunches a **fresh** browser at the session's original URL. | Treat it as a restart: you are logged out. Prefer `visus session stop`. |

## Targeting

| Message | Cause | Fix |
|---|---|---|
| `error: provide an index, or --selector / --role / --text` | No target given, or only `--name`. `--name` qualifies `--role`; it is not a target. | `visus click --role button --name Submit`, or use an index. |
| `error: IndexError: field index 9 out of range (have 4; run list_fields first)` | The index cache is empty or shorter than you think. | `visus list-fields` first, every time the page changes. |
| A command reports success but the wrong element reacted | The index cache was captured on a **previous** page. Nothing re-validates it. | Re-run `visus list-fields` after every navigation and after every click that submits a form. |
| `error: ValueError: provide one of: index, role, text, selector` | The daemon received an empty target dict — usually a hand-built op, not the CLI. | Send one of `index`, `role`, `text`, `selector`. |
| `error: StrictModeViolation: …` | The selector matched more than one element. | Add `--name` to `--role`, use a more specific selector, or switch to an index. |
| `error: ElementNotFoundError: …` / `error: VisusTimeoutError: …` | The element never became actionable within the timeout. | `visus wait --state visible -s "…" --timeout 15000` first; check you are on the right tab with `visus tabs`. |

## Command confusion

| Symptom | Cause | Fix |
|---|---|---|
| `visus screenshot` opened a new browser instead of capturing the session | `visus screenshot <URL>` is a one-off browser command. | Use `visus session-screenshot -o shot.png [--full-page]`. |
| `visus clear` did not clear the input | `clear` removes the numbered overlay. | Use `visus clear-input <idx>`. |
| `visus press Enter` fails with a target error | `press` requires a target; `Enter` is being read as the index. | `visus press <idx> Enter`, or `visus press -s "#pwd" --key Enter`. |
| `visus console` launched a browser | With no session running, the REPL starts a **headed** daemon. | `visus session start --headless` first if you need headless. |
| `error: unknown op 'xyz'` | The daemon does not implement that op — usually a CLI/daemon version mismatch. | Reinstall: `pip install -U "visus-web[cli]"`, then `visus session stop && visus session start`. |

## Environment

| Symptom | Cause | Fix |
|---|---|---|
| `visus: command not found` | The console script is not on PATH. | `python -m visus.web.cli <command>`, or `uvx --from "visus-web[cli]" visus <command>`. |
| `` `The `visus` CLI needs the [cli] extra` `` | Installed without the extra. | `pip install "visus-web[cli]"` |
| `The visus-web MCP server needs the [mcp] extra` | Same, for MCP. | `pip install "visus-web[mcp]"` |
| `ModuleNotFoundError: No module named 'cv2'` / `rapidocr_onnxruntime` from `read-text` / `solve-captcha` / `find-image` | Vision runs **inside the daemon**; the extra is missing there. | `pip install "visus-web[vision]"`, then restart the session. |
| A framed box says `does not match the tool version` | Your repo's installed copy of the skill differs from the one in the package. | Run the command the box names: `visus install --skills` (or `--skills=agents`). Line endings alone never trigger it. |
| `visus doctor` prints `FAILED: …` | The browser or driver cannot launch. | Install the browser; Selenium Manager resolves the driver. `visus install --engine edge` forces a one-time resolve. |

## Quoting

Selector quoting is the top source of "it works in bash, not in PowerShell"
failures. See [windows-shell.md](windows-shell.md).
````

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_skill_docs.py -v --no-cov`
Expected: PASS — 10 passed

- [ ] **Step 6: Run the gates**

Run: `uv run ruff check src tests && uv run mypy && uv run pytest -q`
Expected: all three clean.

- [ ] **Step 7: Commit**

```bash
git add src/visus/web/skills/visus-web/references/cli-targeting.md src/visus/web/skills/visus-web/references/troubleshooting.md tests/test_skill_docs.py
git commit -m "docs(skill): add targeting and troubleshooting references"
```

---

### Task 9: The remaining nine references and the link-integrity gate

**Files:**
- Create: nine files under `src/visus/web/skills/visus-web/references/`
- Modify: `src/visus/web/skills/visus-web/SKILL.md` (append `## Specific tasks`)
- Modify: `tests/test_skill_docs.py`

**Interfaces:**
- Consumes: nothing at runtime.
- Produces: `references/*.md` == exactly 12 files, each linked from `SKILL.md`.
- Each file below states **what it covers** and **the exact source to port from**, plus its opening content verbatim. Size by complexity, not uniformly — `cli-session.md` and `library-api.md` are the long ones; `vision.md` and `pytest-plugin.md` are short.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skill_docs.py`:

```python
_REFERENCES = (
    "cli-session.md",
    "cli-targeting.md",
    "cli-commands.md",
    "cli-json-and-piping.md",
    "cli-repl.md",
    "windows-shell.md",
    "mcp-tools.md",
    "vision.md",
    "tracing-reports.md",
    "pytest-plugin.md",
    "troubleshooting.md",
    "library-api.md",
)


def test_every_reference_exists_and_is_linked() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    linked = set(re.findall(r"\]\(references/([A-Za-z0-9._-]+)\)", text))
    on_disk = {p.name for p in (SKILL_DIR / "references").glob("*.md")}
    assert on_disk == set(_REFERENCES), f"unexpected reference files: {on_disk}"
    assert linked == set(_REFERENCES), f"unlinked: {sorted(set(_REFERENCES) - linked)}"


def test_no_reference_link_is_dead() -> None:
    for path in (SKILL_DIR / "references").glob("*.md"):
        for target in re.findall(r"\]\(([A-Za-z0-9._-]+\.md)\)", path.read_text(encoding="utf-8")):
            assert (SKILL_DIR / "references" / target).is_file(), f"{path.name} -> {target}"


def test_skill_has_a_specific_tasks_index() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert "## Specific tasks" in text
    tail = text.split("## Specific tasks", 1)[1]
    assert tail.count("](references/") >= 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_skill_docs.py -k "reference or specific_tasks" -v --no-cov`
Expected: FAIL — `AssertionError: unexpected reference files: {'cli-targeting.md', 'cli-commands.md', 'troubleshooting.md'}`

- [ ] **Step 3: Create `references/cli-session.md`** (~110 lines)

Covers: the daemon lifecycle end to end; the `.visus/` directory; upward discovery; the `--engine` / `--headless` options; what `session status` reports; the index cache and its invalidation rule; tabs and popups; the one-off commands (`open`, `screenshot <URL>`, `pdf <URL>`, `codegen`, `run`) that launch their **own** browser and never see the session.
Port from: `README.md:286-293` (session table), `session_client.py:58-66` (upward discovery), `:129-194` (spawn + 20 s wait), `:197-214` (stop), `session_server.py:601-604` (`.visus/`), `main.py:263-282` (`session status` keys), `main.py:147-153`/`:117-130`/`:133-144`/`:170-194`/`:156-159` (the five one-off commands).

Opening content, verbatim:

```markdown
# The session daemon

`visus` is a thin client over a background browser process. The daemon owns the
browser; every command is a one-line JSON request to it.

```bash
visus session start https://example.com   # headed by default
visus session start --headless --engine edge
visus session status                      # pid, port, engine, url, title, fields_cached
visus session stop                        # closes the browser and deletes .visus/
```

## Where the session lives

`session start` writes `.visus/session.json` (pid, port, token, engine, url) in
the directory you ran it from, plus `.visus/session.json.lock` and
`.visus/daemon.log`. Every other command searches **upward** from the current
directory, git-style, for `.visus/session.json`. So a session started at a repo
root serves every subdirectory — and a sibling directory outside that chain gets
its own daemon.

A session is considered live only when its pid is alive **and** its port
accepts a connection. A file that fails either check is deleted automatically.
```

- [ ] **Step 4: Create `references/cli-json-and-piping.md`** (~70 lines)

Covers: which eight commands take `--json` (`translate`, `session status`, `list-fields`, `tabs`, `snapshot`, `cookies`, `eval`, `find-image`) and what shape each emits; exit codes (0/1/2) as the reliable failure signal; `jq` recipes; capturing a value into a shell variable; snapshot-diff around an action; why you should check the exit code rather than parse the message.
Port from: `main.py:51`, `:265`, `:288`, `:456`, `:521`, `:771`, `:816`, `:871` (the flags) and `main.py:205-213` (the error funnel).

Opening content, verbatim:

```markdown
# JSON output, exit codes and piping

## Exit codes are the contract

| Code | Meaning |
|---|---|
| `0` | The command succeeded. |
| `1` | The command ran and failed — no session, daemon error, missing target. |
| `2` | Usage error — bad flag, missing value, unknown skill target. |

Branch on the exit code, never on the message text. `visus expect-text` is the
exception by design: it *prints* `PASSED` or `FAILED: <detail>` and still exits
0, so an assertion never aborts a script.

## `--json`

Eight commands emit machine-readable output:

| Command | Shape |
|---|---|
| `visus list-fields --json` | array of field objects (`index`, `kind`, `name`, `code`, `css`, `xpath`, `frame`, `deep`, …) |
| `visus snapshot --json` | array of `{role, name}` |
| `visus tabs --json` | `{"tabs": [{index, title, url, active}]}` |
| `visus session status --json` | the full status object |
| `visus cookies --json` | array of cookie objects |
| `visus eval "<fn>" --json` | the evaluated value as JSON |
| `visus find-image t.png --json` | `{found, x, y, confidence}` |
| `visus translate '<el>' --json` | selectors + ordered candidates |
```

- [ ] **Step 5: Create `references/cli-repl.md`** (~65 lines)

Covers: `visus console [URL]`; that it attaches to an existing session and starts a **headed** one if none exists; the full command vocabulary; the five names that differ from the CLI (`list`→`list-fields`, `text`→`get-text`, `attr`→`get-attribute`, `expect`→`expect-text`, `screenshot`→`session-screenshot`); that the REPL only accepts integer indexes (no `--selector`); the nine ops it does not cover (upload, drag, add-cookies, clear-cookies, read-text, solve-captcha, find-image, and the two tab-follow ops); that `quit` leaves the session alive.
Port from: `console.py:19-53` (the help text — reproduce it as the vocabulary table), `console.py:96-215` (dispatch, for the divergences), `console.py:218-249` (start-if-absent, `quit`).

Opening content, verbatim:

```markdown
# The interactive REPL

```bash
visus console                 # attach to the running session
visus console https://example.com --headless
```

If no session is running, `visus console` **starts one** — headed unless you
pass `--headless`. `quit` exits the REPL and leaves the session alive.

The REPL is a shorter dialect of the CLI, not a different tool. Five names
differ:

| REPL | CLI |
|---|---|
| `list` | `visus list-fields` |
| `text N` | `visus get-text N` |
| `attr href N` | `visus get-attribute href N` |
| `expect N some words` | `visus expect-text N "some words"` |
| `screenshot [path]` | `visus session-screenshot -o path` |

The REPL targets **only by integer index** — `click #submit` is not accepted.
Use the CLI when you need `--selector` / `--role` / `--text`.
```

- [ ] **Step 6: Create `references/windows-shell.md`** (~75 lines)

Covers: why quoting breaks (`pyproject.toml:15` classifies Windows; `main.py:53-57` documents that `translate` exists because "the shell mangles `<`, `>`, `"`"); PowerShell vs cmd vs bash quoting tables for a CSS selector, an XPath with quotes, a JSON cookie argument, and a JS arrow function; the `--%` stop-parsing token; here-strings; the clipboard path via `visus translate`; `Get-Clipboard -Raw` (`main.py:33-36`).
Port from: `main.py:28-40` (clipboard), `main.py:43-58` (the docstring stating the motivation), `main.py:785-798` (`add-cookies` JSON argument), `main.py:812-830` (`eval`).

Opening content, verbatim:

```markdown
# Quoting on Windows

`visus` is a Windows-first tool and Windows shells mangle the characters
selectors are made of. `visus translate` exists precisely because of this — it
reads a DevTools "Copy element" blob straight off the clipboard so `<`, `>` and
`"` never touch the command line.

| Value | PowerShell | cmd.exe | bash / zsh |
|---|---|---|---|
| CSS `#user` | `visus click -s '#user'` | `visus click -s "#user"` | `visus click -s '#user'` |
| XPath with quotes | `visus click -s '//button[@id="go"]'` | `visus click -s "//button[@id='go']"` | `visus click -s '//button[@id="go"]'` |
| JS arrow fn | `visus eval '() => document.title'` | `visus eval "() => document.title"` | `visus eval '() => document.title'` |
| JSON cookies | `visus add-cookies '[{"name":"a","value":"b","url":"http://x"}]'` | use a here-file, cmd cannot nest quotes | same as PowerShell |

In PowerShell, **single quotes are literal** — prefer them. Double quotes
interpolate `$`, which will silently eat a jQuery-style selector.
```

- [ ] **Step 7: Create `references/mcp-tools.md`** (~85 lines)

Covers: how to run it (`visus-web-mcp` / `visus mcp`), the client config JSON, the eleven tool groups and all 45 names, the shared target parameters (`selector`, `role`+`name`, `text`, `exact`, `frame`), manual-vs-auto tab follow, the four tools that exist **only** in MCP (`browser_network_requests`, `browser_console_messages`, `browser_tab_activate`, `browser_set_tab_follow`), the absence of index targeting in MCP, and the skill resources/prompt added in Task 10.
Port from: `README.md:192-256` (config block, the 11-row tool-group table, the target-parameter table, the tab-follow paragraph) and `tests/test_mcp_server.py:27-84` (the authoritative 45 names).

Opening content, verbatim:

```markdown
# The MCP server

```bash
pip install "visus-web[mcp]"
visus-web-mcp          # stdio; `visus mcp` is the same thing
```

**45 tools** over its own browser. Note: the MCP server's browser is a
*different process* from the CLI session daemon, with opposite defaults —
headless by default, and new tabs are **not** followed automatically.

The server also serves this skill: resource `visus://skill/SKILL.md`, resource
template `visus://skill/references/{name}`, and the prompt
`visus_web_quickstart`.
```

- [ ] **Step 8: Create `references/vision.md`** (~45 lines)

Covers: the `[vision]` extra; the three CLI commands with their real flags; the library entry points; that OCR/matching run **inside the daemon**, so the extra must be installed where the daemon runs; that `list-fields` highlighting pollutes screenshots and must be cleared first.
Port from: `main.py:838-894` (the three commands), `README.md` vision section, `session_server.py:492-521` (`_op_find_image`, which proves the extra is needed daemon-side).

Opening content, verbatim:

```markdown
# Vision — OCR and image matching

```bash
pip install "visus-web[vision]"     # RapidOCR + OpenCV + Pillow + NumPy
```

Install it where the **daemon** runs — `read-text`, `solve-captcha` and
`find-image` all execute inside the daemon process.

```bash
visus read-text 4                          # OCR the element's screenshot
visus solve-captcha -s "#captcha"          # OCR a distorted text captcha
visus find-image button.png -c 0.85 --json # OpenCV template match over the page
visus find-image icon.png 4                # scope the search to field 4
```

Clear the numbered overlay first (`visus clear`) or list with `--no-highlight` —
the highlight markers are real DOM nodes and they show up in the pixels.
```

- [ ] **Step 9: Create `references/tracing-reports.md`** (~70 lines)

Covers: `rpa()` as the batteries-included path (records the run, writes a single-file HTML report **even when a step raises**, prints a summary); `tracing.record()` around any block; what the report contains (base64-embedded screenshots, KPI band, per-step correlated logs, ARIA snapshot on failure, `backtrack_steps`); the output layout `./visus-runs/<name>-<timestamp>/`; and the honest caveat that **none of this is reachable from the CLI today** and that `VISUS_WEB_TRACING=1` alone is a no-op outside `tracing.record()`.
Port from: `README.md:393-410` (the `rpa()` parameter block), `README.md` "Tracing & HTML reports" section, `tracing.py:81-139`, `observability/report.py:355-365`, `api/_steps.py:166`.

Opening content, verbatim:

```markdown
# Tracing and HTML reports

The strongest thing `visus.web` has that a CLI wrapper cannot give you: a
**single-file HTML report** with every screenshot embedded as base64, a KPI band
(total steps, success rate, duration, failures, distinct pages, backtrack
steps), per-step correlated logs, and an ARIA snapshot captured automatically at
the point of failure. It opens in any browser — mail it, attach it to a ticket,
publish it as a CI artifact.

```python
from visus.web import rpa, expect

with rpa("login", engine="chrome") as page:
    page.goto("https://example.com/login")
    page.get_by_label("Email").fill("ada@example.com")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_text("Welcome")).to_be_visible()
# -> ./visus-runs/login-<timestamp>/report.html  (+ run.zip, + a printed summary)
```

**Caveat:** tracing is a *library* feature. No `visus` command starts or stops a
trace, and setting `VISUS_WEB_TRACING=1` on its own does nothing — a recorder
only exists inside `rpa()` or `tracing.record()`.
```

- [ ] **Step 10: Create `references/pytest-plugin.md`** (~45 lines)

Covers: that the plugin auto-loads for every user through the `pytest11` entry point (`pyproject.toml:58-59`); the three fixtures; the CLI options `--visus-engine`, `--visus-headed`, `--visus-output`; screenshot-on-failure; automatic soft-assert verification; and that this repo's own suite disables the plugin with `-p no:visus_web` for a coverage reason that does not apply to yours.
Port from: `pyproject.toml:58-59`, `pyproject.toml:71-74` (the comment explaining `-p no:visus_web`), `README.md` "pytest plugin" section, `src/visus/web/pytest_plugin.py:51-88`.

Opening content, verbatim:

```markdown
# The pytest plugin

Installing `visus-web` registers a pytest plugin automatically — no `conftest.py`
wiring needed.

```python
from visus.web import expect

def test_login(visus_page):
    visus_page.goto("https://example.com/login")
    visus_page.get_by_label("Email").fill("ada@example.com")
    visus_page.get_by_role("button", name="Sign in").click()
    expect(visus_page.get_by_text("Welcome")).to_be_visible()
```

| Fixture | Scope | What you get |
|---|---|---|
| `visus_browser` | session | a launched browser |
| `visus_context` | function | a fresh context |
| `visus_page` | function | a fresh page, screenshotted on failure |

```bash
pytest --visus-engine edge --visus-headed --visus-output ./artifacts
```
```

- [ ] **Step 11: Create `references/library-api.md`** (~120 lines)

Covers: the public exports (`launch`, `rpa`, `expect`, `Engine`, `Browser`, `Context`, `Page`, `Field`, `errors`, `tracing`, `is_active`, `save_screenshot`); locators; auto-waited actions; reads; the `expect()` matcher list with `.not_` and soft assertions; frames/popups/dialogs/downloads/cookies; `list_fields()` + `page.field(n)` as the library twin of the CLI's index model; `launch(user_data_dir=)`, `launch(remote_url=)` for Selenium Grid, `launch(slow_mo=)`; the `edge_ie` engine for IE-mode legacy apps; `visus.web.async_api` as a 100 % mirror; and `NetworkCapture` (patches fetch/XHR/sendBeacon/dynamic `<script>`/`<img>` plus the CDP Network domain, keeps request **and** response bodies, and scrubs secret headers).
Port from: the existing skill's library sections (now at `src/visus/web/skills/visus-web/SKILL.md` before the Task 6 rewrite — recover them with `git show HEAD~3:skills/using-visus-web/SKILL.md` if needed), `src/visus/web/__init__.py:20-31` (exports), `:63-74` (`slow_mo`, `remote_url`, `user_data_dir`), `engine.py:12` (`edge_ie`), `README.md:119-121` (async), and `src/visus/web/network.py:33-53` (header scrubbing).

Opening content, verbatim:

```markdown
# The Python API

```python
from visus.web import launch, rpa, expect, Engine, Field, errors, tracing

with launch(headless=True) as browser:      # engine defaults to chrome
    page = browser.new_page()
    page.goto("https://example.com")
    page.get_by_role("button", name="Sign in").click()   # auto-waits
    page.get_by_label("Email").fill("ada@example.com")
    expect(page.get_by_text("Welcome")).to_be_visible()  # auto-retries
```

Four rules carry most of the reliability:

- **Auto-wait** — every action waits for visible / stable / enabled / editable /
  hit-testable before acting. **Never add `sleep`.**
- **Web-first assertions** — `expect(loc).to_*()` re-checks until it passes or the
  timeout elapses (5 s by default).
- **Lazy locators** — a `Locator` is a recipe, re-resolved on every use. No stale
  element errors.
- **Strict mode** — a single-element op on a locator matching >1 element raises
  `StrictModeViolation`. Disambiguate with `.first()` / `.last()` / `.nth(i)`.

Timeouts are **milliseconds** (action/navigation 30 000, `expect` 5 000).
```

- [ ] **Step 12: Append the `## Specific tasks` index to `SKILL.md`**

Add at the very end of `src/visus/web/skills/visus-web/SKILL.md`:

```markdown

## Specific tasks

* **Session daemon lifecycle** [references/cli-session.md](references/cli-session.md)
* **Targeting an element** [references/cli-targeting.md](references/cli-targeting.md)
* **Every command** [references/cli-commands.md](references/cli-commands.md)
* **JSON, exit codes, piping** [references/cli-json-and-piping.md](references/cli-json-and-piping.md)
* **The interactive REPL** [references/cli-repl.md](references/cli-repl.md)
* **Quoting on Windows** [references/windows-shell.md](references/windows-shell.md)
* **The MCP server** [references/mcp-tools.md](references/mcp-tools.md)
* **OCR and image matching** [references/vision.md](references/vision.md)
* **Tracing and HTML reports** [references/tracing-reports.md](references/tracing-reports.md)
* **The pytest plugin** [references/pytest-plugin.md](references/pytest-plugin.md)
* **Troubleshooting** [references/troubleshooting.md](references/troubleshooting.md)
* **The Python API** [references/library-api.md](references/library-api.md)
```

- [ ] **Step 13: Run test to verify it passes**

Run: `uv run pytest tests/test_skill_docs.py -v --no-cov`
Expected: PASS — 13 passed

- [ ] **Step 14: Verify the wheel carries all twelve references**

```bash
rm -rf dist && uv build --wheel
python -c "import glob,zipfile; w=sorted(glob.glob('dist/*.whl'))[-1]; n=sorted(f for f in zipfile.ZipFile(w).namelist() if '/skills/' in f); print(len(n)); print('\n'.join(n))"
rm -rf dist
```

Expected: `13` and a listing of `visus/web/skills/visus-web/SKILL.md` plus the twelve `references/*.md`.

- [ ] **Step 15: Run the gates**

Run: `uv run ruff check src tests && uv run mypy && uv run pytest -q`
Expected: all three clean.

- [ ] **Step 16: Commit**

```bash
git add src/visus/web/skills/visus-web tests/test_skill_docs.py
git commit -m "docs(skill): add the nine remaining references and the task index"
```

---

### Task 10: Let the MCP server hand out the skill

**Files:**
- Modify: `src/visus/web/mcp/server.py` (append a new section at the end, before the entry-point block at `:750`)
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `bundled_skill_dir()` from Task 1.
- Produces:
  ```python
  def _bundled_skill_text() -> str: ...
  def _bundled_skill_reference_text(name: str) -> str: ...
  @mcp.resource("visus://skill/SKILL.md", mime_type="text/markdown")
  def visus_web_skill() -> str: ...
  @mcp.resource("visus://skill/references/{name}", mime_type="text/markdown")
  def visus_web_skill_reference(name: str) -> str: ...
  @mcp.prompt()
  def visus_web_quickstart() -> str: ...
  ```
- Resources and prompts live in FastMCP's `_resource_manager` / `_prompt_manager`, **not** `_tool_manager` — the pinned tool count in `tests/test_mcp_server.py:105-112` stays 45 and must not change.
- The reading logic sits in two plain module functions so the tests never depend on what the FastMCP decorators return.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mcp_server.py`:

```python
# ---------------------------------------------------------------------------
# Skill delivery (resources + prompt) — closes the last distribution channel
# ---------------------------------------------------------------------------


def test_skill_resource_returns_the_bundled_skill() -> None:
    from visus.web.cli.skills import bundled_skill_dir
    from visus.web.mcp import server

    text = server._bundled_skill_text()
    assert text == (bundled_skill_dir() / "SKILL.md").read_text(encoding="utf-8")
    assert "visus session start" in text


def test_skill_reference_resource_reads_a_reference_file() -> None:
    from visus.web.mcp import server

    assert "visus list-fields" in server._bundled_skill_reference_text("cli-commands.md")


def test_skill_reference_resource_cannot_escape_the_references_dir() -> None:
    from visus.web.mcp import server

    with pytest.raises(FileNotFoundError):
        server._bundled_skill_reference_text("../SKILL.md")


def test_quickstart_prompt_teaches_the_session_loop() -> None:
    from visus.web.mcp import server

    text = server.visus_web_quickstart()
    assert "visus session start" in text
    assert "visus://skill/SKILL.md" in text


async def test_skill_resource_and_prompt_are_registered() -> None:
    server = importlib.import_module("visus.web.mcp.server")

    uris = [str(r.uri) for r in await server.mcp.list_resources()]
    assert any("SKILL.md" in u for u in uris), uris

    prompts = [p.name for p in await server.mcp.list_prompts()]
    assert "visus_web_quickstart" in prompts, prompts


def test_registering_the_skill_did_not_change_the_tool_count() -> None:
    assert len(_get_tool_names()) == 45
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_server.py -k "skill or quickstart" -v --no-cov`
Expected: FAIL with `AttributeError: module 'visus.web.mcp.server' has no attribute '_bundled_skill_text'`

- [ ] **Step 3: Write minimal implementation**

In `src/visus/web/mcp/server.py`, insert this block immediately **before** the
`# Entry point` comment block at line 750:

```python
# ---------------------------------------------------------------------------
# Skill delivery — an MCP client with no shell can still read the skill
# ---------------------------------------------------------------------------


def _bundled_skill_text() -> str:
    """The bundled SKILL.md, read from the installed package."""
    from visus.web.cli.skills import bundled_skill_dir

    return (bundled_skill_dir() / "SKILL.md").read_text(encoding="utf-8")


def _bundled_skill_reference_text(name: str) -> str:
    """One reference file of the bundled skill. ``name`` is basenamed, never a path."""
    from pathlib import Path

    from visus.web.cli.skills import bundled_skill_dir

    return (bundled_skill_dir() / "references" / Path(name).name).read_text(encoding="utf-8")


@mcp.resource("visus://skill/SKILL.md", mime_type="text/markdown")
def visus_web_skill() -> str:
    """The visus-web agent skill — the same file `visus install --skills` writes."""
    return _bundled_skill_text()


@mcp.resource("visus://skill/references/{name}", mime_type="text/markdown")
def visus_web_skill_reference(name: str) -> str:
    """One reference file of the visus-web skill, e.g. `cli-commands.md`."""
    return _bundled_skill_reference_text(name)


@mcp.prompt()
def visus_web_quickstart() -> str:
    """Teach the caller the visus session loop and where the full skill lives."""
    return (
        "You are driving a real browser with visus-web.\n\n"
        "Read the resource `visus://skill/SKILL.md` for the full skill, and\n"
        "`visus://skill/references/<file>.md` for a specific topic\n"
        "(cli-session, cli-targeting, cli-commands, cli-json-and-piping, cli-repl,\n"
        "windows-shell, mcp-tools, vision, tracing-reports, pytest-plugin,\n"
        "troubleshooting, library-api).\n\n"
        "With shell access, prefer the CLI — it is far cheaper in tokens:\n"
        "  visus session start <url>\n"
        "  visus list-fields\n"
        "  visus fill 1 <text>\n"
        "  visus click --role button --name Submit\n"
        "  visus expect-text --role heading '<expected>'\n"
        "  visus session stop\n\n"
        "Without shell access, use the browser_* tools here. Field indexes are a\n"
        "cache: re-run list-fields after any navigation.\n"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_server.py -v --no-cov`
Expected: PASS — every pre-existing tool assertion still green (45 tools) plus 6 new tests.

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests && uv run mypy && uv run pytest -q`
Expected: all three clean.

- [ ] **Step 6: Commit**

```bash
git add src/visus/web/mcp/server.py tests/test_mcp_server.py
git commit -m "feat(mcp): serve the agent skill as resources and a quickstart prompt"
```

---

### Task 11: Fix the contributor skill's "Add a CLI command" recipe

**Files:**
- Modify: `.claude/skills/developing-visus-web/SKILL.md:60-64`, `:74`
- Test: `tests/test_skill_docs.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing importable. This is the structural fix — the wrong recipe is *why* the shipped skill was allowed to drift to 8-of-54 coverage in the first place.

**What is wrong:** `:63-64` says the whole recipe for a CLI command is "`src/visus/web/cli/main.py`: an `@app.command()` Typer function over the public API". That is true for exactly 5 one-off commands (`main.py:97-159`). The other 45+ go through `_send(op, args)` (`main.py:205-213`) and need a matching `_op_*` in the daemon (`session_server.py:228` does `getattr(self, f"_op_{op}")`), so a contributor who follows the recipe literally ships a command that always fails with `unknown op`. Line `:61` also names a helper `locator(...)` that does not exist — the real one is `make_locator`, and it is keyword-only.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skill_docs.py`:

```python
DEV_SKILL = (
    Path(__file__).resolve().parents[1]
    / ".claude"
    / "skills"
    / "developing-visus-web"
    / "SKILL.md"
)


def test_contributor_recipe_names_every_place_a_session_command_touches() -> None:
    text = DEV_SKILL.read_text(encoding="utf-8")
    for fragment in (
        "session_server.py",
        "_op_",
        "console.py",
        "README.md",
        "references/cli-commands.md",
    ):
        assert fragment in text, f"the CLI recipe never mentions {fragment!r}"


def test_contributor_recipe_names_the_real_locator_helper() -> None:
    text = DEV_SKILL.read_text(encoding="utf-8")
    assert "make_locator" in text
    assert "locator(page, role=" not in text, "that helper does not exist"


def test_contributor_skill_declares_the_full_cli_extra() -> None:
    assert "[cli]` (typer + rich + click)" in DEV_SKILL.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_skill_docs.py -k contributor -v --no-cov`
Expected: FAIL — `AssertionError: the CLI recipe never mentions 'session_server.py'`

- [ ] **Step 3: Write minimal implementation**

In `.claude/skills/developing-visus-web/SKILL.md`, replace lines 60-64:

```markdown
### Add an MCP tool
`src/visus/web/mcp/server.py`: a `@mcp.tool()` thin wrapper over the public API, targeting via the shared `locator(page, role=, name=, text=, selector=, frame=)` helper. Add it to the registration assertion in `tests/test_mcp_server.py` and drive it in `tests/test_e2e_mcp.py`.

### Add a CLI command
`src/visus/web/cli/main.py`: an `@app.command()` Typer function over the public API. Test with `typer.testing.CliRunner` (real browser for browser-touching commands).
```

with:

```markdown
### Add an MCP tool
`src/visus/web/mcp/server.py`: a `@mcp.tool()` thin wrapper over the public API, targeting via the shared `make_locator(page, *, selector=, role=, name=, text=, exact=, frame=)` helper (`mcp/session.py:142-160`; **keyword-only** after `page`). Add the name to `_EXPECTED_TOOLS` in `tests/test_mcp_server.py` — that list is an exact-equality inventory, so the count assertion fails until you do — and drive the tool in `tests/test_e2e_mcp.py`.

### Add a CLI command

There are two kinds of command and only the first is a one-file change.

**One-off command** (launches its own browser: `doctor`, `install`, `screenshot`, `pdf`, `open`, `run`, `codegen`, `translate`, `mcp`, `version`) — `src/visus/web/cli/main.py`: an `@app.command()` Typer function over the public API.

**Session command** (everything else — it drives the running daemon). Five places must change together, or the command ships broken:

1. `src/visus/web/cli/session_server.py`: a `_op_<name>(self, args) -> ...` method. `handle()` dispatches with `getattr(self, f"_op_{op}")` (`:228`), so a missing handler fails at runtime with `unknown op '<name>'`. Resolve the target with `self._target(args)` (index **or** `make_locator` params) and read the locator-text target from `args["target_text"]`, never `args["text"]` — `text` is `fill`'s *value*.
2. `src/visus/web/cli/main.py`: an `@app.command()` that builds its args with `_target_args(index, selector, role, name, text)` (`:222-235`) and sends them through `_send("<name>", args)` (`:205-213`). Never call the daemon directly.
3. `src/visus/web/cli/console.py:96-215`: a `dispatch` branch, so the REPL can reach it.
4. `src/visus/web/cli/console.py:19-53`: a line in `_HELP`.
5. `README.md:286-376` **and** `src/visus/web/skills/visus-web/references/cli-commands.md`: a row in the matching table. `tests/test_skill_docs.py::test_every_cli_command_is_documented` walks `app.registered_commands` and fails listing anything undocumented.

Test with `typer.testing.CliRunner` asserting the exact op name and payload sent to the daemon (the pattern is `tests/test_cli_session.py:1152-1642`), plus a real-browser test of the `_op_*` handler.
```

Then replace line 74's extras list — change:

```
Optional extras: `[dev]`, `[vision]` (rapidocr/opencv/pillow/numpy), `[mcp]` (mcp), `[cli]` (typer).
```

to:

```
Optional extras: `[dev]`, `[vision]` (rapidocr/opencv/pillow/numpy), `[mcp]` (mcp), `[cli]` (typer + rich + click).
```

Finally, add to the same file, directly after the `### Add a CLI command` block:

```markdown
### Change the shipped agent skill

The skill lives at `src/visus/web/skills/visus-web/` and ships inside the wheel.
Its frontmatter `version` must equal `visus.web.__version__` — bump both together.
`tests/test_skill_docs.py` gates command coverage, the MCP tool count, and link
integrity. The contributor guide you are reading is **not** shipped; it lives in
`.claude/skills/developing-visus-web/`.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_skill_docs.py -v --no-cov`
Expected: PASS — 16 passed

- [ ] **Step 5: Run the gates**

Run: `uv run ruff check src tests && uv run mypy && uv run pytest -q`
Expected: all three clean.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/developing-visus-web/SKILL.md tests/test_skill_docs.py
git commit -m "docs(skill): correct the contributor recipe for session CLI commands"
```

---

### Task 12: Repo and PyPI metadata hygiene

**Files:**
- Modify: `.gitignore`
- Modify: `pyproject.toml:14-17`
- Modify: `README.md:944`
- Modify: `mkdocs.yml:32-36`
- Create: `docs/agent-skill.md`
- Test: `tests/test_repo_metadata.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing importable.

- [ ] **Step 1: Write the failing test**

Create `tests/test_repo_metadata.py`:

```python
"""Consistency gates over the repo's own metadata.

These files are read by humans, PyPI and the docs site, and they drift silently
because nothing imports them.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_gitignore_ignores_the_installed_self_skill_but_keeps_the_contributor_one() -> None:
    lines = [ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert ".claude/skills/visus-web/" in lines
    assert ".agents/" in lines
    assert ".claude/" not in lines, "that would untrack the contributor skill"
    assert (ROOT / ".claude" / "skills" / "developing-visus-web" / "SKILL.md").is_file()


def test_gitignore_still_hides_planning_docs_but_allows_the_docs_page() -> None:
    lines = [ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert "/docs/*" in lines
    assert "!/docs/agent-skill.md" in lines


def test_readme_clone_url_matches_the_package_repository_url() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r'^Repository = "([^"]+)"', pyproject, re.M)
    assert match, "pyproject.toml has no Repository URL"
    assert f"git clone {match.group(1)}" in readme


def test_pypi_metadata_is_not_thin() -> None:
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
    mkdocs = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
    assert "agent-skill.md" in mkdocs, "the mkdocs nav does not reach the skill"
    page = ROOT / "docs" / "agent-skill.md"
    assert page.is_file()
    text = page.read_text(encoding="utf-8")
    assert "visus install --skills" in text
    assert "visus session start" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_repo_metadata.py -v --no-cov`
Expected: FAIL — all five tests fail (`.claude/skills/visus-web/` absent from `.gitignore`, `/docs/*` absent, README clones from `matheuszwilk` while the package points at `botvisus`, no `keywords`, no `agent-skill.md`).

- [ ] **Step 3: Update `.gitignore`**

Replace the planning-docs block (currently lines 5-6):

```
# ---- Local-only planning docs (specs/plans kept on disk, NOT tracked) ----
/docs/
```

with:

```
# ---- Local-only planning docs (specs/plans kept on disk, NOT tracked) ----
# `/docs/*` (not `/docs/`) so a single tracked page can be re-included below —
# git cannot un-ignore a file whose parent directory is excluded.
/docs/*
!/docs/agent-skill.md
```

And add a new block directly after the "Editors / OS" section at the end of the file:

```
# ---- Agent skills installed into this repo (build artifacts) ----
# `visus install --skills` writes the shipped skill here; the source of truth is
# src/visus/web/skills/visus-web/. The contributor skill under
# .claude/skills/developing-visus-web/ IS tracked — do not widen this to `.claude/`.
.claude/skills/visus-web/
.agents/
```

- [ ] **Step 4: Fix the clone URL**

In `README.md`, replace line 944:

```
git clone https://github.com/matheuszwilk/visus-framework-web.git
```

with:

```
git clone https://github.com/botvisus/visus-framework-web.git
```

*(`pyproject.toml:21-23` is the published metadata and therefore authoritative. If the `botvisus` org is not the real home, change `pyproject.toml` instead and re-run the test — it only enforces that the two agree.)*

- [ ] **Step 5: Enrich the PyPI metadata**

In `pyproject.toml`, replace lines 14-17:

```toml
classifiers = [
    "Operating System :: Microsoft :: Windows",
    "Programming Language :: Python :: 3",
]
```

with:

```toml
keywords = [
    "browser-automation",
    "selenium",
    "web-testing",
    "rpa",
    "playwright-style",
    "locators",
    "mcp",
    "agent-skill",
    "ocr",
    "captcha",
]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "Operating System :: Microsoft :: Windows",
    "Operating System :: POSIX :: Linux",
    "Operating System :: MacOS",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Software Development :: Testing",
    "Topic :: Software Development :: Testing :: Acceptance",
    "Topic :: Internet :: WWW/HTTP :: Browsers",
    "Typing :: Typed",
]
```

- [ ] **Step 6: Add the docs page and put it in the nav**

Create `docs/agent-skill.md`:

```markdown
# The agent skill

`visus-web` ships an agent skill inside the wheel. Any agent that reads
`.claude/skills/` (Claude Code, GitHub Copilot, and others) picks it up once you
install it into the repository you are working in.

```bash
pip install "visus-web[cli]"
visus install --skills            # -> ./.claude/skills/visus-web/
visus install --skills=agents     # -> ./.agents/skills/visus-web/
visus install-skills --target both --force
```

Every later `visus` invocation compares the installed copy against the packaged
one and prints a framed warning **to stderr** if they diverge, naming the
command that fixes it. Line endings are normalised, so a CRLF checkout never
raises a false alarm.

## What the skill teaches

The session loop, which is how an agent should drive the browser:

```bash
visus session start https://example.com/login
visus list-fields
visus fill 1 ada@example.com
visus click --role button --name "Sign in"
visus expect-text --role heading "Welcome"
visus session stop
```

Twelve reference files sit next to it — session lifecycle, targeting, the full
command table, JSON and piping, the REPL, Windows quoting, the MCP tools,
vision, tracing and reports, the pytest plugin, troubleshooting, and the Python
API.

## Without the CLI

An MCP client can read the same content without a shell: the `visus-web-mcp`
server exposes the resource `visus://skill/SKILL.md`, the resource template
`visus://skill/references/{name}`, and the prompt `visus_web_quickstart`.
```

In `mkdocs.yml`, replace lines 32-36:

```yaml
nav:
  - Home: index.md
  - API reference:
      - Sync API: api.md
      - Async API: api-async.md
```

with:

```yaml
nav:
  - Home: index.md
  - Agent skill: agent-skill.md
  - API reference:
      - Sync API: api.md
      - Async API: api-async.md
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/test_repo_metadata.py -v --no-cov`
Expected: PASS — 5 passed

- [ ] **Step 8: Confirm the metadata still builds**

```bash
rm -rf dist && uv build && uv run python -m twine check dist/*
rm -rf dist
```

Expected: `Checking dist/…: PASSED` for both the wheel and the sdist.
*(If `twine` is not installed: `uv pip install twine`.)*

- [ ] **Step 9: Run the gates**

Run: `uv run ruff check src tests && uv run mypy && uv run pytest -q`
Expected: all three clean.

- [ ] **Step 10: Commit**

```bash
git add .gitignore pyproject.toml README.md mkdocs.yml docs/agent-skill.md tests/test_repo_metadata.py
git commit -m "chore(repo): ignore installed skills, enrich PyPI metadata, put the skill in the docs"
```

---

### Task 13: Resolve the license contradiction

**Files:**
- Modify: **one of** (`README.md:9`, `README.md:958-963`) **or** (`LICENSE`, `NOTICE`, `pyproject.toml:11-12`)
- Test: `tests/test_repo_metadata.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing importable.

**Why this is a task and not a note.** `LICENSE:1-3` and `pyproject.toml:11` declare **Apache-2.0**. `README.md:9` renders a red `License: Proprietary` badge and `README.md:960` says **"Proprietary — all rights reserved. … copying the source, redistributing, modifying, or reverse engineering it is not permitted."** Both are packaged: `license = "Apache-2.0"` becomes the `License-Expression` metadata field, `license-files = ["LICENSE", "NOTICE"]` embeds the Apache text, and `readme = "README.md"` renders the contradicting prose — **on the same PyPI page**. A downstream user who relies on the Apache grant while the author intends proprietary terms is a dispute waiting to happen. **This must resolve before the next release.**

**The decision.** Pick exactly one branch. The test below enforces internal consistency either way; it does not pick for you.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_repo_metadata.py`:

```python
def test_license_metadata_is_self_consistent() -> None:
    """LICENSE, pyproject and README must tell PyPI the same story.

    Today they do not: `pyproject.toml:11` and `LICENSE` say Apache-2.0 while
    `README.md:9` badges "Proprietary" and `README.md:960` says all rights are
    reserved — and all three render on the same PyPI page.
    """
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")

    apache_in_pyproject = 'license = "Apache-2.0"' in pyproject
    apache_in_license_file = "Apache License" in license_text
    assert apache_in_pyproject == apache_in_license_file, (
        "pyproject.toml's license expression and the LICENSE file disagree"
    )

    badge_says_proprietary = "License-Proprietary" in readme
    prose_says_proprietary = "Proprietary — all rights reserved" in readme
    assert badge_says_proprietary == prose_says_proprietary, (
        "the README badge and the README License section disagree"
    )
    assert badge_says_proprietary is not apache_in_pyproject, (
        "the README and the packaged license metadata disagree — both render on PyPI"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_repo_metadata.py::test_license_metadata_is_self_consistent -v --no-cov`
Expected: FAIL with `AssertionError: the README and the packaged license metadata disagree — both render on PyPI`

- [ ] **Step 3: Choose a branch and execute exactly one**

**Branch A — keep Apache-2.0** (the LICENSE file and the packaged metadata already say this; only the README is wrong).

Replace `README.md:9`:

```markdown
[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)
```

with:

```markdown
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
```

and replace `README.md:958-963`:

```markdown
## License

**Proprietary — all rights reserved.** You may install and use `visus-web` as a dependency in your
own projects, but copying the source, redistributing, modifying, or reverse engineering it is **not
permitted**. See [LICENSE](LICENSE) for the full terms. For commercial or redistribution licenses,
contact the author.
```

with:

```markdown
## License

Licensed under the **Apache License, Version 2.0**. See [LICENSE](LICENSE) for the
full text and [NOTICE](NOTICE) for attribution requirements.
```

Leave `LICENSE`, `NOTICE` and `pyproject.toml:11-12` untouched.

**Branch B — make it proprietary** (the README states the author's intent; the packaged metadata is wrong).

Replace `pyproject.toml:11-12`:

```toml
license = "Apache-2.0"
license-files = ["LICENSE", "NOTICE"]
```

with:

```toml
license = "LicenseRef-Proprietary"
license-files = ["LICENSE"]
```

Replace the whole of `LICENSE` with the proprietary grant (this exact text; it matches `README.md:960-963`):

```
Visus Web — Proprietary License
Copyright 2026 Matheus Pereira. All rights reserved.

You may install and use visus-web as a dependency in your own projects.

You may NOT copy the source, redistribute it, modify it, create derivative
works from it, or reverse engineer it, in whole or in part, without prior
written permission from the copyright holder.

For commercial or redistribution licenses, contact the author.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
```

Delete `NOTICE` (`git rm NOTICE`) — it exists only to satisfy Apache-2.0 §4(d) and its text asserts the Apache grant. Leave the README untouched.

Branch B additionally invalidates the Apache-2.0 badge/classifier expectations of anyone who already depends on the current release; note it in the release notes.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_repo_metadata.py -v --no-cov`
Expected: PASS — 6 passed

- [ ] **Step 5: Confirm the packaged metadata agrees**

```bash
rm -rf dist && uv build --wheel
python -c "import glob,zipfile; w=sorted(glob.glob('dist/*.whl'))[-1]; z=zipfile.ZipFile(w); m=[n for n in z.namelist() if n.endswith('METADATA')][0]; print('\n'.join(l for l in z.read(m).decode('utf-8').splitlines() if l.startswith('License')))"
rm -rf dist
```

Expected, Branch A: `License-Expression: Apache-2.0` plus `License-File: LICENSE` and `License-File: NOTICE`.
Expected, Branch B: `License-Expression: LicenseRef-Proprietary` plus `License-File: LICENSE`, and no `NOTICE`.

- [ ] **Step 6: Run the gates**

Run: `uv run ruff check src tests && uv run mypy && uv run pytest -q`
Expected: all three clean.

- [ ] **Step 7: Commit**

Branch A:

```bash
git add README.md tests/test_repo_metadata.py
git commit -m "docs(license): state Apache-2.0 consistently in the README"
```

Branch B:

```bash
git add pyproject.toml LICENSE tests/test_repo_metadata.py
git rm NOTICE
git commit -m "chore(license): publish proprietary terms in the package metadata"
```

---

## Done when

- `uv run ruff check src tests`, `uv run mypy` and `uv run pytest -q` are all clean with coverage ≥90 %.
- `uv build --wheel` produces a wheel containing `visus/web/skills/visus-web/SKILL.md` and twelve `references/*.md`.
- In an empty directory: `visus install --skills` writes `.claude/skills/visus-web/`, appending a byte to the installed `SKILL.md` makes the next `visus version` print a framed `does not match the tool version` box **on stderr**, and rewriting that file with CRLF line endings does not.
- `python -m visus.web.cli version` and `uv run visus version` both print `0.2.0`.
- `tests/test_skill_docs.py` fails the moment a CLI command, an MCP tool, or a reference link is added without its documentation.
- `tests/test_repo_metadata.py` fails the moment the license, the clone URL, the `.gitignore` rules or the docs nav drift apart again.
