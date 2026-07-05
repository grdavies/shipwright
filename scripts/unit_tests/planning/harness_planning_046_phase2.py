#!/usr/bin/env python3
"""PRD 046 phase-2 fixtures — budget, cache, redaction, scheduler (R25, R81-R86, R93)."""
from __future__ import annotations

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
    completed = subprocess.run(["bash", "-c", src], cwd=str(root), env=env, shell=False)
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
PY="$ROOT/scripts/planning_index_gen.py"
DISC="$ROOT/scripts/planning_discover.py"
SCHED="$ROOT/scripts/planning_scheduler.py"
FAIL=0
unset SW_ISSUES_PAGE_SIZE
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
(
  cd "$TMP"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  mkdir -p docs/planning .cursor/hooks/state
  echo ".cursor/hooks/state/" >> .gitignore
  git add .gitignore && git commit -q -m init
  cat > .cursor/workflow.config.json <<'CFG'
{"version":1,"planning":{"store":{"backend":"issue-store","issuesProvider":"github-issues","projectKey":"phase2046","requestBudget":{"github-issues":{"maxCalls":20,"maxPaginationDepth":2,"alertThreshold":0.5,"cacheTtlSeconds":60}}}},"host":{"provider":"github"}}
CFG
  export SW_ISSUES_FIXTURE=1 SW_DISCOVER_SOURCE=issue
  python3 - <<PY
import sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from issues_lib import get_fixture_store
from planning_canonical import compose_issue_body, project_label, type_label
store = get_fixture_store(Path("$TMP"))
store.clear()
root = Path("$TMP")
for uid, title, vis, labels in [
    ("prd-046-private", "Secret PRD title", "private", ["sw:visibility:private", "sw:tier:high", "sw:priority:5"]),
    ("prd-046-public", "Public PRD", "public", ["sw:visibility:public", "sw:tier:low"]),
]:
    body = compose_issue_body("phase2046", "prd", uid, f"---\nid: {uid}\ntype: prd\nstatus: proposed\ntitle: {title}\nvisibility: {vis}\n---\n")
    store.create(title=f"[sw] prd:{uid}", body=body, labels=sorted({project_label("phase2046"), type_label("prd"), f"sw:visibility:{vis}", *labels}), project_key="phase2046", artifact_type="prd", unit_id=uid)
PY
  python3 "$PY" "$TMP" generate >/dev/null
  TABLE=$(python3 "$PY" "$TMP" parse | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['regions']['structural'])")
  echo "$TABLE" | grep -q "prd-046-private: \[private\]" && echo "$TABLE" | grep -q "Secret PRD title" && exit 1 || true
  echo "$TABLE" | grep -q "prd-046-private: \[private\]"
) && ok "derived-index-private-opaque" || bad "derived-index-private-opaque"

(
  cd "$TMP"
  export SW_PLANNING_FORCE_REFRESH=1
  python3 "$PY" "$TMP" generate >/dev/null
  CACHE="$TMP/.cursor/hooks/state/planning-query-cache.json"
  test -f "$CACHE"
  ! grep -q "Secret PRD title" "$CACHE"
) && ok "cache-post-redaction-only" || bad "cache-post-redaction-only"

(
  PTMP=$(mktemp -d)
  trap 'rm -rf "$PTMP"' EXIT
  cd "$PTMP"
  git init -q && git config user.email test@test.com && git config user.name Test
  mkdir -p docs/planning .cursor/hooks/state
  echo ".cursor/hooks/state/" >> .gitignore && git add .gitignore && git commit -q -m init
  cat > .cursor/workflow.config.json <<'CFG'
{"version":1,"planning":{"store":{"backend":"issue-store","issuesProvider":"github-issues","projectKey":"phase2046p","requestBudget":{"github-issues":{"maxCalls":50,"maxPaginationDepth":2,"alertThreshold":0.5,"cacheTtlSeconds":60}}}},"host":{"provider":"github"}}
CFG
  export SW_ISSUES_FIXTURE=1 SW_DISCOVER_SOURCE=issue SW_ISSUES_PAGE_SIZE=1 SW_PLANNING_FORCE_REFRESH=1
  python3 - <<PY
import sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from issues_lib import get_fixture_store
from planning_canonical import compose_issue_body, project_label, type_label
root = Path("$PTMP")
store = get_fixture_store(root)
for uid in ("prd-a", "prd-b"):
    body = compose_issue_body("phase2046p", "prd", uid, f"---\nid: {uid}\ntype: prd\nstatus: proposed\ntitle: T\nvisibility: public\n---\n")
    store.create(title=f"[sw] prd:{uid}", body=body, labels=sorted({project_label("phase2046p"), type_label("prd"), "sw:visibility:public"}), project_key="phase2046p", artifact_type="prd", unit_id=uid)
PY
  if python3 "$PY" "$PTMP" generate >/dev/null 2>&1; then exit 1; fi
  python3 -c "import sys; sys.path.insert(0,'$ROOT/scripts'); import planning_index_gen as pig; assert pig.read_generation_state(__import__('pathlib').Path('$PTMP')).get('indexIncomplete')"
) && ok "pagination-ceiling-index-incomplete" || bad "pagination-ceiling-index-incomplete"

(
  cd "$TMP"
  unset SW_ISSUES_PAGE_SIZE
  python3 -c "import sys; sys.path.insert(0,'$ROOT/scripts'); import planning_index_gen as pig; from pathlib import Path; root=Path('$TMP'); s=pig.read_generation_state(root); s.pop('indexIncomplete',None); s.pop('indexIncompleteReason',None); s['generation']=max(1,int(s.get('generation',0))); pig.write_generation_state(root,s); from planning_query_cache import invalidate_all; invalidate_all(root)"
  export SW_PLANNING_FORCE_REFRESH=1
  python3 "$PY" "$TMP" generate >/dev/null
  OUT=$(python3 "$SCHED" "$TMP" next)
  echo "$OUT" | grep -q '"next":'
) && ok "scheduler-label-driven-next" || bad "scheduler-label-driven-next"

(
  cd "$TMP"
  python3 -c "import sys; sys.path.insert(0,'$ROOT/scripts'); import planning_index_gen as pig; pig.mark_index_incomplete(__import__('pathlib').Path('$TMP'), 'test'); import subprocess; r=subprocess.run([sys.executable,'$SCHED','$TMP','next'], capture_output=True); assert r.returncode!=0"
) && ok "scheduler-refuses-index-incomplete" || bad "scheduler-refuses-index-incomplete"

(
  cd "$TMP"
  python3 "$ROOT/scripts/planning_request_budget.py" "$TMP" status | grep -q totalCharged
) && ok "operator-observable-budget" || bad "operator-observable-budget"

exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
