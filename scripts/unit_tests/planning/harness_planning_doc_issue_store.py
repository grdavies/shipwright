#!/usr/bin/env python3
"""PRD 056 Phase 8 — issue-store doc pipeline authoring fixtures (R11, R13)."""
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
PY_STORE="$ROOT/scripts/planning_store.py"
PY_SPEC="$ROOT/scripts/spec-rigor-check.py"
PY_LINK="$ROOT/scripts/doc_link.py"
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
trap 'restore_config; rm -rf "$TMP" "$ROOT/docs/brainstorms/2026-07-06-doc-issue-store-fixture-requirements.md" "$ROOT/docs/prds/099-doc-issue-store-fixture" "$ROOT/docs/prds/_fixture-doc-filestore"' EXIT

BS_REL="docs/brainstorms/2026-07-06-doc-issue-store-fixture-requirements.md"
PRD_REL="docs/prds/099-doc-issue-store-fixture/099-prd-doc-issue-store-fixture.md"
TASK_REL="docs/prds/099-doc-issue-store-fixture/tasks-099-doc-issue-store-fixture.md"
BS_UID="2026-07-06-doc-issue-store-fixture-requirements"
PRD_UID="099-prd-doc-issue-store-fixture"
TASK_UID="tasks-099-doc-issue-store-fixture"
FS_BS_REL="docs/brainstorms/_fixture-doc-filestore-requirements.md"

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
  python3 - <<PY
import json
from pathlib import Path
cfg = {
  "version": 1,
  "planning": {
    "store": {
      "backend": "issue-store",
      "issuesProvider": "github-issues",
      "projectKey": "fixture-doc",
      "storeLocation": {"mode": "separate-project", "owner": "grdavies", "repo": "planning"},
    }
  },
}
p = Path("$ROOT/.cursor/workflow.config.json")
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
PY
}

read_fixture() {
  case "$1" in
    brainstorm) cat <<'EOF'
---
date: 2026-07-06
topic: doc-issue-store-fixture
visibility: public
---
# Fixture brainstorm

## Summary
Issue-store doc pipeline dry-run fixture.

## Problem Frame
Authoring must route through planning_store.put only.

## Key Decisions
- **D1** Use separate-project issue-store config.

## Requirements
- **R1** Doc commands must not create code-repo stub files under docs/brainstorms or docs/prds.

## Success Criteria
- Harness asserts zero git doc diff after simulated /sw-doc puts.

## Scope Boundaries
- File-store regression only.

## Open Questions
- none
EOF
    ;;
    prd) cat <<'EOF'
---
date: 2026-07-06
topic: doc-issue-store-fixture
visibility: public
brainstorm: docs/brainstorms/2026-07-06-doc-issue-store-fixture-requirements.md
---
# PRD fixture

## Overview
Issue-store doc pipeline authoring fixture.

## Goals
- Route brainstorm, PRD, and tasks through planning_store.put.

## Non-Goals
- Local docs/brainstorms or docs/prds writes in separate-project mode.

## Requirements
- **R1** Doc commands must not create code-repo stub files under docs/brainstorms or docs/prds.

## Technical Requirements
- Use virtual body-path + unit id handles for gates.

## Security & Compliance
- Fixture only.

## Testing Strategy
- harness_planning_doc_issue_store.py

## Rollout Plan
- Phase 8.

## Decision Log
| Date | Decision |
| --- | --- |
| 2026-07-06 | put-only authoring (D1) |

## Open Questions
None
EOF
    ;;
    tasks) cat <<'EOF'
---
frozen: false
visibility: public
---
# Tasks — doc issue-store fixture

## Tasks

### 1. Fixture phase
- [ ] **1.1** fixture task
  - **File:** scripts/planning_artifact_handle.py
  - **Expected:** issue-store handle resolution
  - **R-IDs:** R1

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |

## Traceability

| R-ID | Task ref | Test scenario | ZOMBIES |
|------|----------|---------------|---------|
| R1 | 1.1 | virtual handle gate pass | Z: file-store; O: put only; M: full chain; B: missing unit; I: amend; E: freeze; S: dry-run |
EOF
    ;;
  esac
}

doc_tree_clean() {
  [[ ! -f "$ROOT/$BS_REL" ]] && [[ ! -d "$ROOT/docs/prds/099-doc-issue-store-fixture" ]]
}

# --- file-store unchanged: local write still allowed ---
write_file_store_config
mkdir -p "$ROOT/docs/brainstorms"
printf '%s\n' "# file-store stub" >"$ROOT/$FS_BS_REL"
if [[ -f "$ROOT/$FS_BS_REL" ]]; then
  ok "file-store-unchanged:local-write"
else
  bad "file-store-unchanged:local-write"
fi
rm -f "$ROOT/$FS_BS_REL"

# --- issue-store: simulated /sw-doc dry-run uses put only ---
write_issue_store_config
python3 "$PY_STORE" --root "$ROOT" clear-issue-fixture >/dev/null
BS_BODY="$(read_fixture brainstorm)"
PRD_BODY="$(read_fixture prd)"
TASK_BODY="$(read_fixture tasks)"
python3 "$PY_STORE" --root "$ROOT" put --backend issue-store --unit-id "$BS_UID" --body-path "$BS_REL" --content "$BS_BODY" >/dev/null
python3 "$PY_STORE" --root "$ROOT" put --backend issue-store --unit-id "$PRD_UID" --body-path "$PRD_REL" --content "$PRD_BODY" >/dev/null
python3 "$PY_STORE" --root "$ROOT" put --backend issue-store --unit-id "$TASK_UID" --body-path "$TASK_REL" --content "$TASK_BODY" >/dev/null
if doc_tree_clean; then
  ok "issue-doc-dry-run:no-repo-doc-files"
else
  bad "issue-doc-dry-run:no-repo-doc-files"
fi
PUT_COUNT=$(python3 - <<PY
import json
from pathlib import Path
store = json.loads(Path("$ROOT/.cursor/hooks/state/issue-store-fixture.json").read_text())
print(len(store.get("issues", {})))
PY
)
if [[ "$PUT_COUNT" -ge 3 ]]; then
  ok "issue-doc-dry-run:fixture-puts"
else
  bad "issue-doc-dry-run:fixture-puts"
fi
if OUT=$(python3 "$PY_SPEC" --artifact brainstorm --path "$BS_REL" --unit-id "$BS_UID" 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'"; then
    ok "issue-doc-dry-run:spec-rigor-brainstorm-virtual"
  else
    bad "issue-doc-dry-run:spec-rigor-brainstorm-virtual"
  fi
else
  bad "issue-doc-dry-run:spec-rigor-brainstorm-virtual"
fi
if OUT=$(python3 "$PY_SPEC" --artifact prd --path "$PRD_REL" --unit-id "$PRD_UID" --tier standard 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'"; then
    ok "issue-doc-dry-run:spec-rigor-prd-virtual"
  else
    bad "issue-doc-dry-run:spec-rigor-prd-virtual"
  fi
else
  bad "issue-doc-dry-run:spec-rigor-prd-virtual"
fi
if OUT=$(python3 "$PY_SPEC" --artifact tasks --path "$TASK_REL" --unit-id "$TASK_UID" --prd "$PRD_REL" --prd-unit-id "$PRD_UID" 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'"; then
    ok "issue-doc-dry-run:spec-rigor-tasks-virtual"
  else
    bad "issue-doc-dry-run:spec-rigor-tasks-virtual"
  fi
else
  bad "issue-doc-dry-run:spec-rigor-tasks-virtual"
fi
if OUT=$(python3 "$PY_LINK" check --root "$ROOT" --path "$PRD_REL" --unit-id "$PRD_UID" --tier full 2>/dev/null); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'"; then
    ok "issue-doc-dry-run:doc-link-virtual"
  else
    bad "issue-doc-dry-run:doc-link-virtual"
  fi
else
  bad "issue-doc-dry-run:doc-link-virtual"
fi
python3 "$PY_STORE" --root "$ROOT" clear-issue-fixture >/dev/null

exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
