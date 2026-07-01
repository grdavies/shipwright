#!/usr/bin/env python3
"""Suite registry drift fixtures (PRD 052 R5)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import repo_root

FAIL = 0


def ok(msg: str) -> None:
    print(f"OK  {msg}")


def bad(msg: str) -> None:
    global FAIL
    print(f"FAIL {msg}")
    FAIL = 1


def main() -> int:
    root = repo_root(__file__)
    sys.path.insert(0, str(root / "scripts"))
    import suite_registry as sr

    registry = sr.load_registry(root)
    lane_errors = sr.validate_lanes(registry)
    if lane_errors:
        for err in lane_errors:
            bad(f"registry-lanes: {err}")
    else:
        ok("registry-lanes: pr-ci rows have classification + ciJobName")

    disk = sr.disk_script_set(root)
    reg_fixture_scripts = {
        s
        for s in sr.registry_script_set(registry)
        if s.startswith("scripts/test/") and s.endswith("_fixtures.py")
    }
    missing_on_disk = reg_fixture_scripts - disk
    missing_in_registry = disk - sr.registry_script_set(registry)
    if missing_on_disk:
        bad(f"disk-registry-bijection: registry references missing scripts: {sorted(missing_on_disk)[:5]}")
    if missing_in_registry:
        bad(f"disk-registry-bijection: on-disk suites missing registry rows: {sorted(missing_in_registry)[:5]}")
    if not missing_on_disk and not missing_in_registry:
        ok("disk-registry-bijection: every run_*_fixtures.py has exactly one registry entry")

    manifest_path = root / "core/sw-reference/pr-test-plan.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_by_script = {row["script"]: row for row in manifest.get("fixtures") or []}
    projected = {row["script"]: row for row in sr.manifest_entries(root)}
    manifest_scripts = set(manifest_by_script)
    projected_scripts = set(projected)
    if manifest_scripts != projected_scripts:
        only_manifest = sorted(manifest_scripts - projected_scripts)
        only_registry = sorted(projected_scripts - manifest_scripts)
        if only_manifest:
            bad(f"manifest-pr-ci-subset: manifest-only scripts {only_manifest[:5]}")
        if only_registry:
            bad(f"manifest-pr-ci-subset: registry-only pr-ci scripts {only_registry[:5]}")
    else:
        mismatches = []
        for script, mf in manifest_by_script.items():
            reg = projected[script]
            for key in ("id", "classification", "ciJobName"):
                if mf.get(key) != reg.get(key):
                    mismatches.append(f"{script}:{key}")
        if mismatches:
            bad(f"manifest-pr-ci-subset: field drift {mismatches[:5]}")
        else:
            ok("manifest-pr-ci-subset: committed manifest matches registry pr-ci projection")

    workflow_path = root / ".github/workflows/pr-test-plan-ci.yml"
    generator = root / "scripts/generate-pr-test-plan-ci-workflow.py"
    with tempfile.NamedTemporaryFile(suffix=".yml", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(generator),
                str(manifest_path),
                str(tmp_path),
                str(root),
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            bad(f"workflow-generator: {proc.stderr.strip() or proc.stdout.strip()}")
        elif workflow_path.read_text(encoding="utf-8") != tmp_path.read_text(encoding="utf-8"):
            bad("workflow-generator: committed workflow drift — regen pr-test-plan-ci.yml")
        else:
            ok("workflow-generator: committed workflow matches generator output")
    finally:
        tmp_path.unlink(missing_ok=True)

    sys.path.insert(0, str(root / "scripts" / "test"))
    import run_verify_bundle as rvb

    expected = sr.verify_bundle_entries(root)
    current = rvb.suites_for_verify(root)
    if current != expected:
        bad("verify-order: verify bundle order differs from registry verify lane projection")
    else:
        ok("verify-order: verify bundle list matches registry verify lane projection")

    orphans = {
        "run_build_chain_sot_fixtures.py",
        "run_capability_fixtures.py",
        "run_fanout_fixtures.py",
        "run_guardrail_matrix_fixtures.py",
        "run_hook_fixtures.py",
        "run_relocation_fixtures.py",
    }
    verify_names = set(sr.verify_bundle_entries(root))
    missing_orphans = sorted(orphans - verify_names)
    if missing_orphans:
        bad(f"gap-075-orphans: missing verify lane for {missing_orphans}")
    else:
        ok("gap-075-orphans: six orphan suites registered in verify lane")

    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
