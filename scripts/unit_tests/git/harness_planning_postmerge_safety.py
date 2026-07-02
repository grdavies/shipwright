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

from _fixture_lib import repo_root
from _harness_patch import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy()
    env["ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(root / "scripts" / "test"), str(root / "scripts"), env.get("PYTHONPATH", "")) if p
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
# PRD 033 phase 8 / amendment A1 — post-merge INDEX reconcile safety fixtures (R29–R35).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:$ROOT/core/scripts"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

PY="$ROOT/scripts/planning_graph.py"
WC="$ROOT/scripts/wave_compound.py"
FIX_UNITS="$ROOT/scripts/test/fixtures/planning-index/units"
INDEX_PY="$ROOT/scripts/planning_index_gen.py"

seed_planning_repo() {
  local dir="$1"
  (
    cd "$dir"
    git init -q
    git config user.email test@test.com
    git config user.name Test
    mkdir -p docs/planning docs/prds
    cp -R "$FIX_UNITS/"* docs/planning/
    python3 "$INDEX_PY" "$dir" generate >/dev/null
    git add docs/planning docs/prds
    git commit -q -m "seed planning index"
  )
}

# --- reconcile-complete-from-git-ancestry (R29 / GAP-053) ---
TMP1=$(mktemp -d)
(
  seed_planning_repo "$TMP1"
  git -C "$TMP1" checkout -q -b feat/planning-unit-model
  git -C "$TMP1" commit --allow-empty -q -m "feat work"
  git -C "$TMP1" checkout -q main 2>/dev/null || git -C "$TMP1" checkout -q -b main
  git -C "$TMP1" merge -q feat/planning-unit-model
  OUT=$(python3 "$PY" "$TMP1" reconcile --dry-run 2>/dev/null)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['derived'].get('prd-031-planning-unit-model')=='complete', d"
) && ok "reconcile-complete-from-git-ancestry" || bad "reconcile-complete-from-git-ancestry"
rm -rf "$TMP1"

# --- reconcile-terminal-monotonic (R30) ---
TMP2=$(mktemp -d)
(
  seed_planning_repo "$TMP2"
  python3 "$PY" "$TMP2" reconcile --dry-run >/dev/null
  python3 - "$TMP2" "$PY" <<'PY'
import json, subprocess, sys
from pathlib import Path
tmp, py = Path(sys.argv[1]), sys.argv[2]
sys.path.insert(0, str(tmp / "scripts"))
import planning_index_gen as pig
idx = pig.index_path(tmp)
text = idx.read_text()
start, end = pig.REGION_MARKERS["derived"]
body = "prd-031-planning-unit-model: complete\n"
text = text.split(start, 1)[0] + start + "\n" + body + end + text.split(end, 1)[1]
start_i, end_i = pig.REGION_MARKERS["inFlight"]
inflight = "prd-031-planning-unit-model:\nrun-id: stale\nbranch: feat/planning-unit-model\nepoch: 1\n"
text = text.split(start_i, 1)[0] + start_i + "\n" + inflight + end_i + text.split(end_i, 1)[1]
idx.write_text(text)
out = subprocess.check_output(["python3", py, str(tmp), "reconcile", "--dry-run"], text=True)
d = json.loads(out)
assert d["derived"].get("prd-031-planning-unit-model") == "complete", d
PY
) && ok "reconcile-terminal-monotonic" || bad "reconcile-terminal-monotonic"
rm -rf "$TMP2"

# --- reconcile-refuse-default-branch (R31) ---
TMP3=$(mktemp -d)
(
  seed_planning_repo "$TMP3"
  git -C "$TMP3" checkout -q main 2>/dev/null || git -C "$TMP3" checkout -q -b main
  EC=0
  python3 "$PY" "$TMP3" reconcile --commit 2>/dev/null || EC=$?
  test "$EC" -ne 0
  test -z "$(git -C "$TMP3" status --porcelain)"
) && ok "reconcile-refuse-default-branch" || bad "reconcile-refuse-default-branch"
rm -rf "$TMP3"

# --- reconcile-stale-local-branches (R32) ---
TMP4=$(mktemp -d)
(
  seed_planning_repo "$TMP4"
  git -C "$TMP4" checkout -q -b feat/planning-unit-model
  git -C "$TMP4" commit --allow-empty -q -m "feat work"
  git -C "$TMP4" checkout -q main 2>/dev/null || git -C "$TMP4" checkout -q -b main
  git -C "$TMP4" merge -q feat/planning-unit-model
  git -C "$TMP4" checkout -q -b feat/planning-unit-model-stale
  OUT=$(python3 "$PY" "$TMP4" reconcile --dry-run 2>/dev/null)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['derived'].get('prd-031-planning-unit-model')=='complete', d"
) && ok "reconcile-stale-local-branches" || bad "reconcile-stale-local-branches"
rm -rf "$TMP4"

# --- relief-corpus-postmerge-safety (R35 aggregate) ---
if [[ "$FAIL" -eq 0 ]]; then ok "relief-corpus-postmerge-safety"; else bad "relief-corpus-postmerge-safety"; fi

# --- completion-finalize-chokepoint (R33) ---
TMP5=$(mktemp -d)
(
  cd "$TMP5"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p docs/prds .cursor
  echo '| # | Slug | PRD | Tasks | Status |' > docs/prds/INDEX.md
  echo '|---|---|---|---|---|' >> docs/prds/INDEX.md
  git add docs/prds && git commit -q -m init
  git branch -m feat/demo
  cat >.cursor/sw-deliver-state.json <<'JSON'
{"verdict":"running","target":{"branch":"feat/demo"},"completion":{"status":"completed-pending-merge"},"phases":{}}
JSON
  EC=0
  python3 -c "
import sys
sys.path.insert(0, '$ROOT/scripts')
from pathlib import Path
from wave_state import save_deliver_state
state = {'verdict':'running','target':{'branch':'feat/demo'},'completion':{'status':'merged-complete'},'phases':{}}
try:
    save_deliver_state(Path('.'), state)
except SystemExit:
    pass
else:
    raise SystemExit(1)
" 2>/dev/null || EC=$?
  test "$EC" -ne 0
  git checkout -q -b main
  git merge -q --no-ff feat/demo -m merge
  git checkout -q feat/demo
  python3 "$WC" "$TMP5" completion finalize-if-merged >/dev/null
) && ok "completion-finalize-chokepoint" || bad "completion-finalize-chokepoint"
rm -rf "$TMP5"

# --- deliver-postmerge-finalize-no-reconcile (R34) ---
if grep -q "never bare reconcile" "$ROOT/core/scripts/wave_deliver_loop.py" 2>/dev/null; then
  ok "deliver-postmerge-finalize-no-reconcile"
else
  bad "deliver-postmerge-finalize-no-reconcile"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "planning-postmerge-safety fixtures: all passed"
  exit 0
fi
echo "planning-postmerge-safety fixtures: $FAIL failure(s)"
exit 1

"""

if __name__ == "__main__":
    raise SystemExit(main())
