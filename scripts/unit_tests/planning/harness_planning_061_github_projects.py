#!/usr/bin/env python3
"""PRD 061 phase 3 — GitHub Projects v2 + operator projection matrix (R10-R15, R11a, R11b, R29a)."""
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
PY="$ROOT/scripts/planning_store.py"
GP="$ROOT/scripts/planning_github_projects_v2.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- projects-v2-upsert (R11) ---
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
git -C "$TMP" init -q
mkdir -p "$TMP/.cursor/hooks/state"
cat > "$TMP/.cursor/workflow.config.json" <<'CFG'
{
  "version": 1,
  "planning": {
    "store": {
      "backend": "issue-store",
      "issuesProvider": "github-issues",
      "projectKey": "matrix-fixture",
      "storeLocation": {"mode": "separate-project", "owner": "acme", "repo": "planning"},
      "operatorProjection": {
        "githubProjects": {
          "enabled": true,
          "ownerLogin": "acme",
          "projectNumber": 1,
          "budget": {"maxCalls": 5}
        }
      }
    }
  },
  "host": {"provider": "github"}
}
CFG
export SW_ISSUES_FIXTURE=1
export SW_PROJECTS_FIXTURE=1
if OUT1=$(python3 "$PY" --root "$TMP" projection-refresh) &&    OUT2=$(python3 "$PY" --root "$TMP" projection-refresh) &&    echo "$OUT1" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='ok'; assert d.get('created',0)>=1" &&    echo "$OUT2" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='ok'; assert d.get('skipped',0)>=1 or any(u.get('action')=='noop' for u in d.get('upserts',[]))"; then
  ok "projects-v2-upsert"
else
  bad "projects-v2-upsert"
fi

# --- projects-missing-scope-degrade (R11a) ---
unset SW_PROJECTS_FIXTURE
if OUT=$(python3 "$GP" --root "$TMP" probe-scope) &&    echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('state') in {'available','projection-unavailable'}"; then
  ok "projects-missing-scope-degrade"
else
  bad "projects-missing-scope-degrade"
fi

# --- matrix-docs-present (R10) ---
MATRIX="$ROOT/core/sw-reference/planning-deliver-parity-matrix.md"
for needle in github-issues jira gitlab-issues in-repo-public linear notion; do
  if ! grep -q "$needle" "$MATRIX"; then bad "matrix-docs-present:$needle"; FAIL=1; fi
done
if [[ $FAIL -eq 0 ]]; then ok "matrix-docs-present"; fi

# --- po-browse-four-questions (R11b) ---
WF="$ROOT/docs/guides/workflows.md"
COUNT=0
for q in "which gaps a PRD absorbs" "which brainstorms feed a PRD" "task/phase completion" "backlog vs in-flight vs done"; do
  grep -qi "$q" "$WF" && COUNT=$((COUNT+1)) || true
done
if [[ "$COUNT" -ge 4 ]]; then ok "po-browse-four-questions"; else bad "po-browse-four-questions"; fi

# --- cutover-gate-with-projects (R29a) ---
export SW_PROJECTS_FIXTURE=1
if OUT=$(python3 "$GP" --root "$TMP" cutover-gate) &&    echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('ready') is True"; then
  ok "cutover-gate-with-projects"
else
  bad "cutover-gate-with-projects"
fi

# --- pattern rows (R12-R15) ---
for row in jira-matrix-row gitlab-target-row linear-pattern-recorded notion-pattern-recorded; do
  case "$row" in
    jira-matrix-row) needle='`jira`' ;;
    gitlab-target-row) needle='`gitlab-issues`' ;;
    linear-pattern-recorded) needle='`linear`' ;;
    notion-pattern-recorded) needle='`notion`' ;;
  esac
  if grep -q "$needle" "$MATRIX"; then ok "$row"; else bad "$row"; fi
done

# --- facade projection_refresh shipped ---
if OUT=$(python3 "$PY" --root "$ROOT" list-facade) &&    echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); shipped=set(d.get('shipped',[])); assert 'projection_refresh' in shipped"; then
  ok "conformance-harness-floor"
else
  bad "conformance-harness-floor"
fi

exit $FAIL
"""

if __name__ == "__main__":
    raise SystemExit(main())
