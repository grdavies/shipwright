#!/usr/bin/env python3
"""PRD 047 — cross-provider conformance against Jira Cloud + DC fixtures (R32a/R32b)."""
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
JIRA_CANON="$ROOT/scripts/planning_jira_canonical.py"
CAP="$(content_path providers/issues/CAPABILITIES.md)"
FX="$ROOT/scripts/tests/fixtures/canonical/jira"

# --- verb mapping + degraded issue-lock documented ---
check() { local n="$1" f="$2" p="$3"; if grep -qE "$p" "$f" 2>/dev/null; then ok "$n"; else bad "$n"; fi; }
check "jira-conformance:issue-lock-degraded" "$CAP" "issue-lock.*degraded.*hash-authoritative"
check "jira-conformance:jira-rest-verbs" "$(content_path providers/issues/jira.md)" "issue-create"
check "jira-conformance:cloud-dc-matrix" "$(content_path providers/issues/jira.md)" "Cloud vs DC"

# --- canonical golden vectors (Cloud ADF + DC wiki + server-mutated round-trip) ---
GH=$(python3 -c "import json; print(json.load(open('$ROOT/scripts/tests/fixtures/canonical/github-prd-open.json'))['expectedHash'])")
for fx in prd-open adf-roundtrip server-mutated-adf wiki-dc; do
  FPATH="$FX/${fx}.json"
  if OUT=$(python3 "$JIRA_CANON" normalize --fixture "$FPATH") && \
     echo "$OUT" | python3 -c "import json,sys,pathlib; d=json.load(sys.stdin); exp=json.loads(pathlib.Path(sys.argv[1]).read_text())['expectedHash']; assert d['hash']==exp" "$FPATH"; then
    ok "jira-conformance:canonical-${fx}"
  else
    bad "jira-conformance:canonical-${fx}"
  fi
done
JIRA_H=$(python3 -c "import json; print(json.load(open('$FX/prd-open.json'))['expectedHash'])")
[[ "$GH" == "$JIRA_H" ]] && ok "jira-conformance:cross-provider-parity" || bad "jira-conformance:cross-provider-parity"

# --- fixture CRUD + freeze with degraded lock (hash-authoritative) ---
export SW_ISSUES_FIXTURE=1
export ISSUES_JIRA_TOKEN=fixture-token
export ISSUES_JIRA_EMAIL=fixture-local
python3 - <<PY
import json
from pathlib import Path
Path("$ROOT/.cursor/workflow.config.json").write_text(json.dumps({
  "version": 1,
  "planning": {
    "store": {
      "backend": "issue-store",
      "issuesProvider": "jira",
      "projectKey": "conf047",
      "issues": {
        "endpoint": "https://fixture.atlassian.net",
        "flavor": "cloud",
        "tokenEnv": "ISSUES_JIRA_TOKEN",
        "issueType": "Task"
      }
    }
  }
}, indent=2) + "\\n", encoding="utf-8")
PY
python3 "$PY" --root "$ROOT" clear-issue-fixture >/dev/null
if OUT=$(python3 "$PY" --root "$ROOT" put --backend issue-store --unit-id conf-freeze --body-path docs/prds/099-fixture/099-prd-conf.md --content '# conf freeze') && \
   echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='ok'"; then
  ok "jira-conformance:issue-create"
else
  bad "jira-conformance:issue-create"
fi
if OUT=$(python3 "$PY" --root "$ROOT" freeze --backend issue-store --unit-id conf-freeze --body-path docs/prds/099-fixture/099-prd-conf.md --no-distill) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ok' and d.get('hash')"; then
  ok "jira-conformance:freeze-hash-authoritative"
else
  bad "jira-conformance:freeze-hash-authoritative"
fi

# DC flavor probe path
python3 - <<PY
import json
from pathlib import Path
Path("$ROOT/.cursor/workflow.config.json").write_text(json.dumps({
  "version": 1,
  "planning": {
    "store": {
      "backend": "issue-store",
      "issuesProvider": "jira",
      "projectKey": "conf047dc",
      "issues": {
        "endpoint": "https://jira.fixture.local",
        "flavor": "dc",
        "tokenEnv": "ISSUES_JIRA_TOKEN",
        "issueType": "Task"
      }
    }
  }
}, indent=2) + "\\n", encoding="utf-8")
PY
if OUT=$(python3 "$PY" --root "$ROOT" probe-jira-init) && echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='ok'"; then
  ok "jira-conformance:dc-init-probe"
else
  bad "jira-conformance:dc-init-probe"
fi
FPATH="$FX/wiki-dc.json"
if OUT=$(python3 "$JIRA_CANON" normalize --fixture "$FPATH") && \
   echo "$OUT" | python3 -c "import json,sys,pathlib; d=json.load(sys.stdin); exp=json.loads(pathlib.Path(sys.argv[1]).read_text())['expectedHash']; assert d['hash']==exp" "$FPATH"; then
  ok "jira-conformance:dc-wiki-canonical"
else
  bad "jira-conformance:dc-wiki-canonical"
fi

python3 "$PY" --root "$ROOT" clear-issue-fixture >/dev/null
unset SW_ISSUES_FIXTURE ISSUES_JIRA_TOKEN ISSUES_JIRA_EMAIL

exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
