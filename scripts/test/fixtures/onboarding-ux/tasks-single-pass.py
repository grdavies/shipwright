#!/usr/bin/env python3
"""Ported fixture helper (R27)."""
from __future__ import annotations
import os, re, subprocess, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent.parent))
from _fixture_lib import repo_root

from _harness_patch import patch_source as _patch_source

def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy(); env['ROOT']=str(root)
    env['PYTHONPATH']=str(root/'scripts')+os.pathsep+env.get('PYTHONPATH','')
    return subprocess.run(['bash','-c',_patch_source(_SOURCE,root)],cwd=str(root),env=env,shell=False).returncode
_SOURCE = r"""
#!/usr/bin/env bash
# Assert /sw-tasks command + skill mandate single-pass generation (R9, R25).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$ROOT/scripts/test/fixture-lib.sh"

SW_TASKS="$(content_path commands/sw-tasks.md)"
SW_TASKS_SKILL="$(content_path skills/tasks/SKILL.md)"
FAIL=0

if grep -qE 'Go gate|pause for "Go"|pause for Go|Respond with .Go.' "$SW_TASKS" "$SW_TASKS_SKILL" 2>/dev/null; then
  echo "FAIL tasks-single-pass: sub-task-expansion gate still present in command or skill"
  FAIL=1
else
  echo "OK  tasks-single-pass: no sub-task-expansion gate in command or skill"
fi

if grep -qiE 'single.pass|one pass|single-pass' "$SW_TASKS" "$SW_TASKS_SKILL" 2>/dev/null; then
  echo "OK  tasks-single-pass: single-pass generation documented"
else
  echo "FAIL tasks-single-pass: missing single-pass wording"
  FAIL=1
fi

if grep -q '## Traceability' "$SW_TASKS" && grep -qi 'traceability' "$SW_TASKS_SKILL" && \
   grep -qi 'sub-task' "$SW_TASKS_SKILL"; then
  echo "OK  tasks-single-pass: complete list shape (sub-tasks + traceability)"
else
  echo "FAIL tasks-single-pass: missing sub-task or traceability contract"
  FAIL=1
fi

if grep -qiE 'stop|does not start implementation' "$SW_TASKS" 2>/dev/null; then
  echo "OK  tasks-single-pass: standalone stops without implementation prompt"
else
  echo "FAIL tasks-single-pass: missing standalone stop contract"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
