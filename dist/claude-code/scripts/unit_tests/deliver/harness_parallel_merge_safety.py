#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _sw.vendor_paths import repo_root
from unit_tests._harness_runtime import harness_subprocess_env as _harness_env
from unit_tests._harness_runtime import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = _harness_env(root)
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
# PRD 036 Phase 3 — parallel-merge batch safety fixtures (R9–R12, R18).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LOOP_PY="$ROOT/scripts/wave_deliver_loop.py"
MERGE_PY="$ROOT/scripts/wave_merge.py"
DELIVER_PY="$ROOT/scripts/wave_deliver.py"
SHIP_STATUS="$ROOT/scripts/ship-phase-status.sh"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

write_valid_status() {
  local fix="$1" slug="$2" head="$3"
  mkdir -p "$fix/.cursor/sw-deliver-runs/$slug"
  "$SHIP_STATUS" --verdict merge-ready-green --phase "$slug" --head "$head" \
    --out "$fix/.cursor/sw-deliver-runs/$slug/status.json" >/dev/null
}

# --- whole-batch-no-early-merge (R10) ---
EARLY_FIX=$(mktemp -d)
(
  cd "$EARLY_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  git branch -M main
  HEAD=$(git rev-parse HEAD)
  git branch feat/demo-phase-a "$HEAD"
  git branch feat/demo-phase-b "$HEAD"
  mkdir -p .cursor
  cat >.cursor/workflow.config.json <<'WCFG'
{"review":{"provider":"none"},"checks":{"treatNeutralAsPass":true}}
WCFG
  cat >.cursor/sw-base-state.json <<'JSON'
{"trunkBase":{"name":"main","sha":"0000000000000000000000000000000000000000"}}
JSON
  NOW=$(python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))")
  cat >.cursor/sw-deliver-plan.json <<'JSON'
{"mode":"phase","target":{"branch":"feat/demo"},"items":[{"id":"1","slug":"a","branch":"feat/demo-phase-a"},{"id":"2","slug":"b","branch":"feat/demo-phase-b"}],"edges":[],"waves":[["1","2"]]}
JSON
  cat >.cursor/sw-deliver-state.json <<JSON
{"verdict":"running","target":{"branch":"feat/demo"},"currentWave":1,"specSeed":{"skipped":true},"baseCapture":{"skipped":true},"orchestratorWorktree":{"path":"$EARLY_FIX"},"driverHeartbeatAt":"$NOW","phases":{"1":{"id":"1","slug":"a","status":"in-flight","branch":"feat/demo-phase-a"},"2":{"id":"2","slug":"b","status":"in-flight","branch":"feat/demo-phase-b"}},"phaseWorktrees":{"1":{"path":"$EARLY_FIX","name":"a"},"2":{"path":"$EARLY_FIX","name":"b"}}}
JSON
  write_valid_status "$EARLY_FIX" a "$HEAD"
  if OUT=$(python3 "$LOOP_PY" "$EARLY_FIX" compute-next 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['next']['action']=='await-in-flight', d
assert 'whole-batch' in d['next'].get('note','')
"; then exit 0; fi
  exit 1
) && ok "whole-batch-no-early-merge" || bad "whole-batch-no-early-merge"
rm -rf "$EARLY_FIX"

# --- deterministic-merge-order (R11) ---
ORDER_FIX=$(mktemp -d)
(
  cd "$ORDER_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  mkdir -p .cursor
  cat >.cursor/sw-deliver-plan.json <<'JSON'
{"mode":"phase","target":{"branch":"feat/order"},"items":[{"id":"1","slug":"b","branch":"feat/order-b"},{"id":"2","slug":"a","branch":"feat/order-a"}],"edges":[],"waves":[["1","2"]]}
JSON
  cat >.cursor/sw-deliver-state.json <<'JSON'
{"target":{"branch":"feat/order"},"phases":{"1":{"slug":"b","branch":"feat/order-b"},"2":{"slug":"a","branch":"feat/order-a"}},"mergeQueue":[{"phaseSlug":"a","head":"def"},{"phaseSlug":"b","head":"abc"}]}
JSON
  python3 - <<PY
import json, sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from wave_merge import load_state, reorder_merge_queue
root = Path("$ORDER_FIX")
state = load_state(root)
reorder_merge_queue(state, root)
queue = state.get("mergeQueue") or []
assert [e.get("phaseSlug") for e in queue] == ["b", "a"], queue
PY
) && ok "deterministic-merge-order" || bad "deterministic-merge-order"
rm -rf "$ORDER_FIX"

# --- contention-generator-output-separation (R9) ---
CONT_FIX=$(mktemp -d)
(
  cd "$CONT_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  mkdir -p docs/prds/036-x
  cat >docs/prds/036-x/tasks.md <<'MD'
---
frozen: true
---
# Tasks

## Phase Dependencies
| Phase | Depends on |
|-------|------------|
| 1 | none |
| 2 | none |

### 1. Alpha — S
- [ ] 1.1 Touch golden
  - **File:** `scripts/test/fixtures/parity/cursor-golden.manifest`

### 2. Beta — S
- [ ] 2.1 Run generate
  - **File:** `scripts/wave_deliver_loop.py`
  - Run `python3 -m sw generate --all` after edits.
MD
  python3 "$DELIVER_PY" "$CONT_FIX" plan --task-list docs/prds/036-x/tasks.md --type feat --skip-base-check >/dev/null
  python3 - <<PY
import json
from pathlib import Path
plan = json.loads(Path(".cursor/sw-deliver-plan.json").read_text())
waves = plan.get("waves") or []
assert len(waves) >= 2, waves
assert "1" not in (waves[0] if waves else []) or "2" not in (waves[0] if waves else []), waves
edges = plan.get("contention", {}).get("injectedEdges") or []
assert edges, plan.get("contention")
PY
) && ok "contention-generator-output-separation" || bad "contention-generator-output-separation"
rm -rf "$CONT_FIX"

# --- deterministic-conflict-autoregen (R12) ---
REGEN_FIX=$(mktemp -d)
(
  cd "$REGEN_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  echo base >shared.txt && git add shared.txt && git commit -q -m init
  git branch -m feat/target
  git checkout -q -b feat/target-phase-a
  echo a >shared.txt && git add shared.txt && git commit -q -m a
  git checkout -q feat/target
  git checkout -q -b feat/target-phase-b
  echo b >shared.txt && git add shared.txt && git commit -q -m b
  git checkout -q feat/target
  mkdir -p scripts/test/fixtures/parity
  echo golden-a >scripts/test/fixtures/parity/cursor-golden.manifest
  git add scripts/test/fixtures/parity/cursor-golden.manifest && git commit -q -m golden-a
  git checkout feat/target-phase-a -q
  mkdir -p scripts/test/fixtures/parity
  echo golden-b >scripts/test/fixtures/parity/cursor-golden.manifest
  git add scripts/test/fixtures/parity/cursor-golden.manifest && git commit -q -m golden-b
  git checkout feat/target -q
  mkdir -p .cursor
  cat >.cursor/sw-deliver-state.json <<'JSON'
{"target":{"branch":"feat/target"},"phases":{"1":{"slug":"a","branch":"feat/target-phase-a"}},"mergeQueue":[{"phaseSlug":"a","head":"phase-a"}],"orchestratorWorktree":{"path":"REGEN_ORCH"}}
JSON
  python3 -c "import json; p=json.load(open('.cursor/sw-deliver-state.json')); p['orchestratorWorktree']['path']='$REGEN_FIX'; json.dump(p, open('.cursor/sw-deliver-state.json','w'))"
  SW_DETERMINISTIC_REGEN_STUB=pass python3 "$MERGE_PY" "$REGEN_FIX" merge exec \
    --phase-slug a --phase-branch feat/target-phase-a --target feat/target \
    --orchestrator-worktree "$REGEN_FIX" >/dev/null
) && ok "deterministic-conflict-autoregen" || bad "deterministic-conflict-autoregen"
rm -rf "$REGEN_FIX"

# --- semantic-conflict-halt (R12) ---
SEM_FIX=$(mktemp -d)
(
  cd "$SEM_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  echo base >src.txt && git add src.txt && git commit -q -m init
  git branch -m feat/target
  git checkout -q -b feat/target-phase-a
  echo phase-a >src.txt && git add src.txt && git commit -q -m a
  git checkout -q feat/target
  echo target-tip >src.txt && git add src.txt && git commit -q -m target-tip
  mkdir -p .cursor
  cat >.cursor/sw-deliver-state.json <<JSON
{"target":{"branch":"feat/target"},"phases":{"1":{"slug":"a","branch":"feat/target-phase-a"}},"mergeQueue":[{"phaseSlug":"a","head":"phase-a"}],"orchestratorWorktree":{"path":"$SEM_FIX"}}
JSON
  set +e
  OUT=$(SW_DETERMINISTIC_REGEN_STUB=pass python3 "$MERGE_PY" "$SEM_FIX" merge exec \
    --phase-slug a --phase-branch feat/target-phase-a --target feat/target \
    --orchestrator-worktree "$SEM_FIX" 2>/dev/null)
  EC=$?
  set -e
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('reason')=='semantic-conflict' or d.get('cause')=='merge-queue:conflict', d"
  test "$EC" -eq 20
) && ok "semantic-conflict-halt" || bad "semantic-conflict-halt"
rm -rf "$SEM_FIX"

if [[ "$FAIL" -eq 0 ]]; then
  echo "parallel-merge-safety fixtures: all passed"
  exit 0
fi
echo "parallel-merge-safety fixtures: $FAIL failure(s)"
exit 1

"""
if __name__ == "__main__":
    raise SystemExit(main())
