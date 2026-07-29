"""Boundary, module-size, and compatibility-matrix fixtures (PRD 082 phase 15 / R27)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from planning_boundary_lint import lint_repo as boundary_lint_repo, validate_compat_matrix
from planning_module_size_lint import (
    MODULE_LINE_CAP,
    classify_path,
    lint_repo as size_lint_repo,
    shim_exemption_for,
)
from _planning_pkg_loader import load_submodule

_boundary = load_submodule("providers._boundary")
provider_import_violations = _boundary.provider_import_violations

MATRIX_REL = Path("core/sw-reference/planning-compat-matrix.md")


def test_boundary_lint_passes_on_repo() -> None:
    result = boundary_lint_repo(REPO_ROOT)
    assert result["verdict"] == "pass", result
    assert result["extractionComplete"] is True


def test_boundary_lint_fails_provider_import_outside_adapters(tmp_path: Path) -> None:
    target = tmp_path / "scripts" / "issues_lib.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "from planning_github_client import GitHubIssuesClient\n",
        encoding="utf-8",
    )
    violations = provider_import_violations(tmp_path)
    assert violations
    result = boundary_lint_repo(tmp_path)
    assert result["verdict"] == "warn"
    assert result["extractionComplete"] is False


def test_boundary_lint_errors_when_extraction_complete(tmp_path: Path) -> None:
    for rel in (
        "scripts/planning/providers/github.py",
        "scripts/planning/providers/gitlab.py",
        "scripts/planning/providers/jira.py",
        "scripts/planning/providers/linear.py",
        "scripts/issues_lib.py",
    ):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# stub\nfrom planning_github_client import GitHubIssuesClient\n", encoding="utf-8")
    result = boundary_lint_repo(tmp_path)
    assert result["verdict"] == "fail"
    assert result["extractionComplete"] is True


def test_size_lint_passes_on_authored_package_modules() -> None:
    result = size_lint_repo(REPO_ROOT)
    assert result["verdict"] == "pass", result
    assert result["cap"] == MODULE_LINE_CAP
    assert any(row["path"] == "scripts/planning_store.py" for row in result["exemptionsApplied"])


def test_size_lint_exempts_distribution_and_vendor(tmp_path: Path) -> None:
    dist = tmp_path / "dist/cursor/scripts/planning/backends/huge.py"
    dist.parent.mkdir(parents=True)
    dist.write_text("\n".join("x = 1" for _ in range(MODULE_LINE_CAP + 50)), encoding="utf-8")
    vendor = tmp_path / "scripts/planning/_sw/vendor/huge.py"
    vendor.parent.mkdir(parents=True)
    vendor.write_text("\n".join("x = 1" for _ in range(MODULE_LINE_CAP + 50)), encoding="utf-8")
    result = size_lint_repo(tmp_path)
    assert result["verdict"] == "pass"
    assert classify_path(tmp_path, dist)["distribution"] is True
    assert classify_path(tmp_path, vendor)["vendored"] is True


def test_size_lint_honours_recorded_shim_exemption() -> None:
    shim = shim_exemption_for("scripts/planning_store.py")
    assert shim is not None
    assert shim["expiresWith"] == "compat-removal-milestone"
    info = classify_path(REPO_ROOT, REPO_ROOT / "scripts/planning_store.py")
    assert info["shimExemption"] is not None
    assert info["subjectToCap"] is False


def test_size_lint_fails_oversized_authored_package_module(tmp_path: Path) -> None:
    target = tmp_path / "scripts/planning/backends/oversized.py"
    target.parent.mkdir(parents=True)
    target.write_text("\n".join("x = 1" for _ in range(MODULE_LINE_CAP + 1)), encoding="utf-8")
    result = size_lint_repo(tmp_path)
    assert result["verdict"] == "fail"
    assert result["findings"][0]["path"] == "scripts/planning/backends/oversized.py"


def test_compat_matrix_rows_resolve_to_real_surface() -> None:
    result = validate_compat_matrix(REPO_ROOT)
    assert result["verdict"] == "pass", result
    assert result["rowCount"] > 0
    assert result["missing"] == []


def test_compat_matrix_documents_removal_condition() -> None:
    text = (REPO_ROOT / MATRIX_REL).read_text(encoding="utf-8")
    assert "zero-inventoried-imports-across-enforced-trees" in text
    assert "compat-removal-milestone" in text


def test_inventory_cli_surface_matches_matrix(tmp_path: Path) -> None:
    inventory = {
        "version": 1,
        "symbols": [{"name": "greet", "siteCount": 1}],
        "cli": {"subcommands": ["greet"], "flags": ["--root"]},
    }
    matrix = tmp_path / MATRIX_REL
    matrix.parent.mkdir(parents=True)
    matrix.write_text(
        """\
| Surface kind | Surface | Introduced phase | Supported through | Removal condition | Notes |
| --- | --- | --- | --- | --- | --- |
| symbol | `greet` | 10 | compat-removal | zero-inventor-imports | ok |
| cli-subcommand | `greet` | 14 | compat-removal | zero-inventor-imports | ok |
| cli-flag | `--root` | 14 | compat-removal | zero-inventor-imports | ok |
""",
        encoding="utf-8",
    )
    inv_path = tmp_path / "core/sw-reference/planning-import-inventory.json"
    inv_path.parent.mkdir(parents=True, exist_ok=True)
    inv_path.write_text(json.dumps(inventory), encoding="utf-8")
    result = validate_compat_matrix(tmp_path)
    assert result["verdict"] == "pass"
