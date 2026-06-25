#!/usr/bin/env bash
# Resolve semantic model tier → concrete dispatch ID from workflow config + bundled defaults.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULTS="$ROOT/core/sw-reference/model-routing.defaults.json"

usage() {
  cat <<'EOF'
Usage: resolve-model-tier.sh [--tier NAME | --command SLUG | --skill NAME] [--delegate CHILD]
       [--config PATH]

Output: JSON { "tier", "modelId", "source" }

  --tier NAME       — direct tier lookup (cheap|build|mid|deep)
  --command SLUG    — sw-* command slug (e.g. sw-prd)
  --skill NAME      — skill directory name (e.g. prd)
  --delegate CHILD  — when command routing is inherit, resolve via child command
  --config PATH     — workflow.config.json (default: .cursor/workflow.config.json)
EOF
}

tier="" command="" skill="" delegate="" config=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tier) tier="$2"; shift 2 ;;
    --command) command="$2"; shift 2 ;;
    --skill) skill="$2"; shift 2 ;;
    --delegate) delegate="$2"; shift 2 ;;
    --config) config="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo '{"verdict":"fail","error":"unknown flag"}' >&2; exit 2 ;;
    *) echo '{"verdict":"fail","error":"unexpected argument"}' >&2; exit 2 ;;
  esac
done

if [[ -z "$tier" && -z "$command" && -z "$skill" ]]; then
  usage >&2
  exit 2
fi

if [[ -z "$config" ]]; then
  for candidate in "$ROOT/.cursor/workflow.config.json" "$ROOT/workflow.config.json"; do
    if [[ -f "$candidate" ]]; then
      config="$candidate"
      break
    fi
  done
fi

exec python3 - "$tier" "$command" "$skill" "$delegate" "$config" "$DEFAULTS" <<'PY'
import json
import sys
from pathlib import Path

tier_arg, command, skill, delegate, config_path, defaults_path = sys.argv[1:7]
SEMANTIC = {"cheap", "build", "mid", "deep", "inherit"}


def load_json(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def fail(msg: str, code: int = 20) -> None:
    print(json.dumps({"verdict": "fail", "error": msg}))
    sys.exit(code)


defaults_doc = load_json(defaults_path)
base_cmd = defaults_doc.get("routing", {}).get("commands", {})
base_skill = defaults_doc.get("routing", {}).get("skills", {})

cfg = load_json(config_path) if config_path else {}
models = cfg.get("models", {}) if isinstance(cfg, dict) else {}
tiers = models.get("tiers", {}) if isinstance(models, dict) else {}
routing = models.get("routing", {}) if isinstance(models, dict) else {}
cmd_routing = {**base_cmd, **(routing.get("commands", {}) if isinstance(routing.get("commands"), dict) else {})}
skill_routing = {**base_skill, **(routing.get("skills", {}) if isinstance(routing.get("skills"), dict) else {})}


def resolve_tier_name(name: str, source: str) -> None:
    if name not in SEMANTIC:
        fail(f"unknown tier {name!r}")
    if name == "inherit":
        print(json.dumps({"tier": "inherit", "modelId": None, "source": source}))
        sys.exit(0)
    if name not in tiers:
        fail(f"tier {name!r} not in models.tiers")
    print(json.dumps({"tier": name, "modelId": tiers[name], "source": source}))
    sys.exit(0)


if tier_arg:
    resolve_tier_name(tier_arg, "tier")

if command:
    if command not in cmd_routing:
        fail(f"missing routing.commands entry for {command!r}")
    raw = cmd_routing[command]
    source = "routing.commands"
    if raw == "inherit":
        if delegate:
            if delegate not in cmd_routing:
                fail(f"missing routing.commands entry for delegate {delegate!r}")
            child_raw = cmd_routing[delegate]
            source = f"inherit:{delegate}"
            if child_raw == "inherit":
                fail(f"delegate {delegate!r} also inherits — cannot resolve")
            resolve_tier_name(child_raw, source)
        resolve_tier_name("inherit", source)
    resolve_tier_name(raw, source)

if skill:
    if skill not in skill_routing:
        fail(f"missing routing.skills entry for {skill!r}")
    raw = skill_routing[skill]
    resolve_tier_name(raw, "routing.skills")

fail("no lookup performed")
PY
