#!/usr/bin/env bash
# Two-track docs edit driver — mechanical batch vs substantive worktree+PR (PRD 035 R12/R18).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/scripts/two_track_lib.py"

cmd="${1:-}"
shift || true

topic=""
dry_run=0
index_region=""
paths=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    route|route-substantive) ;;
    --topic) topic="${2:-}"; shift 2 ;;
    --path) paths+=("${2:-}"); shift 2 ;;
    --index-region) index_region="${2:-}"; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help)
      echo "usage: docs-edit-route.sh route [--path P ...] [--index-region derived|inFlight|structural] [--dry-run]" >&2
      echo "       docs-edit-route.sh route-substantive --topic <topic> [--dry-run]" >&2
      exit 2
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$cmd" ]] || { echo "usage: docs-edit-route.sh <route|route-substantive>" >&2; exit 2; }

classify() {
  local args=(python3 "$PY" "$ROOT" classify)
  if [[ ${#paths[@]} -gt 0 ]]; then
    args+=(--paths "${paths[@]}")
  fi
  if [[ -n "$index_region" ]]; then
    args+=(--index-region "$index_region")
  fi
  "${args[@]}"
}

case "$cmd" in
  route)
    [[ ${#paths[@]} -gt 0 ]] || { echo '{"verdict":"fail","error":"paths required"}' >&2; exit 2; }
    OUT=$(classify)
    TRACK=$(echo "$OUT" | python3 -c "import json,sys; print(json.load(sys.stdin)['track'])")
    if [[ "$TRACK" == "mechanical" ]]; then
      if [[ "$dry_run" -eq 1 ]]; then
        MERGE=$(bash "$ROOT/scripts/docs-merge.sh" open --dry-run)
        python3 -c "import json,sys; c=json.load(sys.stdin); m=json.loads(sys.argv[1]); print(json.dumps({'verdict':'pass','track':'mechanical','classify':c,'merge':m}))" "$MERGE" <<<"$OUT"
      else
        MERGE=$(bash "$ROOT/scripts/docs-merge.sh" open)
        python3 -c "import json,sys; c=json.load(sys.stdin); m=json.loads(sys.argv[1]); print(json.dumps({'verdict':'pass','track':'mechanical','classify':c,'merge':m}))" "$MERGE" <<<"$OUT"
      fi
    else
      [[ -n "$topic" ]] || topic="docs-edit"
      if [[ "$dry_run" -eq 1 ]]; then
        WT=$(bash "$ROOT/scripts/docs_worktree.sh" provision --topic "$topic" --dry-run)
        PR=$(bash "$ROOT/scripts/docs_pr.sh" --topic "$topic" --dry-run)
        python3 -c "import json,sys; c=json.load(sys.stdin); w=json.loads(sys.argv[1]); p=json.loads(sys.argv[2]); print(json.dumps({'verdict':'pass','track':'substantive','classify':c,'worktree':w,'pr':p}))" "$WT" "$PR" <<<"$OUT"
      else
        WT=$(bash "$ROOT/scripts/docs_worktree.sh" provision --topic "$topic")
        PR=$(bash "$ROOT/scripts/docs_pr.sh" --topic "$topic")
        python3 -c "import json,sys; c=json.load(sys.stdin); w=json.loads(sys.argv[1]); p=json.loads(sys.argv[2]); print(json.dumps({'verdict':'pass','track':'substantive','classify':c,'worktree':w,'pr':p}))" "$WT" "$PR" <<<"$OUT"
      fi
    fi
    ;;
  route-substantive)
    [[ -n "$topic" ]] || { echo '{"verdict":"fail","error":"topic required"}' >&2; exit 2; }
    if [[ "$dry_run" -eq 1 ]]; then
      WT=$(bash "$ROOT/scripts/docs_worktree.sh" provision --topic "$topic" --dry-run)
      PR=$(bash "$ROOT/scripts/docs_pr.sh" --topic "$topic" --dry-run)
      python3 -c "import json,sys; w=json.loads(sys.argv[1]); p=json.loads(sys.argv[2]); print(json.dumps({'verdict':'pass','track':'substantive','worktree':w,'pr':p}))" "$WT" "$PR"
    else
      WT=$(bash "$ROOT/scripts/docs_worktree.sh" provision --topic "$topic")
      PR=$(bash "$ROOT/scripts/docs_pr.sh" --topic "$topic")
      python3 -c "import json,sys; w=json.loads(sys.argv[1]); p=json.loads(sys.argv[2]); print(json.dumps({'verdict':'pass','track':'substantive','worktree':w,'pr':p}))" "$WT" "$PR"
    fi
    ;;
  *)
    echo "unknown command: $cmd" >&2
    exit 2
    ;;
esac
