#!/usr/bin/env python3
"""Deliver phase acceptance + gap-check fixtures (PRD 055 R11-R15, R25)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from _sw.vendor_paths import repo_root


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ok(name: str) -> None:
    print(f"OK  {name}")


def bad(name: str, detail: str = "") -> None:
    print(f"FAIL {name}")
    if detail:
        print(detail)


def main(argv: list[str] | None = None) -> int:
    root = repo_root(__file__)
    fail = 0
    loop_py = root / "scripts" / "wave_deliver_loop.py"
    gap_gate = root / "scripts" / "gap-check-gate.py"
    ship_status = root / "scripts" / "ship-phase-status.py"
    phase_gate = root / "scripts" / "phase_acceptance_gate.py"

    with tempfile.TemporaryDirectory() as tmp:
        fix = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=fix, check=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=fix, check=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=fix, check=True)
        subprocess.run(["git", "commit", "--allow-empty", "-q", "-m", "init"], cwd=fix, check=True)
        subprocess.run(["git", "branch", "-M", "main"], cwd=fix, check=True)
        (fix / ".cursor").mkdir(parents=True, exist_ok=True)

        tasks_rel = "docs/prds/099-test/tasks-099-test.md"
        (fix / "docs/prds/099-test").mkdir(parents=True, exist_ok=True)
        (fix / tasks_rel).write_text(
            """---
frozen: true
topic: acceptance-test
---
### 3. Deliver phase acceptance gates

- [ ] 3.1 Implement phase_acceptance_gate
  - **File:** `scripts/phase_acceptance_gate.py`
- [ ] 3.2 Wire acceptance gate
  - **File:** `scripts/wave_deliver_loop.py`
- [ ] 3.3 Harden wave_state ledger check
  - **File:** `scripts/wave_state.py`
""",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=fix, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "tasks"], cwd=fix, check=True)

        phase_slug = "deliver-phase-acceptance-gates"
        phase_head = subprocess.run(
            ["git", "-C", str(fix), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        subprocess.run(
            ["git", "-C", str(fix), "branch", f"feat/demo-phase-{phase_slug}", phase_head],
            check=True,
        )

        state = {
            "verdict": "running",
            "target": {"type": "feat", "slug": "demo", "branch": "feat/demo"},
            "source_task_list": tasks_rel,
            "currentWave": 1,
            "driverHeartbeatAt": utc_now(),
            "orchestratorWorktree": {"path": str(fix)},
            "specSeed": {"skipped": True},
            "baseCapture": {"skipped": True},
            "phases": {
                "3": {
                    "id": "3",
                    "slug": phase_slug,
                    "status": "in-flight",
                    "branch": f"feat/demo-phase-{phase_slug}",
                    "startedAt": utc_now(),
                }
            },
            "phaseWorktrees": {"3": {"path": str(fix), "name": "phase-wt"}},
            "taskLedger": {"tasks": {}, "phases": {}},
        }
        (fix / ".cursor/sw-deliver-state.json").write_text(
            json.dumps(state), encoding="utf-8"
        )
        plan = {
            "source_task_list": tasks_rel,
            "items": [{"id": "3", "slug": phase_slug}],
            "waves": [["3"]],
        }
        (fix / ".cursor/sw-deliver-plan.json").write_text(json.dumps(plan), encoding="utf-8")

        status_dir = fix / ".cursor/sw-deliver-runs" / phase_slug
        status_dir.mkdir(parents=True, exist_ok=True)
        status_doc = {
            "verdict": "merge-ready-green",
            "phase": phase_slug,
            "phaseMode": True,
            "head": phase_head,
            "updatedAt": utc_now(),
        }
        (status_dir / "status.json").write_text(json.dumps(status_doc), encoding="utf-8")
        (status_dir / "gap-check.status.json").write_text(
            json.dumps({"verdict": "pass", "binding": True, "updatedAt": utc_now()}),
            encoding="utf-8",
        )

        sys.path.insert(0, str(root / "scripts"))
        from phase_acceptance_gate import check_phase_acceptance

        accepted, cause = check_phase_acceptance(fix, state, plan, "3", phase_slug)
        if not accepted and cause:
            ok("deliver-phase-blocked-open-subtasks")
        else:
            bad("deliver-phase-blocked-open-subtasks", f"accepted={accepted} cause={cause}")
            fail += 1

        import importlib.util
        spec = importlib.util.spec_from_file_location("wave_deliver_loop", loop_py)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        gate_ok, gate_cause = mod.phase_acceptance_ok(fix, state, plan, "3", phase_slug)
        if not gate_ok:
            ok("deliver-phase-blocked-open-subtasks-via-loop-helper")
        else:
            bad("deliver-phase-blocked-open-subtasks-via-loop-helper", str(gate_cause))
            fail += 1

        repo_gap_dir = root / ".cursor" / "sw-deliver-runs" / phase_slug
        repo_gap_dir.mkdir(parents=True, exist_ok=True)
        repo_gap_path = repo_gap_dir / "gap-check.status.json"
        repo_gap_path.write_text(
            json.dumps({"verdict": "halt", "binding": True, "cause": "partial"}),
            encoding="utf-8",
        )
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    str(ship_status),
                    "--verdict",
                    "merge-ready-green",
                    "--phase",
                    phase_slug,
                    "--head",
                    phase_head,
                    "--out",
                    str(repo_gap_dir / "blocked-status.json"),
                ],
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                ok("gap-check-gate-blocks-merge-ready")
            else:
                bad("gap-check-gate-blocks-merge-ready", proc.stdout + proc.stderr)
                fail += 1
        finally:
            if repo_gap_path.is_file():
                repo_gap_path.unlink()
            blocked = repo_gap_dir / "blocked-status.json"
            if blocked.is_file():
                blocked.unlink()

        proc = subprocess.run(
            [
                sys.executable,
                str(gap_gate),
                "check",
                str(fix),
                "--phase-slug",
                phase_slug,
                "--deliver-merge",
                "--fast",
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 2 and "deliver-gap-check-no-fast-skip" in (proc.stdout + proc.stderr):
            ok("deliver-gap-check-no-fast-skip")
        else:
            bad("deliver-gap-check-no-fast-skip", f"ec={proc.returncode} {proc.stdout} {proc.stderr}")
            fail += 1

    if fail:
        print(f"deliver fixtures: {fail} failure(s)")
        return 1
    print("deliver fixtures: all passed")
    return 0


if __name__ == "__main__":
    run_module_main(main)
