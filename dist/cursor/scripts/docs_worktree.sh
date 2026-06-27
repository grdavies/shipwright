#!/usr/bin/env bash
# Docs-on-a-branch worktree provisioning (PRD 026 R28, R29).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_HELPER="$ROOT/scripts/shipwright-state.sh"

usage() {
  echo "usage: docs_worktree.sh {provision|resume|status} --topic <topic> [--dry-run]" >&2
  exit 2
}

load_default_branch() {
  python3 - <<'PY' "$ROOT"
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
for rel in ('.cursor/workflow.config.json', 'workflow.config.json'):
    p = root / rel
    if p.is_file():
        try:
            b = json.loads(p.read_text()).get('defaultBaseBranch')
            if b:
                print(b)
                raise SystemExit(0)
        except json.JSONDecodeError:
            pass
print('main')
PY
}

topic=""
cmd=""
dry_run=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    provision|resume|status) cmd="$1"; shift ;;
    --topic) topic="${2:-}"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done
[[ -n "$cmd" && -n "$topic" ]] || usage

branch="$(python3 "$ROOT/scripts/worktree_lib.py" docs-branch "$topic")"
default="$(load_default_branch)"
wt_name="docs-$(python3 -c "import re,sys; print(re.sub(r'[^a-z0-9]+','-', sys.argv[1].lower()).strip('-'))" "$topic")"
wt_root="$(git -C "$ROOT" rev-parse --show-toplevel)/.sw-worktrees"
path="$wt_root/$wt_name"

if [[ "$branch" == "$default" ]]; then
  echo "{\"verdict\":\"fail\",\"error\":\"refused: docs branch equals default trunk\"}" >&2
  exit 20
fi

if ! python3 "$ROOT/scripts/worktree_lib.py" validate "$branch" >/dev/null 2>&1; then
  echo "{\"verdict\":\"fail\",\"error\":\"non-conforming docs branch: $branch\"}" >&2
  exit 12
fi

current="$(git -C "$ROOT" branch --show-current 2>/dev/null || true)"
if [[ "$current" == "$default" && "$cmd" == "provision" && "$dry_run" -eq 0 ]]; then
  : # provisioning from trunk checkout is expected
fi

case "$cmd" in
  status)
    if [[ -d "$path" ]]; then
      printf '{"verdict":"pass","branch":"%s","path":"%s","exists":true}\n' "$branch" "$path"
    else
      printf '{"verdict":"pass","branch":"%s","exists":false}\n' "$branch"
    fi
  ;;
  resume)
    [[ -d "$path" ]] || {
      echo "{\"verdict\":\"fail\",\"error\":\"docs worktree missing — run provision first\",\"path\":\"$path\"}" >&2
      exit 1
    }
    printf '{"verdict":"pass","action":"resume","branch":"%s","path":"%s"}\n' "$branch" "$path"
  ;;
  provision)
  if [[ -d "$path" ]]; then
    printf '{"verdict":"pass","action":"provision","branch":"%s","path":"%s","note":"already exists"}\n' "$branch" "$path"
    exit 0
  fi
  if [[ "$dry_run" -eq 1 ]]; then
    printf '{"verdict":"pass","action":"provision","dry_run":true,"branch":"%s","path":"%s"}\n' "$branch" "$path"
    exit 0
  fi
  mkdir -p "$wt_root"
  host_remote="$(python3 "$ROOT/scripts/host_lib.py" --root "$ROOT" remote-name 2>/dev/null || echo origin)"
  git -C "$ROOT" fetch "$host_remote" "$default" 2>/dev/null || true
  base_ref="$default"
  if ! git -C "$ROOT" show-ref --verify --quiet "refs/heads/$default"; then
    base_ref="HEAD"
  fi
  if git -C "$ROOT" show-ref --verify --quiet "refs/heads/$branch"; then
    git -C "$ROOT" worktree add "$path" "$branch" >/dev/null
  else
    git -C "$ROOT" worktree add -b "$branch" "$path" "$base_ref" >/dev/null
  fi
  printf '{"verdict":"pass","action":"provision","branch":"%s","path":"%s"}\n' "$branch" "$path"
  ;;
esac
