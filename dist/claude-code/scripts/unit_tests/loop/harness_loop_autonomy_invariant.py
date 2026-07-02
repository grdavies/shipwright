#!/usr/bin/env python3
"""PRD 041 R27/R30/R31 loop auto-propose invariant fixtures."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from _fixture_lib import repo_root

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _fixture_lib import FixtureContext
import loop_autonomy as la
import sw_state_write_lib as writer


PY = _SCRIPTS_ROOT / "loop_autonomy.py"


def mk_repo(root: Path, cfg: dict) -> None:
    subprocess.run(["git", "init"], cwd=root, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    (root / ".cursor").mkdir(exist_ok=True)
    (root / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")


def run_py(root: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(PY), str(root), *args],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    ctx = FixtureContext(__file__)
    tmp = ctx.mktemp("loop-autonomy-")
    try:
        base_cfg = {
            "loop": {
                "autoPropose": {
                    "enabled": True,
                    "maxPerDay": 3,
                    "dedupWindow": 3600,
                    "cooldownMinutes": 0,
                    "maxOpenMetaUnits": 5,
                    "scheduler": "manual",
                }
            },
            "planning": {"autonomy": "full-conductor"},
        }
        mk_repo(tmp, base_cfg)

        ec, out = run_py(tmp, "check-dispatch", "--command", "/sw-deliver run foo")
        if ec == la.NESTED_DISPATCH_EXIT:
            ctx.ok("forbidden orchestrators fail closed")
        else:
            ctx.bad(f"expected nested dispatch exit, got {ec}")

        ec, _ = run_py(tmp, "check-dispatch", "--command", "bash -c /sw-prd --draft")
        if ec == la.WRAPPER_EXIT:
            ctx.ok("wrapper indirection fails closed")
        else:
            ctx.bad(f"expected wrapper exit, got {ec}")

        ec, _ = run_py(tmp, "check-dispatch", "--command", "doc.afterTasks:auto /sw-deliver")
        if ec == la.DOC_AFTER_TASKS_EXIT:
            ctx.ok("doc.afterTasks:auto forbidden")
        else:
            ctx.bad(f"expected doc.afterTasks exit, got {ec}")

        ec, out = run_py(
            tmp,
            "check-dispatch",
            "--command",
            "python3 scripts/planning_gap_capture.py capture --signal-id x",
        )
        if ec == 0:
            ctx.ok("closed allowlist accepts planning_gap_capture prefix")
        else:
            ctx.bad(f"allowlist gap_capture rejected: {out}")

        ec, out = run_py(tmp, "check-dispatch", "--command", "/sw-prd")
        if ec == la.NESTED_DISPATCH_EXIT:
            ctx.ok("/sw-prd without --draft rejected")
        else:
            ctx.bad("/sw-prd must be draft-only")

        ec, out = run_py(tmp, "evaluate", "--gap-class", "plugin-self", "--destination", "meta-shipwright")
        data = json.loads(out)
        ev = data.get("evaluation") or {}
        if ev.get("verdict") == "propose" and ev.get("eligibleAuto") is False:
            ctx.ok("meta propose-only under full-conductor")
        else:
            ctx.bad(f"meta should be propose-only: {ev}")

        ec, out = run_py(tmp, "propose", "--signal-id", "sig-1", "--title", "Test gap")
        if ec == 0:
            state = json.loads((tmp / ".cursor/hooks/state/loop-autonomy.json").read_text())
            handoff = state.get("handoffQueue") or []
            if not handoff:
                ctx.ok("proposal-only without handoff command")
            else:
                ctx.bad("unexpected handoff without command")
            if (state.get("proposalLog") or [])[-1].get("draftOnly") is True:
                ctx.ok("draftOnly proposal record")
            else:
                ctx.bad("missing draftOnly flag")
        else:
            ctx.bad(f"propose failed: {out}")

        ec, out = run_py(
            tmp,
            "enqueue-handoff",
            "--command",
            "python3 scripts/planning-graph.py reconcile --dry-run",
            "--reason",
            "test",
        )
        if ec == 0:
            state = json.loads((tmp / ".cursor/hooks/state/loop-autonomy.json").read_text())
            entry = (state.get("handoffQueue") or [])[-1]
            if entry.get("inert") and entry.get("requiresHumanAck") and entry.get("executed") is False:
                ctx.ok("handoffQueue inert until human ack")
            else:
                ctx.bad(f"handoff not inert: {entry}")
        else:
            ctx.bad(f"enqueue failed: {out}")

        runaway_root = ctx.mktemp("loop-runaway-")
        mk_repo(
            runaway_root,
            {
                **base_cfg,
                "loop": {
                    "autoPropose": {
                        **base_cfg["loop"]["autoPropose"],
                        "maxPerDay": 1,
                        "cooldownMinutes": 0,
                    }
                },
            },
        )
        run_py(runaway_root, "propose", "--signal-id", "a", "--title", "one")
        ec, out = run_py(runaway_root, "propose", "--signal-id", "b", "--title", "two")
        if ec == la.RUNAWAY_EXIT:
            ctx.ok("runaway containment maxPerDay")
        else:
            ctx.bad(f"expected runaway exit, got {ec}: {out}")
        shutil.rmtree(runaway_root, ignore_errors=True)

        sched_root = ctx.mktemp("loop-sched-")
        mk_repo(
            sched_root,
            {
                **base_cfg,
                "loop": {
                    "autoPropose": {
                        **base_cfg["loop"]["autoPropose"],
                        "scheduler": "scheduled",
                    }
                },
            },
        )
        ec, out = run_py(sched_root, "evaluate", "--scheduled")
        data = json.loads(out)
        if data.get("evaluation", {}).get("verdict") == "refuse":
            ctx.ok("scheduled runs maintenance-only under full-conductor")
        else:
            ctx.bad(f"scheduled refuse expected: {out}")
        shutil.rmtree(sched_root, ignore_errors=True)

        redact_root = ctx.mktemp("loop-redact-")
        mk_repo(redact_root, base_cfg)
        schema_dest = redact_root / "core/sw-reference"
        schema_dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ctx.root / "core/sw-reference/loop-health.schema.json", schema_dest / "loop-health.schema.json")
        payload = {
            "version": 1,
            "recordedAt": "2026-01-01T00:00:00Z",
            "diagnosticOnly": True,
            "gating": False,
            "metrics": {
                "reviewEffort": {"reviewRounds": 0, "stabilizeReentries": 0},
                "reworkDefect": {"reopenedPhases": 0, "postMergeReverts": 0},
                "incidents": {"status": "unknown"},
                "inboxRanking": [],
            },
            "note": "Bearer sk-live-abcdefghijklmnopqrstuvwxyz123456",
        }
        try:
            writer.write_from_text(redact_root, store="loop-health", text=json.dumps(payload))
            stored = (writer.resolve_store_path(redact_root, "loop-health")).read_text(encoding="utf-8")
            if "sk-live-" in stored:
                ctx.bad("secret landed on disk")
            else:
                ctx.ok("redaction fail-closed for loop-health store")
        except writer.StateWriteError:
            ctx.ok("redaction fail-closed for loop-health store")
        shutil.rmtree(redact_root, ignore_errors=True)
    finally:
        ctx.cleanup()
    return 1 if ctx.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
