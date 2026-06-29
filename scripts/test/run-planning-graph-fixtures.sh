#!/usr/bin/env bash
# Planning lifecycle + graph fixtures (PRD 033 phase 1).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:$ROOT/core/scripts"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

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

exit $FAIL
