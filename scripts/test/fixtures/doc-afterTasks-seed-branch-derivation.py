#!/usr/bin/env python3
"""Ported fixture helper (R27)."""
from __future__ import annotations
import os, re, subprocess, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))
from _fixture_lib import repo_root

from _harness_patch import patch_source as _patch_source

def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy(); env['ROOT']=str(root)
    env['PYTHONPATH']=str(root/'scripts')+os.pathsep+env.get('PYTHONPATH','')
    return subprocess.run(['bash','-c',_patch_source(_SOURCE,root)],cwd=str(root),env=env,shell=False).returncode
_SOURCE = r"""
#!/usr/bin/env bash
# Assert <type>/<slug> derived via shared /sw-deliver resolver (R81).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q 'scripts/wave.sh preflight --task-list' "$SW_DOC" && \
   grep -q 'target.branch' "$SW_DOC" && \
   grep -q 'scripts/wave_deliver.py' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-branch-derivation: uses shared deliver resolver"
else
  echo "FAIL doc-afterTasks-seed-branch-derivation: missing shared resolver reference"
  FAIL=1
fi

if grep -q 'do \*\*not\*\*' "$SW_DOC" && grep -qi 're-implement branch derivation' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-branch-derivation: forbids divergent re-implementation"
else
  echo "FAIL doc-afterTasks-seed-branch-derivation: missing no re-implement guard"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
