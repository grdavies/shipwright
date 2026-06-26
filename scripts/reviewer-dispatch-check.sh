#!/usr/bin/env bash
# Fail-closed preflight before reviewer/persona/native-panel Task dispatch (PRD 012 R2–R4).
#
# Usage:
#   reviewer-dispatch-check.sh --agent <id> --parent-model <concrete-model-id> [--override] [--config PATH]
#
# Exit 0 + JSON pass when a concrete model resolves and parent tier >= roles.builder.
# Exit 20 + JSON fail with cause no-model-resolved | parent-below-builder.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESOLVER="$ROOT/scripts/resolve-model-tier.sh"
AGENT=""
PARENT_MODEL=""
OVERRIDE=0
CONFIG=""

usage() {
  sed -n '2,8p' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) AGENT="${2:-}"; shift 2 ;;
    --parent-model) PARENT_MODEL="${2:-}"; shift 2 ;;
    --override) OVERRIDE=1; shift ;;
    --config) CONFIG="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo '{"verdict":"fail","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done

if [[ -z "$AGENT" || -z "$PARENT_MODEL" ]]; then
  echo '{"verdict":"fail","error":"--agent and --parent-model required"}' >&2
  exit 2
fi

RESOLVE_ARGS=(--agent "$AGENT")
[[ -n "$CONFIG" ]] && RESOLVE_ARGS+=(--config "$CONFIG")

RESOLVED="$("$RESOLVER" "${RESOLVE_ARGS[@]}" 2>/dev/null || true)"
MODEL_ID="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('modelId') or '')" "$RESOLVED" 2>/dev/null || true)"
TIER="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get('tier') or '')" "$RESOLVED" 2>/dev/null || true)"

if [[ -z "$MODEL_ID" || "$TIER" == "inherit" ]]; then
  python3 - <<'PY' "$AGENT"
import json, sys
print(json.dumps({
    "verdict": "fail",
    "cause": "no-model-resolved",
    "agent": sys.argv[1],
    "remediation": f"bash scripts/resolve-model-tier.sh --agent {sys.argv[1]} && stamp concrete model: on Task",
}))
PY
  exit 20
fi

CONFIG_ARG=()
[[ -n "$CONFIG" ]] && CONFIG_ARG=(--config "$CONFIG")

exec python3 - "$ROOT" "$AGENT" "$PARENT_MODEL" "$MODEL_ID" "$TIER" "$OVERRIDE" ${CONFIG_ARG[@]+"${CONFIG_ARG[@]}"} <<'PY'
import json
import subprocess
import sys
from pathlib import Path

root, agent, parent_model, model_id, tier, override_s, *config_tail = sys.argv[1:]
override = override_s == "1"
config = ""
for i, arg in enumerate(config_tail):
    if arg == "--config" and i + 1 < len(config_tail):
        config = config_tail[i + 1]
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
    for name, mid in tiers.items():
        if mid == concrete:
            return name
    return None


parent_tier = model_to_tier(parent_model)
builder_rank = tier_rank(builder_tier)
parent_rank = tier_rank(parent_tier) if parent_tier else None

if parent_rank is None or builder_rank is None:
    print(json.dumps({
        "verdict": "fail",
        "cause": "no-model-resolved",
        "agent": agent,
        "parentModel": parent_model,
        "remediation": "resolve parent model to a known models.tiers concrete ID before dispatch",
    }))
    sys.exit(20)

if parent_rank < builder_rank and not override:
    print(json.dumps({
        "verdict": "fail",
        "cause": "parent-below-builder",
        "agent": agent,
        "parentModel": parent_model,
        "parentTier": parent_tier,
        "builderTier": builder_tier,
        "remediation": "raise parent session to builder tier or pass --override with explicit recorded consent",
    }))
    sys.exit(20)

print(json.dumps({
    "verdict": "pass",
    "agent": agent,
    "tier": tier,
    "modelId": model_id,
    "parentModel": parent_model,
    "parentTier": parent_tier,
    "builderTier": builder_tier,
    "override": override,
}))
PY
