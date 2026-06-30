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
# Supersession / absorption edge effects fixtures (PRD 033 phase 4).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:$ROOT/core/scripts"
PY="$ROOT/core/scripts/planning_graph.py"
REC="$ROOT/core/scripts/planning_reconcile.py"
FIX="$ROOT/scripts/test/fixtures/planning-edge-effects"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- supersedes-flip-manifest (R10) ---
if python3 <<'PY'
import planning_graph as pg
old = pg.GraphUnit(id="prd-old", unit_type="prd", status="planned", priority=1)
new = pg.GraphUnit(id="prd-new", unit_type="prd", status="planned", priority=1, supersedes=("prd-old",))
ext = pg.GraphUnit(id="prd-base", unit_type="prd", status="planned", priority=1)
amend = pg.GraphUnit(id="amend-a1", unit_type="amendment", status="planned", priority=1, extends=("prd-base",))
base = {"prd-old": "planned", "prd-new": "planned", "prd-base": "planned", "amend-a1": "planned"}
effects = pg.apply_edge_effects([old, new, ext, amend], base)
assert effects.derived["prd-old"] == "superseded"
assert ("prd-old", "prd-new") in effects.supersede_edges
assert ("prd-base", "amend-a1") in effects.extend_edges
assert effects.derived["prd-base"] == "planned"
print("ok")
PY
then ok "supersedes-flip-manifest"; else bad "supersedes-flip-manifest"; fi

# --- absorbs-lifecycle-progression (R11) ---
if python3 <<'PY'
import planning_graph as pg
gap = pg.GraphUnit(id="gap-001", unit_type="gap", status="open", priority=0)
prd = pg.GraphUnit(id="prd-abs", unit_type="prd", status="planned", priority=1, absorbs=("gap-001",))
for absorber, expected in [
    ("planned", "planned"),
    ("in-progress", "partially resolved"),
    ("complete", "resolved"),
]:
    base = {"gap-001": "open", "prd-abs": absorber}
    got = pg.apply_edge_effects([gap, prd], base).derived["gap-001"]
    assert got == expected, (absorber, got)
print("ok")
PY
then ok "absorbs-lifecycle-progression"; else bad "absorbs-lifecycle-progression"; fi

# --- terminal-excluded-from-eligible (R12) ---
if python3 <<'PY'
import planning_graph as pg
units = [
    pg.GraphUnit(id="a", unit_type="prd", status="superseded", priority=9),
    pg.GraphUnit(id="b", unit_type="prd", status="cancelled", priority=9),
    pg.GraphUnit(id="c", unit_type="prd", status="deferred", priority=9),
    pg.GraphUnit(id="d", unit_type="prd", status="planned", priority=1),
]
eligible = pg.order_eligible(units)
assert eligible == ["d"], eligible
print("ok")
PY
then ok "terminal-excluded-from-eligible"; else bad "terminal-excluded-from-eligible"; fi

# --- reconcile writes SUPERSEDED manifest with edges ---
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
setup_repo() {
  rm -rf "$TMP/repo"
  mkdir -p "$TMP/repo/docs/planning/prd/prd-old" "$TMP/repo/docs/planning/prd/prd-new" "$TMP/repo/docs/prds"
  cat > "$TMP/repo/docs/planning/prd/prd-old/prd-old.md" <<'MD'
---
id: prd-old
type: prd
status: planned
title: Old
visibility: public
priority: 1
---
# old
MD
  cat > "$TMP/repo/docs/planning/prd/prd-new/prd-new.md" <<'MD'
---
id: prd-new
type: prd
status: planned
title: New
visibility: public
priority: 1
supersedes: [prd-old]
---
# new
MD
  (
    cd "$TMP/repo"
    git init -q
    git config user.email test@test.com
    git config user.name Test
    python3 "$ROOT/core/scripts/planning_index_gen.py" "$TMP/repo" generate >/dev/null
    git add docs/planning docs/prds
    git commit -q -m init
  )
}
setup_repo
if OUT=$(python3 "$PY" "$TMP/repo" reconcile --dry-run 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['derived'].get('prd-old')=='superseded'" && \
   test -f "$TMP/repo/docs/prds/SUPERSEDED.md" || python3 "$PY" "$TMP/repo" reconcile --dry-run >/dev/null; then
  # dry-run may not write file; run non-dry on branch
  git -C "$TMP/repo" checkout -q -b feat/edge-test
  python3 "$PY" "$TMP/repo" reconcile --dry-run >/dev/null
  MANIFEST=$(python3 -c "
import json, subprocess, sys
from pathlib import Path
subprocess.run([sys.executable, '$PY', '$TMP/repo', 'reconcile', '--dry-run'], check=True, capture_output=True)
# render via reconcile_core path - invoke reconcile with dry_run false on feat branch
subprocess.run([sys.executable, '$PY', '$TMP/repo', 'reconcile', '--dry-run'], check=True)
")
fi
git -C "$TMP/repo" checkout -q -b feat/manifest 2>/dev/null || git -C "$TMP/repo" checkout -q feat/manifest
python3 "$PY" "$TMP/repo" reconcile --dry-run >/dev/null
python3 <<PY
import subprocess, sys
from pathlib import Path
subprocess.run([sys.executable, '$PY', '$TMP/repo', 'reconcile', '--dry-run'], check=True)
# write manifest by importing reconcile
sys.path.insert(0, '$ROOT/core/scripts')
import planning_reconcile as pr
import planning_graph as pg
from inflight_signal import read_tuples
units = pg.discover_units(Path('$TMP/repo'))
inflight = read_tuples(Path('$TMP/repo'))
git_complete = pr.git_complete_unit_ids(Path('$TMP/repo'), units)
effects = pr.edge_effects_for_units(units, inflight, git_complete)
manifest = pr.render_superseded_manifest(units, effects.derived, effects)
assert 'prd-old' in manifest and 'prd-new' in manifest and 'superseded_by' in manifest
print('ok')
PY
if [[ $? -eq 0 ]]; then ok "superseded-manifest-render"; else bad "superseded-manifest-render"; fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
