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
# Migration-bridge backfill fixtures (PRD 032 phase 5 — R10).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/scripts/inflight_migration_bridge.py"
INF="$ROOT/scripts/inflight-migration-bridge.sh"
SIG="$ROOT/scripts/inflight_signal.py"
PIG="$ROOT/scripts/planning_index_gen.py"
FIX_SRC="$ROOT/scripts/test/fixtures/planning-index"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

[[ -f "$PY" ]] || { bad "inflight_migration_bridge.py missing"; exit 1; }
[[ -x "$INF" ]] || chmod +x "$INF"

seed_repo() {
  local dest="$1"
  mkdir -p "$dest/docs/planning"
  cp -R "$FIX_SRC/units/"* "$dest/docs/planning/"
  python3 "$PIG" "$dest" generate --writer generator >/dev/null
}

# --- migration-bridge-backfill-no-desync (R10) ---
TMP=$(mktemp -d)
trap 'rm -rf "$TMP" "$TMP2"' EXIT
(
  cd "$TMP"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  seed_repo "$TMP"
  git add docs/planning
  git commit -q -m "seed"
  mkdir -p .cursor
  # Legacy marker: running deliver state without inflightLease (pre-032 writer)
  cat > .cursor/sw-deliver-state.legacy-run.json <<'JSON'
{"verdict":"running","target":{"branch":"feat/legacy-sample"},"source_task_list":"docs/prds/031-planning-unit-model/tasks-031-planning-unit-model.md","legacyInFlightMarker":{"unitId":"prd-031-planning-unit-model","runId":"deliver-legacy-run","branch":"feat/legacy-sample","epoch":1}}
JSON
  OUT=$(python3 "$PY" "$TMP" reconcile)
  echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='pass', d
assert len(d.get('promoted',[]))==1, d
assert d['promoted'][0]['runId']=='deliver-legacy-run'
"
  READ=$(python3 "$SIG" "$TMP" read --unit prd-031-planning-unit-model)
  echo "$READ" | python3 -c "
import json,sys
d=json.load(sys.stdin)
t=d['tuple']
assert t and t['runId']=='deliver-legacy-run'
assert t['branch']=='feat/legacy-sample'
"
  # Idempotent re-run: already committed, no desync
  OUT2=$(python3 "$PY" "$TMP" reconcile)
  echo "$OUT2" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='pass', d
assert d.get('skipped') or d.get('promoted')==[] or len(d.get('promoted',[]))==0, d
"
) && ok "migration-bridge-backfill-no-desync" || bad "migration-bridge-backfill-no-desync"

# --- desync protection: conflicting live runs ---
TMP2=$(mktemp -d)
(
  cd "$TMP2"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  seed_repo "$TMP2"
  git add docs/planning && git commit -q -m "seed"
  mkdir -p .cursor
  cat > .cursor/sw-deliver-state.a.json <<'JSON'
{"verdict":"running","target":{"branch":"feat/a"},"source_task_list":"docs/prds/031-planning-unit-model/tasks-031-planning-unit-model.md","inflightLease":{"runId":"deliver-a","epoch":1}}
JSON
  python3 "$SIG" "$TMP2" write --target feat/a --unit prd-031-planning-unit-model --run-id deliver-a --branch feat/a --epoch 1 >/dev/null
  cat > .cursor/sw-deliver-state.b.json <<'JSON'
{"verdict":"running","target":{"branch":"feat/b"},"source_task_list":"docs/prds/031-planning-unit-model/tasks-031-planning-unit-model.md","legacyInFlightMarker":{"unitId":"prd-031-planning-unit-model","runId":"deliver-b","branch":"feat/b","epoch":2}}
JSON
  set +e
  OUT=$(python3 "$PY" "$TMP2" reconcile 2>&1)
  EC=$?
  set -e
  [[ "$EC" -ne 0 ]]
  echo "$OUT" | grep -qi 'desync'
) && ok "migration-bridge-desync-failclosed" || bad "migration-bridge-desync-failclosed"

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
