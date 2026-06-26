#!/usr/bin/env bash
# Fixtures for secret-safety guardrails (PRD 007 Phase 9 — R41/R42/R50–R52).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCAN="$ROOT/scripts/secret-scan.sh"
PUSH="$ROOT/scripts/git-push.sh"
GUARD="$ROOT/scripts/redaction-guard.sh"
FAIL=0

ok()   { echo "OK  $1"; }
bad()  { echo "FAIL $1"; FAIL=1; }

FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT

cd "$FIX"
git init -q
git config user.email test@test.com
git config user.name Test
git commit --allow-empty -q -m init
mkdir -p .cursor
cp "$ROOT/.cursor/sw-secret-scan-allowlist.json" .cursor/

# --- secret-scan-prepush: deny patterns block push locally ---
echo 'api_key=ghp_deadbeefdeadbeefdeadbeefdeadbeefdead' > leak.txt
git add leak.txt
git commit -q -m 'plant secret'
set +e
bash "$SCAN" pre-push >/dev/null 2>&1
EC=$?
set -e
if [[ "$EC" -eq 1 ]]; then
  ok "secret-scan-prepush: deny pattern blocks scan"
else
  bad "secret-scan-prepush: expected exit 1 got $EC"
fi

# --- secret-patterns-single-source-allowlist: allowlisted fixture literal passes ---
git reset --hard -q HEAD~1 2>/dev/null || true
echo 'SECRET_SCAN_FIXTURE_ALLOWLIST_MARKER sk_test_fixture_allowlisted_secret_scan_0123456789' > fixture.txt
git add fixture.txt
git commit -q -m 'allowlisted fixture'
set +e
bash "$SCAN" pre-push >/dev/null 2>&1
EC_ALLOW=$?
set -e
if [[ "$EC_ALLOW" -eq 0 ]]; then
  ok "secret-patterns-single-source-allowlist: allowlisted literal passes"
else
  bad "secret-patterns-single-source-allowlist: allowlisted literal should pass got $EC_ALLOW"
fi

# patterns-check + memory_redact coupling
set +e
python3 "$ROOT/scripts/secret_scan.py" patterns-check >/dev/null 2>&1
EC_PAT=$?
set -e
if [[ "$EC_PAT" -eq 0 ]]; then
  ok "secret-patterns-single-source-allowlist: patterns-check passes"
else
  bad "secret-patterns-single-source-allowlist: patterns-check failed ec=$EC_PAT"
fi

# path-aware pre-push diff + config namespace not treated as internal host
set +e
PYTHONPATH="$ROOT/scripts" python3 - <<'PY' >/dev/null 2>&1
import subprocess
from pathlib import Path

from secret_scan import load_allowlist, scan_diff, scan_text

root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
allowlist = load_allowlist(root)

doc = "Resolve `review.local` from workflow.config.json"
assert not scan_text(doc, allowlist=allowlist, path="docs/guide.md"), "review.local should not match INTERNAL_HOST"

fixture_diff = """diff --git a/scripts/test/run-secret-scan-fixtures.sh b/scripts/test/run-secret-scan-fixtures.sh
--- a/scripts/test/run-secret-scan-fixtures.sh
+++ b/scripts/test/run-secret-scan-fixtures.sh
+echo 'api_key=ghp_deadbeefdeadbeefdeadbeefdeadbeefdead' > leak.txt
"""
assert not scan_diff(fixture_diff, allowlist=allowlist), "fixture path allowlist should apply per diff file"
PY
EC_PATH=$?
set -e
if [[ "$EC_PATH" -eq 0 ]]; then
  ok "secret-scan-path-aware-diff: review.local + fixture path allowlist"
else
  bad "secret-scan-path-aware-diff: path-aware scan regression ec=$EC_PATH"
fi

# fail-closed on corrupt allowlist
echo 'not-json' > .cursor/sw-secret-scan-allowlist.json
set +e
bash "$SCAN" pre-push >/dev/null 2>&1
EC_CORRUPT=$?
set -e
if [[ "$EC_CORRUPT" -eq 2 ]]; then
  ok "secret-patterns-single-source-allowlist: corrupt allowlist fails closed (exit 2)"
else
  bad "secret-patterns-single-source-allowlist: corrupt allowlist expected exit 2 got $EC_CORRUPT"
fi

# --- secret-scan-at-sw-pr-push: sw-pr documents git-push wrapper ---
if grep -qE 'git-push\.sh' "$ROOT/core/commands/sw-pr.md"; then
  ok "secret-scan-at-sw-pr-push: sw-pr uses git-push wrapper"
else
  bad "secret-scan-at-sw-pr-push: sw-pr missing git-push.sh"
fi
if grep -qE 'secret-scan' "$ROOT/core/commands/sw-pr.md"; then
  ok "secret-scan-at-sw-pr-push: sw-pr documents secret-scan"
else
  bad "secret-scan-at-sw-pr-push: sw-pr missing secret-scan reference"
fi

# git-push.sh invokes scan before push (dry-run: scan only path)
if grep -qE 'secret-scan\.sh' "$ROOT/scripts/git-push.sh"; then
  ok "secret-scan-at-sw-pr-push: git-push.sh invokes secret-scan"
else
  bad "secret-scan-at-sw-pr-push: git-push.sh missing secret-scan"
fi

# --- redaction-mechanical-guard: bare filter-branch refused ---
set +e
bash "$GUARD" check-command -- git filter-branch --force --index-filter 'true' HEAD >/dev/null 2>&1
EC_FB=$?
set -e
if [[ "$EC_FB" -eq 20 ]]; then
  ok "redaction-mechanical-guard: bare filter-branch refused (exit 20)"
else
  bad "redaction-mechanical-guard: bare filter-branch expected exit 20 got $EC_FB"
fi

# --- redaction-range-scoped-guard: range allowed + rule present ---
set +e
bash "$GUARD" check-command -- git filter-branch --force main..feature-branch >/dev/null 2>&1
EC_RANGE=$?
set -e
if [[ "$EC_RANGE" -eq 0 ]]; then
  ok "redaction-range-scoped-guard: range-scoped filter-branch allowed"
else
  bad "redaction-range-scoped-guard: range-scoped should pass got $EC_RANGE"
fi
if [[ -f "$ROOT/core/rules/sw-redaction-scope.mdc" ]]; then
  ok "redaction-range-scoped-guard: sw-redaction-scope rule present"
else
  bad "redaction-range-scoped-guard: sw-redaction-scope.mdc missing"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "secret-scan fixtures: FAIL"
  exit 1
fi
echo "secret-scan fixtures: PASS"
