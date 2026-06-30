#!/usr/bin/env bash
# Safety-invariant parity fixtures under planPolicy: proposed (PRD 022 phase 6 — R2, R23, R25).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VALIDATE="$ROOT/scripts/wave_plan_validate.py"
TERM_PY="$ROOT/scripts/wave_terminal.py"
STATE_PY="$ROOT/scripts/wave_state.py"
PUSH="$ROOT/scripts/git-push.sh"
GUARD="$ROOT/scripts/redaction-guard.sh"
REDACT="$ROOT/scripts/memory-redact.sh"
SCAN="$ROOT/scripts/secret-scan.sh"
WF="$ROOT/.cursor/workflow.config.json"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT

mkdir -p "$FIX/.cursor" "$FIX/core/sw-reference" "$FIX/scripts"
cp -R "$ROOT/core/sw-reference/." "$FIX/core/sw-reference/"
for f in kernel_classification.py guidelines_validate.py plan_floor_evaluator.py wave_plan_validate.py orchestrator_step_plan.py plan_persist.py wave_deliver.py wave_json_io.py wave_terminal.py wave_state.py capability_trust.py memory_redact.py secret_patterns.py; do
  cp "$ROOT/scripts/$f" "$FIX/scripts/"
done

cat >"$FIX/.cursor/workflow.config.json" <<'JSON'
{"orchestration":{"planPolicy":"proposed"},"defaultBaseBranch":"main"}
JSON

CANONICAL_STEPS='["sw-tmp-init","sw-execute","sw-verify","verification-gate","sw-review","sw-simplify","gap-check","sw-commit","sw-pr","sw-watch-ci","sw-stabilize","sw-ready","sw-tmp-clean"]'

# Shared: proposed policy active + kernel chokepoint registered.
assert_proposed_chokepoint() {
  local fixture="$1"
  local chokepoint_id="$2"
  if python3 - <<PY
import sys
sys.path.insert(0, "$FIX/scripts")
from pathlib import Path
from kernel_classification import load_classification
from wave_plan_validate import read_config_plan_policy

root = Path("$FIX")
assert read_config_plan_policy(root) == "proposed", read_config_plan_policy(root)
data = load_classification(root)
match = [c for c in data.get("kernelChokepoints") or [] if c.get("id") == "$chokepoint_id"]
assert match, "missing chokepoint $chokepoint_id"
assert match[0].get("layer") == "kernel", match[0]
PY
  then
    ok "$fixture"
  else
    bad "$fixture"
  fi
}

# --- plan-proposed-memory-preflight-required ---
assert_proposed_chokepoint "plan-proposed-memory-preflight-required" "memory-preflight-routing"
if python3 - <<PY
import sys
sys.path.insert(0, "$FIX/scripts")
from capability_trust import MEMORY_GATES, authorize_executable

assert "memory-preflight" in MEMORY_GATES
entry = {
    "kind": "provider",
    "executable": True,
    "capability": {"metadata": {"providerFamily": "memory", "gateRef": "fake-bypass-gate.sh"}},
}
auth = authorize_executable(
    entry,
    {"config": {"memory": {"provider": "recallium"}}},
    eligible=True,
    repo_root=None,
    resolve_config_value=lambda cfg, key: (cfg.get("memory") or {}).get("provider"),
    is_configured=lambda v: bool(v),
)
assert auth["authorized"] is False and auth["refusalReason"] == "unknown_gate", auth
entry["capability"]["metadata"]["gateRef"] = "memory-preflight"
auth2 = authorize_executable(
    entry,
    {"config": {"memory": {"provider": "recallium"}}},
    eligible=True,
    repo_root=None,
    resolve_config_value=lambda cfg, key: (cfg.get("memory") or {}).get("provider"),
    is_configured=lambda v: bool(v),
)
assert auth2["authorized"] is True, auth2
PY
then
  ok "plan-proposed-memory-preflight-required gate-enforced"
else
  bad "plan-proposed-memory-preflight-required gate-enforced"
fi

# --- plan-proposed-memory-redact-fail-closed ---
assert_proposed_chokepoint "plan-proposed-memory-redact-fail-closed" "memory-redaction-chokepoint"
if printf 'token=%s\n' 'AKIAIOSFODNN7EXAMPLE' | bash "$REDACT" 2>/dev/null | python3 -c "
import sys
text = sys.stdin.read()
assert 'AKIAIOSFODNN7EXAMPLE' not in text
assert '[REDACTED' in text or 'REDACTED' in text
"; then
  ok "plan-proposed-memory-redact-fail-closed redacts-secrets"
else
  bad "plan-proposed-memory-redact-fail-closed redacts-secrets"
fi
if python3 - <<PY
import sys
sys.path.insert(0, "$FIX/scripts")
from capability_trust import KERNEL_HOOK_SOURCE_MARKERS, is_kernel_hook_source

assert any("memory-redact" in m for m in KERNEL_HOOK_SOURCE_MARKERS)
assert is_kernel_hook_source("scripts/memory-redact.sh")
PY
then
  ok "plan-proposed-memory-redact-fail-closed kernel-hook-marker"
else
  bad "plan-proposed-memory-redact-fail-closed kernel-hook-marker"
fi

# --- plan-proposed-secret-scan-before-push ---
assert_proposed_chokepoint "plan-proposed-secret-scan-before-push" "git-push-secret-scan"
if grep -qE 'secret-scan\.sh' "$PUSH"; then
  ok "plan-proposed-secret-scan-before-push git-push-wrapper"
else
  bad "plan-proposed-secret-scan-before-push git-push-wrapper"
fi
if OUT=$(python3 "$VALIDATE" "$FIX" validate --tier phase --phase-type ship \
  --proposal "{\"steps\":[\"sw-tmp-init\",\"sw-execute\",\"sw-commit\",\"sw-pr\"]}" 2>/dev/null) \
  && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict'] in ('reject','ambiguous')
assert any('chokepoint' in r or 'ordering' in r or 'missing' in r for r in d.get('reasons',[]))
"; then
  ok "plan-proposed-secret-scan-before-push kernel-envelope-rejects-skip"
else
  bad "plan-proposed-secret-scan-before-push kernel-envelope-rejects-skip"
fi

# --- plan-proposed-no-main-auto-merge ---
assert_proposed_chokepoint "plan-proposed-no-main-auto-merge" "no-main-auto-merge"
SHIP_FIX=$(mktemp -d)
(
  cd "$SHIP_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  git branch -M main
  git checkout -qb feat/terminal-proposed
  mkdir -p .cursor
  cat > .cursor/workflow.config.json <<'JSON'
{"orchestration":{"planPolicy":"proposed"},"defaultBaseBranch":"main","deliver":{"terminal":{"autonomy":"auto"}}}
JSON
  echo '{"verdict":"running","prd_number":"022","target":{"branch":"feat/terminal-proposed"},"phases":{"1":{"status":"green-merged","slug":"a"}},"compoundShip":{"premergeDone":true}}' \
    > .cursor/sw-deliver-state.feat-terminal-proposed.json
  if OUT=$(python3 "$TERM_PY" "$SHIP_FIX" terminal ship run --dry-run 2>/dev/null) \
    && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('neverAutoMergesMain') is True
assert 'merge' not in ' '.join(d.get('steps',[])).lower() or 'gate' in json.dumps(d)
"; then
    exit 0
  fi
  exit 1
) && ok "plan-proposed-no-main-auto-merge terminal-human-gate" \
  || bad "plan-proposed-no-main-auto-merge terminal-human-gate"
rm -rf "$SHIP_FIX"

# --- plan-proposed-merge-single-flight ---
assert_proposed_chokepoint "plan-proposed-merge-single-flight" "merge-single-flight-lock"
LOCK_FIX=$(mktemp -d)
mkdir -p "$LOCK_FIX/.cursor"
cp "$FIX/.cursor/workflow.config.json" "$LOCK_FIX/.cursor/"
if python3 "$STATE_PY" "$LOCK_FIX" lock acquire --target feat/alpha --nonblock >/dev/null 2>&1; then
  set +e
  python3 "$STATE_PY" "$LOCK_FIX" lock acquire --target feat/alpha --nonblock 2>/dev/null
  EC_LOCK=$?
  set -e
  if [[ "$EC_LOCK" -eq 20 ]]; then
    ok "plan-proposed-merge-single-flight O_EXCL-refused"
  else
    bad "plan-proposed-merge-single-flight O_EXCL-refused (ec=$EC_LOCK)"
  fi
else
  bad "plan-proposed-merge-single-flight O_EXCL-refused (first acquire failed)"
fi
rm -rf "$LOCK_FIX"

# --- plan-proposed-redaction-guard-range-scope ---
assert_proposed_chokepoint "plan-proposed-redaction-guard-range-scope" "range-scoped-redaction-guard"
set +e
bash "$GUARD" check-command -- git filter-branch --force --index-filter 'true' HEAD >/dev/null 2>&1
EC_FB=$?
bash "$GUARD" check-command -- git filter-branch --force main..feature-branch >/dev/null 2>&1
EC_RANGE=$?
set -e
if [[ "$EC_FB" -eq 20 ]] && [[ "$EC_RANGE" -eq 0 ]]; then
  ok "plan-proposed-redaction-guard-range-scope mechanical-guard"
else
  bad "plan-proposed-redaction-guard-range-scope mechanical-guard (bare=$EC_FB range=$EC_RANGE)"
fi

# --- plan-proposed-guardrails-hook-non-selectable ---
assert_proposed_chokepoint "plan-proposed-guardrails-hook-non-selectable" "beforeSubmitPrompt-guardrails"
if python3 - <<PY
import sys
sys.path.insert(0, "$FIX/scripts")
from capability_trust import KERNEL_HOOK_SLOTS, authorize_executable, parse_hook_slot

assert "beforeSubmitPrompt" in KERNEL_HOOK_SLOTS
slot = parse_hook_slot("hooks.json:beforeSubmitPrompt")
assert slot == "beforeSubmitPrompt"
entry = {
    "kind": "hook",
    "executable": True,
    "capability": {"metadata": {"gateRef": "hooks.json:beforeSubmitPrompt"}},
}
auth = authorize_executable(
    entry,
    {"config": {}},
    eligible=True,
    repo_root=None,
    resolve_config_value=lambda cfg, key: None,
    is_configured=lambda v: False,
)
assert auth["authorized"] is False and auth["refusalReason"] == "unknown_hook", auth
PY
then
  ok "plan-proposed-guardrails-hook-non-selectable manifest-refused"
else
  bad "plan-proposed-guardrails-hook-non-selectable manifest-refused"
fi
if python3 - <<PY
import json
from pathlib import Path
data = json.loads(Path("$ROOT/core/sw-reference/kernel-classification.json").read_text())
match = [c for c in data.get("kernelChokepoints") or [] if c.get("id") == "beforeSubmitPrompt-guardrails"]
assert match and match[0].get("nonSelectable") is True
PY
then
  ok "plan-proposed-guardrails-hook-non-selectable non-selectable-flag"
else
  bad "plan-proposed-guardrails-hook-non-selectable non-selectable-flag"
fi

# --- cross-cutting: canonical plan passes, kernel-skip rejected under proposed ---
if OUT=$(python3 "$VALIDATE" "$FIX" validate --tier phase --phase-type ship \
  --proposal "{\"steps\":$CANONICAL_STEPS}" 2>/dev/null) \
  && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='pass'
plan=d.get('plan') or {}
assert plan.get('planPolicy')=='proposed'
"; then
  ok "plan-proposed-canonical-chain-passes"
else
  bad "plan-proposed-canonical-chain-passes"
fi

# --- verify.test registration ---
if grep -q 'run-plan-proposed-parity-fixtures.sh' "$WF" 2>/dev/null; then
  ok "plan-proposed-verify-registration"
else
  bad "plan-proposed-verify-registration"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "plan-proposed-parity fixtures: all passed"
  exit 0
fi
echo "plan-proposed-parity fixtures: $FAIL failure(s)"
exit 1
