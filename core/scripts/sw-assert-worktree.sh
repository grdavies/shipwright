#!/usr/bin/env bash
# Fail-closed guard: block implementation entry on bare default-branch checkout (PRD 002 R6/R27).
#
# Usage: sw-assert-worktree.sh
# Exit 0 — safe to proceed (linked worktree, non-default branch, or hotfix/release branch)
# Exit 1 — blocked (default branch in primary checkout)
# Exit 2 — configuration error
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$ROOT" ]]; then
  echo "sw-assert-worktree: not inside a git repository" >&2
  exit 2
fi

read_default_branch() {
  python3 - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
    if candidate.is_file():
        try:
            cfg = json.loads(candidate.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            break
        print(cfg.get("defaultBaseBranch", "main"))
        raise SystemExit
print("main")
PY
}

DEFAULT_BRANCH="$(read_default_branch)"
CURRENT="$(git branch --show-current 2>/dev/null || true)"
if [[ -z "$CURRENT" ]]; then
  echo "sw-assert-worktree: detached HEAD — provision a worktree and phase branch first" >&2
  exit 1
fi

# Non-default branch: always allowed (feat/, pf/, fix/, etc.)
if [[ "$CURRENT" != "$DEFAULT_BRANCH" ]]; then
  exit 0
fi

# Allowed on-main branch prefixes (sw-start: hotfix/release may target main)
case "$CURRENT" in
  hotfix/*|release/*) exit 0 ;;
esac

# Linked worktree: .git is a pointer file with gitdir (not bare primary checkout on default branch)
if [[ -f "$ROOT/.git" ]] && head -1 "$ROOT/.git" 2>/dev/null | grep -q '^gitdir:'; then
  exit 0
fi

echo "sw-assert-worktree: refused — implementation on bare ${DEFAULT_BRANCH} without a linked worktree" >&2
echo "sw-assert-worktree: run /sw-worktree provision then /sw-start before /sw-execute" >&2
exit 1
