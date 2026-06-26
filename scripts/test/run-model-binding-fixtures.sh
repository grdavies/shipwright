#!/usr/bin/env bash
# PRD 012 model-tier runtime binding fixture suite (R11).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

RESOLVE="$ROOT/scripts/resolve-model-tier.sh"
PREFLIGHT="$ROOT/scripts/reviewer-dispatch-check.sh"
MODEL_CHECK="$ROOT/scripts/model-tier-check.sh"
SCHEMA="$ROOT/.sw/config.schema.json"
DEFAULTS="$ROOT/core/sw-reference/model-routing.defaults.json"
CONFIG="$ROOT/.cursor/workflow.config.json"
DISPATCH="$ROOT/core/rules/sw-subagent-dispatch.mdc"
DOC_REVIEW="$ROOT/core/skills/doc-review/SKILL.md"
TIERING="$ROOT/core/sw-reference/models-tiering.md"
AGENTS_DIR="$ROOT/core/agents"

TMPDIR_FIX="${TMPDIR:-/tmp}/sw-model-binding-$$"
mkdir -p "$TMPDIR_FIX"
trap 'rm -rf "$TMPDIR_FIX"' EXIT

# --- resolve-model-tier-agent ---
if OUT=$(bash "$RESOLVE" --agent sw-coherence-reviewer --config "$CONFIG" 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['tier']=='build' and d['modelId']=='composer-2.5' and d['source']=='routing.agents'"; then
  ok "resolve-model-tier-agent"
else
  bad "resolve-model-tier-agent"
fi

# --- resolve-model-tier-agent-default ---
if OUT=$(bash "$RESOLVE" --agent totally-unmapped-agent-xyz --config "$CONFIG" 2>/dev/null) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['source']=='roles.reviewer-default' and d['modelId']"; then
  ok "resolve-model-tier-agent-default"
else
  bad "resolve-model-tier-agent-default"
fi

# --- dispatch-preflight-no-model ---
BROKEN="$TMPDIR_FIX/broken-config.json"
python3 - <<'PY' "$BROKEN"
import json, sys
json.dump({
    "models": {
        "tiers": {},
        "roles": {"builder": "build", "reviewer": "build"},
        "routing": {"agents": {"sw-coherence-reviewer": "build"}},
    }
}, open(sys.argv[1], "w"))
PY
set +e
PREF_OUT=$(bash "$PREFLIGHT" --agent sw-coherence-reviewer --parent-model composer-2.5 --config "$BROKEN" 2>/dev/null)
PREF_EC=$?
set -e
if [[ "$PREF_EC" -eq 20 ]] && echo "$PREF_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('cause')=='no-model-resolved'"; then
  ok "dispatch-preflight-no-model"
else
  bad "dispatch-preflight-no-model (ec=$PREF_EC)"
fi

# --- dispatch-preflight-parent-floor ---
set +e
PF_OUT=$(bash "$PREFLIGHT" --agent sw-coherence-reviewer --parent-model composer-2.5-fast --config "$CONFIG" 2>/dev/null)
PF_EC=$?
set -e
if [[ "$PF_EC" -eq 20 ]] && echo "$PF_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('cause')=='parent-below-builder'"; then
  ok "dispatch-preflight-parent-floor"
else
  bad "dispatch-preflight-parent-floor"
fi

# --- dispatch-binding-single-source ---
DOC_ID=$(bash "$RESOLVE" --agent sw-coherence-reviewer --config "$CONFIG" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['modelId'])")
NAT_ID=$(bash "$RESOLVE" --agent correctness --config "$CONFIG" 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['modelId'])")
if [[ -n "$DOC_ID" && -n "$NAT_ID" ]]; then
  ok "dispatch-binding-single-source"
else
  bad "dispatch-binding-single-source"
fi

# --- routing-agents-schema ---
if python3 - <<'PY' "$SCHEMA" "$DEFAULTS"
import json, sys
schema = json.load(open(sys.argv[1]))
defaults = json.load(open(sys.argv[2]))
agents_schema = (
    schema.get("properties", {})
    .get("models", {})
    .get("properties", {})
    .get("routing", {})
    .get("properties", {})
    .get("agents")
)
assert agents_schema is not None
assert defaults.get("routing", {}).get("agents")
PY
then
  ok "routing-agents-schema"
else
  bad "routing-agents-schema"
fi

# --- model-tier-check-agents-map ---
BAD_CFG="$TMPDIR_FIX/bad-agents.json"
python3 - <<'PY' "$CONFIG" "$BAD_CFG"
import json, sys
cfg = json.load(open(sys.argv[1]))
cfg = dict(cfg)
models = dict(cfg.get("models", {}))
routing = dict(models.get("routing", {}))
agents = dict(routing.get("agents", {}))
agents["sw-coherence-reviewer"] = "not-a-real-tier"
routing["agents"] = agents
models["routing"] = routing
cfg["models"] = models
json.dump(cfg, open(sys.argv[2], "w"))
PY
set +e
MC_OUT=$(bash "$MODEL_CHECK" --config "$BAD_CFG" 2>/dev/null)
MC_EC=$?
set -e
if [[ "$MC_EC" -eq 20 ]]; then
  ok "model-tier-check-agents-map-rejects-invalid"
else
  bad "model-tier-check-agents-map-rejects-invalid (ec=$MC_EC)"
fi
set +e
MC_OK=$(bash "$MODEL_CHECK" --config "$CONFIG" 2>/dev/null)
MC_OK_EC=$?
set -e
if [[ "$MC_OK_EC" -eq 0 ]] && echo "$MC_OK" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('agentsMapped',0)>0"; then
  ok "model-tier-check-agents-map-valid"
else
  bad "model-tier-check-agents-map-valid"
fi

# --- reviewer-frontmatter-inherit ---
INHERIT_FAIL=0
for f in "$AGENTS_DIR"/sw-*-reviewer.md; do
  [[ -f "$f" ]] || continue
  if ! grep -q '^model: inherit' "$f"; then
    INHERIT_FAIL=1
    break
  fi
done
if [[ "$INHERIT_FAIL" -eq 0 ]]; then
  ok "reviewer-frontmatter-inherit"
else
  bad "reviewer-frontmatter-inherit"
fi

# --- task-dispatch-hook (Option C — registered in both platform hooks.json files) ---
if bash "$ROOT/scripts/test/fixtures/task-dispatch-hook-feasibility.sh" >/dev/null 2>&1; then
  ok "task-dispatch-hook-registered"
else
  bad "task-dispatch-hook-registered"
fi

# --- model-binding-docs-presence ---
if grep -q 'models.routing.agents' "$DISPATCH" && \
   grep -q 'reviewer-dispatch-check.sh' "$DISPATCH" && \
   grep -q 'resolve-model-tier.sh --agent' "$DOC_REVIEW" && \
   grep -q 'models.routing.agents' "$TIERING"; then
  ok "model-binding-docs-presence"
else
  bad "model-binding-docs-presence"
fi

# --- model-binding-emitter-freshness ---
if bash "$ROOT/scripts/test/run-emitter-fixtures.sh" >/dev/null 2>&1; then
  ok "model-binding-emitter-freshness"
else
  bad "model-binding-emitter-freshness"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "run-model-binding-fixtures: FAIL"
  exit 1
fi
echo "run-model-binding-fixtures: PASS"
