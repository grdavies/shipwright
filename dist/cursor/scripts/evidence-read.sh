#!/usr/bin/env bash
# Shared safe evidence file/dir reads (plan 005 U4).
# Source from verify-evidence.sh, simplify-gate.sh, feedback-closure-gate.sh.
set -euo pipefail

stat_uid() {
  local target="$1"
  if stat -f '%u' "$target" >/dev/null 2>&1; then
    stat -f '%u' "$target"
  else
    stat -c '%u' "$target"
  fi
}

stat_perms() {
  local target="$1"
  if stat -f '%Lp' "$target" >/dev/null 2>&1; then
    stat -f '%Lp' "$target"
  else
    stat -c '%a' "$target"
  fi
}

caller_uid() {
  id -u
}

# Validate a run directory: real dir, not symlink, caller-owned, mode 0700.
validate_run_dir() {
  local dir="$1"
  [[ -n "$dir" && -d "$dir" ]] || return 1
  [[ -L "$dir" ]] && return 1
  [[ "$(stat_uid "$dir")" == "$(caller_uid)" ]] || return 1
  local perms
  perms="$(stat_perms "$dir")"
  [[ "$perms" == "700" ]] || return 1
  return 0
}

# safe_read_check PATH — exit 0 if safe to read, 1 if rejected.
safe_read_check() {
  local path="$1"
  [[ -e "$path" ]] || return 1
  [[ -L "$path" ]] && return 1
  [[ "$(stat_uid "$path")" == "$(caller_uid)" ]] || return 1
  local perms
  perms="$(stat_perms "$path")"
  local group_digit=$(((perms / 10) % 10))
  local other_digit=$((perms % 10))
  # Reject group/world-writable only (644 repo fixtures remain readable).
  [[ $((group_digit & 2)) -ne 0 ]] && return 1
  [[ $((other_digit & 2)) -ne 0 ]] && return 1
  return 0
}

# safe_jq PATH FILTER — read JSON via a single fd (TOCTOU-safe within bash 3.2).
safe_jq() {
  local path="$1" filter="$2"
  safe_read_check "$path" || return 1
  exec 3< "$path"
  jq "$filter" <&3
  local ec=$?
  exec 3<&-
  return $ec
}

# safe_jq_r PATH FILTER — raw (-r) output for string/number scalars.
safe_jq_r() {
  local path="$1" filter="$2"
  safe_read_check "$path" || return 1
  exec 3< "$path"
  jq -r "$filter" <&3
  local ec=$?
  exec 3<&-
  return $ec
}
