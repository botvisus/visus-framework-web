"""Per-package coverage floors, on top of the single global gate.

``--cov-fail-under`` is one number over the whole of ``visus.web`` — roughly
11,300 statements across 8 sub-packages. ``visus/web/cli`` and
``visus/web/mcp`` alone are roughly 3,200 of those, so either could rot for
months while the global total stays above 90%. This script re-aggregates the
machine-readable ``coverage.json`` per top-level sub-package of ``visus/web``
and fails when any package falls below the floor recorded in
``coverage-floors.json``.

    uv run pytest -q --cov-report=json          # writes coverage.json
    uv run python scripts/check_coverage.py     # enforce global + per-package
    uv run python scripts/check_coverage.py --freeze   # (re)record the floors

``coverage-floors.json`` ships with an empty ``packages`` map until the repo
owner runs ``--freeze`` from a real full-suite run (this script never
fabricates numbers it did not measure). With ``packages`` empty, ``main()``
enforces only the pre-existing global floor — see ``violations()`` below —
so CI does not crash before that freeze happens.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10 — tomllib landed in 3.11
    import tomli as tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT = REPO_ROOT / "coverage.json"
DEFAULT_FLOORS = REPO_ROOT / "coverage-floors.json"
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: Everything under ``visus/web/<name>/`` buckets as ``<name>``; modules sitting
#: directly in ``visus/web/`` bucket as ``_root``.
MARKER = "visus/web/"
ROOT_BUCKET = "_root"
DEFAULT_SLACK = 3.0


def package_of(path: str) -> str | None:
    """Bucket one coverage.json file key. ``None`` for paths outside visus.web."""
    rel = path.replace("\\", "/")
    idx = rel.rfind(MARKER)
    if idx < 0:
        return None
    tail = rel[idx + len(MARKER) :]
    head, sep, _rest = tail.partition("/")
    return head if sep else ROOT_BUCKET


def package_totals(report: dict[str, Any]) -> dict[str, float]:
    """Statement-coverage percent per sub-package, weighted by statement count."""
    acc: dict[str, list[int]] = {}
    files: dict[str, Any] = report.get("files") or {}
    for path, entry in files.items():
        package = package_of(path)
        if package is None:
            continue
        summary = entry["summary"]
        bucket = acc.setdefault(package, [0, 0])
        bucket[0] += int(summary["covered_lines"])
        bucket[1] += int(summary["num_statements"])
    return {
        package: (100.0 if statements == 0 else round(100.0 * covered / statements, 2))
        for package, (covered, statements) in sorted(acc.items())
    }


def global_floor(pyproject: Path = PYPROJECT) -> float:
    """The one global gate, read from ``[tool.coverage.report] fail_under``."""
    data: dict[str, Any] = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return float(data["tool"]["coverage"]["report"]["fail_under"])


def violations(
    totals: dict[str, float],
    floors: dict[str, float],
    *,
    global_total: float,
    global_min: float,
) -> list[str]:
    """Human-readable lines describing every floor that was not met.

    An empty ``floors`` (the pre-freeze state of ``coverage-floors.json``)
    yields no per-package checks at all — only the global floor is enforced.
    """
    out: list[str] = []
    if global_total + 1e-9 < global_min:
        out.append(f"TOTAL: {global_total:.2f}% < global floor {global_min:.2f}%")
    for package in sorted(floors):
        floor = float(floors[package])
        actual = totals.get(package)
        if actual is None:
            out.append(f"{package}: no statements in the report (package renamed or deleted?)")
        elif actual + 1e-9 < floor:
            out.append(f"{package}: {actual:.2f}% < floor {floor:.2f}%")
    return out


def freeze(totals: dict[str, float], slack: float) -> dict[str, float]:
    """Record today's numbers, minus *slack*, as tomorrow's floors."""
    return {package: round(max(0.0, pct - slack), 2) for package, pct in sorted(totals.items())}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Enforce per-package coverage floors.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--floors", type=Path, default=DEFAULT_FLOORS)
    parser.add_argument("--pyproject", type=Path, default=PYPROJECT)
    parser.add_argument(
        "--freeze", action="store_true", help="Rewrite the floors file from this report."
    )
    parser.add_argument(
        "--slack",
        type=float,
        default=DEFAULT_SLACK,
        help="Points below today's number to record when freezing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if not args.report.is_file():
        print(
            f"error: {args.report} not found — run `pytest --cov-report=json` first",
            file=sys.stderr,
        )
        return 2

    report: dict[str, Any] = json.loads(args.report.read_text(encoding="utf-8"))
    totals = package_totals(report)
    global_total = float(report["totals"]["percent_covered"])
    minimum = global_floor(args.pyproject)

    width = max((len(name) for name in totals), default=8)
    for package, pct in totals.items():
        print(f"  {package:<{width}}  {pct:6.2f}%")
    print(f"  {'TOTAL':<{width}}  {global_total:6.2f}%  (global floor {minimum:.2f}%)")

    if args.freeze:
        payload = {"slack": args.slack, "packages": freeze(totals, args.slack)}
        args.floors.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"\nfroze {len(payload['packages'])} per-package floors into {args.floors}")
        return 0

    if not args.floors.is_file():
        print(
            f"error: {args.floors} not found — run once with --freeze to record it",
            file=sys.stderr,
        )
        return 2

    recorded: dict[str, Any] = json.loads(args.floors.read_text(encoding="utf-8"))
    floors = {name: float(value) for name, value in recorded["packages"].items()}
    failures = violations(totals, floors, global_total=global_total, global_min=minimum)
    if failures:
        print("\nCoverage floors NOT met:", file=sys.stderr)
        for line in failures:
            print(f"  - {line}", file=sys.stderr)
        return 1
    print("\nAll coverage floors met.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
