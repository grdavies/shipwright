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
# Assert orchestrator never inlines implementation; --after-tasks override (R8, R10, R30).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
SW_SHIP="$(content_path commands/sw-ship.md)"
SW_NAMING="$(content_path rules/sw-naming.mdc)"
FAIL=0

if grep -qi 'never inlines implementation\|never write implementation files inline' "$SW_DOC"; then
  echo "OK  boundary-no-inline: sw-doc never inlines implementation"
else
  echo "FAIL boundary-no-inline: sw-doc inline-impl guard missing"
  FAIL=1
fi

if grep -q '\-\-after-tasks' "$SW_DOC" && grep -q 'doc.afterTasks' "$SW_DOC"; then
  echo "OK  boundary-no-inline: sw-doc --after-tasks override"
else
  echo "FAIL boundary-no-inline: sw-doc after-tasks override missing"
  FAIL=1
fi

if grep -q '\-\-after-tasks' "$SW_SHIP" && grep -qi 'frozen-task-list' "$SW_SHIP"; then
  echo "OK  boundary-no-inline: sw-ship --after-tasks at frozen-task boundary"
else
  echo "FAIL boundary-no-inline: sw-ship --after-tasks integration missing"
  FAIL=1
fi

if grep -q 'shipwright-state.sh' "$SW_SHIP" && grep -qi 'agent' "$SW_SHIP"; then
  echo "OK  boundary-no-inline: agent auto choice recorded on sw-ship"
else
  echo "FAIL boundary-no-inline: sw-ship agent run record missing"
  FAIL=1
fi

if grep -qi 'never inlines implementation' "$SW_NAMING" && grep -qi 'auto' "$SW_NAMING"; then
  echo "OK  boundary-no-inline: sw-naming permits auto-dispatch not inline impl"
else
  echo "FAIL boundary-no-inline: sw-naming doc boundary amendment missing"
  FAIL=1
fi

if ! grep -qE 'Go gate' "$SW_DOC" 2>/dev/null; then
  echo "OK  boundary-no-inline: no Go gate reference in sw-doc"
else
  echo "FAIL boundary-no-inline: Go gate still in sw-doc"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
