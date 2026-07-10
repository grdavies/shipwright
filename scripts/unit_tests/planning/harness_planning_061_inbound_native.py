#!/usr/bin/env python3
"""PRD 061 phase 5 — inbound comment sync + namespaced native unit ids (R18, R19)."""
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
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

if OUT=$(python3 -c "
import json, tempfile, subprocess
from pathlib import Path
import sys
sys.path.insert(0, '$ROOT/scripts')
import planning_store as ps
from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body

root = Path(tempfile.mkdtemp())
subprocess.run(['git','init','-q'], cwd=root, check=True)
(root / '.cursor').mkdir(parents=True, exist_ok=True)
fixture = root / '.cursor/hooks/state/issue-store-fixture.json'
store = FixtureIssuesStore(fixture)
body = compose_issue_body('fixture-061', 'prd', '061-planning-store-interface-architecture', '# PRD\n')
record = store.create(
    title='PRD fixture', body=body,
    labels=['sw:project:fixture-061', 'sw:prd', 'sw:unit:061-planning-store-interface-architecture'],
    project_key='fixture-061', artifact_type='prd', unit_id='061-planning-store-interface-architecture',
)
store.add_comment(record.id, '<!-- sw-chunk-overflow -->\noverflow', markers=['sw-chunk-overflow'])
store.add_comment(record.id, 'Operator note for authoring', markers=[])
store.add_comment(record.id, '<!-- sw-freeze-record -->\nhash', markers=['sw-freeze-record'])
(root / '.cursor/workflow.config.json').write_text(json.dumps({
    'version': 1,
    'host': {'provider': 'github'},
    'planning': {'store': {'backend': 'issue-store', 'issuesProvider': 'github-issues', 'projectKey': 'fixture-061'}},
}), encoding='utf-8')
(root / '.cursor/hooks/state/issue-store-unit-index.json').write_text(json.dumps({
    'version': 1,
    'units': {
        'fixture-061:061-planning-store-interface-architecture': record.id,
        'fixture-061:gh:1': record.id,
    },
}), encoding='utf-8')
ps.save_legacy_unit_map(root, {'061-planning-store-interface-architecture': 'gh:1'})
out = ps.comment_sync(root, unit_id='061-planning-store-interface-architecture', body_path='docs/prds/061-x/x.md', consumer='authoring')
assert out.get('verdict') == 'ok', out
assert out.get('count') == 1, out
assert 'Operator note' in out['comments'][0]['body']
print('pass')
"); then ok "inbound-comments-facade"; else bad "inbound-comments-facade"; fi

if OUT=$(python3 -c "
import sys
sys.path.insert(0, '$ROOT/scripts')
import planning_store as ps
assert ps.format_native_unit_id('github-issues', 352) == 'gh:352'
assert ps.is_namespaced_native_unit_id('gh:352')
assert not ps.is_namespaced_native_unit_id('061-planning-store-interface-architecture')
assert ps.is_bare_integer_unit_id('061')
try:
    ps.reject_bare_integer_unit_id('061')
    raise SystemExit('expected-reject')
except SystemExit as exc:
    if exc.code == 'expected-reject':
        raise
print('pass')
"); then ok "namespaced-native-ids"; else bad "namespaced-native-ids"; fi

if OUT=$(python3 -c "
import tempfile, subprocess
from pathlib import Path
import sys
sys.path.insert(0, '$ROOT/scripts')
import planning_store as ps
from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body
root = Path(tempfile.mkdtemp())
subprocess.run(['git','init','-q'], cwd=root, check=True)
(root / '.cursor').mkdir(parents=True, exist_ok=True)
store = FixtureIssuesStore(root / '.cursor/hooks/state/issue-store-fixture.json')
body = compose_issue_body('fixture-061', 'gap', 'gap-077-sample', '# Gap\n')
record = store.create(title='Gap', body=body, labels=[], project_key='fixture-061', artifact_type='gap', unit_id='gap-077-sample')
ps.register_legacy_unit_mapping(root, 'gap-077-sample', ps.format_native_unit_id('github-issues', record.number))
assert ps.resolve_legacy_unit_id(root, 'gap-077-sample') == f'gh:{record.number}'
assert ps.reverse_resolve_legacy_unit_id(root, f'gh:{record.number}') == 'gap-077-sample'
print('pass')
"); then ok "legacy-compatibility-map"; else bad "legacy-compatibility-map"; fi

exit $FAIL
"""

if __name__ == "__main__":
    raise SystemExit(main())
