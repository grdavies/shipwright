#!/usr/bin/env bash
# Single per-repo configurator for /sw-init (PRD 018 R29/R30/R32).
#
# Usage:
#   sw-configure.py detect [--propose]
#   sw-configure.py schema-version
#   sw-configure.py shipwright-version
#   sw-configure.py drift-check [--config PATH]
#   sw-configure.py portability-check [--config PATH]
#   sw-configure.py write-draft [--accept-defaults] [--write-verify] [--config PATH]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CMD="${1:-}"
shift || true

schema_path() {
  # shellcheck source=sw-resolve-plugin-root.py
  local script_dir plugin_root
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  # shellcheck disable=SC1091
  source "$script_dir/sw-resolve-plugin-root.py"
  plugin_root="$(sw_resolve_plugin_root "$script_dir")"
  for candidate in \
    "$ROOT/.sw/config.schema.json" \
    "$ROOT/core/sw-reference/config.schema.json" \
    "$plugin_root/core/sw-reference/config.schema.json" \
    "${CURSOR_PLUGIN_ROOT:-}/core/sw-reference/config.schema.json" \
    "${CURSOR_PLUGIN_ROOT:-}/.sw/config.schema.json"; do
    if [[ -f "$candidate" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  echo "$ROOT/.sw/config.schema.json"
}

shipwright_version() {
  for candidate in \
    "$ROOT/version.txt" \
    "${CURSOR_PLUGIN_ROOT:-}/version.txt"; do
    if [[ -f "$candidate" ]]; then
      tr -d '[:space:]' < "$candidate"
      return 0
    fi
  done
  echo "unknown"
}

schema_version() {
  local schema
  schema="$(schema_path)"
  python3 - "$schema" <<'PY'
import hashlib, json, sys
from pathlib import Path
p = Path(sys.argv[1])
if not p.is_file():
    print("unknown")
else:
    raw = p.read_bytes()
    print(hashlib.sha256(raw).hexdigest()[:12])
PY
}

case "$CMD" in
  detect)
    PROPOSE=""
    [[ "${1:-}" == "--propose" ]] && PROPOSE="--propose"
    bash "$ROOT/scripts/detect-project-type.py" --root "$ROOT" $PROPOSE
    ;;
  schema-version) schema_version ;;
  shipwright-version) shipwright_version ;;
  drift-check)
    CONFIG=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --config) CONFIG="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    [[ -z "$CONFIG" && -f "$ROOT/.cursor/workflow.config.json" ]] && CONFIG="$ROOT/.cursor/workflow.config.json"
    SW_VER="$(shipwright_version)"
    SCH_VER="$(schema_version)"
    python3 - "$CONFIG" "$SW_VER" "$SCH_VER" <<'PY'
import json, sys
from pathlib import Path
config_path, sw_ver, sch_ver = sys.argv[1:4]
stale = False
configured = {}
if config_path and Path(config_path).is_file():
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))
    configured = cfg.get("configuredWith") or {}
    if configured.get("shipwrightVersion") != sw_ver or configured.get("schemaVersion") != sch_ver:
        stale = True
else:
    stale = False
print(json.dumps({
    "stale": stale,
    "configuredWith": configured,
    "current": {"shipwrightVersion": sw_ver, "schemaVersion": sch_ver},
    "notice": "config may be stale; run /sw-init to refresh" if stale else None,
}, indent=2))
PY
    ;;
  portability-check)
    CONFIG=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --config) CONFIG="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    [[ -z "$CONFIG" && -f "$ROOT/.cursor/workflow.config.json" ]] && CONFIG="$ROOT/.cursor/workflow.config.json"
    bash "$ROOT/scripts/verify-unconfigured.py" --config "${CONFIG:-/nonexistent}" --json || true
    DETECT="$(bash "$ROOT/scripts/detect-project-type.py" --root "$ROOT" --propose 2>/dev/null || echo '{}')"
    DRIFT="$(bash "$0" drift-check --config "${CONFIG:-}")"
    GH_OK="unknown"
    if bash "$ROOT/scripts/host-doctor.py" --root "$ROOT" >/dev/null 2>&1; then
      gh="present"
    elif command -v gh >/dev/null 2>&1; then
      GH_OK="available"
    else
      GH_OK="missing"
    fi
    python3 - "$DETECT" "$DRIFT" "$GH_OK" <<'PY'
import json, sys
detect = json.loads(sys.argv[1] or "{}")
drift = json.loads(sys.argv[2] or "{}")
gh = sys.argv[3]
lines = []
if detect.get("verifyGaps"):
    lines.append(f"verify gaps: {', '.join(detect['verifyGaps'])}")
lines.append(f"gh: {gh}")
if drift.get("stale"):
    lines.append(drift.get("notice", "config stale"))
if gh == "missing":
    lines.append("warning: host token missing — set host.tokenEnv for CI-readiness gate")
print(json.dumps({"summary": lines, "gh": gh, "drift": drift}, indent=2))
PY
    ;;
  write-draft)
    ACCEPT=0
    WRITE_VERIFY=0
    CONFIG=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --accept-defaults) ACCEPT=1; shift ;;
        --write-verify) WRITE_VERIFY=1; shift ;;
        --config) CONFIG="$2"; shift 2 ;;
        *) shift ;;
      esac
    done
    OUT="/tmp/sw-init-draft.json"
    python3 - "$ROOT" "$OUT" "$ACCEPT" "$WRITE_VERIFY" "$(shipwright_version)" "$(schema_version)" <<'PY'
import json, subprocess, sys
from pathlib import Path

root, out_path, accept, write_verify, sw_ver, sch_ver = sys.argv[1:7]
accept = accept == "1"
write_verify = write_verify == "1"

detect = json.loads(subprocess.check_output(
    ["bash", str(Path(root)/"scripts/detect-project-type.py"), "--root", root, "--propose"],
    text=True,
))

draft = {
    "doc": {"afterTasks": "confirm"},
    "delegation": {"mode": "bind-only"},
    "orchestration": {"planPolicy": "canonical"},
    "deliver": {"autonomy": {"mode": "autonomous", "maxRunMinutes": 1440, "maxIterations": 500}},
    "compound": {"autonomy": "supervised"},
    "guardrails": {"enforceBeforeSubmit": True, "requireRuleClass": False},
    "review": {"provider": "none"},
    "memory": {"provider": "in-repo", "sourceOfTruth": "auto"},
    "planning": {
        "store": {"backend": "in-repo-public"},
    },
    "configuredWith": {"shipwrightVersion": sw_ver, "schemaVersion": sch_ver},
}

comm_defaults_path = Path(root) / "core/sw-reference/communication-routing.defaults.json"
if comm_defaults_path.is_file():
    try:
        comm_defaults = json.loads(comm_defaults_path.read_text(encoding="utf-8"))
        if isinstance(comm_defaults, dict):
            draft["communication"] = comm_defaults
    except json.JSONDecodeError:
        pass

if accept:
    draft["verifyGaps"] = detect.get("verifyGaps") or []
    draft["projectTypeDetection"] = {"matches": detect.get("matches", []), "ambiguous": detect.get("ambiguous", False)}
elif write_verify:
    verify = {}
    for key, meta in (detect.get("proposals") or {}).items():
        if meta.get("safe") and meta.get("command"):
            verify[key] = meta["command"]
    if verify:
        draft["verify"] = verify

Path(out_path).write_text(json.dumps(draft, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"verdict": "pass", "path": out_path, "verifyWritten": bool(draft.get("verify"))}, indent=2))
PY
    ;;
  *)
    echo '{"verdict":"fail","error":"usage: sw-configure.py detect|schema-version|shipwright-version|drift-check|portability-check|write-draft"}' >&2
    exit 2
    ;;
esac
