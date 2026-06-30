#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import repo_root
from _harness_patch import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy()
    env["ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(root / "scripts"), env.get("PYTHONPATH", "")) if p
    )
    src = _patch_source(_SOURCE, root)
    completed = subprocess.run(
        ["bash", "-c", src],
        cwd=str(root),
        env=env,
        shell=False,
    )
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
# PRD 036 Phase 4 — terminal status provenance + recovery fixtures (R13–R18).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
STATUS_PY="$ROOT/scripts/status_integrity.py"
SHIP_STATUS="$ROOT/scripts/ship-phase-status.sh"
LOOP_PY="$ROOT/scripts/wave_deliver_loop.py"
MERGE_PY="$ROOT/scripts/wave_merge.py"
WAVE="$ROOT/scripts/wave.sh"

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- provenance-marker-roundtrip (R13) ---
FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT
cd "$FIX"
git init -q
git config user.email test@test.com
git config user.name Test
git commit --allow-empty -q -m init
git branch -M main
HEAD=$(git rev-parse HEAD)
mkdir -p .cursor/sw-deliver-runs/alpha
cat >.cursor/workflow.config.json <<'WCFG'
{"review":{"provider":"none"},"checks":{"treatNeutralAsPass":true}}
WCFG
cat >.cursor/sw-base-state.json <<'JSON'
{"trunkBase":{"name":"main","sha":"0000000000000000000000000000000000000000"}}
JSON
if OUT=$("$SHIP_STATUS" --verdict merge-ready-green --phase alpha --head "$HEAD" --out .cursor/sw-deliver-runs/alpha/status.json 2>/dev/null) &&    echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('provenanceMarker')
assert len(d.get('provenanceMarker',''))==64
" && python3 "$STATUS_PY" validate --path .cursor/sw-deliver-runs/alpha/status.json >/dev/null; then
  ok "provenance-marker-roundtrip"
else
  bad "provenance-marker-roundtrip"
fi

# --- forged-merge-ready-green-rejected (R14) ---
FORGED='{"verdict":"merge-ready-green","phase":"alpha","phaseMode":true,"head":"'"$HEAD"'","gate":{"verdict":"green"},"provenanceMarker":"deadbeef","writtenAt":"2020-01-01T00:00:00Z"}'
if python3 -c "import json,sys; json.loads(sys.argv[1])" "$FORGED" >/dev/null &&    ! python3 "$STATUS_PY" validate --path /dev/stdin <<<"$FORGED" >/dev/null 2>&1; then
  ok "forged-merge-ready-green-rejected"
else
  bad "forged-merge-ready-green-rejected"
fi

# --- abbreviated-head-rejected (R14) ---
SHORT='{"verdict":"merge-ready-green","phase":"alpha","head":"abc123","writtenAt":"2020-01-01T00:00:00Z"}'
if ! python3 "$STATUS_PY" validate --path /dev/stdin <<<"$SHORT" >/dev/null 2>&1; then
  ok "abbreviated-head-rejected"
else
  bad "abbreviated-head-rejected"
fi

# --- stuck-stale-classification (R15) ---
export SW_STATUS_TIP_QUIESCENCE_SECONDS=0
HAND='{"verdict":"in-progress","phase":"alpha","head":"'"$HEAD"'","writtenAt":"2020-01-01T00:00:00Z"}'
python3 - <<PY2 "$ROOT" "$HEAD" "$HAND"
import json, sys
from pathlib import Path
root = Path.cwd()
repo = Path(sys.argv[1])
head = sys.argv[2]
hand = json.loads(sys.argv[3])
sys.path.insert(0, str(repo / "scripts"))
from status_integrity import classify_stuck_stale
ok, detail = classify_stuck_stale(
    root,
    phase_slug="alpha",
    phase_branch="main",
    branch_head=head,
    status=hand,
    pr_number=None,
    quiescence_seconds=0,
)
assert ok and detail.get("reason") == "stuck-stale", detail
PY2
if [[ $? -eq 0 ]]; then ok "stuck-stale-classification"; else bad "stuck-stale-classification"; fi

# --- canonical-reemit-action (R16) ---
cat >.cursor/sw-deliver-plan.json <<'JSON'
{"verdict":"pass","mode":"phase","target":{"branch":"feat/demo"},"items":[{"id":"1","slug":"alpha","branch":"main"}],"waves":[["1"]]}
JSON
NOW=$(python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")
cat >.cursor/sw-deliver-state.json <<JSON
{"verdict":"running","target":{"branch":"feat/demo"},"currentWave":1,"baseCapture":{"skipped":true},"specSeed":{"skipped":true},"orchestratorWorktree":{"path":"/tmp/orch"},"driverHeartbeatAt":"$NOW","phases":{"1":{"id":"1","slug":"alpha","status":"in-flight","branch":"main","startedAt":"$NOW"}},"statusReemitAttempts":{}}
JSON
printf '%s' "$HAND" >.cursor/sw-deliver-runs/alpha/status.json
if OUT=$(SW_STATUS_TIP_QUIESCENCE_SECONDS=0 python3 "$LOOP_PY" "$FIX" compute-next 2>/dev/null) &&    echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='canonical-reemit', d
"; then
  ok "stuck-stale-routes-canonical-reemit"
else
  bad "stuck-stale-routes-canonical-reemit"
fi

# --- merge-enqueue-requires-valid-marker (R14) ---
cat >.cursor/sw-deliver-runs/alpha/status-bad.json <<JSON
{"verdict":"merge-ready-green","phase":"alpha","head":"$HEAD","gate":{"verdict":"green"},"provenanceMarker":"bad","writtenAt":"2020-01-01T00:00:00Z"}
JSON
set +e
python3 "$MERGE_PY" "$FIX" merge enqueue --phase-slug alpha --status-path .cursor/sw-deliver-runs/alpha/status-bad.json >/dev/null 2>&1
EC=$?
set -e
if [[ "$EC" -ne 0 ]]; then
  ok "merge-enqueue-rejects-forged-status"
else
  bad "merge-enqueue-rejects-forged-status"
fi

# --- recovery-command-documented (R17) ---
if grep -qE '/sw-ship --phase-mode --from' "$ROOT/core/commands/sw-ship.md" &&    grep -qE '/sw-ship --phase-mode --from' "$ROOT/core/rules/sw-conductor.mdc"; then
  ok "recovery-command-documented"
else
  bad "recovery-command-documented"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "status-integrity fixtures: all passed"
  exit 0
fi
echo "status-integrity fixtures: $FAIL failure(s)"
exit 1

"""

if __name__ == "__main__":
    raise SystemExit(main())
