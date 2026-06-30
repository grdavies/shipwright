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
# Assert sw-ready + living-status echo review state from gate (R29).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_READY="$(content_path commands/sw-ready.md)"
SW_STATUS="$(content_path commands/sw-status.md)"
LIVING="$(content_path skills/living-status/SKILL.md)"
FAIL=0

for label_path in "sw-ready:$SW_READY" "sw-status:$SW_STATUS" "living-status:$LIVING"; do
  label="${label_path%%:*}"
  path="${label_path#*:}"
  if grep -q 'review: off' "$path" && grep -q 'review: not configured' "$path"; then
    echo "OK  ready-review-echo: $label documents review: off and review: not configured"
  else
    echo "FAIL ready-review-echo: $label missing review state echo strings"
    FAIL=1
  fi
  if grep -q 'coderabbitState' "$path"; then
    echo "OK  ready-review-echo: $label maps coderabbitState from gate JSON"
  else
    echo "FAIL ready-review-echo: $label missing coderabbitState mapping"
    FAIL=1
  fi
done

if grep -q 'check-gate.sh' "$SW_READY" && grep -q 'check-gate.sh' "$LIVING"; then
  echo "OK  ready-review-echo: gate script referenced for review echo"
else
  echo "FAIL ready-review-echo: check-gate.sh must drive review echo"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
