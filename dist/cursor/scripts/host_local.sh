#!/usr/bin/env bash
# Local / no-remote host adapter (PRD 026 Phase 3).
set -euo pipefail
ROOT=""
VERB=""
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) VERB="$1"; shift; ARGS=("$@"); break ;;
  esac
done
[[ -n "$ROOT" ]] || ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIXTURE="${SW_LOCAL_GATE_FIXTURE:-${SW_HOST_FIXTURE:-}}"
kv() {
  local key="$1" default="${2-}" i=0
  while [[ $i -lt ${#ARGS[@]} ]]; do
    if [[ "${ARGS[$i]}" == "--$key" && $((i + 1)) -lt ${#ARGS[@]} ]]; then
      echo "${ARGS[$((i + 1))]}"
      return 0
    fi
    i=$((i + 1))
  done
  echo "$default"
}
emit_json() {
  python3 -c 'import json,sys; print(json.dumps(json.loads(sys.argv[1]), indent=2))' "$1"
}
degraded_json() {
  emit_json "{\"verdict\":\"degraded\",\"verb\":\"$VERB\",\"provider\":\"none\",\"reason\":\"$1\",\"retryable\":false}"
  exit 0
}
run_lib() {
  python3 "${SCRIPT_DIR}/host_local_lib.py" --root "$ROOT" "$@"
}
case "$VERB" in
  repo-meta)
    payload="$(run_lib repo-meta)"
    emit_json "$payload"
    ;;
  resolve-pr-for-branch)
    payload="$(run_lib resolve-pr)"
    emit_json "$payload"
    ;;
  pr-view)
    num="$(kv number 0)"
    payload="$(run_lib pr-view-verb --number "$num")"
    emit_json "$payload"
    ;;
  pr-list)
    head="$(kv head)"
    payload="$(run_lib pr-list --head "$head")"
    emit_json "$payload"
    ;;
  pr-head)
    num="$(kv number 0)"
    payload="$(run_lib pr-head --number "$num")"
    emit_json "$payload"
    ;;
  checks)
    checks_file="${SCRIPT_DIR}/test/fixtures/host/checks-${FIXTURE}.json"
    if [[ -n "$FIXTURE" && -f "$checks_file" ]]; then
      payload="$(python3 "${SCRIPT_DIR}/host_local_lib.py" checks-from-file --file "$checks_file")"
    else
      payload="$(run_lib checks-default)"
    fi
    emit_json "$payload"
    ;;
  review-threads)
    payload='{"verdict":"ok","verb":"review-threads","provider":"none","data":{"unresolved":0,"actionable":0,"localEvidence":true}}'
    emit_json "$payload"
    ;;
  pr-create|merge)
    degraded_json "capability-missing"
    ;;
  *)
    degraded_json "capability-missing"
    ;;
esac
