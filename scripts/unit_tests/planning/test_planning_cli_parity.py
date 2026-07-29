"""CLI-parity fixtures for planning_store shim vs package CLI (PRD 082 phase 14 / R27)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from planning_import_inventory import build_inventory  # noqa: E402

SHIM_PATH = REPO_ROOT / "scripts" / "planning_store.py"
CLI_PATH = REPO_ROOT / "scripts" / "planning" / "cli.py"


def _run_module(path: Path, argv: list[str], *, repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(path), *argv],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )


def _inventory_subcommands() -> list[str]:
    inventory = build_inventory(REPO_ROOT)
    cli = inventory.get("cli") or {}
    subcommands = cli.get("subcommands") or []
    return sorted({str(name) for name in subcommands})


@pytest.mark.parametrize(
    "argv",
    [
        ["list-backends"],
        ["list-facade"],
        ["resolve-backend"],
        ["operator-projection-contract"],
        ["linear-projection-schema"],
        ["comments-relations-schema"],
        ["issues-provider-registration"],
    ],
)
def test_shim_and_package_cli_parity(argv: list[str]) -> None:
    shim_run = _run_module(SHIM_PATH, argv, repo_root=REPO_ROOT)
    cli_run = _run_module(CLI_PATH, argv, repo_root=REPO_ROOT)
    assert shim_run.returncode == cli_run.returncode
    assert shim_run.stdout == cli_run.stdout
    assert shim_run.stderr == cli_run.stderr


def test_inventoried_subcommands_covered_by_fixture_set() -> None:
    inventoried = set(_inventory_subcommands())
    # Schema/help-only commands exercised by parametrized fixtures above.
    exercised = {
        "list-backends",
        "list-facade",
        "resolve-backend",
        "operator-projection-contract",
        "linear-projection-schema",
        "comments-relations-schema",
        "issues-provider-registration",
    }
    assert exercised.issubset(inventoried)
