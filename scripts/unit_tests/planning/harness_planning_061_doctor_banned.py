#!/usr/bin/env python3
"""PRD 061 task 1.3 — doctor + completion_log/reconcile_lib fail-closed on banned writes (R3)."""
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
# PRD 061 task 1.3 — doctor + completion_log/reconcile_lib banned-write fail-closed (R3).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
export SW_ISSUES_FIXTURE=1
PY_STORE="$ROOT/scripts/planning_store.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

init_issue_store_fixture() {
  local dest="$1"
  mkdir -p "$dest/.cursor" "$dest/docs/planning/prd/prd-061-doctor-banned"
  git -C "$dest" init -q
  git -C "$dest" config user.email t@t.com
  git -C "$dest" config user.name T
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
      "projectKey": "fixture-061",
    }
  },
}
p = Path("$dest/.cursor/workflow.config.json")
p.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
PY
  cat >"$dest/docs/planning/prd/prd-061-doctor-banned/prd-061-doctor-banned.md" <<'EOF'
---
id: prd-061-doctor-banned
type: prd
status: draft
---
# PRD 061 doctor banned fixture
EOF
  mkdir -p "$dest/docs/prds"
  cp "$ROOT/docs/prds/INDEX.md" "$dest/docs/prds/INDEX.md" 2>/dev/null || printf '# index\n| # | slug | prd | tasks | status |\n' >"$dest/docs/prds/INDEX.md"
  cp "$ROOT/docs/prds/COMPLETION-LOG.md" "$dest/docs/prds/COMPLETION-LOG.md" 2>/dev/null || printf '# log\n| Date | PRD | Phase | Notes |\n|---|---|---|---|\n' >"$dest/docs/prds/COMPLETION-LOG.md"
  git -C "$dest" add . && git -C "$dest" commit -q -m init
}

ISSUE_FIX=$(mktemp -d)
init_issue_store_fixture "$ISSUE_FIX"

# --- doctor-dirty-banned-path (R3): planning_store doctor CLI ---
if OUT=$(python3 "$PY_STORE" --root "$ISSUE_FIX" doctor 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('verdict') == 'pass', d
"; then
  ok "doctor-dirty-banned-path:clean-pass"
else
  bad "doctor-dirty-banned-path:clean-pass"
fi
echo "# dirty" >>"$ISSUE_FIX/docs/prds/INDEX.md"
set +e
DIRTY_OUT=$(python3 "$PY_STORE" --root "$ISSUE_FIX" doctor 2>/dev/null)
DIRTY_RC=$?
set -e
if [[ "$DIRTY_RC" -eq 20 ]] && echo "$DIRTY_OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('verdict') == 'fail', d
assert d.get('halt') == 'banned-living-doc-drift', d
"; then
  ok "doctor-dirty-banned-path:dirty-fail"
else
  bad "doctor-dirty-banned-path:dirty-fail"
fi
git -C "$ISSUE_FIX" checkout -q -- docs/prds/INDEX.md

# --- completion_log fail-closed under issue-store ---
if python3 - <<PY
import json
import os
import sys
from pathlib import Path
root = Path("$ISSUE_FIX")
sys.path.insert(0, str(Path("$ROOT/scripts")))
os.environ["SW_ISSUES_FIXTURE"] = "1"
from _sw.completion_log import append_log_idempotent
out = append_log_idempotent(root, prd="061", phase="all", notes="fixture")
assert out.get("verdict") == "fail", out
assert out.get("halt") == "banned-living-doc-write", out
print("ok")
PY
then
  ok "completion-log-banned-write-fail-closed"
else
  bad "completion-log-banned-write-fail-closed"
fi

# --- reconcile_lib fail-closed under issue-store ---
if python3 - <<PY
import json
import os
import sys
from pathlib import Path
root = Path("$ISSUE_FIX")
sys.path.insert(0, str(Path("$ROOT/scripts")))
os.environ["SW_ISSUES_FIXTURE"] = "1"
import reconcile_lib as rl
out = rl.set_index_status(root, "061", "in-progress")
assert out.get("verdict") == "fail", out
assert out.get("halt") == "banned-living-doc-write", out
out2 = rl.reconcile_prd_index(root, dry_run=False, allow_default=True)
assert out2.get("verdict") == "fail", out2
assert out2.get("halt") == "banned-living-doc-write", out2
print("ok")
PY
then
  ok "reconcile-lib-banned-write-fail-closed"
else
  bad "reconcile-lib-banned-write-fail-closed"
fi

rm -rf "$ISSUE_FIX"
exit $FAIL
"""

if __name__ == "__main__":
    raise SystemExit(main())
