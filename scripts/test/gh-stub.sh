#!/usr/bin/env bash
# Minimal gh stub for check-gate fixture tests. Place ahead of real gh on PATH.
# Select fixture set via SW_GATE_FIXTURE (green|yellow-pending|red-fail|blocked-empty).
set -euo pipefail

FIXTURE="${SW_GATE_FIXTURE:-green}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/fixtures" && pwd)"

cmd="${1:-}"
shift || true

sw_jq_filter() {
  local out="$1"
  shift
  local args=("$@")
  local i=0
  while [ $i -lt ${#args[@]} ]; do
    if [ "${args[$i]}" = "--jq" ] && [ $((i + 1)) -lt ${#args[@]} ]; then
      echo "$out" | jq -r "${args[$((i + 1))]}"
      return
    fi
    i=$((i + 1))
  done
  echo "$out"
}

case "$cmd" in
  pr)
    sub="${1:-}"
    shift || true
    case "$sub" in
      view)
        rest=("$@")
        joined="${rest[*]}"
        if [[ "$joined" == *"--json"* ]]; then
          case "$FIXTURE" in
            no-pr) out='{}' ;;
            *)
              out=$(jq -n \
                --argjson n 42 \
                --arg h "abc123def4567890abcdef1234567890abcdef12" \
                '{number:$n, headRefOid:$h}')
              ;;
          esac
          sw_jq_filter "$out" "${rest[@]}"
        fi
        ;;
      checks)
        local_pr="${1:-42}"
        cat "$DIR/checks-${FIXTURE}.json" 2>/dev/null || cat "$DIR/checks-green.json"
        ;;
    esac
    ;;
  repo)
    sub="${1:-}"
    shift || true
    rest=("$@")
    joined="${rest[*]}"
    if [ "$sub" = "view" ] && [[ "$joined" == *"--json"* ]]; then
      out='{"nameWithOwner":"owner/repo"}'
      sw_jq_filter "$out" "${rest[@]}"
    fi
    ;;
  api)
    endpoint="${1:-}"
    shift || true
    rest=("$@")
    if [ "$endpoint" = "graphql" ]; then
      if [ -f "$DIR/threads-${FIXTURE}.json" ]; then
        out=$(cat "$DIR/threads-${FIXTURE}.json")
      else
        out=$(cat "$DIR/reviews-${FIXTURE}.json" 2>/dev/null || echo '{"data":{"repository":{"pullRequest":{"reviews":{"nodes":[]}}}}}')
      fi
      sw_jq_filter "$out" "${rest[@]}"
    elif [[ "$endpoint" == repos/* ]]; then
      if [[ "$endpoint" == */commits/* ]]; then
        out='{"commit":{"committer":{"date":"2020-01-01T00:00:00Z"}}}'
        sw_jq_filter "$out" "${rest[@]}"
      else
        out=$(cat "$DIR/comments-${FIXTURE}.json" 2>/dev/null || echo '[]')
        sw_jq_filter "$out" "${rest[@]}"
      fi
    fi
    ;;
esac
exit 0
