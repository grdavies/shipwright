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
# Assert seed excludes brainstorms; agent auto records seed commit branch+SHA (R83).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q 'docs/brainstorms' "$SW_DOC" && grep -qi 'Exclude' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-brainstorm-excluded: brainstorm path excluded"
else
  echo "FAIL doc-afterTasks-seed-brainstorm-excluded: brainstorm exclusion missing"
  FAIL=1
fi

if grep -q 'untracked or ignored path' "$SW_DOC" || grep -q 'untracked/ignored' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-brainstorm-excluded: untracked/ignored excluded"
else
  echo "FAIL doc-afterTasks-seed-brainstorm-excluded: untracked/ignored exclusion missing"
  FAIL=1
fi

if grep -q 'seed commit (branch + SHA)' "$SW_DOC" && \
   grep -q 'shipwright-state.sh write' "$SW_DOC" && \
   grep -q '\-\-after-tasks=auto' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-brainstorm-excluded: agent auto records seed commit"
else
  echo "FAIL doc-afterTasks-seed-brainstorm-excluded: seed commit run-record missing"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
