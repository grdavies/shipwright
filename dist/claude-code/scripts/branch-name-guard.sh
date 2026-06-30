#!/usr/bin/env bash
# Branch-name conformance guard.
#
# Single source of truth for allowed branch type prefixes: the Conventional-Commit
# types declared in release-please-config.json (changelog-sections[].type). Used by
# scripts/worktree.py (provision floor) and scripts/wave_deliver.py (multi-feature
# derivation) so a non-conforming branch (notably the legacy `pf/` prefix) can never
# be minted off-script (PRD 007 R22/R23/R25/R27).
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

slugify() {
  printf '%s' "$1" \
    | sed -E 's#^[A-Za-z]+/##' \
    | tr '[:upper:]' '[:lower:]' \
    | sed -E 's/[^a-z0-9._/-]+/-/g; s#/+#/#g; s/^[-/]+//; s/[-/]+$//'
}

derive() {
  local raw="$1"
  local type="${2:-feat}"
  local slug
  slug="$(slugify "$raw")"
  [[ -n "$slug" ]] || slug="work"
  echo "${type}/${slug}"
}

validate() {
  local branch="$1"
  local alt
  alt="$(types_alternation)"
  if [[ "$branch" =~ ^(${alt})/[a-z0-9][a-z0-9._/-]*$ ]]; then
    printf '{"verdict":"pass","branch":"%s"}\n' "$branch"
    return 0
  fi
  printf '{"verdict":"fail","branch":"%s","allowedTypes":"%s","remediation":"use <type>/<slug> with a release-please type, e.g. %s"}\n' \
    "$branch" "$(load_types)" "$(derive "$branch")" >&2
  return 3
}

cmd="${1:-}"
shift || true
case "$cmd" in
  types) load_types ;;
  validate)
    [[ $# -ge 1 ]] || { echo "usage: branch-name-guard.py validate <branch>" >&2; exit 2; }
    validate "$1"
    ;;
  derive)
    [[ $# -ge 1 ]] || { echo "usage: branch-name-guard.py derive <name> [type]" >&2; exit 2; }
    derive "$@"
    ;;
  *)
    echo "usage: branch-name-guard.py {types | validate <branch> | derive <name> [type]}" >&2
    exit 2
    ;;
esac
