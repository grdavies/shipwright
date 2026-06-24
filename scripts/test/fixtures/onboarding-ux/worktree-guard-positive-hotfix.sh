#!/usr/bin/env bash
# Positive: hotfix/* branch on primary checkout is allowed (R27 on-main path).
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
git -C "$TMP/repo" checkout -q -b hotfix/critical-fix

set +e
OUT=$(cd "$TMP/repo" && bash "$GUARD" 2>&1)
EC=$?
set -e

if [[ "$EC" -eq 0 ]]; then
  echo "OK  worktree-guard positive: hotfix branch on primary checkout"
  exit 0
fi

echo "FAIL worktree-guard positive hotfix expected exit=0 (ec=$EC)"
echo "$OUT"
exit 1
