#!/usr/bin/env python3
"""PRD 056 Phase 9 — separate-project docs bypass fixtures (R14–R16)."""
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
export SW_ISSUES_FIXTURE=1
export SW_FORCE_MATERIALIZE=1
PY_STORE="$ROOT/scripts/planning_store.py"
PY_DOCS_WT="$ROOT/scripts/docs_worktree.py"
PY_SPEC="$ROOT/scripts/wave_spec_seed.py"
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
trap 'restore_config; git -C "$ROOT" reset -q HEAD -- docs/brainstorms/_fixture-sep-bypass.md docs/prds/_fixture-sep-bypass 2>/dev/null || true; git -C "$ROOT" checkout -q -- docs/brainstorms/_fixture-sep-bypass.md docs/prds/_fixture-sep-bypass 2>/dev/null || true; rm -rf "$TMP" "$ROOT/docs/brainstorms/_fixture-sep-bypass.md" "$ROOT/docs/prds/_fixture-sep-bypass" "$ROOT/.cursor/planning-materialized"' EXIT

TASK_REL="docs/prds/099-sep-bypass-fixture/tasks-099-sep-bypass-fixture.md"
PRD_REL="docs/prds/099-sep-bypass-fixture/099-prd-sep-bypass-fixture.md"
STRAY_REL="docs/prds/_fixture-sep-bypass/stray-prd.md"
GITIGNORE_REL="docs/prds/_fixture-sep-bypass/gitignored-prd.md"
TOPIC="sep-bypass-fixture"

write_file_store_config() {
  python3 - <<PY
import json
from pathlib import Path
p = Path("$ROOT/.cursor/workflow.config.json")
p.parent.mkdir(parents=True, exist_ok=True)
cfg = {"version": 1, "planning": {"store": {"backend": "in-repo-public"}}}
p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
PY
}

write_issue_store_config() {
  local target_root="${1:-$ROOT}"
  python3 - <<PY
import json
from pathlib import Path
cfg = {
  "version": 1,
  "planning": {
    "store": {
      "backend": "issue-store",
      "issuesProvider": "github-issues",
      "projectKey": "fixture-sep",
      "storeLocation": {"mode": "separate-project", "owner": "grdavies", "repo": "planning"},
    }
  },
}
p = Path("$target_root/.cursor/workflow.config.json")
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
PY
}

write_issue_store_config_isolated() {
  local target_root="$1"
  python3 - <<PY
import json
from pathlib import Path
cfg = {
  "version": 1,
  "host": {"provider": "github"},
  "planning": {
    "store": {
      "backend": "issue-store",
      "issuesProvider": "github-issues",
      "projectKey": "fixture-sep",
      "storeLocation": {"mode": "separate-project", "owner": "grdavies", "repo": "planning"},
    }
  },
}
p = Path("$target_root/.cursor/workflow.config.json")
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
PY
}

init_doctor_repo() {
  DOCTOR_REPO="$TMP/doctor-repo"
  mkdir -p "$DOCTOR_REPO/.cursor"
  git -C "$DOCTOR_REPO" init -q
  git -C "$DOCTOR_REPO" config user.email "fixture@test"
  git -C "$DOCTOR_REPO" config user.name "fixture"
  git -C "$DOCTOR_REPO" remote add origin https://github.com/grdavies/shipwright.git
  write_issue_store_config_isolated "$DOCTOR_REPO"
  git -C "$DOCTOR_REPO" add .cursor/workflow.config.json
  git -C "$DOCTOR_REPO" commit -q -m "init"
}

seed_issue_task_fixture() {
  TASK_BODY=$(cat <<'EOF'
---
frozen: true
visibility: public
---
# Tasks — sep bypass fixture

### 0. Fixture phase
- [x] **0.1** fixture
  - **File:** scripts/wave_spec_seed.py
  - **Expected:** separate-project skip
  - **R-IDs:** R16
EOF
)
  PRD_BODY=$'---\nid: 099-prd-sep-bypass-fixture\ntype: feat\nstatus: proposed\nvisibility: public\n---\n# PRD\n'
  python3 "$PY_STORE" --root "$ROOT" put --backend issue-store \
    --unit-id 099-prd-sep-bypass-fixture --body-path "$PRD_REL" --content "$PRD_BODY" >/dev/null
  python3 "$PY_STORE" --root "$ROOT" freeze --backend issue-store \
    --unit-id 099-prd-sep-bypass-fixture --body-path "$PRD_REL" --no-distill >/dev/null
  python3 "$PY_STORE" --root "$ROOT" put --backend issue-store \
    --unit-id tasks-099-sep-bypass-fixture --body-path "$TASK_REL" --content "$TASK_BODY" >/dev/null
  python3 "$PY_STORE" --root "$ROOT" freeze --backend issue-store \
    --unit-id tasks-099-sep-bypass-fixture --body-path "$TASK_REL" --no-distill >/dev/null
}

# --- 9.1 file-store: docs_worktree still provisions path (dry-run) ---
write_file_store_config
if OUT=$(python3 "$PY_DOCS_WT" provision --topic "$TOPIC" --dry-run 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('path') and not d.get('skipped')"; then
    ok "docs-worktree-file-store:provision-path"
  else
    bad "docs-worktree-file-store:provision-path"
  fi
else
  bad "docs-worktree-file-store:provision-path"
fi

# --- 9.1 separate-project: docs_worktree skipped, issue refs only ---
write_issue_store_config
if OUT=$(python3 "$PY_DOCS_WT" provision --topic "$TOPIC" 2>/dev/null); then
  if echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('skipped') and d.get('reason')=='separate-project-issue-store'
h=d.get('handoff',{})
assert h.get('issueRefsOnly') and h.get('projectKey')=='fixture-sep'
assert h.get('storeLocation',{}).get('owner')=='grdavies'
assert 'path' not in d and 'path' not in h
"; then
    ok "docs-worktree-separate-project:provision-skip"
  else
    bad "docs-worktree-separate-project:provision-skip"
  fi
else
  bad "docs-worktree-separate-project:provision-skip"
fi
WT_PATH="$ROOT/.sw-worktrees/docs-$TOPIC"
if [[ ! -d "$WT_PATH" ]]; then
  ok "docs-worktree-separate-project:no-local-worktree"
else
  bad "docs-worktree-separate-project:no-local-worktree"
fi

# --- 9.2 doctor: isolated repo tests ---
init_doctor_repo
DOCTOR_STRAY="docs/prds/_fixture-sep-bypass/stray-prd.md"
DOCTOR_GITIGNORE="docs/prds/_fixture-sep-bypass/gitignored-prd.md"
if OUT=$(python3 "$PY_STORE" --root "$DOCTOR_REPO" doctor 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'"; then
    ok "doctor-separate-project:clean-pass"
  else
    bad "doctor-separate-project:clean-pass"
  fi
else
  bad "doctor-separate-project:clean-pass"
fi

mkdir -p "$DOCTOR_REPO/docs/prds/_fixture-sep-bypass"
printf '%s\n' '# stray' >"$DOCTOR_REPO/$DOCTOR_STRAY"
git -C "$DOCTOR_REPO" add "$DOCTOR_STRAY"
set +e
OUT=$(python3 "$PY_STORE" --root "$DOCTOR_REPO" doctor 2>/dev/null)
RC=$?
set -e
if [[ "$RC" -eq 20 ]]; then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='fail' and '$DOCTOR_STRAY' in d.get('paths',[])"; then
    ok "doctor-separate-project:tracked-stray-exit20"
  else
    bad "doctor-separate-project:tracked-stray-exit20"
  fi
else
  bad "doctor-separate-project:tracked-stray-exit20"
fi
git -C "$DOCTOR_REPO" reset -q HEAD -- "$DOCTOR_STRAY"
rm -f "$DOCTOR_REPO/$DOCTOR_STRAY"

mkdir -p "$DOCTOR_REPO/docs/prds/_fixture-sep-bypass"
printf '%s\n' '# gitignored' >"$DOCTOR_REPO/$DOCTOR_GITIGNORE"
if OUT=$(python3 "$PY_STORE" --root "$DOCTOR_REPO" doctor 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'"; then
    ok "doctor-separate-project:gitignored-only-pass"
  else
    bad "doctor-separate-project:gitignored-only-pass"
  fi
else
  bad "doctor-separate-project:gitignored-only-pass"
fi

# --- 9.2 doctor: file-store skipped (no-op) on main repo ---
write_file_store_config
mkdir -p "$ROOT/docs/prds/_fixture-sep-bypass"
STRAY_REL="docs/prds/_fixture-sep-bypass/stray-prd.md"
printf '%s\n' '# file-store stray' >"$ROOT/$STRAY_REL"
git -C "$ROOT" add "$STRAY_REL" 2>/dev/null || true
if OUT=$(python3 "$PY_STORE" --root "$ROOT" doctor 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('skipped') and d.get('verdict')=='pass'"; then
    ok "doctor-file-store:skipped-noop"
  else
    bad "doctor-file-store:skipped-noop"
  fi
else
  bad "doctor-file-store:skipped-noop"
fi
git -C "$ROOT" reset -q HEAD -- "$STRAY_REL" 2>/dev/null || true
rm -rf "$ROOT/docs/prds/_fixture-sep-bypass"

# --- 9.3 spec-seed: separate-project skips code-repo copy ---
write_issue_store_config
seed_issue_task_fixture
if OUT=$(python3 "$PY_SPEC" "$ROOT" spec-seed --task-list "$TASK_REL" 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('skipped') and d.get('reason')=='separate-project-issue-store'"; then
    ok "spec-seed-separate-project:skip-copy"
  else
    bad "spec-seed-separate-project:skip-copy"
  fi
else
  bad "spec-seed-separate-project:skip-copy"
fi
if [[ ! -d "$ROOT/docs/prds/099-sep-bypass-fixture" ]]; then
  ok "spec-seed-separate-project:no-repo-doc-dir"
else
  bad "spec-seed-separate-project:no-repo-doc-dir"
fi
python3 "$PY_STORE" --root "$ROOT" clear-issue-fixture >/dev/null

exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
