#!/usr/bin/env bash
# Seed models.tiers + models.routing into a workflow config draft (PRD 008).
# Usage: seed-model-config.py [--platform cursor|claude-code] [--config PATH] [--repair routing|tiers|all]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLATFORM=""
CONFIG=""
REPAIR="all"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --platform) PLATFORM="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --repair) REPAIR="$2"; shift 2 ;;
    -h|--help)
      echo "usage: seed-model-config.py [--platform cursor|claude-code] [--config PATH] [--repair routing|tiers|all]"
      exit 0
      ;;
    *) echo '{"verdict":"fail","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done

if [[ -z "$PLATFORM" ]]; then
  PLATFORM="$(bash "$ROOT/scripts/detect-platform.py")"
fi

if [[ -z "$CONFIG" ]]; then
  for candidate in "$ROOT/.cursor/workflow.config.json" "$ROOT/workflow.config.json"; do
    if [[ -f "$candidate" ]]; then
      CONFIG="$candidate"
      break
    fi
  done
fi

DEFAULTS="$ROOT/core/sw-reference/model-routing.defaults.json"
exec python3 - "$ROOT" "$PLATFORM" "$CONFIG" "$DEFAULTS" "$REPAIR" <<'PY'
import json
import sys
from pathlib import Path

root, platform, config_path, defaults_path, repair = sys.argv[1:6]

CATALOGS = {
    "cursor": {
        "tiers": {
            "cheap": "composer-2.5-fast",
            "build": "composer-2.5",
            "mid": "gpt-5.5-medium",
            "deep": "claude-opus-4-8-thinking-high",
        },
        "aliases": {"fast": "cheap"},
        "roles": {"builder": "build", "reviewer": "build"},
    },
    "claude-code": {
        "tiers": {
            "cheap": "claude-4.5-haiku-thinking",
            "build": "claude-4.6-sonnet-medium-thinking",
            "mid": "claude-4.6-sonnet-medium-thinking",
            "deep": "claude-opus-4-8-thinking-high",
        },
        "aliases": {"fast": "cheap"},
        "roles": {"builder": "build", "reviewer": "build"},
    },
}

if platform not in CATALOGS:
    print(json.dumps({"verdict": "fail", "error": f"unknown platform {platform!r}"}))
    sys.exit(2)

defaults = json.loads(Path(defaults_path).read_text(encoding="utf-8"))
routing = defaults.get("routing", {})

cfg = {}
cfg_path = Path(config_path) if config_path else None
if cfg_path and cfg_path.is_file():
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))

models = cfg.setdefault("models", {}) if isinstance(cfg, dict) else {}
if repair in ("all", "tiers"):
    models.update(CATALOGS[platform])
if repair in ("all", "routing"):
    models["routing"] = routing

cfg["models"] = models

out = {
    "verdict": "pass",
    "platform": platform,
    "repair": repair,
    "models": models,
    "tierSummary": {k: models["tiers"][k] for k in ("cheap", "build", "mid", "deep")},
    "note": "Re-run on another platform overwrites models.tiers when --repair tiers|all",
}
print(json.dumps(out, indent=2))
PY
