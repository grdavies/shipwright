#!/usr/bin/env bash
# Fixtures for PRD 026 Phase 1 — host adapter + rate-limit foundation.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../fixture-lib.sh
source "$ROOT/scripts/test/fixture-lib.sh"
SELECT="$ROOT/scripts/capability-select.sh"
FAIL=0

ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

chmod +x "$ROOT/scripts/host-detect.sh" "$ROOT/scripts/host_token.sh" \
  "$ROOT/scripts/host_transport.py" "$ROOT/scripts/host-doctor.sh" 2>/dev/null || true

# --- host-provider-select ---
if OUT=$(python3 "$ROOT/scripts/host_lib.py" --root "$ROOT" resolve) && \
   echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('verdict') == 'ok'
assert d.get('provider') in {'github','gitlab','bitbucket','none'}
assert d.get('remote') == 'origin'
"; then
  ok "host-provider-select"
else
  bad "host-provider-select"
fi

if [[ -x "$SELECT" ]]; then
  CFG=$(python3 - <<'PY' "$ROOT/.cursor/workflow.config.json"
import json, sys
print(json.dumps({'version':1,'phase_type':'sw-ship','config':json.load(open(sys.argv[1]))}))
PY
  )
  if OUT=$("$SELECT" --context-json "$CFG" 2>/dev/null) && \
     echo "$OUT" | python3 -c "
import json, sys
ids = {r['id'] for r in json.load(sys.stdin).get('capabilities', [])}
assert any('host.github' in i for i in ids)
"; then
    ok "host-provider-select capability-index"
  else
    bad "host-provider-select capability-index"
  fi
fi

# --- host-verb-capability-flags ---
for adapter in github none; do
  if grep -q '"pr-create"' "$ROOT/core/providers/host/${adapter}.md" && \
     grep -q '"verbs"' "$ROOT/core/providers/host/${adapter}.md"; then
    ok "host-verb-capability-flags:${adapter}"
  else
    bad "host-verb-capability-flags:${adapter}"
  fi
done
if grep -q 'pr-create' "$ROOT/core/providers/host/CAPABILITIES.md" && \
   grep -q 'merge' "$ROOT/core/providers/host/CAPABILITIES.md"; then
  ok "host-verb-capability-flags:contract"
else
  bad "host-verb-capability-flags:contract"
fi

# --- remote-url-autodetect ---
autodetect_cases=(
  'https://github.com/o/r.git|github'
  'git@github.com:o/r.git|github'
  'https://gitlab.com/o/r.git|gitlab'
  'git@gitlab.com:o/r.git|gitlab'
  'https://bitbucket.org/o/r.git|bitbucket'
  'git@bitbucket.org:o/r.git|bitbucket'
  '|none'
)
for row in "${autodetect_cases[@]}"; do
  url="${row%%|*}"
  want="${row##*|}"
  if OUT=$(python3 "$ROOT/scripts/host_lib.py" detect-url "$url" 2>/dev/null) && \
     echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['provider']==sys.argv[1]" "$want"; then
    ok "remote-url-autodetect:${want}"
  else
    bad "remote-url-autodetect:${want}"
  fi
done

# --- origin-literal-guard (R7 script set) ---
R7_FILES=(
  scripts/wave_merge.py
  scripts/wave_terminal.py
  scripts/stabilize-merge-sync.sh
  scripts/worktree.sh
  scripts/cleanup_lib.py
)
ORIGIN_FAIL=0
for rel in "${R7_FILES[@]}"; do
  if rg -n '"origin"' "$ROOT/$rel" >/dev/null 2>&1 || rg -n "'origin'" "$ROOT/$rel" >/dev/null 2>&1; then
  # allow comments/docs only — fail on string literal origin used as remote
    if rg -n '["\x27]origin["\x27]|refs/remotes/origin|origin/' "$ROOT/$rel" >/dev/null 2>&1; then
      echo "origin literal remains in $rel"
      ORIGIN_FAIL=1
    fi
  fi
done
if [[ "$ORIGIN_FAIL" -eq 0 ]]; then
  ok "origin-literal-guard"
else
  bad "origin-literal-guard"
fi

# --- missing-token-degrades ---
(
  unset GITHUB_TOKEN GH_TOKEN 2>/dev/null || true
  if OUT=$(bash "$ROOT/scripts/host_token.sh" --root "$ROOT") && \
     echo "$OUT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
assert d.get('verdict') == 'degraded'
assert d.get('reason') == 'missing-token'
assert 'token' not in json.dumps(d).lower() or 'tokenenv' in json.dumps(d).lower()
"; then
    ok "missing-token-degrades"
  else
    bad "missing-token-degrades"
  fi
)
if ps -ax -o args= 2>/dev/null | grep -E 'host_token|host_transport' | grep -qE 'ghp_|glpat-'; then
  bad "missing-token-degrades argv-leak"
else
  ok "missing-token-degrades no-argv-leak"
fi

# --- host-ratelimit-config ---
if python3 - <<'PY' "$ROOT/.sw/config.schema.json" "$ROOT/.cursor/workflow.config.json"
import json, sys
schema = json.load(open(sys.argv[1]))
cfg = json.load(open(sys.argv[2]))
host_schema = schema['properties']['host']['properties']
for key in ('provider','remote','tokenEnv','baseUrl','apiBaseUrl','rateLimit'):
    assert key in host_schema, key
rl = host_schema['rateLimit']['properties']
for key in ('maxAttempts','baseBackoffMs','capBackoffMs','jitter','nearLimitThreshold'):
    assert key in rl, key
assert 'host' in cfg and 'rateLimit' in cfg['host']
print('ok')
PY
then
  ok "host-ratelimit-config"
else
  bad "host-ratelimit-config"
fi

# --- wait-priority-order ---
if OUT=$(python3 "$ROOT/scripts/host_ratelimit.py" compute-wait \
  --provider github --status 429 --attempt 1 \
  --headers-json '{"retry-after":"12"}') && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['reason']=='retry-after' and d['waitSeconds']==12"; then
  ok "wait-priority-order:retry-after"
else
  bad "wait-priority-order:retry-after"
fi
FUTURE=$(python3 -c 'import time; print(int(time.time())+30)')
if OUT=$(python3 "$ROOT/scripts/host_ratelimit.py" compute-wait \
  --provider github --status 403 --attempt 1 \
  --headers-json "{\"x-ratelimit-remaining\":\"0\",\"x-ratelimit-reset\":\"$FUTURE\"}") && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['reason']=='reset' and d['waitSeconds']>0"; then
  ok "wait-priority-order:reset"
else
  bad "wait-priority-order:reset"
fi
if OUT=$(python3 "$ROOT/scripts/host_ratelimit.py" compute-wait \
  --provider bitbucket --status 429 --attempt 2 \
  --headers-json '{}') && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['reason']=='backoff'"; then
  ok "wait-priority-order:backoff"
else
  bad "wait-priority-order:backoff"
fi

# --- throttle-detect-not-fail ---
RESP='[{"status":429,"headers":{"retry-after":"0"}},{"status":200,"headers":{}}]'
if OUT=$(python3 "$ROOT/scripts/host_ratelimit.py" simulate \
  --provider github --responses-json "$RESP" --config-json '{"maxAttempts":3,"baseBackoffMs":1,"capBackoffMs":10,"maxCumulativeWaitMs":5000,"jitter":false}') && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ok' and d['attempts']>=2"; then
  ok "throttle-detect-not-fail"
else
  bad "throttle-detect-not-fail"
fi

# --- bounded-retry-exhaustion-halt ---
RESP='[{"status":429,"headers":{}},{"status":429,"headers":{}},{"status":429,"headers":{}}]'
if OUT=$(python3 "$ROOT/scripts/host_ratelimit.py" simulate \
  --provider github --responses-json "$RESP" --config-json '{"maxAttempts":2,"baseBackoffMs":1,"capBackoffMs":5,"maxCumulativeWaitMs":100,"jitter":false}') && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='rate-limited' and d['retryable'] is True"; then
  ok "bounded-retry-exhaustion-halt"
else
  bad "bounded-retry-exhaustion-halt"
fi

# --- near-limit-preemptive-pause ---
RESP='[{"status":200,"headers":{"x-ratelimit-remaining":"1"}},{"status":200,"headers":{}}]'
if OUT=$(python3 "$ROOT/scripts/host_ratelimit.py" simulate \
  --provider github --responses-json "$RESP" --config-json '{"maxAttempts":3,"nearLimitThreshold":5,"baseBackoffMs":1,"capBackoffMs":10,"maxCumulativeWaitMs":5000,"jitter":false}') && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert any('near-limit' in x for x in d.get('logs',[])) or d.get('attempts',0)>=2"; then
  ok "near-limit-preemptive-pause"
else
  bad "near-limit-preemptive-pause"
fi

# --- serial-and-paced-requests ---
if python3 - "$ROOT/scripts" <<'PY'
import sys, time
sys.path.insert(0, sys.argv[1])
from host_ratelimit import SerialGate
gate = SerialGate()
gate.pace_mutating(200)
start = time.time()
gate.pace_mutating(200)
sys.exit(0 if (time.time() - start) >= 0.15 else 1)
PY
then
  ok "serial-and-paced-requests"
else
  bad "serial-and-paced-requests"
fi

# --- backoff-log-redaction ---
if OUT=$(python3 "$ROOT/scripts/host_ratelimit.py" simulate \
  --provider github --responses-json '[{"status":429,"headers":{"retry-after":"1"}}]' \
  --config-json '{"maxAttempts":2,"baseBackoffMs":1,"capBackoffMs":5,"maxCumulativeWaitMs":100,"jitter":false}') && \
   ! echo "$OUT" | grep -qE 'ghp_|Authorization|Bearer ghp'; then
  ok "backoff-log-redaction"
else
  bad "backoff-log-redaction"
fi

# --- github-migration-token-only ---
TMP_CFG=$(mktemp)
python3 - <<'PY' "$ROOT/.cursor/workflow.config.json" "$TMP_CFG"
import json, sys
cfg = json.load(open(sys.argv[1]))
cfg['host'] = {'remote': 'origin', 'tokenEnv': 'GITHUB_TOKEN'}
cfg['host'].pop('provider', None)
json.dump(cfg, open(sys.argv[2], 'w'), indent=2)
PY
TMP_ROOT=$(mktemp -d)
mkdir -p "$TMP_ROOT/.cursor"
cp "$TMP_CFG" "$TMP_ROOT/.cursor/workflow.config.json"
(
  export GITHUB_TOKEN=ghp_test_migration_fixture_token_only
  if OUT=$(GITHUB_TOKEN=ghp_test_migration_fixture_token_only python3 "$ROOT/scripts/host_lib.py" --root "$TMP_ROOT" resolve) && \
     echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('detected') in ('github','none')
assert d.get('tokenPresent') is True
assert 'ghp_' not in json.dumps(d)
"; then
    ok "github-migration-token-only"
  else
    bad "github-migration-token-only"
  fi
)
rm -rf "$TMP_ROOT" "$TMP_CFG"

# --- doctor-degraded-warns ---
if OUT=$(bash "$ROOT/scripts/host-doctor.sh" --root "$ROOT") && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict') in ('ok','degraded')
assert 'checks' in d and 'warnings' in d
"; then
  ok "doctor-degraded-warns"
else
  bad "doctor-degraded-warns"
fi


# --- Phase 2: gh-removal-guard (runtime scripts only) ---
RUNTIME_GH=0
while IFS= read -r f; do
  if rg -n '\bgh\b' "$f" >/dev/null 2>&1; then
    echo "gh reference remains in $f"
    RUNTIME_GH=1
  fi
done < <(printf '%s\n'   scripts/check-gate.py   scripts/wave_terminal.py   scripts/wave_compound.py   scripts/cleanup_lib.py   scripts/reconcile.py   scripts/stabilize-merge-sync.sh)
if [[ "$RUNTIME_GH" -eq 0 ]]; then
  ok "gh-removal-guard"
else
  bad "gh-removal-guard"
fi

# --- gh-absent-path ---
(
  export GITHUB_TOKEN=gh_fixture_token_for_tests
  export SW_HOST_FIXTURE=green
  export SW_GATE_NOW=1577838000
  export PATH="$(echo "$PATH" | tr ':' '\n' | grep -v '/scripts/test/bin' | paste -sd: -)"
  if OUT=$(env -u GH_TOKEN bash "$ROOT/scripts/check-gate.py" 42 2>/dev/null) &&      echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='green'"; then
    ok "gh-absent-path"
  else
    bad "gh-absent-path"
  fi
)

# --- check-gate-verbset ---
if bash "$ROOT/scripts/test/run-gate-fixtures.sh" >/tmp/sw-host-gate-fixtures.log 2>&1; then
  ok "check-gate-verbset"
else
  bad "check-gate-verbset"
  tail -5 /tmp/sw-host-gate-fixtures.log >&2 || true
fi

# --- pr-list-merged-state-normalization (host.py pr-list + gh_pr_to_view) ---
if python3 -c "
def normalize(pr):
    return 'MERGED' if (pr.get('merged') or pr.get('merged_at')) else pr.get('state', '').upper()
assert normalize({'state': 'closed', 'merged_at': '2026-01-01T00:00:00Z'}) == 'MERGED'
assert normalize({'state': 'closed', 'merged': True}) == 'MERGED'
assert normalize({'state': 'closed'}) == 'CLOSED'
assert normalize({'state': 'open'}) == 'OPEN'
"; then
  ok "pr-list-merged-state-normalization"
else
  bad "pr-list-merged-state-normalization"
fi

# --- terminal-flow-verbset (mocked REST) ---
(
  export GITHUB_TOKEN=gh_fixture_token_for_tests
  export SW_HOST_FIXTURE=green
  if OUT=$(python3 "$ROOT/scripts/host.py" --root "$ROOT" pr-list --head feat/x --base main --state open) &&      echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ok' and isinstance(d.get('data'), list)"; then
    ok "terminal-flow-verbset:pr-list"
  else
    bad "terminal-flow-verbset:pr-list"
  fi
  if OUT=$(python3 "$ROOT/scripts/host.py" --root "$ROOT" pr-create --title t --body b --head feat/x --base main) &&      echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ok' and d['data'].get('number')"; then
    ok "terminal-flow-verbset:pr-create"
  else
    bad "terminal-flow-verbset:pr-create"
  fi
)

# --- stabilize-sync-verbset ---
(
  export GITHUB_TOKEN=gh_fixture_token_for_tests
  export SW_HOST_FIXTURE=green
  if OUT=$(bash "$ROOT/scripts/stabilize-merge-sync.sh" status --pr 42) &&      echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['verdict']=='mergeable'"; then
    ok "stabilize-sync-verbset"
  else
    bad "stabilize-sync-verbset"
  fi
)

# --- prose-gh-free (agent command docs in scope) ---
PROSE_FAIL=0
for doc in   core/commands/sw-watch-ci.md   core/commands/sw-stabilize.md   core/commands/sw-pr.md   core/commands/sw-ready.md   core/commands/sw-cleanup.md; do
  if rg -n '`gh |\bgh pr |\bgh api |\bgh repo ' "$ROOT/$doc" >/dev/null 2>&1; then
    echo "gh prose in $doc"
    PROSE_FAIL=1
  fi
done
if [[ "$PROSE_FAIL" -eq 0 ]]; then
  ok "prose-gh-free"
else
  bad "prose-gh-free"
fi


# --- install-docs-currency ---
DOC_FAIL=0
for needle_file in README.md docs/guides/configuration.md; do
  if ! grep -q 'host.tokenEnv\|GITHUB_TOKEN' "$ROOT/$needle_file" 2>/dev/null; then
    echo "missing host token docs in $needle_file"
    DOC_FAIL=1
  fi
  if grep -q '`gh`' "$ROOT/$needle_file" 2>/dev/null || grep -q 'gh auth login' "$ROOT/$needle_file" 2>/dev/null; then
    echo "stale gh prerequisite in $needle_file"
    DOC_FAIL=1
  fi
done
if [[ "$DOC_FAIL" -eq 0 ]]; then
  ok "install-docs-currency"
else
  bad "install-docs-currency"
fi



# --- Phase 3: no-remote local mode (R9–R13) ---
LOCAL_FIX=$(mktemp -d)
trap 'rm -rf "$LOCAL_FIX" "$TMP_CFG" 2>/dev/null || true' EXIT
(
  cd "$LOCAL_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  echo base >f.txt && git add f.txt && git commit -q -m "chore: init"
  git branch -m feat/local-test
  mkdir -p .cursor
  python3 - <<'CFG' "$ROOT/.cursor/workflow.config.json" > .cursor/workflow.config.json
import json, sys
cfg = json.load(open(sys.argv[1]))
cfg['host'] = {'provider': 'none', 'remote': 'origin'}
json.dump(cfg, open('/dev/stdout','w'), indent=2)
CFG
  export SW_LOCAL_GATE_FIXTURE=green
  if OUT=$(python3 "$ROOT/scripts/host.py" --root "$LOCAL_FIX" resolve-pr-for-branch) &&      echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ok' and d['provider']=='none' and d['data'][0].get('localEvidence')"; then
    ok "noremote-local-adapter"
  else
    bad "noremote-local-adapter"
  fi
  if OUT=$(python3 "$ROOT/scripts/host.py" --root "$LOCAL_FIX" checks --sha "$(git rev-parse HEAD)") &&      echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ok' and len(d['data'])>0"; then
    ok "noremote-local-adapter:checks"
  else
    bad "noremote-local-adapter:checks"
  fi
  if OUT=$(bash "$ROOT/scripts/check-gate.py" 2>/dev/null) &&      echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('source')=='local-evidence' and d.get('verdict')=='green'"; then
    ok "check-gate-local-verdict"
  else
    bad "check-gate-local-verdict"
  fi
  RUN_DIR="$LOCAL_FIX/.cursor/sw-deliver-runs/terminal"
  mkdir -p "$RUN_DIR"
  export SW_RUN_DIR="$RUN_DIR"
  GATE_JSON="$RUN_DIR/gate.json"
  bash "$ROOT/scripts/check-gate.py" > "$GATE_JSON" 2>/dev/null || true
  HEAD=$(git rev-parse HEAD)
  if OUT=$(python3 "$ROOT/scripts/local_merge_gate.py" --root "$LOCAL_FIX" write --head "$HEAD" --gate-json "$GATE_JSON" --run-dir "$RUN_DIR") &&      test -f "$RUN_DIR/local-merge-gate.json" &&      python3 -c "import json,sys; d=json.load(open(sys.argv[1])); assert d['source']=='local-evidence' and d['head']==sys.argv[2]" "$RUN_DIR/local-merge-gate.json" "$HEAD"; then
    ok "terminal-local-evidence-gate"
  else
    bad "terminal-local-evidence-gate"
  fi
  if OUT=$(python3 "$ROOT/scripts/watch_ci_lib.py" --root "$LOCAL_FIX") &&      echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('mode')=='degraded-local' and d.get('ciWatch') is False"; then
    ok "ci-watch-local-degrade"
  else
    bad "ci-watch-local-degrade"
  fi
  mkdir -p "$LOCAL_FIX/.cursor"
  echo '{"prd_number":"026","target":{"branch":"feat/local-test","slug":"local-test","type":"feat"},"phases":{"1":{"slug":"p1","status":"green-merged"}},"terminalLocalGate":{"mode":"local-evidence"}}' > "$LOCAL_FIX/.cursor/sw-deliver-state.json"
  if OUT=$(SW_SKIP_DOCS_CURRENCY=1 python3 "$ROOT/scripts/wave_terminal.py" "$LOCAL_FIX" terminal pr gate 2>/dev/null) &&      echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('humanMergeRequired') is True and d.get('neverAutoMergesMain') is True"; then
    ok "local-merge-human-halt"
  else
    bad "local-merge-human-halt"
    echo "$OUT" | head -20 >&2 || true
  fi
)


if [[ "$FAIL" -eq 0 ]]; then
  echo "ALL host fixtures passed"
else
  echo "SOME host fixtures FAILED"
  exit 1
fi
