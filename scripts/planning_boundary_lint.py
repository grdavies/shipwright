#!/usr/bin/env python3
"""Import-boundary lint for planning provider client modules (PRD 082 phase 15 / R27)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from _planning_pkg_loader import load_submodule

_boundary = load_submodule("providers._boundary")
ALLOWED_IMPORT_PREFIXES = _boundary.ALLOWED_IMPORT_PREFIXES
FORBIDDEN_CLIENT_MODULES = _boundary.FORBIDDEN_CLIENT_MODULES
provider_import_violations = _boundary.provider_import_violations

MATRIX_REL = Path("core/sw-reference/planning-compat-matrix.md")
INVENTORY_REL = Path("core/sw-reference/planning-import-inventory.json")
REQUIRED_PROVIDER_ADAPTERS = (
    "scripts/planning/providers/github.py",
    "scripts/planning/providers/gitlab.py",
    "scripts/planning/providers/jira.py",
    "scripts/planning/providers/linear.py",
)


def provider_extraction_complete(root: Path) -> bool:
    """Phase 13 provider adapter extraction is complete when all adapters are present."""
    return all((root / rel).is_file() for rel in REQUIRED_PROVIDER_ADAPTERS)


def lint_repo(root: Path) -> dict[str, object]:
    violations = provider_import_violations(root)
    extraction_complete = provider_extraction_complete(root)
    if violations:
        verdict = "fail" if extraction_complete else "warn"
        severity = "error" if extraction_complete else "warn"
    else:
        verdict = "pass"
        severity = "ok"
    return {
        "verdict": verdict,
        "severity": severity,
        "extractionComplete": extraction_complete,
        "violations": violations,
        "forbiddenModules": sorted(FORBIDDEN_CLIENT_MODULES),
        "allowedImportPrefixes": list(ALLOWED_IMPORT_PREFIXES),
    }


def parse_compat_matrix_rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.startswith("|") or line.startswith("| ---"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 5 or cells[0] in {"Surface kind", "Kind"}:
            continue
        rows.append(
            {
                "kind": cells[0],
                "surface": cells[1],
                "phase": cells[2],
                "supportedThrough": cells[3],
                "removalCondition": cells[4],
                "notes": cells[5] if len(cells) > 5 else "",
            }
        )
    return rows


def validate_compat_matrix(root: Path) -> dict[str, object]:
    matrix_path = root / MATRIX_REL
    inventory_path = root / INVENTORY_REL
    if not matrix_path.is_file():
        return {"verdict": "fail", "error": f"missing matrix: {MATRIX_REL.as_posix()}"}
    if not inventory_path.is_file():
        return {"verdict": "fail", "error": f"missing inventory: {INVENTORY_REL.as_posix()}"}

    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    symbols = {
        str(row.get("name") or "")
        for row in inventory.get("symbols", [])
        if isinstance(row, dict)
    }
    cli = inventory.get("cli", {})
    subcommands = set(cli.get("subcommands", [])) if isinstance(cli, dict) else set()
    flags = set(cli.get("flags", [])) if isinstance(cli, dict) else set()

    missing: list[str] = []
    rows = parse_compat_matrix_rows(matrix_path.read_text(encoding="utf-8"))
    for row in rows:
        kind = row["kind"].lower()
        surface = row["surface"].strip("`")
        if kind == "symbol":
            if surface not in symbols:
                missing.append(f"symbol:{surface}")
        elif kind == "cli-subcommand":
            if surface not in subcommands:
                missing.append(f"cli-subcommand:{surface}")
        elif kind == "cli-flag":
            if surface not in flags:
                missing.append(f"cli-flag:{surface}")
        elif kind == "shim":
            if "#" in surface:
                pyz_rel, module = surface.split("#", 1)
                pyz_path = root / pyz_rel
                module_file = module if module.endswith(".py") else f"{module}.py"
                if not pyz_path.is_file():
                    missing.append(f"shim:{surface}")
                else:
                    import zipfile

                    with zipfile.ZipFile(pyz_path) as zf:
                        if module_file not in zf.namelist():
                            missing.append(f"shim:{surface}")
            else:
                shim_path = root / surface
                if not shim_path.is_file():
                    missing.append(f"shim:{surface}")
        elif kind == "condition":
            continue
        else:
            missing.append(f"unknown-kind:{kind}:{surface}")

    return {
        "verdict": "pass" if not missing else "fail",
        "rowCount": len(rows),
        "missing": missing,
        "matrixPath": MATRIX_REL.as_posix(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lint planning provider import boundaries")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true", help="Exit non-zero on fail severity")
    parser.add_argument(
        "--validate-matrix",
        action="store_true",
        help="Validate planning-compat-matrix.md rows against the import inventory",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.validate_matrix:
        result = validate_compat_matrix(root)
        print(json.dumps(result, indent=2))
        if args.check and result.get("verdict") != "pass":
            return 20
        return 0

    result = lint_repo(root)
    print(json.dumps(result, indent=2))
    if args.check and result.get("verdict") == "fail":
        return 20
    return 0


if __name__ == "__main__":
    run_module_main(main)
