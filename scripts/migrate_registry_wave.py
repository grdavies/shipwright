#!/usr/bin/env python3
"""Apply pytest migration registry updates for a migration wave (PRD 054 TR12)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import suite_registry as sr

MIGRATION_WAVES_REL = Path("core/sw-reference/migration-waves.json")
RUN_PYTEST_SCRIPT = "scripts/test/run_pytest.py"
MANIFEST_REL = Path("core/sw-reference/pr-test-plan.manifest.json")
WORKFLOW_REL = Path(".github/workflows/pr-test-plan-ci.yml")
WORKFLOW_GEN = Path("scripts/generate-pr-test-plan-ci-workflow.py")


def load_wave_suites(root: Path, wave: str) -> list[dict[str, Any]]:
    data = json.loads((root / MIGRATION_WAVES_REL).read_text(encoding="utf-8"))
    suites = (data.get("waves") or {}).get(wave, {}).get("suites") or []
    if not suites:
        raise SystemExit(f"wave {wave!r} has no suites")
    return suites


def apply_registry_wave(root: Path, wave: str) -> list[str]:
    """Update suite-registry rows for wave inventory. Returns legacy paths to delete."""
    registry = sr.load_registry(root)
    by_id = {row["id"]: row for row in registry.get("suites") or []}
    legacy_paths: list[str] = []
    for suite in load_wave_suites(root, wave):
        entry = by_id.get(suite["id"])
        if entry is None:
            raise SystemExit(f"registry missing suite id {suite['id']!r}")
        entry["pytestPath"] = suite["pytestPath"]
        entry["script"] = RUN_PYTEST_SCRIPT
        legacy_paths.append(suite["legacy"])
    registry["suites"] = list(by_id.values())
    registry_path = root / sr.REGISTRY_REL
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")
    return legacy_paths


def regen_manifest_and_workflow(root: Path) -> None:
    manifest_path = root / MANIFEST_REL
    manifest = sr.regen_manifest_preserving_scenarios(root)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(root / WORKFLOW_GEN),
            str(manifest_path),
            str(root / WORKFLOW_REL),
            str(root),
        ],
        cwd=str(root),
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit("workflow generator failed")


def delete_legacy_scripts(root: Path, legacy_paths: list[str]) -> None:
    for rel in legacy_paths:
        path = root / rel
        if path.is_file():
            path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate suite-registry + manifest for a pytest wave.")
    parser.add_argument("wave", choices=["W1", "W2", "W3"])
    parser.add_argument("--delete-legacy", action="store_true", help="Remove legacy run_*_fixtures.py files")
    args = parser.parse_args(argv)
    root = sr.repo_root()
    legacy_paths = apply_registry_wave(root, args.wave)
    regen_manifest_and_workflow(root)
    if args.delete_legacy:
        delete_legacy_scripts(root, legacy_paths)
    print(f"Applied {args.wave} registry migration ({len(legacy_paths)} suites)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
