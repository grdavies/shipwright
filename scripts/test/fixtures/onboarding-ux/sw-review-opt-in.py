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
# Assert sw-review.md describes CodeRabbit as opt-in, not default (R14, R16).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_REVIEW="$(content_path commands/sw-review.md)"
FAIL=0

if grep -nE 'CodeRabbit default' "$SW_REVIEW" >/dev/null 2>&1; then
  echo "FAIL sw-review-opt-in: must not describe CodeRabbit as default"
  FAIL=1
else
  echo "OK  sw-review-opt-in: no CodeRabbit default phrasing"
fi

if grep -q 'review\.provider: "none"' "$SW_REVIEW" && grep -qi 'canonical' "$SW_REVIEW"; then
  echo "OK  sw-review-opt-in: canonical review.provider:none documented"
else
  echo "FAIL sw-review-opt-in: missing canonical opt-out documentation"
  FAIL=1
fi

if grep -qi 'opt-in' "$SW_REVIEW" || grep -q 'default is `none`' "$SW_REVIEW" || \
   grep -q 'default `none`' "$SW_REVIEW"; then
  echo "OK  sw-review-opt-in: none/opt-in default documented"
else
  echo "FAIL sw-review-opt-in: must document none as default or CodeRabbit as opt-in"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
