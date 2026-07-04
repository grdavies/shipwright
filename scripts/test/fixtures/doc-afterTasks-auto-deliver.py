#!/usr/bin/env python3
"""Ported fixture helper (R27)."""
from __future__ import annotations
import os, re, subprocess, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))
from _sw.vendor_paths import repo_root

from unit_tests._harness_runtime import patch_source as _patch_source

def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy(); env['ROOT']=str(root)
    env['PYTHONPATH']=str(root/'scripts')+os.pathsep+env.get('PYTHONPATH','')
    return subprocess.run(['bash','-c',_patch_source(_SOURCE,root)],cwd=str(root),env=env,shell=False).returncode
_SOURCE = r"""
#!/usr/bin/env bash
# Assert auto dispatch invokes /sw-deliver run; agent override recorded before dispatch (R76, R79).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q '\*\*`auto`\*\*' "$SW_DOC" && \
   grep -q '/sw-deliver run <frozen-task-list-path>' "$SW_DOC"; then
  echo "OK  doc-afterTasks-auto-deliver: auto dispatches /sw-deliver run"
else
  echo "FAIL doc-afterTasks-auto-deliver: auto missing /sw-deliver run dispatch"
  FAIL=1
fi

if grep -q 'implementing on branch' "$SW_DOC"; then
  echo "OK  doc-afterTasks-auto-deliver: branch notice before dispatch"
else
  echo "FAIL doc-afterTasks-auto-deliver: missing implementing on branch notice"
  FAIL=1
fi

if grep -q 'shipwright-state.py override-add' "$SW_DOC" && \
   grep -q '\-\-after-tasks=auto' "$SW_DOC" && grep -qi 'before.*dispatch' "$SW_DOC"; then
  echo "OK  doc-afterTasks-auto-deliver: agent override recorded before dispatch"
else
  echo "FAIL doc-afterTasks-auto-deliver: agent override record missing"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
