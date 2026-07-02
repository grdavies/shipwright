#!/usr/bin/env python3
"""Suite registry drift checks (PRD 052 R5, ported for pytest)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import suite_registry as sr


def run_suite_registry_check(root: Path | None = None) -> tuple[int, list[str]]:
    """Return (exit_code, lines) mirroring legacy fixture suite output."""
    root = root or sr.repo_root()
    lines: list[str] = []
    fail = 0

    def ok(msg: str) -> None:
        lines.append(f"OK  {msg}")

    def bad(msg: str) -> None:
        nonlocal fail
        lines.append(f"FAIL {msg}")
        fail = 1

    registry = sr.load_registry(root)
    lane_errors = sr.validate_lanes(registry)
    if lane_errors:
        for err in lane_errors:
            bad(f"registry-lanes: {err}")
    else:
        ok("registry-lanes: pr-ci rows have classification + ciJobName")

    disk = sr.disk_script_set(root)
    reg_fixture_scripts = sr.registry_legacy_fixture_set(registry)
    missing_on_disk = reg_fixture_scripts - disk
    missing_in_registry = disk - reg_fixture_scripts
    if missing_on_disk:
        bad(f"disk-registry-bijection: registry references missing scripts: {sorted(missing_on_disk)[:5]}")
    if missing_in_registry:
        bad(f"disk-registry-bijection: on-disk suites missing registry rows: {sorted(missing_in_registry)[:5]}")
    if not missing_on_disk and not missing_in_registry:
        ok("disk-registry-bijection: every run_*_fixtures.py has exactly one registry entry")

    manifest_path = root / "core/sw-reference/pr-test-plan.manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_by_id = {row["id"]: row for row in manifest.get("fixtures") or []}
    projected_by_id = {row["id"]: row for row in sr.manifest_entries(root)}
    manifest_ids = set(manifest_by_id)
    projected_ids = set(projected_by_id)
    if manifest_ids != projected_ids:
        only_manifest = sorted(manifest_ids - projected_ids)
        only_registry = sorted(projected_ids - manifest_ids)
        if only_manifest:
            bad(f"manifest-pr-ci-subset: manifest-only ids {only_manifest[:5]}")
        if only_registry:
            bad(f"manifest-pr-ci-subset: registry-only pr-ci ids {only_registry[:5]}")
    else:
        mismatches = []
        for suite_id, mf in manifest_by_id.items():
            reg = projected_by_id[suite_id]
            for key in ("script", "args", "classification", "ciJobName"):
                if mf.get(key) != reg.get(key):
                    mismatches.append(f"{suite_id}:{key}")
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

    orphan_ids = {
        "build-chain-sot-fixtures",
        "capability-fixtures",
        "fanout-fixtures",
        "guardrail-matrix-fixtures",
        "hook-fixtures",
        "relocation-fixtures",
    }
    verify_ids = set(sr.verify_bundle_entries(root))
    missing_orphans = sorted(orphan_ids - verify_ids)
    if missing_orphans:
        bad(f"gap-075-orphans: missing verify lane for {missing_orphans}")
    else:
        ok("gap-075-orphans: six orphan suites registered in verify lane")

    contributing_path = root / "CONTRIBUTING.md"
    contributing_text = contributing_path.read_text(encoding="utf-8")
    contributing_scripts: set[str] = set()
    for match in re.findall(r"python3 scripts/test/(run_\w+_fixtures\.py)", contributing_text):
        contributing_scripts.add(f"scripts/test/{match}")
    for match in re.findall(
        r"python3 scripts/test/run_pytest\.py (scripts/unit_tests/\S+)",
        contributing_text,
    ):
        contributing_scripts.add(match)
    doc_lane = set(sr.doc_lane_entries(root))
    only_contributing = sorted(contributing_scripts - doc_lane)
    only_doc_lane = sorted(doc_lane - contributing_scripts)
    if only_contributing or only_doc_lane:
        if only_contributing:
            bad(f"contributing-doc-lane: CONTRIBUTING-only scripts {only_contributing[:5]}")
        if only_doc_lane:
            bad(f"contributing-doc-lane: registry doc lane only {only_doc_lane[:5]}")
    else:
        ok("contributing-doc-lane: CONTRIBUTING fixture list matches registry doc lane")

    return (1 if fail else 0), lines


def main() -> int:
    code, lines = run_suite_registry_check()
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
