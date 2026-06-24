#!/usr/bin/env bash
# Golden tests for the byte-parity harness (snapshot + compare).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SNAPSHOT="$ROOT/scripts/snapshot-tree.sh"
COMPARE="$ROOT/scripts/test/parity-compare.sh"
FIX="$ROOT/scripts/test/fixtures/parity"
GOLDEN="$FIX/cursor-golden.manifest"

chmod +x "$SNAPSHOT" "$COMPARE"

FAIL=0
TMP_BASE="$(mktemp -d "${TMPDIR:-/tmp}/pf-parity-fix.XXXXXX")"
trap 'rm -rf "$TMP_BASE"' EXIT

run_expect() {
  local name="$1" expect_ec="$2"
  shift 2
  set +e
  OUT=$("$@" 2>&1)
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

# Fixture tree: happy match
HAPPY="$TMP_BASE/happy-tree"
mkdir -p "$HAPPY/commands"
echo 'cmd body' >"$HAPPY/commands/pf-test.md"
MANIFEST_HAPPY="$TMP_BASE/happy.manifest"
printf 'commands/pf-test.md\t%s\n' "$(shasum -a 256 "$HAPPY/commands/pf-test.md" | awk '{print $1}')" >"$MANIFEST_HAPPY"
run_expect happy-match 0 "$COMPARE" "$HAPPY" "$MANIFEST_HAPPY"

# Missing file
MISSING="$TMP_BASE/missing-tree"
mkdir -p "$MISSING/commands"
run_expect missing-file 1 "$COMPARE" "$MISSING" "$MANIFEST_HAPPY"

# Extra file
EXTRA="$TMP_BASE/extra-tree"
cp -R "$HAPPY" "$EXTRA"
echo 'extra' >"$EXTRA/commands/extra.md"
run_expect extra-file 1 "$COMPARE" "$EXTRA" "$MANIFEST_HAPPY"

# Hash diff
DIFF="$TMP_BASE/diff-tree"
cp -R "$HAPPY" "$DIFF"
echo 'changed' >"$DIFF/commands/pf-test.md"
run_expect hash-diff 1 "$COMPARE" "$DIFF" "$MANIFEST_HAPPY"

# Deterministic re-snapshot
TMP_MANIFEST="$(mktemp)"
"$SNAPSHOT" "$TMP_MANIFEST"
"$SNAPSHOT" "${TMP_MANIFEST}.2"
if cmp -s "$TMP_MANIFEST" "${TMP_MANIFEST}.2"; then
  echo "OK  snapshot-deterministic identical across two runs"
else
  echo "FAIL snapshot-deterministic manifests differ between runs"
  FAIL=1
fi
rm -f "$TMP_MANIFEST" "${TMP_MANIFEST}.2"

# Live repo golden manifest matches current emittable tree
if [ ! -f "$GOLDEN" ]; then
  echo "FAIL cursor-golden.manifest missing at $GOLDEN"
  FAIL=1
else
  run_expect cursor-golden-vs-repo 0 "$COMPARE" "$ROOT" "$GOLDEN"
fi

exit "$FAIL"
