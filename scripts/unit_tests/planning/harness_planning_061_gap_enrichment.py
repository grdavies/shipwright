#!/usr/bin/env python3
"""PRD 061 phase 4 task 4.1 — gap enrichment gate + draft inbox + feedback auto-fill (R17, R17a)."""
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
# PRD 061 phase 4.1 — gap enrichment + draft inbox (R17, R17a).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
PY="$ROOT/scripts/planning_gap_capture.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

STUB_CONTENT=$'---\nid: gap-999-stub\ntype: gap\nstatus: open\ntitle: stub\nvisibility: public\n---\n\n# stub\n'

# --- gap-put-requires-problem-context (R17) ---
if OUT=$(python3 -c "
import sys
sys.path.insert(0, '$ROOT/scripts')
import planning_gap_capture as pgc
stub = '---\nid: gap-999\ntype: gap\n---\n\n# stub\n'
try:
    pgc.require_gap_enrichment(stub)
    raise SystemExit('unexpected-pass')
except SystemExit as exc:
    if str(exc) == 'unexpected-pass':
        raise
print('pass')
"); then
  ok "gap-put-requires-problem-context"
else
  bad "gap-put-requires-problem-context"
fi

# --- feedback-autofill-related-next (R17a) ---
if OUT=$(python3 -c "
import sys, tempfile, subprocess
from pathlib import Path
sys.path.insert(0, '$ROOT/scripts')
import planning_gap_capture as pgc
root = Path(tempfile.mkdtemp())
subprocess.run(['git','init','-q'], cwd=root, check=True)
(root / '.cursor').mkdir(parents=True, exist_ok=True)
(root / 'docs' / 'prds').mkdir(parents=True, exist_ok=True)
calls = []
class FakeBackend:
    backend_id = 'in-repo-public'
    def put(self, unit_id, body_path, content, *, content_class=None):
        calls.append(content)
        from planning_store import StoreResult
        return StoreResult('ok', unit_id, body_path, self.backend_id, content=content)
import planning_gap_capture as mod
mod.ps.get_backend = lambda r: FakeBackend()
out = mod.capture_gap(
    root,
    signal_id='sig-feedback',
    title='Feedback pain',
    problem='Operator saw flaky verify',
    context='Redacted CI log excerpt',
    authoritative=True,
    dry_run=False,
)
body = calls[0]
assert '## Related units' in body and 'none' in body
assert '## Suggested next step' in body and 'triage' in body
assert '## Problem' in body and 'flaky verify' in body
print('pass')
"); then
  ok "feedback-autofill-related-next"
else
  bad "feedback-autofill-related-next"
fi

# --- draft-inbox-then-materialize (R17) ---
if OUT=$(python3 -c "
import sys, tempfile, subprocess
from pathlib import Path
sys.path.insert(0, '$ROOT/scripts')
import planning_gap_capture as pgc
root = Path(tempfile.mkdtemp())
subprocess.run(['git','init','-q'], cwd=root, check=True)
(root / '.cursor').mkdir(parents=True, exist_ok=True)
(root / 'docs' / 'prds').mkdir(parents=True, exist_ok=True)
draft = pgc.capture_gap(root, signal_id='sig-draft', title='Needs enrichment', dry_run=False)
assert draft.get('action') == 'draft-inbox'
calls = []
class FakeBackend:
    backend_id = 'in-repo-public'
    def put(self, unit_id, body_path, content, *, content_class=None):
        calls.append(content)
        from planning_store import StoreResult
        return StoreResult('ok', unit_id, body_path, self.backend_id, content=content)
pgc.ps.get_backend = lambda r: FakeBackend()
mat = pgc.materialize_gap_draft(
    root,
    signal_id='sig-draft',
    problem='Real problem',
    context='Real context',
)
assert calls and '## Problem' in calls[0]
print('pass')
"); then
  ok "draft-inbox-materialize-put"
else
  bad "draft-inbox-materialize-put"
fi

exit $FAIL
"""

if __name__ == "__main__":
    raise SystemExit(main())
