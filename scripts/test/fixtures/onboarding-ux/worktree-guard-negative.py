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
# Negative: bare default-branch checkout blocks implementation entry (R27).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
GUARD="$ROOT/scripts/sw-assert-worktree.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

git init -q "$TMP/repo"
git -C "$TMP/repo" config user.email "test@example.com"
git -C "$TMP/repo" config user.name "Test"
git -C "$TMP/repo" checkout -b main 2>/dev/null || git -C "$TMP/repo" branch -M main
echo ok >"$TMP/repo/README.md"
git -C "$TMP/repo" add README.md
git -C "$TMP/repo" commit -m init -q

set +e
OUT=$(cd "$TMP/repo" && bash "$GUARD" 2>&1)
EC=$?
set -e

if [[ "$EC" -ne 0 ]] && echo "$OUT" | grep -qi 'bare main'; then
  echo "OK  worktree-guard negative: blocks bare main"
  exit 0
fi

echo "FAIL worktree-guard negative expected exit!=0 with bare main message (ec=$EC)"
echo "$OUT"
exit 1

"""
if __name__=="__main__": raise SystemExit(main())
