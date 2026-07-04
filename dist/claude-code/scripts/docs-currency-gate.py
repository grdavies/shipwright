#!/usr/bin/env python3
"""Hard-block when living-doc ledger drifts from durable deliver state for the current run (R50). """
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def _resolve_argv(argv: list[str]) -> list[str]:
    if len(argv) >= 3 and argv[1] == "--state-root":
        import sys as _sys
        _sys.stderr.write(
            "DEPRECATION: docs-currency-gate.py --state-root is deprecated; "
            "use four positional args (repo_root state_root state.json plan.json)\n"
        )
        state_root = Path(argv[2])
        state_path = state_root / ".cursor" / "sw-deliver-state.json"
        if not state_path.is_file():
            matches = sorted((state_root / ".cursor").glob("sw-deliver-state.*.json"))
            state_path = matches[0] if len(matches) == 1 else state_path
        plan_path = state_root / ".cursor" / "sw-deliver-plan.json"
        return [argv[0], str(state_root), str(state_root), str(state_path), str(plan_path)]
    return argv


def main(argv: list[str] | None = None) -> int:
    import json
    import re
    import sys
    from pathlib import Path

    raw_argv = list(argv if argv is not None else sys.argv)
    resolved = _resolve_argv(raw_argv)
    root = Path(resolved[1])
    state_root = Path(resolved[2])
    state = json.loads(Path(resolved[3]).read_text())
    plan = json.loads(Path(resolved[4]).read_text()) if Path(resolved[4]).is_file() else {}

    prd = str(state.get("prd_number") or plan.get("prd_number") or "").zfill(3)
    if not prd or prd == "000":
        print(json.dumps({"verdict": "fail", "error": "prd_number missing"}))
        sys.exit(2)

    phases = state.get("phases") or {}
    from wave_living_docs import derive_index_status
    from wave_state import phase_complete

    all_green = bool(phases) and all(phase_complete((m or {}).get("status")) for m in phases.values())
    merged_main = False
    try:
        import subprocess
        proc = subprocess.run(
            [sys.executable, str(root / "scripts" / "wave_compound.py"), str(state_root), "completion", "check-merge"],
            cwd=str(state_root),
            text=True,
            capture_output=True,
        )
        if proc.returncode == 0:
            merged_main = bool(json.loads(proc.stdout).get("merged"))
    except Exception:
        pass

    expected = derive_index_status(state, merged_main)

    index_path = root / "docs" / "prds" / "INDEX.md"
    index_status = None
    if index_path.is_file():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if not line.startswith("|") or line.startswith("| #") or line.startswith("|---"):
                continue
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 4 and parts[0].zfill(3) == prd:
                index_status = parts[4] if len(parts) >= 5 else parts[3]
                break

    drift = []
    if index_status is None:
        drift.append({"kind": "index-missing-row", "prd": prd})
    elif index_status != expected:
        drift.append({"kind": "index-status", "prd": prd, "expected": expected, "actual": index_status})

    # COMPLETION-LOG: when all phases green, expect an entry for this PRD
    log_path = root / "docs" / "prds" / "COMPLETION-LOG.md"
    if all_green and log_path.is_file():
        log_text = log_path.read_text(encoding="utf-8")
        if f"| {prd.lstrip('0')} |" not in log_text and f"| {prd} |" not in log_text:
            drift.append({"kind": "completion-log-missing", "prd": prd})

    # GAP-BACKLOG: unresolved rows for this PRD when it is complete (R3 / PRD 048)
    gap_path = root / "docs" / "prds" / "GAP-BACKLOG.md"
    if expected == "complete" and gap_path.is_file():
        from gap_backlog import parse_gap_backlog

        backlog = parse_gap_backlog(gap_path.read_text(encoding="utf-8"))
        prd_n = str(int(prd)) if prd.isdigit() else prd.lstrip("0") or prd
        sched_re = re.compile(
            rf"^PRD\s+0*{re.escape(str(int(prd_n))) if prd_n.isdigit() else re.escape(prd_n)}(?:\s+A\d+)?$",
            re.I,
        )
        for row in backlog.rows:
            st = row.status.lower()
            if st == "open" or (st == "scheduled" and sched_re.match(row.schedule.strip())):
                drift.append({"kind": "gap-still-open", "prd": prd, "row": row.gap_id})

    # GAP-BACKLOG index/table integrity (R54)
    import subprocess
    gb = subprocess.run(
        [sys.executable, str(root / "scripts" / "gap_backlog.py"), "--root", str(root), "check"],
        text=True,
        capture_output=True,
    )
    if gb.returncode != 0:
        try:
            payload = json.loads(gb.stdout or gb.stderr)
        except json.JSONDecodeError:
            payload = {"error": gb.stderr or gb.stdout}
        drift.append({"kind": "gap-backlog-integrity", "detail": payload})

    if drift:
        print(json.dumps({"verdict": "fail", "action": "docs-currency-gate", "prd": prd, "drift": drift}))
        sys.exit(1)

    print(json.dumps({"verdict": "pass", "action": "docs-currency-gate", "prd": prd, "indexStatus": index_status, "expected": expected}))
    return 0

if __name__ == "__main__":
    run_module_main(main)
