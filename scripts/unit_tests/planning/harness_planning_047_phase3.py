#!/usr/bin/env python3
"""PRD 047 phase-3 — Bitbucket guidance wiring + end-to-end acceptance (R32b, D25)."""
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
source "$ROOT/scripts/test/fixture-lib.sh"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }
PY="$ROOT/scripts/planning_store.py"

write_cfg() {
  python3 - <<PY
import json
from pathlib import Path
Path("$ROOT/.cursor/workflow.config.json").write_text(json.dumps($1, indent=2) + "\\n", encoding="utf-8")
PY
}

write_cfg '{
  "version": 1,
  "host": {"provider": "bitbucket"},
  "planning": {"store": {"backend": "issue-store", "projectKey": "bb047"}}
}'
if OUT=$(python3 "$PY" --root "$ROOT" bitbucket-issue-store-guidance) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('hostProvider')=='bitbucket'
assert d.get('defaultPath')=='separate-project'
assert d.get('never')=='native-bitbucket-issues'
opts={o['path']:o for o in d.get('options',[])}
assert 'separate-project' in opts and 'jira' in opts
"; then
  ok "bitbucket-guidance:unset-issues-provider"
else
  bad "bitbucket-guidance:unset-issues-provider"
fi
if OUT=$(python3 "$PY" --root "$ROOT" resolve-backend) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('fallbackReason')=='bitbucket-issues-unavailable'
assert d.get('guidance',{}).get('never')=='native-bitbucket-issues'
"; then
  ok "bitbucket-guidance:resolve-backend-fallback"
else
  bad "bitbucket-guidance:resolve-backend-fallback"
fi

write_cfg '{
  "version": 1,
  "host": {"provider": "bitbucket"},
  "planning": {
    "store": {
      "backend": "issue-store",
      "issuesProvider": "jira",
      "projectKey": "bb-jira-047",
      "storeLocation": {"mode": "separate-project", "owner": "plan-org", "repo": "planning"},
      "issues": {
        "endpoint": "https://fixture.atlassian.net",
        "flavor": "cloud",
        "tokenEnv": "ISSUES_JIRA_TOKEN",
        "issueType": "Task"
      }
    }
  }
}'
export SW_ISSUES_FIXTURE=1
export ISSUES_JIRA_TOKEN=fixture-token
export ISSUES_JIRA_EMAIL=fixture-local
python3 "$PY" --root "$ROOT" clear-issue-fixture >/dev/null
if OUT=$(python3 "$PY" --root "$ROOT" put --backend issue-store --unit-id bb-jira-prd --body-path docs/prds/099-fixture/099-prd-bb-jira.md --content '# bb jira prd') && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ok' and d['backend']=='issue-store'"; then
  ok "bitbucket-jira-e2e:put"
else
  bad "bitbucket-jira-e2e:put"
fi
if OUT=$(python3 "$PY" --root "$ROOT" get --backend issue-store --unit-id bb-jira-prd --body-path docs/prds/099-fixture/099-prd-bb-jira.md) && \
   echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['content']=='# bb jira prd'"; then
  ok "bitbucket-jira-e2e:get"
else
  bad "bitbucket-jira-e2e:get"
fi

write_cfg '{
  "version": 1,
  "host": {"provider": "bitbucket"},
  "planning": {
    "store": {
      "backend": "issue-store",
      "issuesProvider": "github-issues",
      "projectKey": "bb-sep-047",
      "storeLocation": {"mode": "separate-project", "owner": "plan-org", "repo": "planning"}
    }
  }
}'
python3 "$PY" --root "$ROOT" clear-issue-fixture >/dev/null
if OUT=$(python3 "$PY" --root "$ROOT" put --backend issue-store --unit-id bb-sep-prd --body-path docs/prds/099-fixture/099-prd-bb-sep.md --content '# bb separate prd') && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ok'"; then
  ok "bitbucket-separate-project-e2e:put"
else
  bad "bitbucket-separate-project-e2e:put"
fi
LOC=$(python3 "$PY" --root "$ROOT" resolve-store-location)
echo "$LOC" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('mode')=='separate-project'" && ok "bitbucket-separate-project-e2e:store-location" || bad "bitbucket-separate-project-e2e:store-location"

python3 "$PY" --root "$ROOT" clear-issue-fixture >/dev/null
unset SW_ISSUES_FIXTURE ISSUES_JIRA_TOKEN ISSUES_JIRA_EMAIL

exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
