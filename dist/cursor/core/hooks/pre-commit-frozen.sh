#!/usr/bin/env bash
# Local pre-commit hook: block commits touching frozen artifacts.
# Early warning only — bypassable via --no-verify. CI check-frozen.py is authoritative.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
CHECK="$ROOT/scripts/check-frozen.py"

if [ ! -x "$CHECK" ]; then
  echo "sw-freeze: check-frozen.py missing or not executable; refusing commit" >&2
  exit 1
fi

STAGED="$(git diff --cached --name-only)"
[ -z "$STAGED" ] && exit 0

is_frozen_at_head() {
  local path="$1"
  git show "HEAD:$path" 2>/dev/null | awk '
    /^---$/ { fm=1; next }
    fm && /^---$/ { exit }
    fm && /^frozen:[[:space:]]*true/ { found=1; exit }
    END { exit !found }
  '
}

VIOLATIONS=()
while IFS= read -r path; do
  [ -z "$path" ] && continue
  # New files (not at HEAD) are allowed — mirrors check-frozen status A
  if ! git cat-file -e "HEAD:$path" 2>/dev/null; then
    continue
  fi
  if is_frozen_at_head "$path"; then
    if git diff --cached --quiet -- "$path" 2>/dev/null; then
      : # no staged change
    else
      TMPDIR_CB="$(mktemp -d)"
      git show "HEAD:$path" >"$TMPDIR_CB/old" 2>/dev/null || true
      git show ":$path" >"$TMPDIR_CB/new" 2>/dev/null || true
      if python3 "$ROOT/scripts/checkbox_diff.py" is-checkbox-only "$TMPDIR_CB/old" "$TMPDIR_CB/new" >/dev/null 2>&1; then
        rm -rf "$TMPDIR_CB"
        continue
      fi
      rm -rf "$TMPDIR_CB"
      VIOLATIONS+=("$path")
    fi
  fi
done <<< "$STAGED"

if [ "${#VIOLATIONS[@]}" -gt 0 ]; then
  echo "sw-freeze: refusing commit — frozen artifact(s) modified:" >&2
  printf '  %s\n' "${VIOLATIONS[@]}" >&2
  echo "Use /sw-amend for post-freeze changes. Bypass with --no-verify (CI will still block)." >&2
  exit 1
fi

exit 0
