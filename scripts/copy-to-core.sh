#!/usr/bin/env bash
# Refresh core/ workflow copies from repo-root scripts (content dirs live only under core/ post-U6).
#
# Usage: scripts/copy-to-core.sh [--force]
#   --force  Allow orphan deletion outside deprecatedAllowlist (fixtures/CI only; logged).
#
# Idempotent: re-run refreshes core/scripts from root harness scripts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE="$ROOT/core"
MANIFEST="$CORE/sw-reference/build-chain-sot.json"
FORCE=0

for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --help|-h)
      cat <<'EOF'
Usage: scripts/copy-to-core.sh [--force]

Sync repo-root harness and content dirs into core/ per build-chain-sot.json.

  --force  Permit deleting core/sw-reference orphans outside deprecatedAllowlist.
           Restricted to fixture/CI invocations; logs a warning.
EOF
      exit 0
      ;;
    *)
      echo "copy-to-core: unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$MANIFEST" ]]; then
  echo "copy-to-core: missing manifest $MANIFEST (run build-chain sync after PRD 038)" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "copy-to-core: jq required to read $MANIFEST" >&2
  exit 1
fi

ALLOWLIST=()
while IFS= read -r line; do ALLOWLIST+=("$line"); done < <(jq -r '.coreAuthoredAllowlist[]' "$MANIFEST")
DEPRECATED=()
while IFS= read -r line; do [[ -n "$line" ]] && DEPRECATED+=("$line"); done < <(jq -r '.deprecatedAllowlist[]? // empty' "$MANIFEST")

is_allowlisted() {
  local rel="$1"
  local entry
  for entry in "${ALLOWLIST[@]}"; do
    case "$entry" in
      */)
        local prefix="${entry%/}"
        if [[ "$rel" == "$prefix" || "$rel" == "$prefix"/* ]]; then
          return 0
        fi
        ;;
      *)
        if [[ "$rel" == "$entry" ]]; then
          return 0
        fi
        ;;
    esac
  done
  return 1
}

is_deprecated() {
  local rel="$1"
  local entry
  if ((${#DEPRECATED[@]} == 0)); then
    return 1
  fi
  for entry in "${DEPRECATED[@]}"; do
    [[ -z "$entry" ]] && continue
    if [[ "$rel" == "$entry" || "$rel" == "$entry"/* ]]; then
      return 0
    fi
  done
  return 1
}

sw_source_has_path() {
  local sw_dir="$1"
  local rel="$2"
  [[ -f "$sw_dir/$rel" || -d "$sw_dir/$rel" ]] && return 0
  local parent="$rel"
  while [[ "$parent" == */* ]]; do
    parent="${parent%/*}"
    [[ -f "$sw_dir/$parent" || -d "$sw_dir/$parent" ]] && return 0
  done
  return 1
}

rsync_sw_reference_excludes() {
  local -a excludes=()
  local entry
  for entry in "${ALLOWLIST[@]}"; do
    excludes+=(--exclude "$entry")
  done
  rsync -a --delete "${excludes[@]}" "$@"
}

check_sw_reference_orphans() {
  local sw_dir="${1:-}"
  [[ -d "$sw_dir" ]] || return 0

  local orphans=()
  local rel

  while IFS= read -r -d '' path; do
    rel="${path#"$CORE/sw-reference/"}"
    is_allowlisted "$rel" && continue
    is_deprecated "$rel" && continue
    sw_source_has_path "$sw_dir" "$rel" && continue
    orphans+=("$rel")
  done < <(find "$CORE/sw-reference" -mindepth 1 \( -type f -o -type d \) -print0 2>/dev/null)

  if [[ "${#orphans[@]}" -eq 0 ]]; then
    return 0
  fi

  if [[ "$FORCE" -eq 1 ]]; then
    echo "copy-to-core: WARNING --force deleting sw-reference orphans: ${orphans[*]}" >&2
    return 0
  fi

  echo "copy-to-core: refuse orphan deletion under core/sw-reference/ (fail-closed):" >&2
  for rel in "${orphans[@]}"; do
    echo "  - $rel" >&2
  done
  echo "copy-to-core: add to coreAuthoredAllowlist, relocate to .sw/, deprecatedAllowlist, or use --force (fixtures/CI only)" >&2
  return 1
}

mkdir -p "$CORE"

for dir in commands skills rules agents providers; do
  [ -d "$ROOT/$dir" ] || continue
  mkdir -p "$CORE/$dir"
  rsync -a --delete "$ROOT/$dir/" "$CORE/$dir/"
done

mkdir -p "$CORE/scripts"
rsync -a --delete \
  --exclude 'test/' \
  --exclude 'check-frozen.sh' \
  "$ROOT/scripts/" "$CORE/scripts/"
rm -f "$CORE/scripts/check-frozen.sh"

if [ -d "$ROOT/.pf" ]; then
  mkdir -p "$CORE/sw-reference"
  check_sw_reference_orphans "$ROOT/.pf" || exit 1
  rsync -a --delete "$ROOT/.pf/" "$CORE/sw-reference/"
elif [ -d "$ROOT/.sw" ]; then
  mkdir -p "$CORE/sw-reference"
  check_sw_reference_orphans "$ROOT/.sw" || exit 1
  rsync_sw_reference_excludes "$ROOT/.sw/" "$CORE/sw-reference/"
fi

echo "copy-to-core: synced emittable content -> $CORE"
