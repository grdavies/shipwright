#!/usr/bin/env bash
# Conventional Commit message validator (PRD 026 R25).
# Types single-sourced from release-please-config.json (same as branch-name-guard).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FALLBACK_TYPES="feat fix perf revert docs chore refactor test"

load_types() {
  local cfg="$ROOT/release-please-config.json"
  if [[ -f "$cfg" ]]; then
    python3 - "$cfg" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
    types = []
    for pkg in data.get("packages", {}).values():
        for sec in pkg.get("changelog-sections", []):
            t = sec.get("type")
            if t and t not in types:
                types.append(t)
    print(" ".join(types) if types else "feat fix perf revert docs chore refactor test")
except Exception:
    print("feat fix perf revert docs chore refactor test")
PY
  else
    echo "$FALLBACK_TYPES"
  fi
}

types_alternation() {
  local types
  types="$(load_types)"
  echo "${types// /|}"
}

validate() {
  local msg="$1"
  if [[ -f "$msg" ]]; then
    msg="$(grep -v '^#' "$msg" | head -1 || true)"
  fi
  local subject
  subject="${msg%%$'\n'*}"
  [[ -n "$subject" ]] || {
    printf '{"verdict":"fail","reason":"empty-subject"}\n' >&2
    return 3
  }
  local alt
  alt="$(types_alternation)"
  if [[ "$subject" =~ ^(${alt})(\([a-z0-9._/-]+\))?!?:\ .+ ]]; then
    printf '{"verdict":"pass","subject":"%s"}\n' "$subject"
    return 0
  fi
  printf '{"verdict":"fail","subject":"%s","allowedTypes":"%s","remediation":"use <type>(<scope>): <description> e.g. feat: add branch guard"}\n' \
    "$subject" "$(load_types)" >&2
  return 3
}

cmd="${1:-}"
shift || true
case "$cmd" in
  types) load_types ;;
  validate)
    [[ $# -ge 1 ]] || { echo "usage: commit-msg-guard.py validate <message-or-file>" >&2; exit 2; }
    validate "$1"
    ;;
  *)
    echo "usage: commit-msg-guard.py {types | validate <message-or-file>}" >&2
    exit 2
    ;;
esac
