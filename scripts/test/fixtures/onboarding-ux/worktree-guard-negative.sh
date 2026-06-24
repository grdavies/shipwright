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
