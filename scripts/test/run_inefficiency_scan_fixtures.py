#!/usr/bin/env python3
"""PRD 041 R25/R26 inefficiency scanner fixtures."""
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
import inefficiency_scan_lib as scan_lib
import planning_gap_capture as pgc


def seed_schemas(ctx: FixtureContext, root: Path) -> None:
    src = ctx.root / "core/sw-reference"
    dest = root / "core/sw-reference"
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("meta-inbox-draft.schema.json",):
        shutil.copy2(src / name, dest / name)


def git_init(ctx: FixtureContext, root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=root, check=True)


def main() -> int:
    ctx = FixtureContext(__file__)
    tmp = ctx.mktemp("inefficiency-scan-")
    try:
        git_init(ctx, tmp)
        seed_schemas(ctx, tmp)
        (tmp / ".cursor").mkdir(exist_ok=True)
        cfg = {
            "inefficiency": {
                "enabled": True,
                "thresholds": {"slowTestSeconds": 5, "slowCiJobSeconds": 10},
                "allowlist": {"manualSteps": ["git status"]},
            },
            "worktree": {"parallelCeiling": 4},
        }
        (tmp / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

        junit = tmp / "junit.xml"
        junit.write_text(
            """<?xml version=\"1.0\"?>
<testsuite><testcase name=\"slow_test\" time=\"12.5\"/></testsuite>""",
            encoding="utf-8",
        )
        (tmp / ".cursor/sw-ci-timing.json").write_text(
            json.dumps({"jobs": [{"name": "ci/integration", "durationSeconds": 120}]}),
            encoding="utf-8",
        )
        deliver_state = {
            "waveBatchingPlan": {
                "waves": [["1"], ["2"], ["3"]],
                "parallelCeiling": 4,
            },
            "benefitMetric": {"planPolicy": "canonical", "phaseWallClockMs": 1000},
        }
        (tmp / ".cursor/sw-deliver-state.json").write_text(json.dumps(deliver_state), encoding="utf-8")
        log_path = tmp / ".cursor/sw-deliver-runs/run.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            log_path.write_text(
                (log_path.read_text(encoding="utf-8") if log_path.is_file() else "")
                + json.dumps({"command": "manual deploy checklist"}) + "\n",
                encoding="utf-8",
            )

        result = scan_lib.scan(
            tmp,
            cfg=cfg,
            junit_path=junit,
            deliver_state_path=tmp / ".cursor/sw-deliver-state.json",
            run_log_path=log_path,
            draft_to_inbox=True,
        )
        classes = {i.get("class") for i in result.get("items") or []}
        required = {
            "long-single-threaded-test",
            "slow-ci-job",
            "serialized-but-parallelizable",
            "repeated-manual-step",
        }
        if required <= classes:
            ctx.ok("action-linked emission for all four detection classes")
        else:
            ctx.bad(f"missing classes: {required - classes}")

        for item in result.get("items") or []:
            if not item.get("action") or not item.get("nextStep"):
                ctx.bad(f"item missing action link: {item}")
                break
        else:
            ctx.ok("each item action-linked")

        if result.get("benefitMetricPresent"):
            ctx.ok("reuses benefitMetric from deliver run-state")
        else:
            ctx.bad("benefitMetric not detected")

        if result.get("drafted"):
            ctx.ok("items routed to meta inbox drafts")
        else:
            ctx.bad("no inbox drafts")

        # Graceful skip fixture
        tmp2 = ctx.mktemp("inefficiency-skip-")
        git_init(ctx, tmp2)
        seed_schemas(ctx, tmp2)
        (tmp2 / ".cursor").mkdir(exist_ok=True)
        (tmp2 / ".cursor/workflow.config.json").write_text(
            json.dumps({"inefficiency": {"enabled": True}}), encoding="utf-8"
        )
        skip = scan_lib.scan(tmp2, draft_to_inbox=False)
        if skip.get("notices") and not skip.get("items"):
            ctx.ok("graceful skip-with-notice when timing sources absent")
        else:
            ctx.bad(f"expected notices-only skip, got {skip}")

        disabled = scan_lib.scan(tmp2, cfg={"inefficiency": {"enabled": False}})
        if disabled.get("verdict") == "skipped":
            ctx.ok("disabled when inefficiency.enabled false")
        else:
            ctx.bad("disabled scanner should skip")
    finally:
        ctx.cleanup()
    return 1 if ctx.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
