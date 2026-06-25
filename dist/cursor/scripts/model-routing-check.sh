#!/usr/bin/env bash
# Validate model-routing.defaults.json coverage and tier references.
# Usage: model-routing-check.sh [--config PATH] [--defaults PATH]
# Exit: 0 pass; 20 fail
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${ROOT}/.sw/workflow.config.example.json"
DEFAULTS="${ROOT}/core/sw-reference/model-routing.defaults.json"
COMM_DEFAULTS="${ROOT}/core/sw-reference/communication-routing.defaults.json"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --defaults) DEFAULTS="$2"; shift 2 ;;
    -h|--help)
      echo "usage: model-routing-check.sh [--config PATH] [--defaults PATH]"
      exit 0
      ;;
    *) echo '{"verdict":"fail","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done

exec python3 - "$ROOT" "$CONFIG" "$DEFAULTS" "$COMM_DEFAULTS" <<'PY'
import json
import sys
from pathlib import Path

root, config_path, defaults_path, comm_defaults_path = sys.argv[1:5]
root_p = Path(root)
violations = []

defaults = json.loads(Path(defaults_path).read_text())
cmd_map = defaults.get("routing", {}).get("commands", {})
skill_map = defaults.get("routing", {}).get("skills", {})
valid_tiers = {"cheap", "build", "mid", "deep", "inherit"}

for key, tier in cmd_map.items():
    if tier not in valid_tiers:
        violations.append({"kind": "command", "key": key, "error": f"invalid tier {tier!r}"})
for key, tier in skill_map.items():
    if tier not in valid_tiers:
        violations.append({"kind": "skill", "key": key, "error": f"invalid tier {tier!r}"})

shipped_cmds = sorted(p.stem for p in (root_p / "core/commands").glob("sw-*.md"))
for cmd in shipped_cmds:
    if cmd not in cmd_map:
        violations.append({"kind": "command", "key": cmd, "error": "missing from defaults"})

shipped_skills = sorted(p.parent.name for p in (root_p / "core/skills").glob("*/SKILL.md"))
for sk in shipped_skills:
    if sk not in skill_map:
        violations.append({"kind": "skill", "key": sk, "error": "missing from defaults"})

comm_path = Path(comm_defaults_path)
if comm_path.is_file():
    comm = json.loads(comm_path.read_text())
    comm_cmds = set((comm.get("routing", {}).get("commands", {}) or {}).keys())
    model_cmds = set(cmd_map.keys())
    if comm_cmds != model_cmds:
        only_comm = sorted(comm_cmds - model_cmds)
        only_model = sorted(model_cmds - comm_cmds)
        if only_comm or only_model:
            violations.append({
                "kind": "parity",
                "error": "communication vs model routing key mismatch",
                "onlyCommunication": only_comm,
                "onlyModel": only_model,
            })

cfg_path = Path(config_path)
if cfg_path.is_file():
    cfg = json.loads(cfg_path.read_text())
    tiers = (cfg.get("models") or {}).get("tiers") or {}
    for key, tier in {**cmd_map, **skill_map}.items():
        if tier != "inherit" and tier not in tiers:
            violations.append({"kind": "config", "key": key, "error": f"tier {tier!r} absent from example models.tiers"})

if violations:
    print(json.dumps({"verdict": "fail", "violations": violations}, ensure_ascii=False))
    sys.exit(20)

print(json.dumps({
    "verdict": "pass",
    "commandCount": len(cmd_map),
    "skillCount": len(skill_map),
    "communicationParityChecked": comm_path.is_file(),
}))
PY
