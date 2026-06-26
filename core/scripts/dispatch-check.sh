#!/usr/bin/env bash
# Fail-closed dispatch binding preflight for delegated Task spawns.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_RESOLVER="$ROOT/scripts/resolve-model-tier.sh"
INTENSITY_RESOLVER="$ROOT/scripts/resolve-intensity.sh"
STATE_TOOL="$ROOT/scripts/shipwright-state.sh"

AGENT=""
COMMAND=""
SKILL=""
PARENT_MODEL=""
CONFIG=""
OVERRIDE=0
DISPATCH_ID=""
SIMULATE_CAPACITY=0

usage() {
  cat <<'EOF'
Usage:
  dispatch-check.sh --agent <id> [--command <sw-*>] [--skill <name>] --parent-model <concrete-model-id>
                    [--dispatch-id <id>] [--override] [--config <path>] [--simulate-capacity]

Exit 0: pass
Exit 20: fail-closed with cause enum:
  - binding:no-model
  - binding:no-intensity
  - harness:capacity
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) AGENT="${2:-}"; shift 2 ;;
    --command) COMMAND="${2:-}"; shift 2 ;;
    --skill) SKILL="${2:-}"; shift 2 ;;
    --parent-model) PARENT_MODEL="${2:-}"; shift 2 ;;
    --dispatch-id) DISPATCH_ID="${2:-}"; shift 2 ;;
    --override) OVERRIDE=1; shift ;;
    --config) CONFIG="${2:-}"; shift 2 ;;
    --simulate-capacity) SIMULATE_CAPACITY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo '{"verdict":"fail","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done

if [[ -z "$AGENT" || -z "$PARENT_MODEL" ]]; then
  echo '{"verdict":"fail","error":"--agent and --parent-model required"}' >&2
  exit 2
fi

if [[ "$SIMULATE_CAPACITY" -eq 1 ]]; then
  python3 - <<'PY' "$AGENT"
import json, sys
print(json.dumps({
    "verdict": "fail",
    "cause": "harness:capacity",
    "agent": sys.argv[1],
    "retryable": True,
    "remediation": "retry with bounded parallelism respecting worktree.parallelCeiling and harness limits",
}))
PY
  exit 20
fi

MODEL_ARGS=(--agent "$AGENT")
INTENSITY_ARGS=(--agent "$AGENT")
[[ -n "$COMMAND" ]] && INTENSITY_ARGS+=(--command "$COMMAND")
[[ -n "$SKILL" ]] && INTENSITY_ARGS+=(--skill "$SKILL")
if [[ -n "$CONFIG" ]]; then
  MODEL_ARGS+=(--config "$CONFIG")
  INTENSITY_ARGS+=(--config "$CONFIG")
fi

MODEL_OUT="$(bash "$MODEL_RESOLVER" "${MODEL_ARGS[@]}" 2>/dev/null || true)"
INTENSITY_OUT="$(bash "$INTENSITY_RESOLVER" "${INTENSITY_ARGS[@]}" 2>/dev/null || true)"

MODEL_ID="$(python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print(d.get('modelId') or '')" "$MODEL_OUT" 2>/dev/null || true)"
MODEL_TIER="$(python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print(d.get('tier') or '')" "$MODEL_OUT" 2>/dev/null || true)"
INTENSITY="$(python3 -c "import json,sys; d=json.loads(sys.argv[1] or '{}'); print(d.get('intensity') or '')" "$INTENSITY_OUT" 2>/dev/null || true)"

if [[ -z "$MODEL_ID" || "$MODEL_TIER" == "inherit" ]]; then
  python3 - <<'PY' "$AGENT" "$COMMAND" "$SKILL"
import json, sys
print(json.dumps({
    "verdict": "fail",
    "cause": "binding:no-model",
    "agent": sys.argv[1],
    "command": sys.argv[2] or None,
    "skill": sys.argv[3] or None,
    "retryable": False,
    "remediation": f"resolve and stamp a concrete model before Task dispatch: bash scripts/resolve-model-tier.sh --agent {sys.argv[1]}",
}))
PY
  exit 20
fi

if [[ "$INTENSITY" != "normal" && "$INTENSITY" != "lite" && "$INTENSITY" != "full" && "$INTENSITY" != "ultra" ]]; then
  python3 - <<'PY' "$AGENT" "$COMMAND" "$SKILL"
import json, sys
print(json.dumps({
    "verdict": "fail",
    "cause": "binding:no-intensity",
    "agent": sys.argv[1],
    "command": sys.argv[2] or None,
    "skill": sys.argv[3] or None,
    "retryable": False,
    "remediation": "set communication.routing (command/skill/agent) or communication.defaultIntensity to normal|lite|full|ultra",
}))
PY
  exit 20
fi

if [[ "$OVERRIDE" -eq 1 ]]; then
  if [[ -z "$DISPATCH_ID" ]]; then
    echo '{"verdict":"fail","cause":"binding:no-override-audit","retryable":false,"remediation":"--override requires --dispatch-id and a prior shipwright-state dispatch-override-add record"}'
    exit 20
  fi
  STATE_JSON="$("$STATE_TOOL" read 2>/dev/null || echo '{}')"
  if ! python3 - <<'PY' "$STATE_JSON" "$DISPATCH_ID"
import json, sys
state = json.loads(sys.argv[1] or "{}")
dispatch_id = sys.argv[2]
records = state.get("dispatchOverrides")
if not isinstance(records, list):
    raise SystemExit(1)
for rec in records:
    if not isinstance(rec, dict):
        continue
    if rec.get("dispatchId") != dispatch_id:
        continue
    if rec.get("actor") and rec.get("timestamp") and isinstance(rec.get("skippedFields"), list) and rec.get("skippedFields"):
        raise SystemExit(0)
raise SystemExit(1)
PY
  then
    echo '{"verdict":"fail","cause":"binding:no-override-audit","retryable":false,"remediation":"record durable override first: bash scripts/shipwright-state.sh dispatch-override-add ..."}'
    exit 20
  fi
fi

exec python3 - "$ROOT" "$AGENT" "$PARENT_MODEL" "$MODEL_ID" "$MODEL_TIER" "$OVERRIDE" "$DISPATCH_ID" "$COMMAND" "$SKILL" ${CONFIG:+--config "$CONFIG"} <<'PY'
import json
import sys
from pathlib import Path

root, agent, parent_model, model_id, tier, override_s, dispatch_id, command_name, skill_name, *tail = sys.argv[1:]
override = override_s == "1"
config = ""
for i, arg in enumerate(tail):
    if arg == "--config" and i + 1 < len(tail):
        config = tail[i + 1]
        break

config_path = Path(config) if config else Path(root) / ".cursor" / "workflow.config.json"
if not config_path.is_file():
    config_path = Path(root) / "workflow.config.json"
models = {}
if config_path.is_file():
    models = json.loads(config_path.read_text(encoding="utf-8")).get("models", {})

tiers = models.get("tiers", {}) if isinstance(models, dict) else {}
roles = models.get("roles", {}) if isinstance(models, dict) else {}
builder_tier = roles.get("builder", "build")
order = ["cheap", "build", "mid", "deep"]

def tier_rank(name: str):
    if name not in order:
        return None
    return order.index(name)

def model_to_tier(concrete: str):
    for tier_name, model in tiers.items():
        if model == concrete:
            return tier_name
    return None

parent_tier = model_to_tier(parent_model)
builder_rank = tier_rank(builder_tier)
parent_rank = tier_rank(parent_tier) if parent_tier else None

if parent_rank is None or builder_rank is None:
    print(json.dumps({
        "verdict": "fail",
        "cause": "binding:no-model",
        "agent": agent,
        "parentModel": parent_model,
        "retryable": False,
        "remediation": "resolve parent session to a concrete models.tiers id before dispatch",
    }))
    sys.exit(20)

reviewer_bound = agent.startswith("sw-") and agent.endswith("-reviewer")
native_panel_bound = agent in {
    "correctness", "security", "adversarial", "data-migration", "maintainability",
    "scope-fidelity", "testing", "performance", "api-contract", "reliability",
    "ui-ux", "type-design", "comment-accuracy", "ai-native",
}

if (reviewer_bound or native_panel_bound) and parent_rank < builder_rank and not override:
    print(json.dumps({
        "verdict": "fail",
        "cause": "binding:no-model",
        "agent": agent,
        "parentModel": parent_model,
        "parentTier": parent_tier,
        "builderTier": builder_tier,
        "retryable": False,
        "remediation": "raise parent session to builder tier or use --override with a recorded durable audit entry",
    }))
    sys.exit(20)

print(json.dumps({
    "verdict": "pass",
    "agent": agent,
    "command": command_name or None,
    "skill": skill_name or None,
    "tier": tier,
    "modelId": model_id,
    "parentModel": parent_model,
    "parentTier": parent_tier,
    "builderTier": builder_tier,
    "dispatchId": dispatch_id or None,
    "override": override,
}))
PY
