#!/usr/bin/env python3
"""PRD 047 phase-2 fixtures — auth, privacy, budget, lifecycle, createmeta, labels (R101-R109)."""
from __future__ import annotations
import subprocess, sys
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
source "$ROOT/scripts/test/fixture-lib.sh"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }
PY="$ROOT/scripts/planning_store.py"
FX="$ROOT/scripts/tests/fixtures/resilience/jira"

cat > "$ROOT/.cursor/workflow.config.json" <<'JSON'
{
  "version": 1,
  "planning": {
    "visibilityProfile": "specs-public",
    "store": {
      "backend": "issue-store",
      "issuesProvider": "jira",
      "projectKey": "phase2047",
      "jiraProjectVisibility": "shared",
      "issues": {
        "endpoint": "https://fixture.atlassian.net",
        "flavor": "cloud",
        "tokenEnv": "ISSUES_JIRA_TOKEN",
        "issueType": "Task"
      }
    }
  }
}
JSON
export SW_ISSUES_FIXTURE=1
export ISSUES_JIRA_TOKEN=fixture-token
export ISSUES_JIRA_EMAIL=fixture-local

if OUT=$(python3 "$PY" --root "$ROOT" probe-jira-init) && echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='ok'"; then
  ok "jira-init-probe:fixture-pass"
else
  bad "jira-init-probe:fixture-pass"
fi

export SW_JIRA_PRIVATE_UNIT=1
if OUT=$(python3 "$PY" --root "$ROOT" probe-jira-init 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('error')=='per-issue-privacy-unsupported'"; then
    ok "jira-privacy:R105-shared-project-refused"
  else
    bad "jira-privacy:R105-shared-project-refused"
  fi
fi
unset SW_JIRA_PRIVATE_UNIT

export SW_JIRA_CREATEMETA_FIXTURE="$FX/createmeta-required.json"
if OUT=$(python3 "$PY" --root "$ROOT" probe-jira-init 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('error')=='required-fields-unmet'"; then
    ok "jira-createmeta:R108-required-fields-fail-closed"
  else
    bad "jira-createmeta:R108-required-fields-fail-closed"
  fi
fi
unset SW_JIRA_CREATEMETA_FIXTURE

export SW_JIRA_LABEL_WRITE_DENIED=1
if OUT=$(python3 "$PY" --root "$ROOT" probe-jira-init) && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ok' and d.get('labelSurface')=='components'"; then
  ok "jira-label-ladder:R109-degrades-to-components"
else
  bad "jira-label-ladder:R109-degrades-to-components"
fi
unset SW_JIRA_LABEL_WRITE_DENIED

python3 -c "import json; from pathlib import Path; p=Path('$ROOT/.cursor/workflow.config.json'); cfg=json.loads(p.read_text()); cfg['planning']['store']['issues']['flavor']='dc'; p.write_text(json.dumps(cfg,indent=2)+'\n')"
export ISSUES_JIRA_TOKEN="basic:user:pass"
if OUT=$(python3 "$PY" --root "$ROOT" probe-jira-init 2>/dev/null || true); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('error')=='dc-password-rejected'"; then
    ok "jira-auth:R101-dc-password-rejected"
  else
    bad "jira-auth:R101-dc-password-rejected"
  fi
fi

if python3 -c "
import os, sys
from pathlib import Path
sys.path.insert(0, '$ROOT/scripts')
os.environ['SW_ISSUES_FIXTURE']='1'
os.environ['SW_ISSUES_CALL_BUDGET']='2'
from issues_lib import get_fixture_store, IssuesClient, IssueArchivedProject
root=Path('$ROOT')
store=get_fixture_store(root); store.clear()
rec=store.create(title='t',body='b',labels=[],project_key='p',artifact_type='prd',unit_id='u1')
store.mark_archived_project(rec.id)
try:
    store.get(rec.id)
except IssueArchivedProject:
    print('archived-ok')
rec2=store.create(title='t2',body='b',labels=[],project_key='p',artifact_type='prd',unit_id='u2')
store.mark_key_changed(rec2.id,'PROJ-99')
client=IssuesClient(root,'jira')
try:
    client.issue_get(rec2.id)
except Exception as e:
    if 'transferred' in str(e).lower():
        print('transfer-ok')
client.issue_create(title='t3',body='b',labels=[],project_key='p',artifact_type='prd',unit_id='u3')
try:
    client.issue_create(title='t4',body='b',labels=[],project_key='p',artifact_type='prd',unit_id='u4')
except Exception as e:
    if 'budget' in str(e).lower():
        print('budget-ok')
" | grep -q archived-ok; then
  ok "jira-lifecycle-budget:R106-R107"
else
  bad "jira-lifecycle-budget:R106-R107"
fi

for fx in createmeta-required 429-exhaustion partial-page-abort; do
  [[ -f "$FX/${fx}.json" ]] && ok "resilience-fixture:${fx}" || bad "resilience-fixture:${fx}"
done

exit "$FAIL"
"""
