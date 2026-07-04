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
# Assert /sw-setup documents doc.afterTasks + review choice (R7, R15, R16, R19).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_INIT="$(content_path commands/sw-init.md)"
FAIL=0

if grep -q 'doc\.afterTasks' "$SW_INIT" && grep -qE 'default \*\*`confirm`\*\*|default \*\*confirm\*\*' "$SW_INIT" && \
   grep -qE '`stop` \| `confirm` \| `auto`' "$SW_INIT"; then
  echo "OK  setup-review-choice: doc.afterTasks default confirm documented"
else
  echo "FAIL setup-review-choice: missing doc.afterTasks default confirm"
  FAIL=1
fi

if grep -qE '`coderabbit` \| `none`' "$SW_INIT" && grep -qE 'default \*\*`none`\*\*|default \*\*none\*\*' "$SW_INIT"; then
  echo "OK  setup-review-choice: review choice coderabbit|none, default none"
else
  echo "FAIL setup-review-choice: missing review choice or none default"
  FAIL=1
fi

if grep -q 'Do \*\*not\*\* offer a separate `disabled` choice' "$SW_INIT"; then
  echo "OK  setup-review-choice: no separate disabled choice"
else
  echo "FAIL setup-review-choice: must reject separate disabled choice"
  FAIL=1
fi

if grep -q 'review\.provider: "none"' "$SW_INIT" && grep -qi 'canonical opt-out' "$SW_INIT"; then
  echo "OK  setup-review-choice: canonical opt-out documented"
else
  echo "FAIL setup-review-choice: missing canonical review.provider:none opt-out"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
