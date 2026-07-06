#!/usr/bin/env python3
"""PRD 056 Phase 0 — deliver run-entry materialize fixtures (R10, R17-R20)."""
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
    completed = subprocess.run(
        ["bash", "-c", src],
        cwd=str(root),
        env=env,
        shell=False,
    )
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
export SW_FORCE_MATERIALIZE=1
export SW_ISSUES_FIXTURE=1
PY_STORE="$ROOT/scripts/planning_store.py"
PY_MAT="$ROOT/scripts/planning_materialize.py"
PY_DELIVER="$ROOT/scripts/wave_deliver.py"
PY_GATE="$ROOT/scripts/planning_deliver_gate.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }
TMP="$(mktemp -d)"
CFG_BACKUP=""
if [[ -f "$ROOT/.cursor/workflow.config.json" ]]; then
  CFG_BACKUP="$TMP/workflow.config.json.bak"
  cp "$ROOT/.cursor/workflow.config.json" "$CFG_BACKUP"
fi
restore_config() {
  if [[ -n "$CFG_BACKUP" ]]; then
    cp "$CFG_BACKUP" "$ROOT/.cursor/workflow.config.json"
  else
    rm -f "$ROOT/.cursor/workflow.config.json"
  fi
}
trap 'restore_config; rm -rf "$TMP" "$ROOT/docs/prds/_fixture-run-entry-filestore" "$ROOT/docs/prds/099-run-entry-fixture" "$ROOT/.cursor/planning-materialized"' EXIT

write_file_store_config() {
  python3 - <<PY
import json
from pathlib import Path
p = Path("$ROOT/.cursor/workflow.config.json")
p.parent.mkdir(parents=True, exist_ok=True)
cfg = {"version": 1, "planning": {"store": {"backend": "in-repo-public"}}}
p.write_text(json.dumps(cfg, indent=2) + "\\n", encoding="utf-8")
PY
}

write_issue_store_config() {
  python3 - <<PY
import json
from pathlib import Path
cfg = {
  "version": 1,
  "planning": {
    "store": {
      "backend": "issue-store",
      "issuesProvider": "github-issues",
      "projectKey": "fixture-alpha",
      "storeLocation": {"mode": "separate-project", "owner": "grdavies", "repo": "planning"},
    }
  },
}
p = Path("$ROOT/.cursor/workflow.config.json")
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(cfg, indent=2) + "\\n", encoding="utf-8")
PY
}

seed_issue_fixtures() {
  PRD_BODY=$'---\\nid: 099-prd-run-entry-fixture\\ntype: prd\\nstatus: proposed\\n---\\n# PRD fixture\\n'
  python3 "$PY_STORE" --root "$ROOT" put --backend issue-store \
    --unit-id 099-prd-run-entry-fixture \
    --body-path "$PRD_REL" \
    --content "$PRD_BODY" >/dev/null
  python3 "$PY_STORE" --root "$ROOT" freeze --backend issue-store \
    --unit-id 099-prd-run-entry-fixture \
    --body-path "$PRD_REL" --no-distill >/dev/null
  python3 "$PY_STORE" --root "$ROOT" put --backend issue-store \
    --unit-id tasks-099-run-entry-fixture \
    --body-path "$TASK_REL" \
    --content "$TASK_BODY" >/dev/null
  python3 "$PY_STORE" --root "$ROOT" freeze --backend issue-store \
    --unit-id tasks-099-run-entry-fixture \
    --body-path "$TASK_REL" --no-distill >/dev/null
}

FS_TASK_REL="docs/prds/_fixture-run-entry-filestore/tasks-099-fs-run-entry.md"
TASK_REL="docs/prds/099-run-entry-fixture/tasks-099-run-entry-fixture.md"
PRD_REL="docs/prds/099-run-entry-fixture/099-prd-run-entry-fixture.md"
TASK_BODY=$(cat <<'EOF'
---
frozen: true
visibility: public
---
# Tasks — run-entry fixture

### 0. Fixture phase
- [ ] **0.1** fixture task
  - **File:** scripts/example.py
EOF
)

rm -rf "$ROOT/.cursor/planning-materialized"
write_file_store_config
mkdir -p "$ROOT/docs/prds/_fixture-run-entry-filestore"
printf '%s' "$TASK_BODY" >"$ROOT/$FS_TASK_REL"
if OUT=$(python3 "$PY_MAT" --root "$ROOT" run-entry --task-list "$FS_TASK_REL" 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('reason') in ('file-store-byte-identical','logical-path-present')"; then
    ok "file-store-skip:run-entry"
  else
    bad "file-store-skip:run-entry"
  fi
else
  bad "file-store-skip:run-entry"
fi
if [[ -d "$ROOT/.cursor/planning-materialized/docs/prds/_fixture-run-entry-filestore" ]]; then
  bad "file-store-skip:no-materialized-dir"
else
  ok "file-store-skip:no-materialized-dir"
fi
rm -f "$ROOT/$FS_TASK_REL"
rm -rf "$ROOT/docs/prds/_fixture-run-entry-filestore"

write_issue_store_config
python3 "$PY_STORE" --root "$ROOT" clear-issue-fixture >/dev/null
seed_issue_fixtures
if [[ -f "$ROOT/$TASK_REL" ]]; then
  bad "issue-run-entry:no-repo-stub-after-put"
else
  ok "issue-run-entry:no-repo-stub-after-put"
fi
if OUT=$(python3 "$PY_MAT" --root "$ROOT" run-entry --task-list "$TASK_REL"); then
  DEST="$ROOT/.cursor/planning-materialized/$TASK_REL"
  if [[ -f "$DEST" ]] && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('action')=='run-entry-materialize'"; then
    ok "issue-run-entry:materialize"
  else
    bad "issue-run-entry:materialize"
  fi
else
  bad "issue-run-entry:materialize"
fi
if OUT=$(python3 "$PY_DELIVER" "$ROOT" preflight --task-list "$TASK_REL" --skip-base-check 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'"; then
    ok "issue-run-entry:preflight"
  else
    bad "issue-run-entry:preflight"
  fi
else
  bad "issue-run-entry:preflight"
fi
if OUT=$(python3 "$PY_DELIVER" "$ROOT" plan --task-list "$TASK_REL" --skip-base-check --dry-run 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'"; then
    ok "issue-run-entry:plan"
  else
    bad "issue-run-entry:plan"
  fi
else
  bad "issue-run-entry:plan"
fi
export SW_DISCOVER_SOURCE=issue
if OUT=$(python3 "$PY_GATE" "$ROOT" next 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('taskList')=='$TASK_REL'"; then
    ok "issue-deliver-next:taskList"
  else
    bad "issue-deliver-next:taskList"
  fi
else
  bad "issue-deliver-next:taskList"
fi
python3 "$PY_STORE" --root "$ROOT" clear-issue-fixture >/dev/null
write_issue_store_config
seed_issue_fixtures
python3 - <<INNER
import sys
from pathlib import Path
sys.path.insert(0, "$ROOT/scripts")
from issues_lib import FixtureIssuesStore
store = FixtureIssuesStore(Path("$ROOT/.cursor/hooks/state/issue-store-fixture.json"))
rec = next(i for i in store._issues.values() if i.unit_id == "tasks-099-run-entry-fixture")
rec.body = rec.body + "\\n<!-- tamper -->"
rec.touch()
store._persist()
INNER
if OUT=$(python3 "$PY_MAT" --root "$ROOT" run-entry --task-list "$TASK_REL" 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('code')=='tamper-detected'"; then
    ok "issue-run-entry:tamper-halt"
  else
    bad "issue-run-entry:tamper-halt"
  fi
else
  ok "issue-run-entry:tamper-halt"
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
