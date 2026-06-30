#!/usr/bin/env bash
# Merge-base sync probe for /sw-stabilize — detect PR merge conflicts before check/thread harvest.
#
# Usage:
#   stabilize-merge-sync.sh status [--pr N]
#   stabilize-merge-sync.sh conflict-files [--base REF]
#   stabilize-merge-sync.sh fetch-base [--base REF]
#
# Exit: 0 mergeable/clean; 1 conflicting; 2 usage; 30 host/metadata unavailable
set -euo pipefail

SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null || echo "$SCRIPT_ROOT")"
cd "$REPO_ROOT"
ROOT="$SCRIPT_ROOT"

PR=""
BASE_REF=""
CMD="${1:-}"
shift || true

usage() {
  sed -n '2,8p' "$0"
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pr) PR="${2:-}"; shift 2 ;;
    --base) BASE_REF="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

host_remote() {
  python3 "$ROOT/scripts/host_lib.py" --root "$ROOT" remote-name
}

default_base() {
  local cfg=""
  for p in "$ROOT/.cursor/workflow.config.json" "$ROOT/workflow.config.json"; do
    [[ -f "$p" ]] && cfg="$p" && break
  done
  if [[ -n "$cfg" ]]; then
    jq -r '.defaultBaseBranch // "main"' "$cfg" 2>/dev/null || echo main
  else
    echo main
  fi
}

resolve_base_ref() {
  if [[ -n "$BASE_REF" ]]; then
    printf '%s\n' "$BASE_REF"
    return
  fi
  local base
  base="$(default_base)"
  if git show-ref --verify --quiet "refs/remotes/$(host_remote)/$base"; then
    printf '%s/%s\n' "$(host_remote)" "$base"
  else
    printf '%s\n' "$base"
  fi
}

host_verb() {
  python3 "$ROOT/scripts/host.py" --root "$ROOT" "$@"
}

pr_json() {
  local out
  if [[ -n "$PR" ]]; then
    out="$(host_verb pr-view --number "$PR" 2>/dev/null || true)"
  else
    resolve="$(host_verb resolve-pr-for-branch 2>/dev/null || true)"
    num="$(python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); items=d.get('data') or []; print(items[0].get('number','') if items else '')" "$resolve" 2>/dev/null || true)"
    [[ -n "$num" ]] || return 1
    out="$(host_verb pr-view --number "$num" 2>/dev/null || true)"
  fi
  python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print(json.dumps(d.get('data'))) if d.get('verdict')=='ok' else sys.exit(1)" "$out" 2>/dev/null
}

cmd_fetch_base() {
  local ref
  ref="$(resolve_base_ref)"
  local hr; hr="$(host_remote)"; git fetch "$hr" "${ref#${hr}/}" 2>/dev/null || git fetch "$hr" "$ref" 2>/dev/null || true
}

list_conflict_files() {
  local base_ref head_ref base_oid merge_out
  base_ref="$(resolve_base_ref)"
  head_ref="$(git rev-parse HEAD)"
  base_oid="$(git merge-base "$head_ref" "$base_ref" 2>/dev/null || true)"
  if [[ -z "$base_oid" ]]; then
    echo '[]'
    return
  fi
  merge_out="$(git merge-tree "$base_oid" "$head_ref" "$base_ref" 2>/dev/null || true)"
  MERGE_TREE_OUT="$merge_out" python3 - <<'PY'
import json, os, re, sys
text = os.environ.get("MERGE_TREE_OUT", "")
paths = []
for line in text.splitlines():
    m = re.match(r"^  base\s+\d+\s+[0-9a-f]+\s+(.+)$", line)
    if m:
        path = m.group(1).strip()
        if path and path not in paths:
            paths.append(path)
print(json.dumps(paths))
PY
}

cmd_status() {
  local pj mergeable merge_state base_ref files_json
  if ! pj="$(pr_json)"; then
    echo '{"verdict":"fail","reason":"no open PR or host unavailable"}'
    exit 30
  fi
  mergeable="$(jq -r '.mergeable // "UNKNOWN"' <<<"$pj")"
  merge_state="$(jq -r '.mergeStateStatus // "UNKNOWN"' <<<"$pj")"
  base_ref="$(jq -r '.baseRefName // "main"' <<<"$pj")"
  if [[ "$mergeable" == "CONFLICTING" || "$merge_state" == "DIRTY" ]]; then
    files_json="$(list_conflict_files)"
    jq -n \
      --argjson pr "$pj" \
      --arg mergeable "$mergeable" \
      --arg mergeStateStatus "$merge_state" \
      --arg baseRefName "$base_ref" \
      --argjson conflictingFiles "$files_json" \
      '{
        verdict: "conflicting",
        mergeable: $mergeable,
        mergeStateStatus: $mergeStateStatus,
        baseRefName: $baseRefName,
        conflictingFiles: $conflictingFiles,
        pr: {number: $pr.number, url: $pr.url, headRefName: $pr.headRefName}
      }'
    exit 1
  fi
  jq -n \
    --argjson pr "$pj" \
    --arg mergeable "$mergeable" \
    --arg mergeStateStatus "$merge_state" \
    --arg baseRefName "$base_ref" \
    '{
      verdict: "mergeable",
      mergeable: $mergeable,
      mergeStateStatus: $mergeStateStatus,
      baseRefName: $baseRefName,
      pr: {number: $pr.number, url: $pr.url, headRefName: $pr.headRefName}
    }'
}

cmd_conflict_files() {
  list_conflict_files
}

case "$CMD" in
  status) cmd_status ;;
  conflict-files) cmd_conflict_files ;;
  fetch-base) cmd_fetch_base ;;
  "") usage ;;
  *) echo "unknown command: $CMD" >&2; usage ;;
esac
