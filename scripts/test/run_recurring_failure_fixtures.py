#!/usr/bin/env python3
"""PRD 041 R22 recurring failure signature fixtures."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import FixtureContext

def seed_schemas(ctx: FixtureContext, root: Path) -> None:
    src = ctx.root / "core/sw-reference"
    dest = root / "core/sw-reference"
    dest.mkdir(parents=True, exist_ok=True)
    for name in (
        "meta-inbox-draft.schema.json",
        "failure-signature.schema.json",
        "root-cause-record.schema.json",
    ):
        shutil.copy2(src / name, dest / name)

import failure_signature_record_lib as fsr
import sw_state_write_lib as writer
import failure_signature_escalate_lib as fse


def git_init(ctx: FixtureContext, root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=root, check=True)


def load_store(root: Path) -> dict:
    path = writer.resolve_store_path(root, "failure-signatures")
    if not path.is_file():
        return {"version": 1, "records": []}
    return json.loads(path.read_text(encoding="utf-8"))


def run_escalation_fixtures(ctx: FixtureContext) -> None:
    threshold = 2
    esc_tmp = ctx.mktemp("recurring-escalate-")
    git_init(ctx, esc_tmp)
    seed_schemas(ctx, esc_tmp)
    shutil.copy2(
        ctx.root / "core/sw-reference/anomaly-patterns.json",
        esc_tmp / "core/sw-reference/anomaly-patterns.json",
    )
    (esc_tmp / ".cursor").mkdir(exist_ok=True)
    (esc_tmp / ".cursor/workflow.config.json").write_text(
        json.dumps({"recurrence": {"threshold": threshold, "enabled": True}}),
        encoding="utf-8",
    )
    msg = "ci flake timeout false-green claimed pass without evidence"
    for run_id in ("run-a", "run-b", "run-c"):
        fsr.record_from_surface(
            esc_tmp,
            "fixture",
            check_id="ci/flaky-test",
            exit_code=1,
            job_id="job-esc",
            message=msg,
            run_id=run_id,
        )
    escalated = fse.scan_and_escalate(
        esc_tmp,
        {"recurrence": {"threshold": threshold, "enabled": True}},
        failure_text=msg,
    )
    if len(escalated) == 1 and escalated[0].get("status") == "escalated":
        ctx.ok("threshold escalation creates root-cause record")
    else:
        ctx.bad(f"expected one escalation, got {escalated}")
        return
    rec = escalated[0]
    if rec.get("signatureClass") == "flake" and rec.get("loopClosed") is False:
        ctx.ok("flake signatureClass requires waiver before loop-close")
    else:
        ctx.bad(f"flake policy unexpected: {rec.get('signatureClass')} loopClosed={rec.get('loopClosed')}")
    patterns = rec.get("anomalyPatterns") or []
    if any(p.get("patternId") == "false-green" and p.get("autoAct") is False for p in patterns):
        ctx.ok("catalog false-green annotates without auto-act")
    else:
        ctx.bad(f"false-green annotation missing: {patterns}")
    fse.acknowledge_flake_waiver(esc_tmp, rec["id"], acknowledged_by="fixture-human")
    closed = fse.load_root_cause_store(esc_tmp)
    updated = next(r for r in closed["records"] if r["id"] == rec["id"])
    if updated.get("loopClosed") is True:
        ctx.ok("flake waiver closes remediation loop")
    else:
        ctx.bad("flake waiver did not close loop")
    tamper_ann = fse.recognize_anomaly_patterns(esc_tmp, "test tampering rewrite", prd_a_flags=[])
    if not any(p.get("patternId") == "test-tampering" for p in tamper_ann):
        ctx.ok("test-tamper absent without PRD A flags")
    else:
        ctx.bad("test-tamper annotated without PRD A flags")
    with_flag = fse.recognize_anomaly_patterns(esc_tmp, "failure", prd_a_flags=["test-tamper-detected"])
    if any(p.get("patternId") == "test-tampering" for p in with_flag):
        ctx.ok("test-tamper annotates only when PRD A flags exist")
    else:
        ctx.bad("test-tamper missing when PRD A flag present")


def main() -> int:
    ctx = FixtureContext(__file__)
    tmp = ctx.mktemp("recurring-failure-")
    try:
        git_init(ctx, tmp)
        seed_schemas(ctx, tmp)

        a = "failed at /tmp/foo/bar line 42 uuid 550e8400-e29b-41d4-a716-446655440000"
        b = "failed at /var/folders/zz/tmp line 99 uuid 550e8400-e29b-41d4-a716-446655440000"
        if fsr.normalize_message(a) == fsr.normalize_message(b):
            ctx.ok("normalization matrix: paraphrase paths/lines match")
        else:
            ctx.bad(f"normalization mismatch: {fsr.normalize_message(a)!r} vs {fsr.normalize_message(b)!r}")

        unrelated_a = fsr.signature_key("ci/test", 1, "job-a", fsr.normalize_message("error a"))
        unrelated_b = fsr.signature_key("ci/lint", 1, "job-a", fsr.normalize_message("error a"))
        if unrelated_a != unrelated_b:
            ctx.ok("unrelated checkId produces distinct keys")
        else:
            ctx.bad("unrelated checks collided")

        fsr.record_from_surface(
            tmp,
            "fixture",
            check_id="ci/test",
            exit_code=1,
            job_id="job-shared",
            message=a,
            run_id="run-1",
        )
        fsr.record_from_surface(
            tmp,
            "fixture",
            check_id="ci/test",
            exit_code=1,
            job_id="job-shared",
            message=b,
            run_id="run-2",
        )
        doc = load_store(tmp)
        records = doc.get("records") or []
        matching = [
            r
            for r in records
            if r.get("key", {}).get("jobId") == "job-shared"
            and r.get("key", {}).get("checkId") == "ci/test"
        ]
        if len(matching) == 1 and matching[0].get("count", 0) >= 2 and len(matching[0].get("runs") or []) >= 2:
            ctx.ok("varied-message same job no split + cross-run increment")
        else:
            ctx.bad(f"expected single upserted record, got {records}")

        fsr.record_from_surface(
            tmp,
            "fixture",
            check_id="ci/lint",
            exit_code=1,
            job_id="job-other",
            message="unrelated lint failure",
            run_id="run-x",
        )
        doc2 = load_store(tmp)
        keys = {writer.key_token(r["key"]) for r in doc2.get("records") or []}
        if len(keys) >= 2:
            ctx.ok("unrelated failures do not collide")
        else:
            ctx.bad("unrelated failures collided in store")

        run_escalation_fixtures(ctx)
    finally:
        ctx.cleanup()
    return 1 if ctx.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
