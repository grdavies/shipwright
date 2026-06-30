#!/usr/bin/env bash
# Validate model tier policy (R9): config roles + reviewer agent dispatch.
# Usage: model-tier-check.py [--config PATH] [--agents-dir PATH]
# Exit: 0 pass or not configured, non-zero on violation
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${ROOT}/.cursor/workflow.config.json"
AGENTS_DIR="${ROOT}/agents"
if [[ ! -d "$AGENTS_DIR" ]] && [[ -d "${ROOT}/core/agents" ]]; then
  AGENTS_DIR="${ROOT}/core/agents"
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="${2:-}"; shift 2 ;;
    --agents-dir) AGENTS_DIR="${2:-}"; shift 2 ;;
    -h|--help)
      echo "usage: model-tier-check.py [--config PATH] [--agents-dir PATH]"
      exit 0
      ;;
    *) echo '{"verdict":"fail","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done

exec python3 - "$ROOT" "$CONFIG" "$AGENTS_DIR" <<'PY'
import json, re, sys
from pathlib import Path

root, config_path, agents_dir = sys.argv[1:4]
config_file = Path(config_path)
agents_path = Path(agents_dir)

INHERIT = "inherit"
CANONICAL_TIER_ORDER = ("cheap", "build", "mid", "deep")


def ordered_tiers(tiers):
    out = [t for t in CANONICAL_TIER_ORDER if t in tiers]
    for name in sorted(tiers):
        if name not in out:
            out.append(name)
    return out


def tier_rank(name, tiers):
    ordered = ordered_tiers(tiers)
    if name not in ordered:
        return None
    return ordered.index(name)


if not config_file.is_file():
    print(json.dumps({"verdict": "pass", "status": "tiering not configured"}))
    sys.exit(0)

config = json.loads(config_file.read_text())
models = config.get("models")
if not models:
    print(json.dumps({"verdict": "pass", "status": "tiering not configured"}))
    sys.exit(0)

tiers = models.get("tiers", {})
aliases = models.get("aliases", {})
roles = models.get("roles", {})
builder_tier = roles.get("builder", "build")
reviewer_role_tier = roles.get("reviewer", builder_tier)
violations = []

for role, tier_name in roles.items():
    if tier_name not in tiers:
        violations.append({
            "kind": "config",
            "error": f"roles.{role} references undefined tier {tier_name!r}",
        })

builder_rank = tier_rank(builder_tier, tiers)
reviewer_rank = tier_rank(reviewer_role_tier, tiers)
if builder_rank is None:
    violations.append({
        "kind": "config",
        "error": f"roles.builder references undefined tier {builder_tier!r}",
    })
if reviewer_rank is None:
    violations.append({
        "kind": "config",
        "error": f"roles.reviewer references undefined tier {reviewer_role_tier!r}",
    })
if not violations and reviewer_rank < builder_rank:
    violations.append({
        "kind": "config",
        "error": f"roles.reviewer tier {reviewer_role_tier!r} below roles.builder tier {builder_tier!r}",
    })

routing = models.get("routing", {}) if isinstance(models.get("routing"), dict) else {}
agents_map = routing.get("agents", {}) if isinstance(routing.get("agents"), dict) else {}

for agent_id, tier_name in sorted(agents_map.items()):
    resolved = tier_name
    if tier_name in aliases:
        resolved = aliases[tier_name]
    if resolved not in tiers:
        violations.append({
            "kind": "config",
            "agent": agent_id,
            "tier": tier_name,
            "error": f"models.routing.agents[{agent_id!r}] references unknown tier {tier_name!r}",
        })


def resolve_dispatch_to_tier(dispatch_value: str):
    if dispatch_value in tiers:
        return dispatch_value
    if dispatch_value in aliases:
        return aliases[dispatch_value]
    if dispatch_value in tiers.values():
        for name, mid in tiers.items():
            if mid == dispatch_value:
                return name
    return None


inherit_count = 0
for agent in sorted(agents_path.glob("sw-*-reviewer.md")):
    text = agent.read_text()
    m = re.search(r"^model:\s*(\S+)", text, re.M)
    if not m:
        violations.append({"agent": agent.name, "error": "missing model frontmatter"})
        continue
    dispatch = m.group(1)
    if dispatch == INHERIT:
        inherit_count += 1
        continue
    if dispatch in tiers:
        violations.append({
            "agent": agent.name,
            "model": dispatch,
            "error": "semantic tier name in model frontmatter — use inherit or a concrete platform model ID",
        })
        continue
    tier_name = resolve_dispatch_to_tier(dispatch)
    if tier_name is None:
        violations.append({"agent": agent.name, "model": dispatch, "error": "unmapped model"})
        continue
    agent_rank = tier_rank(tier_name, tiers)
    if agent_rank is None or builder_rank is None:
        violations.append({
            "agent": agent.name,
            "model": dispatch,
            "error": f"unmapped tier {tier_name!r}",
        })
        continue
    if agent_rank < builder_rank:
        violations.append({
            "agent": agent.name,
            "model": dispatch,
            "tier": tier_name,
            "error": f"reviewer tier {tier_name} below builder tier {builder_tier}",
        })

if violations:
    print(json.dumps({"verdict": "fail", "violations": violations}, ensure_ascii=False))
    sys.exit(20)

out = {
    "verdict": "pass",
    "builderTier": builder_tier,
    "reviewerRoleTier": reviewer_role_tier,
    "inheritReviewers": inherit_count,
    "agentsMapped": len(agents_map),
    "runtimeR9": "orchestrator must dispatch reviewers only when parent model tier >= builder tier"
    if inherit_count else None,
}
print(json.dumps({k: v for k, v in out.items() if v is not None}, ensure_ascii=False))
PY
