#!/usr/bin/env bash
# Planning store + visibility doctor checks (PRD 034 R16, R21, R27).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
BACKEND="$(python3 "$ROOT/scripts/planning_store.py" --root "$ROOT" resolve-backend)"
STORE_BACKEND="$(echo "$BACKEND" | python3 -c "import json,sys; print(json.load(sys.stdin).get('backend','in-repo-public'))")"
python3 - "$ROOT" "$STORE_BACKEND" <<'PY'
import json, os, sys
from pathlib import Path
root = Path(sys.argv[1])
store_backend = sys.argv[2]
checks = [{"check": "store-backend", "status": "ok", "backend": store_backend}]
warnings = []
verdict = "ok"
if store_backend == "local-synced":
    cfg_path = None
    for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
        if candidate.is_file():
            cfg_path = candidate
            break
    sync_path = ""
    if cfg_path:
        cfg = json.loads(cfg_path.read_text())
        sync_path = (((cfg.get("planning") or {}).get("store") or {}).get("localSynced") or {}).get("path") or ""
    if not sync_path:
        checks.append({"check": "local-synced-path", "status": "fail", "reason": "missing-path"})
        warnings.append("local-synced-backend-without-path")
        verdict = "fail"
    else:
        import subprocess
        proc = subprocess.run([
            "python3", str(root / "scripts/planning_store.py"), "--root", str(root),
            "validate-local-synced", "--path", sync_path,
        ], capture_output=True, text=True)
        data = json.loads(proc.stdout or "{}")
        if data.get("verdict") == "ok":
            checks.append({"check": "local-synced-path", "status": "ok", "path": sync_path})
            if data.get("warnings"):
                warnings.extend(data["warnings"])
                if verdict == "ok":
                    verdict = "degraded"
        else:
            checks.append({"check": "local-synced-path", "status": "fail", "path": sync_path})
            warnings.append("local-synced-path-validation-failed")
            verdict = "fail"
if store_backend == "memory":
    from memory_sot import resolve_memory_provider
    provider = resolve_memory_provider(root) or ""
    if not provider:
        checks.append({"check": "memory-provider", "status": "degraded", "reason": "no-provider"})
        warnings.append("memory-backend-degrade-open-no-provider")
        if verdict == "ok":
            verdict = "degraded"
    else:
        checks.append({"check": "memory-provider", "status": "ok", "provider": provider})
print(json.dumps({
    "verdict": verdict,
    "backend": store_backend,
    "warnings": warnings,
    "checks": checks,
    "notes": "local/synced is convenience-not-security; not the public-repo template default (R16)",
}, indent=2))
PY
