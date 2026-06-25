#!/usr/bin/env bash
# Resolve communication intensity for an sw-* command from workflow config + bundled defaults.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULTS="$ROOT/core/sw-reference/communication-routing.defaults.json"

usage() {
  cat <<'EOF'
Usage: communication-resolve.sh <command> [--config <path>] [--child <atomic-command>]

Output: JSON { "command", "intensity", "source" }

  command       — sw-* command name (e.g. sw-prd)
  --config      — workflow.config.json path (default: .cursor/workflow.config.json)
  --child       — when command uses inherit, resolve via child atomic command
EOF
}

cmd="" config="" child=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) config="$2"; shift 2 ;;
    --child) child="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "unknown flag: $1" >&2; exit 1 ;;
    *)
      if [[ -z "$cmd" ]]; then cmd="$1"; else echo "unexpected arg: $1" >&2; exit 1; fi
      shift
      ;;
  esac
done

[[ -n "$cmd" ]] || { usage >&2; exit 1; }

if [[ -z "$config" ]]; then
  for candidate in "$ROOT/.cursor/workflow.config.json" "$ROOT/workflow.config.json"; do
    if [[ -f "$candidate" ]]; then
      config="$candidate"
      break
    fi
  done
fi

python3 - "$cmd" "$config" "$DEFAULTS" "$child" <<'PY'
import json
import sys
from pathlib import Path

command, config_path, defaults_path, child = sys.argv[1:5]
INTENSITIES = {"normal", "lite", "full", "ultra", "inherit"}

def load_json(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))

defaults_doc = load_json(defaults_path)
base_routing = defaults_doc.get("routing", {}).get("commands", {})
default_intensity = defaults_doc.get("defaultIntensity", "full")

cfg = load_json(config_path) if config_path else {}
comm = cfg.get("communication", {}) if isinstance(cfg, dict) else {}
routing = {**base_routing, **(comm.get("routing", {}).get("commands", {}) if isinstance(comm.get("routing"), dict) else {})}
default_intensity = comm.get("defaultIntensity", default_intensity)

raw = routing.get(command, default_intensity)
source = "routing"
if command not in routing:
    source = "defaultIntensity"

if raw == "inherit":
    if child:
        child_raw = routing.get(child, default_intensity)
        if child_raw == "inherit":
            child_raw = default_intensity
            source = "inherit-fallback"
        else:
            source = f"inherit:{child}"
        intensity = child_raw
    else:
        intensity = default_intensity
        source = "inherit-unresolved"
else:
    intensity = raw

if intensity not in {"normal", "lite", "full", "ultra"}:
  if intensity.startswith("wenyan"):
    print(json.dumps({"verdict": "fail", "error": "wenyan intensity rejected", "command": command}))
    sys.exit(20)
  intensity = default_intensity
  source = "invalid-fallback"

print(json.dumps({"command": command, "intensity": intensity, "source": source}))
PY
