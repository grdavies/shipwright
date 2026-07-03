#!/usr/bin/env python3
"""PRD 041 R28 behavioral-anomaly guardrails fixtures."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _fixture_lib import FixtureContext
import behavioral_anomaly_check_lib as bac
import verify_evidence_lib as vel


def seed_schemas(ctx: FixtureContext, root: Path) -> None:
    src = ctx.root / "core/sw-reference"
    dest = root / "core/sw-reference"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("failure-signature.schema.json", "meta-inbox-draft.schema.json"):
        if (src / name).is_file():
            shutil.copy2(src / name, dest / name)


def git_init(ctx: FixtureContext, root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init", "--allow-empty"], cwd=root, capture_output=True, check=True)


def main() -> int:
    ctx = FixtureContext(__file__)
    tmp = ctx.mktemp("behavioral-anomaly-")
    try:
        git_init(ctx, tmp)
        seed_schemas(ctx, tmp)
        tasks = tmp / "tasks.md"
        tasks.write_text(
            "# Tasks\n\n- **File:** `scripts/foo.py`\n\n## Relevant Files\n\n- `docs/guide.md`\n",
            encoding="utf-8",
        )
        (tmp / "scripts").mkdir(exist_ok=True)
        (tmp / "scripts/foo.py").write_text("# ok\n", encoding="utf-8")
        (tmp / "rogue.py").write_text("# rogue\n", encoding="utf-8")
        subprocess.run(["git", "add", "scripts/foo.py"], cwd=tmp, capture_output=True, check=True)

        baseline = tmp / ".shipwright/pre-agent-diff-baseline.json"
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text(json.dumps({"paths": ["scripts/foo.py"]}), encoding="utf-8")

        res = bac.check(tmp, tasks_path=tasks, baseline_path=baseline)
        classes = {a.get("class") for a in res.get("anomalies") or []}
        if "unauthorized-create" in classes:
            ctx.ok("unauthorized create outside declared scope")
        else:
            ctx.bad(f"missing unauthorized-create: {res}")

        (tmp / "docs").mkdir(exist_ok=True)
        (tmp / "docs/other.md").write_text("# other\n", encoding="utf-8")
        subprocess.run(["git", "add", "docs/other.md"], cwd=tmp, capture_output=True, check=True)
        subprocess.run(["git", "commit", "-m", "track other"], cwd=tmp, capture_output=True, check=True)
        (tmp / "docs/other.md").unlink()
        res_del = bac.check(tmp, tasks_path=tasks, baseline_path=baseline, record_signatures=False)
        if any(a.get("class") == "unauthorized-delete" for a in res_del.get("anomalies") or []):
            ctx.ok("unauthorized delete outside declared scope")
        else:
            ctx.bad("missing unauthorized-delete")

        run_dir = tmp / ".cursor/sw-tmp-run"
        run_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(run_dir, 0o700)
        verify_path = run_dir / "sw-verify.status.json"
        verify_path.write_text(
            json.dumps({"exitCode": 0, "status": "pass", "commands": [{"name": "test", "exitCode": 1, "status": "fail"}]}),
            encoding="utf-8",
        )
        os.chmod(verify_path, 0o600)
        false_res = bac.check(tmp, verify_status_path=verify_path, record_signatures=False)
        if any(a.get("class") == "false-success" for a in false_res.get("anomalies") or []):
            ctx.ok("false success when sub-command failed")
        else:
            ctx.bad("missing false-success")

        marker = tmp / ".shipwright/rollback-attempted"
        marker.write_text("1\n", encoding="utf-8")
        (tmp / "dirty.txt").write_text("x\n", encoding="utf-8")
        rollback_res = bac.check(tmp, rollback_marker_path=marker, record_signatures=False)
        if any(a.get("class") == "failed-rollback" for a in rollback_res.get("anomalies") or []):
            ctx.ok("failed rollback leaves dirty tree")
        else:
            ctx.bad("missing failed-rollback")

        steps = tmp / "ship-steps.json"
        steps.write_text(
            json.dumps({"steps": [{"id": "gap-check", "status": "skipped"}]}),
            encoding="utf-8",
        )
        skip_res = bac.check(tmp, ship_steps_path=steps, record_signatures=False)
        if any(a.get("class") == "silent-skip" for a in skip_res.get("anomalies") or []):
            ctx.ok("silent skip without recorded reason")
        else:
            ctx.bad("missing silent-skip")

        bad_verify = run_dir / "bad-verify.status.json"
        bad_verify.write_text("{not-json", encoding="utf-8")
        os.chmod(bad_verify, 0o777)
        integrity_res = bac.check(tmp, verify_status_path=bad_verify, record_signatures=False)
        if integrity_res.get("evidenceIntegrityMismatch"):
            ctx.ok("evidence-integrity mismatch detected")
        else:
            ctx.bad("missing evidence integrity mismatch")

        base_verdict = {"verdict": "verified", "reason": "ok", "evidence": {}}
        overlay = bac.apply_verification_overlay(base_verdict, integrity_res)
        if overlay.get("verdict") == "inconclusive" and overlay.get("inconclusiveClass") == "missing-required":
            ctx.ok("verification-gate overlay promotes integrity mismatch to blocking inconclusive")
        else:
            ctx.bad(f"overlay unexpected: {overlay}")

        promoted, code = vel.compute_and_record(
            tmp,
            verify_path=verify_path,
            behavioral_status_path=None,
        )
        if isinstance(promoted, dict):
            ctx.ok("verification-gate composition with behavioral overlay path")
        else:
            ctx.bad("verify composition failed")
    finally:
        ctx.cleanup()
    return 1 if ctx.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
