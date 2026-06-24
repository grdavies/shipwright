#!/usr/bin/env bash
# Golden tests for platform capability descriptors (M0–M3 schema scope).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VALIDATE="$ROOT/scripts/test/validate-descriptor.sh"
FIX="$ROOT/scripts/test/fixtures/capability"

chmod +x "$VALIDATE"
mkdir -p "$FIX"

FAIL=0

run_expect() {
  local name="$1" expect_ec="$2" desc="$3"
  set +e
  OUT=$("$VALIDATE" "$desc" 2>&1)
  EC=$?
  set -e
  if [ "$EC" -eq "$expect_ec" ]; then
    echo "OK  $name exit=$EC"
  else
    echo "FAIL $name expected exit=$expect_ec got exit=$EC"
    echo "$OUT"
    FAIL=1
  fi
}

run_expect cursor-tier1 0 "$ROOT/platforms/cursor/descriptor.json"
run_expect claude-code-tier1 0 "$ROOT/platforms/claude-code/descriptor.json"

# Unknown flag value (M4-only vocabulary rejected in M1 schema)
cat >"$FIX/bad-hooks-wrapper.json" <<'JSON'
{
  "platform": "codex",
  "hooks": "wrapper",
  "skills": "native",
  "commands": "slash-md",
  "rules": "mdc",
  "subagents": "native",
  "mcp": "yes",
  "memoryXport": "mcp"
}
JSON
run_expect unknown-hooks-value 1 "$FIX/bad-hooks-wrapper.json"

# Missing required flag
cat >"$FIX/missing-flag.json" <<'JSON'
{
  "platform": "cursor",
  "hooks": "native",
  "skills": "native",
  "commands": "slash-md",
  "rules": "mdc",
  "subagents": "native",
  "mcp": "yes"
}
JSON
run_expect missing-memoryXport 1 "$FIX/missing-flag.json"

exit "$FAIL"
