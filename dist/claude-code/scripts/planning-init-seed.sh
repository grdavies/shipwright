#!/usr/bin/env bash
# Seed planning visibility profile, store backend, and privacy notice (PRD 034 R21).
#
# Usage: planning-init-seed.py [--root PATH] [--config PATH]
# Requires an existing workflow.config.json (run after /sw-init write-draft).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,5p' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

[[ -z "$CONFIG" ]] && CONFIG="$ROOT/.cursor/workflow.config.json"
if [[ ! -f "$CONFIG" ]]; then
  echo '{"verdict":"fail","error":"missing-workflow-config","remediation":"run /sw-init write step first"}' >&2
  exit 2
fi

export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"

python3 - "$ROOT" "$CONFIG" <<'PY'
import json
import shutil
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
config_path = Path(sys.argv[2])
cfg = json.loads(config_path.read_text(encoding="utf-8"))
if not isinstance(cfg, dict):
    raise SystemExit(json.dumps({"verdict": "fail", "error": "invalid-workflow-config"}))

planning = cfg.get("planning")
if not isinstance(planning, dict):
    planning = {}
store = planning.get("store")
if not isinstance(store, dict):
    store = {}
if not store.get("backend"):
    store["backend"] = "in-repo-public"
planning["store"] = store
cfg["planning"] = planning
config_path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
PY

PROFILE_OUT="$(python3 "$ROOT/scripts/planning_visibility.py" --root "$ROOT" resolve-default-profile --write)"
PROFILE_EC=$?
if [[ $PROFILE_EC -ne 0 ]]; then
  echo "$PROFILE_OUT" >&2
  exit "$PROFILE_EC"
fi

NOTICE_SRC="$ROOT/core/sw-reference/planning-privacy-notice.md"
NOTICE_DST="$ROOT/.cursor/hooks/state/planning-privacy-notice.md"
mkdir -p "$(dirname "$NOTICE_DST")"
if [[ -f "$NOTICE_SRC" ]]; then
  cp "$NOTICE_SRC" "$NOTICE_DST"
else
  cat >"$NOTICE_DST" <<'EOF'
# Planning privacy notice

Public origin remotes default to all-private. Acknowledge before the first tracked spec commit.
EOF
fi

python3 - "$PROFILE_OUT" <<'PY'
import json, sys
profile = json.loads(sys.argv[1])
print(json.dumps({
    "verdict": "ok",
    "action": "planning-init-seed",
    "visibilityProfile": profile.get("visibilityProfile"),
    "privacyAck": profile.get("privacyAck"),
    "storeBackend": "in-repo-public",
    "privacyNotice": ".cursor/hooks/state/planning-privacy-notice.md",
}, indent=2))
PY
