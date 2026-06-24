#!/usr/bin/env bash
# Run golden gate + hook fixture cases.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STUB="$ROOT/scripts/test/gh-stub.sh"
GATE="$ROOT/scripts/check-gate.sh"
CONFIG_BACKUP=""
CONFIG_PATH="$ROOT/.cursor/workflow.config.json"

restore_config() {
  if [ -n "$CONFIG_BACKUP" ] && [ -f "$CONFIG_BACKUP" ]; then
    mv "$CONFIG_BACKUP" "$CONFIG_PATH"
  elif [ -n "$CONFIG_BACKUP" ]; then
    rm -f "$CONFIG_PATH"
    rmdir "$ROOT/.cursor" 2>/dev/null || true
  fi
}

run_case() {
  local name="$1" fixture="$2" expect_ec="$3" expect_verdict="$4"
  export SW_GATE_FIXTURE="$fixture"
  export SW_GATE_NOW=1577838000
  set +e
  OUT=$(PATH="$(dirname "$STUB"):$PATH" bash "$GATE" 42 2>/dev/null)
  EC=$?
  set -e
  VERDICT=$(echo "$OUT" | jq -r .verdict 2>/dev/null || echo "parse-error")
  if [ "$EC" -eq "$expect_ec" ] && [ "$VERDICT" = "$expect_verdict" ]; then
    echo "OK  $name exit=$EC verdict=$VERDICT"
  else
    echo "FAIL $name expected exit=$expect_ec verdict=$expect_verdict got exit=$EC verdict=$VERDICT"
    echo "$OUT" | jq . 2>/dev/null || echo "$OUT"
    return 1
  fi
}

mkdir -p "$ROOT/scripts/test/bin"
cat > "$ROOT/scripts/test/bin/gh" <<'WRAP'
#!/usr/bin/env bash
exec "$(dirname "$0")/../gh-stub.sh" "$@"
WRAP
chmod +x "$ROOT/scripts/test/bin/gh"
export PATH="$ROOT/scripts/test/bin:$PATH"

FAIL=0
run_case green green 0 green || FAIL=1
run_case yellow-pending yellow-pending 10 yellow || FAIL=1
run_case red-fail red-fail 20 red || FAIL=1
run_case blocked-empty blocked-empty 30 blocked || FAIL=1
run_case blocked-threads blocked-threads 30 blocked || FAIL=1
# repo not onboarded to the review provider: no signal past grace -> non-blocking green
run_case unconfigured unconfigured 0 green || FAIL=1

# nocap provider must never green
if [ -f "$CONFIG_PATH" ]; then
  CONFIG_BACKUP="$(mktemp)"
  cp "$CONFIG_PATH" "$CONFIG_BACKUP"
else
  CONFIG_BACKUP="none"
  mkdir -p "$ROOT/.cursor"
fi
trap restore_config EXIT

cat > "$CONFIG_PATH" <<'CFG'
{
  "review": { "provider": "nocap-stub" },
  "coderabbit": { "reviewGraceMinutes": 15 },
  "checks": { "treatNeutralAsPass": true, "neutralAllowlist": [] }
}
CFG
export SW_GATE_FIXTURE=green
export SW_GATE_NOW=1577838000
OUT=$(bash "$GATE" 42 2>/dev/null) || EC=$?
EC=${EC:-$?}
VERDICT=$(echo "$OUT" | jq -r .verdict)
if [ "$EC" -eq 10 ] && [ "$VERDICT" = "yellow" ]; then
  echo "OK  nocap-stub exit=10 verdict=yellow (never green)"
else
  echo "FAIL nocap-stub expected exit=10 verdict=yellow got exit=$EC verdict=$VERDICT"
  FAIL=1
fi

# review.provider:none opts out of review gating -> green on a clean check fixture
cat > "$CONFIG_PATH" <<'CFG'
{
  "review": { "provider": "none" },
  "coderabbit": { "reviewGraceMinutes": 15 },
  "checks": { "treatNeutralAsPass": true, "neutralAllowlist": [] }
}
CFG
export SW_GATE_FIXTURE=unconfigured
export SW_GATE_NOW=1577838000
unset EC
OUT=$(bash "$GATE" 42 2>/dev/null) || EC=$?
EC=${EC:-$?}
VERDICT=$(echo "$OUT" | jq -r .verdict)
CRSTATE=$(echo "$OUT" | jq -r .coderabbitState)
if [ "$EC" -eq 0 ] && [ "$VERDICT" = "green" ] && [ "$CRSTATE" = "disabled" ]; then
  echo "OK  review-disabled exit=0 verdict=green state=disabled"
else
  echo "FAIL review-disabled expected exit=0 verdict=green state=disabled got exit=$EC verdict=$VERDICT state=$CRSTATE"
  FAIL=1
fi

restore_config
trap - EXIT

bash "$ROOT/scripts/test/run-hook-fixtures.sh" || FAIL=1

exit "$FAIL"
