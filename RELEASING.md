# Releasing visus-web

A release is: bump two version strings, prove the gate is green, tag, and cut a GitHub
Release. `.github/workflows/publish.yml` does the rest through PyPI Trusted Publishing
(OIDC) — there are no tokens and no secrets to manage.

**`workflow_dispatch` does not publish.** Every job in `publish.yml` is guarded by
`if: github.event_name == 'release'`. A manual run from the Actions tab builds nothing.
That guard is the fix for a defect where a dispatch from any branch published that
branch to PyPI, unversioned and untested.

## Steps

1. **Bump the version in ALL THREE places.** They are duplicated and nothing keeps them
   in sync — a release that bumps only one ships a package whose `visus version` lies.

   - `pyproject.toml` → `[project] version = "X.Y.Z"` (line 7)
   - `src/visus/web/__init__.py` → `__version__ = "X.Y.Z"` (line 17)
   - `src/visus/web/skills/visus-web/SKILL.md` → frontmatter `version: "X.Y.Z"` (line 5;
     `tests/test_skill_docs.py` fails the CI gate when it lags — that stopped v0.3.3's
     first publish)

   Verify: `uv run python -c "import visus.web; print(visus.web.__version__)"`

2. **Run the full gate locally.** This is the same set CI runs; run it before tagging so
   a red release job is never the first you hear of a problem.

   ```bash
   uv run ruff check src tests scripts
   uv run mypy
   uv run pytest -q --cov-fail-under=90 --cov-report=json
   uv run python scripts/check_coverage.py
   ```

3. **Ratchet the coverage floors if they moved up.** Floors only ever go up.

   ```bash
   uv run python scripts/check_coverage.py --freeze
   git diff coverage-floors.json
   ```

   If nothing improved, discard the diff. If CI's numbers are the authoritative ones,
   download the `coverage-json` artifact from the `browser-tests` job of the latest CI
   run and freeze from it: `uv run python scripts/check_coverage.py --freeze --report <path>`.

4. **Verify the wheel is shippable.** `twine check` only reads metadata; this opens the
   payload, exactly as the `build` job does.

   ```bash
   uv run python -m build --wheel --no-isolation --outdir dist
   uv run python -c "import glob,zipfile; n=set(zipfile.ZipFile(sorted(glob.glob('dist/*.whl'))[0]).namelist()); print([f for f in ('visus/web/skills/visus-web/SKILL.md','visus/web/backends/selenium/js/bundle.js','visus/web/py.typed') if f not in n] or 'OK')"
   ```

   Expected: `OK`. Then remove `dist/` and `build/`.

5. **Commit, tag and push.**

   ```bash
   git add pyproject.toml src/visus/web/__init__.py coverage-floors.json
   git commit -m "chore: mark vX.Y.Z"
   git tag vX.Y.Z
   git push origin main --tags
   ```

6. **Cut the GitHub Release** on tag `vX.Y.Z`. Publishing the Release fires
   `publish.yml`, which runs the whole CI matrix first (`needs: [test]`), then builds,
   asserts the wheel's contents, and uploads to PyPI.

7. **Verify what landed.**

   ```bash
   pip download --no-deps --dest ./_verify "visus-web[cli]==X.Y.Z"
   ```

   (`./_verify` rather than `/tmp` — this is a Windows-first project and the same command
   has to work in PowerShell. Delete the directory afterwards.)

   Then install it into a clean venv and run `visus --help` and `visus version`. The
   `packaging-tests` job already does this against the pre-release wheel on both
   ubuntu-latest and windows-latest.

## Rolling Selenium

`selenium>=4.38,<5` is a range, so Dependabot only files a PR when a release falls
outside it. Rolling *within* the range is manual and worth doing before each release:

1. `uv pip install --upgrade selenium` and note the new version.
2. Run the full gate (step 2 above). The real-browser suite is the actual test of the
   roll — Selenium Manager resolves a matching driver at launch, so a driver-protocol
   regression shows up as browser test failures, not as an import error.
3. Run the Edge IE-mode test serially, since it excludes itself from parallel runs:
   `uv run pytest tests/test_e2e_edge_ie.py -n 0 --no-cov -m browser`
4. If the new version is outside the current cap, widen `dependencies` in
   `pyproject.toml` and say so in the release notes.
5. Commit as `chore: roll selenium to <version>`.
