"""Unit tests for scripts/check_coverage.py — the per-package coverage floors.

The script is loaded by path because `scripts/` is a repo tool, not an importable
package. Inputs are synthetic coverage.json documents; nothing is patched. The
real end-to-end exercise is ci.yml's browser lane, which runs the script against
a coverage.json produced by an actual full-suite run.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_coverage.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_coverage", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_coverage"] = module
    spec.loader.exec_module(module)
    return module


cc = _load_script()


def _report(files: dict[str, tuple[int, int]], total_pct: float) -> dict[str, Any]:
    """Build a minimal coverage.json: {path: (covered_lines, num_statements)}."""
    return {
        "files": {
            path: {"summary": {"covered_lines": covered, "num_statements": stmts}}
            for path, (covered, stmts) in files.items()
        },
        "totals": {"percent_covered": total_pct},
    }


def test_package_of_buckets_subpackages() -> None:
    assert cc.package_of("src/visus/web/cli/main.py") == "cli"
    assert cc.package_of("src/visus/web/backends/selenium/driver_delegate.py") == "backends"


def test_package_of_buckets_top_level_modules_as_root() -> None:
    assert cc.package_of("src/visus/web/engine.py") == "_root"
    assert cc.package_of("src/visus/web/__init__.py") == "_root"


def test_package_of_handles_windows_separators_and_site_packages() -> None:
    assert cc.package_of(r"src\visus\web\mcp\server.py") == "mcp"
    assert cc.package_of(".venv/Lib/site-packages/visus/web/mcp/server.py") == "mcp"


def test_package_of_ignores_paths_outside_the_package() -> None:
    assert cc.package_of("tests/test_cli.py") is None
    assert cc.package_of("scripts/check_coverage.py") is None


def test_package_totals_weight_by_statement_count() -> None:
    report = _report(
        {
            "src/visus/web/cli/main.py": (5, 10),
            "src/visus/web/cli/session_server.py": (45, 90),
            "src/visus/web/mcp/server.py": (30, 30),
        },
        total_pct=61.5,
    )
    assert cc.package_totals(report) == {"cli": 50.0, "mcp": 100.0}


def test_package_totals_treats_an_empty_package_as_fully_covered() -> None:
    report = _report({"src/visus/web/vision/__init__.py": (0, 0)}, total_pct=100.0)
    assert cc.package_totals(report) == {"vision": 100.0}


def test_violations_flag_a_package_below_its_floor() -> None:
    bad = cc.violations(
        {"cli": 71.0, "mcp": 95.0},
        {"cli": 80.0, "mcp": 90.0},
        global_total=93.0,
        global_min=90.0,
    )
    assert bad == ["cli: 71.00% < floor 80.00%"]


def test_violations_flag_the_global_total() -> None:
    bad = cc.violations({"cli": 99.0}, {"cli": 80.0}, global_total=88.5, global_min=90.0)
    assert bad == ["TOTAL: 88.50% < global floor 90.00%"]


def test_violations_flag_a_package_that_vanished_from_the_report() -> None:
    bad = cc.violations(
        {"cli": 99.0}, {"cli": 80.0, "mcp": 90.0}, global_total=99.0, global_min=90.0
    )
    assert bad == ["mcp: no statements in the report (package renamed or deleted?)"]


def test_violations_are_empty_when_everything_holds() -> None:
    assert cc.violations({"cli": 81.0}, {"cli": 80.0}, global_total=90.0, global_min=90.0) == []


def test_freeze_records_todays_numbers_minus_slack() -> None:
    assert cc.freeze({"cli": 84.0, "mcp": 1.5}, slack=3.0) == {"cli": 81.0, "mcp": 0.0}


def test_main_freeze_then_enforce_round_trip(tmp_path: Path) -> None:
    report_path = tmp_path / "coverage.json"
    floors_path = tmp_path / "coverage-floors.json"
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.coverage.report]\nfail_under = 90\n", encoding="utf-8")
    report_path.write_text(
        json.dumps(
            _report(
                {
                    "src/visus/web/cli/main.py": (80, 100),
                    "src/visus/web/mcp/server.py": (95, 100),
                },
                total_pct=91.0,
            )
        ),
        encoding="utf-8",
    )
    argv = [
        "--report",
        str(report_path),
        "--floors",
        str(floors_path),
        "--pyproject",
        str(pyproject),
    ]

    assert cc.main([*argv, "--freeze", "--slack", "3"]) == 0
    recorded = json.loads(floors_path.read_text(encoding="utf-8"))
    assert recorded == {"slack": 3.0, "packages": {"cli": 77.0, "mcp": 92.0}}

    assert cc.main(argv) == 0

    recorded["packages"]["cli"] = 100.0
    floors_path.write_text(json.dumps(recorded), encoding="utf-8")
    assert cc.main(argv) == 1


def test_main_reports_a_missing_coverage_report(tmp_path: Path) -> None:
    assert cc.main(["--report", str(tmp_path / "nope.json")]) == 2


def test_main_treats_empty_committed_floors_as_global_gate_only(tmp_path: Path) -> None:
    """Before the repo owner runs --freeze, coverage-floors.json ships with an
    empty `packages` map. The gate must degrade to "just the global floor",
    never crash — this is the pre-freeze state the real committed file is in.
    """
    report_path = tmp_path / "coverage.json"
    floors_path = tmp_path / "coverage-floors.json"
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.coverage.report]\nfail_under = 90\n", encoding="utf-8")
    report_path.write_text(
        json.dumps(
            _report({"src/visus/web/cli/main.py": (10, 10)}, total_pct=95.0),
        ),
        encoding="utf-8",
    )
    floors_path.write_text(
        json.dumps({"slack": 3.0, "packages": {}}), encoding="utf-8"
    )
    argv = [
        "--report",
        str(report_path),
        "--floors",
        str(floors_path),
        "--pyproject",
        str(pyproject),
    ]
    assert cc.main(argv) == 0


def test_main_reports_a_missing_floors_file_when_not_freezing(tmp_path: Path) -> None:
    report_path = tmp_path / "coverage.json"
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.coverage.report]\nfail_under = 90\n", encoding="utf-8")
    report_path.write_text(
        json.dumps(_report({"src/visus/web/cli/main.py": (10, 10)}, total_pct=95.0)),
        encoding="utf-8",
    )
    argv = [
        "--report",
        str(report_path),
        "--floors",
        str(tmp_path / "nope-floors.json"),
        "--pyproject",
        str(pyproject),
    ]
    assert cc.main(argv) == 2


def test_the_committed_floors_file_is_wellformed() -> None:
    """Enforces the *shape* of the committed file, not real numbers.

    A fresh checkout ships with `packages` empty — the real per-package numbers
    are frozen by the repo owner from a full-suite run (banned in this
    environment; see the file's own `_comment`). Once frozen, `cli` and `mcp`
    must both be present: they are exactly the packages the global gate can
    hide (see module docstring). This test stays green both before and after
    that freeze, so it never needs `skip`/`xfail`.
    """
    data = json.loads((REPO_ROOT / "coverage-floors.json").read_text(encoding="utf-8"))
    assert isinstance(data["slack"], (int, float))
    assert isinstance(data["packages"], dict)
    assert all(
        isinstance(name, str) and isinstance(value, (int, float)) and 0.0 <= value <= 100.0
        for name, value in data["packages"].items()
    )
    if data["packages"]:
        assert {"cli", "mcp"} <= set(data["packages"]), (
            "cli/ and mcp/ are the packages the global gate can most easily hide "
            "(see scripts/check_coverage.py's module docstring)"
        )
