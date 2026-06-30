#!/usr/bin/env bash
# Resolve review.local config with schema defaults (R14–R16, R61).
#
# Usage: review-local-resolve.py [--config PATH]
# Exit: 0 always; JSON stdout with fire/skip + resolved values
set -euo pipefail

CONFIG="${PWD}/.cursor/workflow.config.json"

usage() {
  echo "Usage: review-local-resolve.py [--config PATH]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

python3 - "$CONFIG" <<'PY'
import json, sys

config_path = sys.argv[1]
try:
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
except (OSError, json.JSONDecodeError):
    cfg = {}

review = cfg.get("review") or {}
local = review.get("local") or {}

enabled = local.get("enabled", True)
provider = local.get("provider", "native")
apply = local.get("apply", "auto")
ui_enrich = (local.get("ui") or {}).get("enrich", "off")

fire = bool(enabled) and provider != "none"
skip_reason = None
if not enabled:
    skip_reason = "review.local.enabled is false"
elif provider == "none":
    skip_reason = 'review.local.provider is "none"'

out = {
    "fire": fire,
    "skip": not fire,
    "skip_reason": skip_reason,
    "resolved": {
        "enabled": enabled,
        "provider": provider,
        "apply": apply,
        "ui": {"enrich": ui_enrich},
    },
    "review_provider": review.get("provider", "none"),
    "independent_of_review_provider": True,
}
print(json.dumps(out, separators=(",", ":")))
PY
