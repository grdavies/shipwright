#!/usr/bin/env python3
"""PRD 061 phase 6 — amend/docs/gap prereq write-back (R16, R23, R26–R29)."""
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
export SW_ISSUES_FIXTURE=1
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
AMEND="$(content_path commands/sw-amend.md)"
README="$ROOT/README.md"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

if grep -qE 'Issue-store mode|planning_store\.py put' "$AMEND" && grep -q 'separate-project' "$AMEND" && grep -q 'Decision amendments' "$AMEND" && grep -q 'file-native' "$AMEND"; then ok "amend-decision-store-only"; else bad "amend-decision-store-only"; fi
if grep -q 'issue-store' "$README" && grep -q 'derived or projected from the planning store' "$README"; then ok "docs-surface-remediation"; else bad "docs-surface-remediation"; fi

if OUT=$(python3 -c "
import json, subprocess, tempfile
from pathlib import Path
import sys
sys.path.insert(0, '$ROOT/scripts')
import planning_store as ps
from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body
from planning_migrate_issue_store import cfg_issues_client

root = Path(tempfile.mkdtemp())
subprocess.run(['git','init','-q'], cwd=root, check=True)
(root / '.cursor').mkdir(parents=True, exist_ok=True)
fixture = root / '.cursor/hooks/state/issue-store-fixture.json'
store = FixtureIssuesStore(fixture)
records = {}
for num, slug in [('078','notion-provider'), ('079','linear-provider')]:
    uid = f'gap-{num}-{slug}'
    body = compose_issue_body('fixture-061', 'gap', uid, f'---\\nid: {uid}\\ntype: gap\\nstatus: open\\nvisibility: public\\n---\\n# Gap\\n')
    rec = store.create(title=f'Gap {num}', body=body, labels=['sw:gap', f'sw:unit:{uid}'], project_key='fixture-061', artifact_type='gap', unit_id=uid)
    records[uid] = rec
cfg = {'version': 1, 'host': {'provider': 'github'}, 'planning': {'store': {'backend': 'issue-store', 'issuesProvider': 'github-issues', 'projectKey': 'fixture-061'}}}
(root / '.cursor/workflow.config.json').write_text(json.dumps(cfg), encoding='utf-8')
(root / '.cursor/hooks/state/issue-store-unit-index.json').write_text(json.dumps({'version': 1, 'units': {f'fixture-061:{uid}': rec.id for uid, rec in records.items()}}), encoding='utf-8')
out = ps.write_back_gap_prereqs_061(root, cfg)
assert out.get('verdict') == 'ok', out
backend = ps.get_backend(root, cfg, override='issue-store')
for uid in records:
    body_path = ps._default_body_path(uid, 'gap')
    fetched = backend.get(uid, body_path)
    assert fetched.verdict == 'ok' and fetched.content and '061-prd-planning-store-interface-architecture' in fetched.content, fetched.content
print('pass')
"); then ok "gap-078-079-depends-061"; else bad "gap-078-079-depends-061"; fi

if OUT=$(python3 -c "
import json, tempfile
from pathlib import Path
import sys
sys.path.insert(0, '$ROOT/scripts')
import planning_store as ps
root = Path(tempfile.mkdtemp())
(root / '.cursor').mkdir(parents=True, exist_ok=True)
cfg = {'version': 1, 'host': {'provider': 'github'}, 'planning': {'store': {'backend': 'issue-store', 'issuesProvider': 'github-issues', 'projectKey': 'fixture-061'}}}
(root / '.cursor/workflow.config.json').write_text(json.dumps(cfg), encoding='utf-8')
out = ps.resolve_absorbed_gaps_061(root, cfg, unit_id='gap-105-opaque-locator')
assert out.get('verdict') == 'fail' and out.get('error') == 'prd-060-gap-denylist', out
print('pass')
"); then ok "depends-060-not-absorb-060-gaps"; else bad "depends-060-not-absorb-060-gaps"; fi

if OUT=$(python3 -c "
import json, tempfile
from pathlib import Path
import sys
sys.path.insert(0, '$ROOT/scripts')
import planning_store as ps
root = Path(tempfile.mkdtemp())
(root / '.cursor').mkdir(parents=True, exist_ok=True)
cfg = {'version': 1, 'planning': {'store': {'backend': 'in-repo-public'}}}
(root / '.cursor/workflow.config.json').write_text(json.dumps(cfg), encoding='utf-8')
out = ps.gate_prd_060_r1_r7(root, cfg)
assert out.get('verdict') == 'pass', out
print('pass')
"); then ok "rollout-after-060-r1-r7"; else bad "rollout-after-060-r1-r7"; fi

if OUT=$(python3 -c "
import json, subprocess, tempfile
from pathlib import Path
import sys
sys.path.insert(0, '$ROOT/scripts')
import planning_store as ps
from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body
from planning_migrate_issue_store import cfg_issues_client

root = Path(tempfile.mkdtemp())
subprocess.run(['git','init','-q'], cwd=root, check=True)
(root / '.cursor').mkdir(parents=True, exist_ok=True)
fixture = root / '.cursor/hooks/state/issue-store-fixture.json'
store = FixtureIssuesStore(fixture)
uid = 'gap-077-comment-sync'
body = compose_issue_body('fixture-061', 'gap', uid, '---\\nid: gap-077\\ntype: gap\\nstatus: open\\nvisibility: public\\n---\\n# Gap\\n')
rec = store.create(title='Gap 077', body=body, labels=['sw:gap', 'sw:unit:gap-077-comment-sync'], project_key='fixture-061', artifact_type='gap', unit_id=uid)
cfg = {'version': 1, 'host': {'provider': 'github'}, 'planning': {'store': {'backend': 'issue-store', 'issuesProvider': 'github-issues', 'projectKey': 'fixture-061'}}}
(root / '.cursor/workflow.config.json').write_text(json.dumps(cfg), encoding='utf-8')
(root / '.cursor/hooks/state/issue-store-unit-index.json').write_text(json.dumps({'version': 1, 'units': {f'fixture-061:{uid}': rec.id}}), encoding='utf-8')
out = ps.resolve_absorbed_gaps_061(root, cfg, unit_id=uid)
assert out.get('verdict') == 'ok', out
client = cfg_issues_client(root)
rec = client.issue_search(project_key='fixture-061', unit_id=uid, artifact_type='gap')[0]
assert rec.state == 'closed', rec.state
print('pass')
"); then ok "absorb-077-104-109-resolve"; else bad "absorb-077-104-109-resolve"; fi

exit $FAIL
"""

if __name__ == "__main__":
    raise SystemExit(main())
