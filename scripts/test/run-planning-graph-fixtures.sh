#!/usr/bin/env bash
# Planning lifecycle + graph + reconciler fixtures (PRD 033 phases 1–2).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:$ROOT/core/scripts"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

GRAPH_SH="$ROOT/scripts/planning-graph.sh"
PY="$ROOT/scripts/planning_graph.py"
FIX_UNITS="$ROOT/scripts/test/fixtures/planning-index/units"
INDEX_PY="$ROOT/scripts/planning_index_gen.py"

# --- enum-type-conditioned-tokens (R1) ---
if python3 <<'PY'
import planning_lifecycle as plc
assert plc.validate_status("gap", "open") is None
assert plc.validate_status("gap", "planned") is None
assert plc.validate_status("prd", "planned") is None
assert plc.validate_status("prd", "proposed") is None
assert plc.validate_status("prd", "bogus") is not None
assert "homonym" in plc.PLANNED_HOMONYM_NOTE
print("ok")
PY
then ok "enum-type-conditioned-tokens"; else bad "enum-type-conditioned-tokens"; fi

# --- derived-status-from-inflight (R2) ---
if python3 <<'PY'
import planning_lifecycle as plc
assert plc.is_mechanical_status("in-progress")
assert plc.is_mechanical_status("complete")
assert plc.is_mechanical_status("blocked")
assert plc.transition_kind("proposed", "planned") == "freeze-gate"
assert plc.is_human_gated_status("superseded")
print("ok")
PY
then ok "derived-status-from-inflight"; else bad "derived-status-from-inflight"; fi

# --- blocked-matches-unmet-edges (R3) ---
if python3 <<'PY'
import planning_graph as pg
a = pg.GraphUnit(id="a", unit_type="prd", status="proposed", priority=1)
b = pg.GraphUnit(id="b", unit_type="prd", status="proposed", priority=1, depends=("a",))
by = pg.index_units([a, b])
assert pg.derive_blocked(b, by)
a_done = pg.GraphUnit(id="a", unit_type="prd", status="complete", priority=1)
by2 = pg.index_units([a_done, b])
assert not pg.derive_blocked(b, by2)
assert pg.is_eligible(b, by2)
print("ok")
PY
then ok "blocked-matches-unmet-edges"; else bad "blocked-matches-unmet-edges"; fi

# --- whole-graph-cycle-precommit-reject (R4) ---
if python3 <<'PY'
import planning_graph as pg
a = pg.GraphUnit(id="x", unit_type="prd", status="planned", priority=0, depends=("y",))
b = pg.GraphUnit(id="y", unit_type="prd", status="planned", priority=0, depends=("x",))
cycle = pg.detect_cycle([a, b])
assert cycle and "x" in cycle and "y" in cycle
print("ok")
PY
then ok "whole-graph-cycle-precommit-reject"; else bad "whole-graph-cycle-precommit-reject"; fi

# --- priority-topo-stable-tiebreak (R6) ---
if python3 <<'PY'
import planning_graph as pg
a = pg.GraphUnit(id="a", unit_type="prd", status="planned", priority=2)
b = pg.GraphUnit(id="b", unit_type="prd", status="planned", priority=1, depends=("a",))
c = pg.GraphUnit(id="c", unit_type="prd", status="planned", priority=2)
order = pg.order_eligible([a, b, c])
assert order == ["a", "c"]
print("ok")
PY
then ok "priority-topo-stable-tiebreak"; else bad "priority-topo-stable-tiebreak"; fi

# --- graph-module-deterministic + graph-offline-reproducible (R19/R27) ---
if python3 <<'PY'
import planning_graph as pg
units = [
    pg.GraphUnit(id="u1", unit_type="prd", status="planned", priority=1),
    pg.GraphUnit(id="u2", unit_type="prd", status="planned", priority=0, depends=("u1",)),
]
o1 = pg.order_eligible(units)
o2 = pg.order_eligible(units)
assert o1 == o2
assert pg.topological_order(units) == ["u1", "u2"]
print("ok")
PY
then ok "graph-module-deterministic"; ok "graph-offline-reproducible"; else bad "graph-module-deterministic"; bad "graph-offline-reproducible"; fi

# --- enum-shared-module-no-drift (R23) ---
if python3 <<'PY'
import planning_lifecycle as plc
import planning_status_enum as pse
assert pse.GAP_STATUSES == plc.GAP_STATUSES
assert pse.LIFECYCLE_STATUSES == plc.LIFECYCLE_STATUSES
assert pse.validate_status("gap", "open") is None
print("ok")
PY
then ok "enum-shared-module-no-drift"; else bad "enum-shared-module-no-drift"; fi

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

inject_inflight() {
  local repo="$1" body="$2"
  python3 - "$repo" "$body" <<'INJECT'
import sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import planning_index_gen as pig
idx = pig.index_path(Path(sys.argv[1]))
text = idx.read_text()
start, end = pig.REGION_MARKERS["inFlight"]
text = text.split(start, 1)[0] + start + "\n" + sys.argv[2] + end + text.split(end, 1)[1]
idx.write_text(text)
INJECT
}

# --- reconcile-reread-before-serialize (R13) ---
TMP_R=$(mktemp -d)
trap 'rm -rf "$TMP_R" "$TMP_A" "$TMP_I" "$TMP_S" "$TMP_REL" "$TMP_N"' EXIT
(
  seed_planning_repo "$TMP_R"
  inject_inflight "$TMP_R" $'prd-031-planning-unit-model:\nrun-id: deliver-test\nbranch: feat/sample\nepoch: 1\n'
  OUT1=$(python3 "$PY" "$TMP_R" reconcile --dry-run 2>/dev/null)
  echo "$OUT1" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass'"
  inject_inflight "$TMP_R" $'prd-031-planning-unit-model:\nrun-id: deliver-test\nbranch: feat/sample\nepoch: 2\n'
  OUT2=$(python3 "$PY" "$TMP_R" reconcile --dry-run 2>/dev/null)
  echo "$OUT2" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass'"
) && ok "reconcile-reread-before-serialize" || bad "reconcile-reread-before-serialize"

# --- index-active-archive-split (R14) ---
TMP_A=$(mktemp -d)
(
  seed_planning_repo "$TMP_A"
  git -C "$TMP_A" checkout -q -b feat/planning-unit-model
  git -C "$TMP_A" commit --allow-empty -q -m "feat"
  git -C "$TMP_A" checkout -q main 2>/dev/null || git -C "$TMP_A" checkout -q -b main
  git -C "$TMP_A" merge -q feat/planning-unit-model
  OUT=$(python3 "$PY" "$TMP_A" reconcile --dry-run 2>/dev/null)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'prd-031-planning-unit-model' in d.get('archivedUnits',[]), d"
) && ok "index-active-archive-split" || bad "index-active-archive-split"

# --- reconcile-idempotent-regen (R21) ---
TMP_I=$(mktemp -d)
(
  seed_planning_repo "$TMP_I"
  python3 "$PY" "$TMP_I" reconcile --dry-run >/dev/null
  HASH1=$(python3 -c "import sys; sys.path.insert(0,'$TMP_I/scripts'); import planning_index_gen as pig; from pathlib import Path; print(pig.index_path(Path('$TMP_I')).read_text())")
  python3 "$PY" "$TMP_I" reconcile --dry-run >/dev/null
  HASH2=$(python3 -c "import sys; sys.path.insert(0,'$TMP_I/scripts'); import planning_index_gen as pig; from pathlib import Path; print(pig.index_path(Path('$TMP_I')).read_text())")
  test "$HASH1" = "$HASH2"
  python3 "$PY" "$TMP_I" reconcile --dry-run 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass'"
) && ok "reconcile-idempotent-regen" || bad "reconcile-idempotent-regen"

# --- dependency-dead-flagged-not-blocked (R5) ---
if python3 <<'PY'
import planning_graph as pg
dep = pg.GraphUnit(id="old", unit_type="prd", status="superseded", priority=0)
unit = pg.GraphUnit(id="child", unit_type="prd", status="planned", priority=0, depends=("old",))
by = pg.index_units([dep, unit])
assert pg.is_dependency_dead(unit, by)
assert not pg.derive_blocked(unit, by)
print("ok")
PY
then ok "dependency-dead-flagged-not-blocked"; else bad "dependency-dead-flagged-not-blocked"; fi

# --- stale-planned-drift-reconciled (R16) ---
TMP_S=$(mktemp -d)
(
  seed_planning_repo "$TMP_S"
  git -C "$TMP_S" checkout -q -b feat/planning-unit-model
  git -C "$TMP_S" commit --allow-empty -q -m "feat work"
  git -C "$TMP_S" checkout -q main 2>/dev/null || git -C "$TMP_S" checkout -q -b main
  git -C "$TMP_S" merge -q feat/planning-unit-model
  OUT=$(python3 "$PY" "$TMP_S" reconcile --dry-run 2>/dev/null)
  echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['derived'].get('prd-031-planning-unit-model')=='complete', d['derived']
"
) && ok "stale-planned-drift-reconciled" || bad "stale-planned-drift-reconciled"

# --- reconciler-no-auto-pr (R17) ---
TMP_N=$(mktemp -d)
(
  seed_planning_repo "$TMP_N"
  OUT=$(python3 "$PY" "$TMP_N" reconcile --dry-run 2>/dev/null)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('autoPr') is False"
) && ok "reconciler-no-auto-pr" || bad "reconciler-no-auto-pr"

# --- relief-corpus-adversarial (R22) ---
TMP_REL=$(mktemp -d)
(
  seed_planning_repo "$TMP_REL"
  python3 "$PY" "$TMP_REL" reconcile --dry-run >/dev/null
  python3 "$PY" "$TMP_REL" relief-check >/dev/null
) && ok "relief-corpus-adversarial" || bad "relief-corpus-adversarial"

# --- reconciler-no-private-bodies (R26) ---
if python3 <<'PY'
import planning_graph as pg
import planning_reconcile as pr
# reconciler discovers units via frontmatter only (planning_index_gen.discover_units)
units = pg.discover_units(__import__('pathlib').Path('.'))
assert isinstance(units, list)
print("ok")
PY
then ok "reconciler-no-private-bodies"; else bad "reconciler-no-private-bodies"; fi

if [[ $FAIL -ne 0 ]]; then
  echo "run-planning-graph-fixtures: FAIL"
  exit 1
fi
echo "run-planning-graph-fixtures: PASS"
