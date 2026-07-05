#!/usr/bin/env python3
"""PRD 047 phase-1 doc-impact gate (R49)."""
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
check() { local n="$1" f="$2" p="$3"; if grep -qE "$p" "$f" 2>/dev/null; then ok "$n"; else bad "$n"; fi; }

JIRA="$(content_path providers/issues/jira.md)"
CAP="$(content_path providers/issues/CAPABILITIES.md)"
ISSUE_STORE="$(content_path providers/planning-store/issue-store.md)"
FREEZE="$(content_path commands/sw-freeze.md)"
CONFIG="$ROOT/docs/guides/configuration.md"
CANON="$ROOT/scripts/planning_jira_canonical.py"
CAP_INDEX="$ROOT/core/sw-reference/capability-index.json"
FX_DIR="$ROOT/scripts/tests/fixtures/canonical/jira"

check "doc-currency-047:jira-adapter-spec" "$JIRA" "issuesProvider.*jira"
check "doc-currency-047:jira-lcd-mapping" "$JIRA" "summary"
check "doc-currency-047:jira-rest-verbs" "$JIRA" "issue-create"
check "doc-currency-047:jira-cloud-dc-matrix" "$JIRA" "Cloud vs DC"
check "doc-currency-047:jira-canonical-hash" "$JIRA" "post-write re-fetched"
check "doc-currency-047:jira-artifact-placement" "$JIRA" "freeze-record"
check "doc-currency-047:jira-freeze-decoupling" "$JIRA" "lifecycle-drift"
check "doc-currency-047:jira-issue-lock-degraded" "$JIRA" "degraded"
check "doc-currency-047:jira-config-endpoint" "$JIRA" "endpoint"
check "doc-currency-047:jira-config-flavor" "$JIRA" "flavor"
check "doc-currency-047:jira-config-tokenEnv" "$JIRA" "tokenEnv"
check "doc-currency-047:jira-config-freezeRecordField" "$JIRA" "freezeRecordField"
check "doc-currency-047:jira-auth-probes" "$JIRA" "Auth probes"
check "doc-currency-047:jira-privacy-R105" "$JIRA" "per-issue privacy"
check "doc-currency-047:jira-request-budget" "$JIRA" "Request budget"
check "doc-currency-047:jira-lifecycle-R107" "$JIRA" "Lifecycle edges"
check "doc-currency-047:jira-createmeta-R108" "$JIRA" "createmeta"
check "doc-currency-047:jira-label-ladder-R109" "$JIRA" "Label degradation ladder"

check "doc-currency-047:capabilities-jira-rest" "$CAP" "degraded.*hash-authoritative"
check "doc-currency-047:capabilities-cloud-dc" "$CAP" "Jira Cloud vs DC"
check "doc-currency-047:capabilities-label-ladder" "$CAP" "Label degradation ladder"

check "doc-currency-047:issue-store-jira-crossref" "$ISSUE_STORE" "core/providers/issues/jira.md"
if grep -q "until PRD 047" "$ISSUE_STORE" 2>/dev/null; then bad "doc-currency-047:issue-store-no-jira-fallback"; else ok "doc-currency-047:issue-store-no-jira-fallback"; fi

INIT="$(content_path commands/sw-init.md)"
check "doc-currency-047:sw-init-jira-probe" "$INIT" "probe-jira-init"
check "doc-currency-047:sw-freeze-lifecycle-drift" "$FREEZE" "lifecycle-drift"

check "doc-currency-047:configuration-jira-endpoint" "$CONFIG" "issues\.endpoint"
check "doc-currency-047:configuration-jira-flavor" "$CONFIG" "issues\.flavor"
check "doc-currency-047:configuration-jira-tokenEnv" "$CONFIG" "issues\.tokenEnv"
check "doc-currency-047:configuration-jira-freezeRecordField" "$CONFIG" "freezeRecordField"
check "doc-currency-047:configuration-jira-probe-init" "$CONFIG" "probe-jira-init"
check "doc-currency-047:configuration-jira-fieldDefaults" "$CONFIG" "fieldDefaults"
check "doc-currency-047:configuration-jira-labelSurface" "$CONFIG" "labelSurface"
grep -q "until PRD 047" "$CONFIG" 2>/dev/null && bad "doc-currency-047:configuration-no-jira-fallback" || ok "doc-currency-047:configuration-no-jira-fallback"

[[ -f "$CANON" ]] && ok "doc-currency-047:planning-jira-canonical-present" || bad "doc-currency-047:planning-jira-canonical-present"
grep -q "adf_to_markdown" "$CANON" && ok "doc-currency-047:adf-to-markdown" || bad "doc-currency-047:adf-to-markdown"
grep -q "wiki_to_markdown" "$CANON" && ok "doc-currency-047:wiki-to-markdown" || bad "doc-currency-047:wiki-to-markdown"
grep -q "snapshot_from_fixture" "$CANON" && ok "doc-currency-047:snapshot-from-fixture" || bad "doc-currency-047:snapshot-from-fixture"

python3 -c "import json; d=json.load(open('$CAP_INDEX')); assert any(c.get('id')=='provider.providers.issues.jira' for c in d['capabilities'])"   && ok "doc-currency-047:capability-index-jira" || bad "doc-currency-047:capability-index-jira"

PROBE="$ROOT/scripts/planning_jira_probe.py"
[[ -f "$PROBE" ]] && ok "doc-currency-047:planning-jira-probe-present" || bad "doc-currency-047:planning-jira-probe-present"
FX_RES="$ROOT/scripts/tests/fixtures/resilience/jira"
for fx in createmeta-required 429-exhaustion partial-page-abort; do
  [[ -f "$FX_RES/${fx}.json" ]] && ok "doc-currency-047:resilience-${fx}" || bad "doc-currency-047:resilience-${fx}"
done
for fx in prd-open adf-roundtrip server-mutated-adf wiki-dc; do
  [[ -f "$FX_DIR/${fx}.json" ]] && ok "doc-currency-047:fixture-${fx}" || bad "doc-currency-047:fixture-${fx}"
done


BITBUCKET="$(content_path providers/host/bitbucket.md)"
WORKFLOWS="$ROOT/docs/guides/workflows.md"
COMMANDS="$ROOT/docs/guides/commands.md"
check "doc-currency-047-p3:bitbucket-eol-routing" "$BITBUCKET" "never.*route to native"
check "doc-currency-047-p3:bitbucket-separate-project-default" "$BITBUCKET" "separate-project"
check "doc-currency-047-p3:bitbucket-jira-opt-in" "$BITBUCKET" "issuesProvider: jira"
check "doc-currency-047-p3:bitbucket-guidance-command" "$BITBUCKET" "bitbucket-issue-store-guidance"
check "doc-currency-047-p3:workflows-bitbucket-hosts" "$WORKFLOWS" "Bitbucket hosts"
check "doc-currency-047-p3:workflows-jira-opt-in" "$WORKFLOWS" "Jira \(Cloud first\)"
check "doc-currency-047-p3:workflows-separate-planning" "$WORKFLOWS" "separate.*planning"
check "doc-currency-047-p3:commands-jira-probe" "$COMMANDS" "probe-jira-init"
check "doc-currency-047-p3:commands-bitbucket-guidance" "$COMMANDS" "bitbucket-issue-store-guidance"
[[ -f "$ROOT/scripts/unit_tests/planning/harness_planning_047_conformance.py" ]] && ok "doc-currency-047-p3:conformance-runner" || bad "doc-currency-047-p3:conformance-runner"

exit "$FAIL"
"""

if __name__ == "__main__":
    raise SystemExit(main())
