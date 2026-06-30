#!/usr/bin/env bash
# Hard-block when living-doc ledger drifts from durable deliver state for the current run (R50).
#
# Usage:
#   docs-currency-gate.sh [--state-root PATH]
#
# Exit: 0 pass; 1 drift (hard block); 2 usage/config error
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_ROOT="$ROOT"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --state-root) STATE_ROOT="${2:-}"; shift 2 ;;
    -h|--help)
      sed -n '2,6p' "$0"
      exit 0
      ;;
    *) echo '{"verdict":"fail","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done

STATE_JSON="$(python3 "$ROOT/scripts/wave_state.py" "$STATE_ROOT" resolve state-path 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('path',''))")"
if [[ -z "$STATE_JSON" || ! -f "$STATE_JSON" ]]; then
  STATE_JSON="$STATE_ROOT/.cursor/sw-deliver-state.json"  # legacy repo-wide fallback when resolve has no scoped file
fi
PLAN_JSON="$STATE_ROOT/.cursor/sw-deliver-plan.json"
if [[ ! -f "$STATE_JSON" ]]; then
  echo '{"verdict":"fail","error":"no deliver state"}' >&2
  exit 2
fi

python3 - "$ROOT" "$STATE_ROOT" "$STATE_JSON" "$PLAN_JSON" <<'PY'
import json
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
state_root = Path(sys.argv[2])
state = json.loads(Path(sys.argv[3]).read_text())
plan = json.loads(Path(sys.argv[4]).read_text()) if Path(sys.argv[4]).is_file() else {}

prd = str(state.get("prd_number") or plan.get("prd_number") or "").zfill(3)
if not prd or prd == "000":
    print(json.dumps({"verdict": "fail", "error": "prd_number missing"}))
    sys.exit(2)

phases = state.get("phases") or {}
all_green = bool(phases) and all(
    (m or {}).get("status") == "green-merged" for m in phases.values()
)
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

if merged_main:
    expected = "complete"
elif any((m or {}).get("status") not in ("pending",) for m in phases.values()):
    expected = "in-progress"
else:
    expected = "not-started"

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

# GAP-BACKLOG: open rows absorbed-by this PRD when it is complete
gap_path = root / "docs" / "prds" / "GAP-BACKLOG.md"
if expected == "complete" and gap_path.is_file():
    for line in gap_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("| Date") or line.startswith("|---"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 5:
            continue
        status = parts[-1].lower()
        absorbed = parts[-2].zfill(3) if len(parts) >= 6 and parts[-2].isdigit() else ""
        if status == "open" and absorbed == prd:
            drift.append({"kind": "gap-still-open", "prd": prd, "row": parts[2]})

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
PY
