#!/usr/bin/env python3
"""PRD 041 R29 loop-health fixtures."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _fixture_lib import repo_root

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _fixture_lib import FixtureContext
import loop_health_lib as lh
import sw_state_write_lib as writer


def seed_schema(ctx: FixtureContext, root: Path) -> None:
    dest = root / "core/sw-reference"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ctx.root / "core/sw-reference/loop-health.schema.json", dest / "loop-health.schema.json")


def git_init(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=root, check=True)


def main() -> int:
    ctx = FixtureContext(__file__)
    tmp = ctx.mktemp("loop-health-")
    try:
        git_init(tmp)
        seed_schema(ctx, tmp)
        (tmp / ".cursor").mkdir(exist_ok=True)
        cfg = {"loopHealth": {"enabled": True, "staleInboxDays": 7}}
        (tmp / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

        deliver = {
            "reviewRounds": 3,
            "reopenedPhases": 2,
            "benefitMetric": {
                "stabilizeReentries": [{"step": "stabilize"}, {"step": "stabilize"}],
            },
        }
        deliver_path = tmp / ".cursor/sw-deliver-state.json"
        deliver_path.write_text(json.dumps(deliver), encoding="utf-8")

        inbox = tmp / ".cursor/sw-meta-inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
        (inbox / "sig-a.json").write_text(
            json.dumps(
                {
                    "signalId": "sig-a",
                    "destination": "meta-shipwright",
                    "gapClass": "plugin-self",
                    "title": "Flaky stabilize",
                    "status": "draft",
                    "capturedAt": old_ts,
                    "recurrence": 4,
                }
            ),
            encoding="utf-8",
        )
        (inbox / "sig-b.json").write_text(
            json.dumps(
                {
                    "signalId": "sig-b",
                    "destination": "meta-shipwright",
                    "gapClass": "plugin-self",
                    "title": "CI noise",
                    "status": "draft",
                    "capturedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "recurrence": 2,
                }
            ),
            encoding="utf-8",
        )

        result = lh.aggregate(tmp, cfg=cfg, deliver_state_path=deliver_path, persist=True)
        if result.get("verdict") != "ok":
            ctx.bad(f"aggregate failed: {result}")
        else:
            ctx.ok("aggregation persisted")

        record = result["record"]
        metrics = record["metrics"]
        review = metrics["reviewEffort"]
        if review["reviewRounds"] == 3 and review["stabilizeReentries"] == 2:
            ctx.ok("review effort from deliver state and benefitMetric")
        else:
            ctx.bad(f"review effort mismatch: {review}")

        if metrics["incidents"].get("status") == "unknown":
            ctx.ok("unknown incidents when no host/json source")
        else:
            ctx.bad(f"expected unknown incidents, got {metrics['incidents']}")

        ranking = metrics.get("inboxRanking") or []
        if len(ranking) >= 2 and ranking[0]["signalId"] == "sig-a" and ranking[0]["score"] >= ranking[1]["score"]:
            ctx.ok("inbox ranked by recurrence x reviewRounds")
        else:
            ctx.bad(f"inbox ranking unexpected: {ranking}")

        if record.get("gating") is False and record.get("diagnosticOnly") is True:
            ctx.ok("no gating; diagnostic-only record")
        else:
            ctx.bad("gating/diagnosticOnly flags wrong")

        summary = lh.surface_summary(record)
        if summary.get("gating") is False and summary.get("topInbox") and "Incidents: unknown" in summary.get("message", ""):
            ctx.ok("retrospective surface_summary")
        else:
            ctx.bad(f"surface_summary incomplete: {summary}")

        store_path = writer.resolve_store_path(tmp, "loop-health")
        if store_path.is_file():
            ctx.ok("loop-health store written via sw_state_write_lib")
        else:
            ctx.bad("store path missing")

        known_tmp = ctx.mktemp("loop-health-known-")
        git_init(known_tmp)
        seed_schema(ctx, known_tmp)
        (known_tmp / ".cursor").mkdir(exist_ok=True)
        (known_tmp / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
        (known_tmp / ".cursor/sw-post-merge-incidents.json").write_text(
            json.dumps({"count": 1, "items": [{"id": "rev-1", "kind": "revert"}]}),
            encoding="utf-8",
        )
        inc = lh.load_incidents(known_tmp)
        if inc.get("status") == "known" and inc.get("count") == 1:
            ctx.ok("known incidents from sw-post-merge-incidents.json")
        else:
            ctx.bad(f"known incidents failed: {inc}")
        shutil.rmtree(known_tmp, ignore_errors=True)
    finally:
        ctx.cleanup()
    return 1 if ctx.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
