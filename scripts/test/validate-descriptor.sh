#!/usr/bin/env bash
# Validate a platform descriptor against platforms/descriptor.schema.json (M0–M3 scope).
#
# Usage: scripts/test/validate-descriptor.sh <descriptor.json>
# Exit 0 when valid; non-zero with a named error on failure.
set -euo pipefail

DESC="${1:?descriptor path required}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCHEMA="$ROOT/platforms/descriptor.schema.json"

if [ ! -f "$DESC" ]; then
  echo "descriptor-validate: file not found: $DESC" >&2
  exit 2
fi
if [ ! -f "$SCHEMA" ]; then
  echo "descriptor-validate: schema not found: $SCHEMA" >&2
  exit 2
fi

if ! jq -e . "$DESC" >/dev/null 2>&1; then
  echo "descriptor-validate: invalid JSON: $DESC"
  exit 1
fi

REQUIRED_KEYS=(platform hooks skills commands rules subagents mcp memoryXport)
for key in "${REQUIRED_KEYS[@]}"; do
  if [ "$(jq -r --arg k "$key" 'has($k)' "$DESC")" != "true" ]; then
    echo "descriptor-validate: missing required flag: $key"
    exit 1
  fi
done

EXTRA_COUNT=$(jq -r \
  --argjson req "$(printf '%s\n' "${REQUIRED_KEYS[@]}" | jq -R . | jq -s .)" \
  '[keys[] | select(. as $k | ($req | index($k)) | not)] | length' "$DESC")
if [ "$EXTRA_COUNT" != "0" ]; then
  EXTRA_KEYS=$(jq -r \
    --argjson req "$(printf '%s\n' "${REQUIRED_KEYS[@]}" | jq -R . | jq -s .)" \
    '[keys[] | select(. as $k | ($req | index($k)) | not)] | join(",")' "$DESC")
  echo "descriptor-validate: unknown keys: $EXTRA_KEYS"
  exit 1
fi

allowed_for() {
  local field="$1"
  jq -r --arg f "$field" '.properties[$f].enum[]?' "$SCHEMA"
}

validate_enum() {
  local field="$1"
  local value
  value="$(jq -r --arg f "$field" '.[$f]' "$DESC")"
  local allowed match=0
  while IFS= read -r allowed; do
    [ -n "$allowed" ] || continue
    if [ "$value" = "$allowed" ]; then
      match=1
      break
    fi
  done < <(allowed_for "$field")
  if [ "$match" -eq 0 ]; then
    echo "descriptor-validate: invalid $field value: $value"
    exit 1
  fi
}

for key in hooks skills commands rules subagents mcp memoryXport; do
  validate_enum "$key"
done

PLATFORM="$(jq -r '.platform' "$DESC")"
if [ -z "$PLATFORM" ] || [ "$PLATFORM" = "null" ]; then
  echo "descriptor-validate: platform must be a non-empty string"
  exit 1
fi

echo "descriptor-validate: ok platform=$PLATFORM"
exit 0
