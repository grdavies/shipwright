#!/usr/bin/env python3
"""PRD 061 phase 4 tasks 4.2–4.3 — hybrid frontmatter + structural projection (R20–R22)."""
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
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

CANONICAL=$'---\nid: gap-010-sample\ntype: gap\nstatus: open\ntitle: Sample\ntags: [source:feedback, signal:abc]\nvisibility: public\nblocks: gap-009-other\nextends: 060-prd-x\nsupersedes: gap-008-old\n---\n\n# Sample\n\nBody text.\n'

if OUT=$(python3 -c "
import sys
sys.path.insert(0, '$ROOT/scripts')
from planning_canonical import (
    operator_body_from_canonical,
    canonical_content_from_operator,
    has_raw_yaml_frontmatter,
    structural_labels_from_content,
    type_label,
)
canonical = '''$CANONICAL'''
op = operator_body_from_canonical(canonical)
assert not op.startswith('---'), op[:40]
assert 'Body text.' in op
labels = structural_labels_from_content(canonical)
assert type_label('gap') in labels
rebuilt = canonical_content_from_operator(labels, op, unit_id='gap-010-sample')
assert has_raw_yaml_frontmatter(rebuilt)
print('pass')
"); then ok "operator-body-no-raw-yaml"; else bad "operator-body-no-raw-yaml"; fi

if OUT=$(python3 -c "
import sys
sys.path.insert(0, '$ROOT/scripts')
from planning_canonical import structural_labels_from_content, type_label
canonical = '''$CANONICAL'''
labels = structural_labels_from_content(canonical)
assert type_label('gap') in labels
assert any(l.startswith('sw:tag:') for l in labels)
assert any(l.startswith('sw:blocks:') for l in labels)
assert any(l.startswith('sw:extends:') for l in labels)
assert any(l.startswith('sw:supersedes:') for l in labels)
print('pass')
"); then ok "structural-keys-projected"; else bad "structural-keys-projected"; fi

if OUT=$(python3 -c "
import sys, tempfile, subprocess, json
from pathlib import Path
sys.path.insert(0, '$ROOT/scripts')
import planning_store as ps
root = Path(tempfile.mkdtemp())
subprocess.run(['git','init','-q'], cwd=root, check=True)
(root / '.cursor').mkdir(parents=True, exist_ok=True)
(root / '.cursor' / 'workflow.config.json').write_text(json.dumps({'planning': {'store': {'backend': 'in-repo-public'}}}), encoding='utf-8')
cfg = ps.load_workflow_config(root)
first = ps.backfill_frontmatter_hybrid(root, cfg, apply=False)
second = ps.backfill_frontmatter_hybrid(root, cfg, apply=False)
assert first['counts'] == second['counts']
print('pass')
"); then ok "frontmatter-backfill-idempotent"; else bad "frontmatter-backfill-idempotent"; fi

exit $FAIL
"""

if __name__ == "__main__":
    raise SystemExit(main())
