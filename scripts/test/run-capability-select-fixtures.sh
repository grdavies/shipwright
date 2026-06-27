#!/usr/bin/env bash
# Golden tests for deterministic capability selector (PRD 021 R10, R12, R14, R25).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SELECT="$ROOT/scripts/capability-select.sh"
FIX="$ROOT/scripts/test/fixtures/capability-select"
FAIL=0

chmod +x "$SELECT"

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

assert_ids_contain() {
  local name="$1" json="$2" want="$3"
  if echo "$json" | python3 -c "
import json, sys
data = json.load(sys.stdin)
ids = {row['id'] for row in data.get('capabilities', [])}
sys.exit(0 if sys.argv[1] in ids else 1)
" "$want" 2>/dev/null; then
    echo "OK  $name contains $want"
  else
    echo "FAIL $name missing capability $want"
    echo "$json" | python3 -c "import json,sys; print([r['id'] for r in json.load(sys.stdin).get('capabilities',[])])" 2>/dev/null || true
    FAIL=1
  fi
}

assert_ids_exclude() {
  local name="$1" json="$2" unwanted="$3"
  if echo "$json" | python3 -c "
import json, sys
data = json.load(sys.stdin)
ids = {row['id'] for row in data.get('capabilities', [])}
sys.exit(1 if sys.argv[1] in ids else 0)
" "$unwanted" 2>/dev/null; then
    echo "OK  $name excludes $unwanted"
  else
    echo "FAIL $name unexpectedly includes $unwanted"
    FAIL=1
  fi
}

assert_capability_trust() {
  local name="$1" json="$2" cap_id="$3" want_eligible="$4" want_executable="$5" want_authorized="$6" want_reason="${7:-}"
  if echo "$json" | python3 -c "
import json, sys
data = json.load(sys.stdin)
cap_id, want_eligible, want_executable, want_authorized, want_reason = sys.argv[1:6]
row = next((r for r in data.get('capabilities', []) if r.get('id') == cap_id), None)
if row is None:
    print(f'missing capability {cap_id}')
    sys.exit(1)
checks = [
    row.get('eligible') == (want_eligible == 'true'),
    row.get('executable') == (want_executable == 'true'),
    row.get('authorized') == (want_authorized == 'true'),
]
if want_reason:
    checks.append(row.get('refusalReason') == want_reason)
if all(checks):
    sys.exit(0)
print(row)
sys.exit(1)
" "$cap_id" "$want_eligible" "$want_executable" "$want_authorized" "$want_reason" 2>/dev/null; then
    echo "OK  $name"
  else
    echo "FAIL $name trust state for $cap_id"
    echo "$json" | python3 -c "import json,sys; print([r for r in json.load(sys.stdin).get('capabilities',[]) if r.get('id')=='$cap_id'])"
    FAIL=1
  fi
}

build_fixture_index() {
  local core_dir="$1" index_path="$2"
  python3 -c "
import json, sys
sys.path.insert(0, '$ROOT/scripts')
from capability_index import build_index
from pathlib import Path
index = build_index(Path('$core_dir'))
Path('$index_path').write_text(json.dumps(index, indent=2) + '\n')
"
}

# --- selector-determinism-repeat-identical ---
CTX_DOC_REVIEW='{"version":1,"phase_type":"sw-doc-review","body_snapshot":"# Minimal PRD\nNo security signals."}'
OUT1=$("$SELECT" --context-json "$CTX_DOC_REVIEW")
OUT2=$("$SELECT" --context-json "$CTX_DOC_REVIEW")
if [ "$OUT1" = "$OUT2" ]; then
  echo "OK  selector-determinism-repeat-identical"
else
  echo "FAIL selector-determinism-repeat-identical output drift"
  FAIL=1
fi

# Across dist trees when present
for DIST in "$ROOT/dist/cursor" "$ROOT/dist/claude-code"; do
  if [ -x "$DIST/scripts/capability-select.sh" ]; then
    D1=$("$DIST/scripts/capability-select.sh" --context-json "$CTX_DOC_REVIEW" 2>/dev/null || true)
    D2=$("$DIST/scripts/capability-select.sh" --context-json "$CTX_DOC_REVIEW" 2>/dev/null || true)
    if [ -n "$D1" ] && [ "$D1" = "$D2" ] && [ "$D1" = "$OUT1" ]; then
      echo "OK  selector-determinism-repeat-identical dist $(basename "$DIST")"
    elif [ -n "$D1" ]; then
      echo "FAIL selector-determinism-repeat-identical dist $(basename "$DIST")"
      FAIL=1
    fi
  fi
done

# --- selector-isolation-fixture (failing-before: security gated off) ---
CTX_MINIMAL='{"version":1,"body_snapshot":"# Hello\nPlain requirements."}'
OUT_MIN=$("$SELECT" --context-json "$CTX_MINIMAL")
assert_ids_contain selector-isolation-core-always-on "$OUT_MIN" persona.sw-coherence-reviewer
assert_ids_exclude selector-isolation-security-gated-off "$OUT_MIN" persona.sw-security-reviewer

# passing-after: security signal present
CTX_AUTH='{"version":1,"body_snapshot":"# Auth PRD\nWe need OAuth login and session handling."}'
OUT_AUTH=$("$SELECT" --context-json "$CTX_AUTH")
assert_ids_contain selector-isolation-security-gated-on "$OUT_AUTH" persona.sw-security-reviewer

# --- capability-dropin-frontmatter-only (R12) ---
DROPIN="$FIX/dropin"
DROPIN_CORE="$DROPIN/core"
DROPIN_INDEX="$DROPIN/capability-index.json"
rm -rf "$DROPIN_CORE"
mkdir -p "$DROPIN_CORE/skills/dropin-demo" "$DROPIN_CORE/sw-reference"
cat >"$DROPIN_CORE/skills/dropin-demo/SKILL.md" <<'YAML'
---
name: dropin-demo
capability:
  version: 1
  triggers:
    - type: text_token
      selectionFamily: doc-review
      source: body_snapshot
      match: whole_token
      tokens:
        - dropin-marker
  metadata:
    skill: dropin-demo
    selectionFamily: doc-review
---
YAML
python3 -c "
import json, sys
sys.path.insert(0, '$ROOT/scripts')
from capability_index import build_index
from pathlib import Path
index = build_index(Path('$DROPIN_CORE'))
Path('$DROPIN_INDEX').write_text(json.dumps(index, indent=2) + '\n')
"
DROPIN_CTX='{"version":1,"body_snapshot":"Uses dropin-marker token in prose."}'
DROPIN_OUT=$(python3 "$ROOT/scripts/capability_select.py" --root "$DROPIN" --index "$DROPIN_INDEX" --context-json "$DROPIN_CTX" --skip-freshness)
assert_ids_contain capability-dropin-frontmatter-only "$DROPIN_OUT" skill.dropin-demo

# --- signal_context resume snapshot ---
RESUME_DIR=$(mktemp -d)
trap 'rm -rf "$RESUME_DIR"' EXIT
CTX_RESUME='{"version":1,"body_snapshot":"# Resume\nOAuth auth flow."}'
FIRST=$(python3 "$ROOT/scripts/capability_select.py" --root "$ROOT" --context-json "$CTX_RESUME" --run-dir "$RESUME_DIR")
SECOND=$(python3 "$ROOT/scripts/capability_select.py" --root "$ROOT" --context-json '{"version":1,"body_snapshot":"mutated"}' --run-dir "$RESUME_DIR" --resume)
if [ "$FIRST" = "$SECOND" ]; then
  echo "OK  signal-context-resume-snapshot"
else
  echo "FAIL signal-context-resume-snapshot"
  FAIL=1
fi
if [ -f "$RESUME_DIR/signal-context.json" ]; then
  echo "OK  signal-context-durable-write"
else
  echo "FAIL signal-context-durable-write"
  FAIL=1
fi

# --- run-log-capability-set-surfaced (R21) ---
LOG_ROOT=$(mktemp -d)
LOG_PHASE="$LOG_ROOT/.cursor/sw-deliver-runs/run-log-fixture-phase"
mkdir -p "$LOG_PHASE"
LOG_INDEX="$ROOT/core/sw-reference/capability-index.json"
LOG_CTX='{"version":1,"phase_type":"sw-doc-review","body_snapshot":"# Auth PRD\nOAuth login flow."}'
LOG_OUT=$(python3 "$ROOT/scripts/capability_select.py" --root "$LOG_ROOT" --index "$LOG_INDEX" \
  --context-json "$LOG_CTX" --run-dir "$LOG_PHASE" --skip-freshness 2>/dev/null || true)
DELIVER_LOG="$LOG_ROOT/.cursor/sw-deliver-runs/run.log"
PHASE_LOG="$LOG_PHASE/run.log"
if python3 -c "
import json, sys
from pathlib import Path

deliver = Path(sys.argv[1])
phase = Path(sys.argv[2])
selection = json.loads(sys.argv[3])
want = {row['id'] for row in selection.get('capabilities', [])}

def check(path: Path) -> bool:
    if not path.is_file():
        return False
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry.get('event') != 'capability-selection':
            continue
        got = set(entry.get('resolvedCapabilities') or [])
        if got != want:
            return False
        if not entry.get('inputsHash'):
            return False
        if not entry.get('precedenceTrace'):
            return False
        if not entry.get('at'):
            return False
        if not entry.get('activationRecord'):
            return False
        return True
    return False

sys.exit(0 if check(deliver) and check(phase) else 1)
" "$DELIVER_LOG" "$PHASE_LOG" "$LOG_OUT"; then
  echo "OK  run-log-capability-set-surfaced"
else
  echo "FAIL run-log-capability-set-surfaced"
  FAIL=1
fi
rm -rf "$LOG_ROOT"

# --- stale index fails closed (failing-before) ---
INDEX="$ROOT/core/sw-reference/capability-index.json"
if [ -f "$INDEX" ]; then
  INDEX_BACKUP=$(mktemp)
  cp "$INDEX" "$INDEX_BACKUP"
  python3 -c "
import json
from pathlib import Path
p = Path('$INDEX')
data = json.loads(p.read_text())
data['capabilities'].append({
  'id': 'phantom.tamper',
  'kind': 'skill',
  'sourcePath': 'core/skills/phantom/SKILL.md',
  'executable': False,
  'capability': {'version': 1, 'triggers': [{'type': 'always_on'}]},
})
p.write_text(json.dumps(data, indent=2) + '\n')
"
  run_expect selector-stale-index-fails-closed 20 "$SELECT" --context-json "$CTX_MINIMAL"
  cp "$INDEX_BACKUP" "$INDEX"
  rm -f "$INDEX_BACKUP"
  run_expect selector-fresh-index-passes 0 "$SELECT" --context-json "$CTX_MINIMAL"
fi

# --- capability-trust-unconfigured-provider (R27) ---
TRUST_UNCONFIGURED="$FIX/trust-unconfigured-provider"
TRUST_UNCONFIGURED_CORE="$TRUST_UNCONFIGURED/core"
TRUST_UNCONFIGURED_INDEX="$TRUST_UNCONFIGURED/capability-index.json"
rm -rf "$TRUST_UNCONFIGURED_CORE"
mkdir -p "$TRUST_UNCONFIGURED_CORE/providers/review" "$TRUST_UNCONFIGURED_CORE/sw-reference"
cat >"$TRUST_UNCONFIGURED_CORE/providers/review/unconfigured.md" <<'YAML'
---
capability:
  version: 1
  triggers:
    - type: always_on
      selectionFamily: providers
  metadata:
    providerFamily: review
    adapterId: coderabbit
    gateRef: check-gate.sh
    selectionFamily: providers
---
YAML
build_fixture_index "$TRUST_UNCONFIGURED_CORE" "$TRUST_UNCONFIGURED_INDEX"
TRUST_UNCONFIGURED_CTX='{"version":1,"config":{"review":{"provider":"none"}}}'
TRUST_UNCONFIGURED_OUT=$(python3 "$ROOT/scripts/capability_select.py" \
  --root "$TRUST_UNCONFIGURED" --index "$TRUST_UNCONFIGURED_INDEX" \
  --context-json "$TRUST_UNCONFIGURED_CTX" --skip-freshness)
assert_capability_trust capability-trust-unconfigured-provider "$TRUST_UNCONFIGURED_OUT" \
  provider.providers.review.unconfigured true true false unconfigured_provider

# --- capability-trust-unknown-hook (R27) ---
TRUST_UNKNOWN_HOOK="$FIX/trust-unknown-hook"
TRUST_UNKNOWN_HOOK_CORE="$TRUST_UNKNOWN_HOOK/core"
TRUST_UNKNOWN_HOOK_INDEX="$TRUST_UNKNOWN_HOOK/capability-index.json"
rm -rf "$TRUST_UNKNOWN_HOOK_CORE"
mkdir -p "$TRUST_UNKNOWN_HOOK_CORE/hooks" "$TRUST_UNKNOWN_HOOK_CORE/sw-reference"
cat >"$TRUST_UNKNOWN_HOOK_CORE/hooks/augment-hook.md" <<'YAML'
---
capability:
  version: 1
  triggers:
    - type: always_on
      selectionFamily: hooks
  metadata:
    selectionFamily: hooks
    gateRef: hooks.json:unknownSlot
---
YAML
build_fixture_index "$TRUST_UNKNOWN_HOOK_CORE" "$TRUST_UNKNOWN_HOOK_INDEX"
TRUST_UNKNOWN_HOOK_OUT=$(python3 "$ROOT/scripts/capability_select.py" \
  --root "$TRUST_UNKNOWN_HOOK" --index "$TRUST_UNKNOWN_HOOK_INDEX" \
  --context-json '{"version":1}' --skip-freshness)
assert_capability_trust capability-trust-unknown-hook "$TRUST_UNKNOWN_HOOK_OUT" \
  hook.augment-hook true true false unknown_hook

# --- capability-config-override-untrusted (R27) ---
TRUST_OVERRIDE="$FIX/trust-config-override"
TRUST_OVERRIDE_CORE="$TRUST_OVERRIDE/core"
TRUST_OVERRIDE_INDEX="$TRUST_OVERRIDE/capability-index.json"
rm -rf "$TRUST_OVERRIDE_CORE"
mkdir -p "$TRUST_OVERRIDE_CORE/providers/review" "$TRUST_OVERRIDE_CORE/sw-reference"
cat >"$TRUST_OVERRIDE_CORE/providers/review/override-target.md" <<'YAML'
---
capability:
  version: 1
  triggers:
    - type: always_on
      selectionFamily: providers
  metadata:
    providerFamily: review
    adapterId: coderabbit
    gateRef: check-gate.sh
    selectionFamily: providers
---
YAML
build_fixture_index "$TRUST_OVERRIDE_CORE" "$TRUST_OVERRIDE_INDEX"
TRUST_OVERRIDE_CTX='{"version":1,"config":{"review":{"provider":"native"}}}'
TRUST_OVERRIDE_OUT=$(python3 "$ROOT/scripts/capability_select.py" \
  --root "$TRUST_OVERRIDE" --index "$TRUST_OVERRIDE_INDEX" \
  --context-json "$TRUST_OVERRIDE_CTX" --skip-freshness)
assert_capability_trust capability-config-override-untrusted "$TRUST_OVERRIDE_OUT" \
  provider.providers.review.override-target true true false config_override_untrusted

# --- capability-index-tamper-reject (R27) ---
TRUST_TAMPER="$FIX/trust-index-tamper"
TRUST_TAMPER_CORE="$TRUST_TAMPER/core"
TRUST_TAMPER_INDEX="$TRUST_TAMPER/capability-index.json"
rm -rf "$TRUST_TAMPER_CORE"
mkdir -p "$TRUST_TAMPER_CORE/providers/review" "$TRUST_TAMPER_CORE/sw-reference"
python3 -c "
import json
from pathlib import Path
index = {
  'version': 1,
  'capabilities': [{
    'id': 'provider.providers.review.tampered',
    'kind': 'provider',
    'sourcePath': 'core/providers/review/tampered.md',
    'executable': True,
    'capability': {
      'version': 1,
      'triggers': [{'type': 'always_on', 'selectionFamily': 'providers'}],
      'metadata': {
        'providerFamily': 'review',
        'adapterId': 'coderabbit',
        'gateRef': 'check-gate.sh',
        'selectionFamily': 'providers',
      },
    },
  }],
}
Path('$TRUST_TAMPER_INDEX').parent.mkdir(parents=True, exist_ok=True)
Path('$TRUST_TAMPER_INDEX').write_text(json.dumps(index, indent=2) + '\n')
"
TRUST_TAMPER_CTX='{"version":1,"config":{"review":{"provider":"coderabbit"}}}'
TRUST_TAMPER_OUT=$(python3 "$ROOT/scripts/capability_select.py" \
  --root "$TRUST_TAMPER" --index "$TRUST_TAMPER_INDEX" \
  --context-json "$TRUST_TAMPER_CTX" --skip-freshness)
assert_capability_trust capability-index-tamper-reject "$TRUST_TAMPER_OUT" \
  provider.providers.review.tampered true true false index_tamper

# --- capability-hook-kernel-non-selectable (R27) ---
KERNEL_HOOK="$FIX/kernel-hook"
KERNEL_HOOK_CORE="$KERNEL_HOOK/core"
KERNEL_HOOK_INDEX="$KERNEL_HOOK/capability-index.json"
rm -rf "$KERNEL_HOOK_CORE"
mkdir -p "$KERNEL_HOOK_CORE/hooks" "$KERNEL_HOOK_CORE/sw-reference"
cat >"$KERNEL_HOOK_CORE/hooks/before-submit-guardrails.md" <<'YAML'
---
capability:
  version: 1
  triggers:
    - type: always_on
      selectionFamily: hooks
  metadata:
    selectionFamily: hooks
    gateRef: hooks.json:beforeSubmitPrompt
---
YAML
run_expect capability-hook-kernel-lint-rejects 1 \
  python3 "$ROOT/scripts/capability_manifest_lint.py" \
  --root "$KERNEL_HOOK" --core "$KERNEL_HOOK_CORE" --index "$KERNEL_HOOK_INDEX"
build_fixture_index "$KERNEL_HOOK_CORE" "$KERNEL_HOOK_INDEX"
KERNEL_HOOK_OUT=$(python3 "$ROOT/scripts/capability_select.py" \
  --root "$KERNEL_HOOK" --index "$KERNEL_HOOK_INDEX" \
  --context-json '{"version":1}' --skip-freshness)
assert_ids_exclude capability-hook-kernel-non-selectable "$KERNEL_HOOK_OUT" hook.before-submit-guardrails

exit "$FAIL"
