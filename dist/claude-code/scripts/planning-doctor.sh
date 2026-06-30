#!/usr/bin/env bash
# Planning store + visibility doctor checks (PRD 034 R16, R21, R27).
#
# Usage: planning-doctor.py [--root PATH] [--no-sweep]
# Exit 0 always; JSON verdict on stdout. Never prints provider tokens (R27).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SWEEP=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    --no-sweep) SWEEP=0; shift ;;
    -h|--help) sed -n '2,5p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
export SWEEP

python3 - "$ROOT" <<'PY'
import json
import os
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
sweep = os.environ.get("SWEEP", "1") == "1"

TOKEN_PATTERNS = (
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
)


def sanitize(value):
    if isinstance(value, str):
        out = value
        for pat in TOKEN_PATTERNS:
            out = pat.sub("[REDACTED:TOKEN]", out)
        return out
    if isinstance(value, list):
        return [sanitize(v) for v in value]
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items()}
    return value


def run_json(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    raw = proc.stdout.strip() or proc.stderr.strip() or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"verdict": "fail", "error": "invalid-json", "raw": raw[:200]}


checks: list[dict] = []
warnings: list[str] = []
verdict = "ok"

backend_data = run_json([
    "python3", str(root / "scripts/planning_store.py"), "--root", str(root), "resolve-backend",
])
store_backend = backend_data.get("backend", "in-repo-public")
checks.append({"check": "store-backend", "status": "ok", "backend": store_backend})

# Store reachability (R21)
reach_cmd = [
    "python3", str(root / "scripts/planning_store.py"), "--root", str(root),
    "exists", "--unit-id", "__doctor-probe__", "--body-path", "__doctor-probe__.md",
]
reach = run_json(reach_cmd)
if store_backend == "in-repo-public":
    if reach.get("verdict") in {"ok", "missing"}:
        checks.append({"check": "store-reachability", "status": "ok", "backend": store_backend})
    else:
        checks.append({"check": "store-reachability", "status": "fail", "backend": store_backend})
        warnings.append("in-repo-public-unreachable")
        verdict = "fail"
elif store_backend == "local-synced":
    cfg_path = None
    for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
        if candidate.is_file():
            cfg_path = candidate
            break
    sync_path = ""
    if cfg_path:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        sync_path = (
            ((cfg.get("planning") or {}).get("store") or {}).get("localSynced") or {}
        ).get("path") or ""
    if not sync_path:
        checks.append({"check": "local-synced-path", "status": "fail", "reason": "missing-path"})
        warnings.append("local-synced-backend-without-path")
        verdict = "fail"
    else:
        data = run_json([
            "python3", str(root / "scripts/planning_store.py"), "--root", str(root),
            "validate-local-synced", "--path", sync_path,
        ])
        if data.get("verdict") == "ok":
            checks.append({"check": "local-synced-path", "status": "ok", "path": sync_path})
            checks.append({"check": "store-reachability", "status": "ok", "backend": store_backend})
            for w in data.get("warnings") or []:
                warnings.append(str(w))
                if verdict == "ok":
                    verdict = "degraded"
        else:
            checks.append({"check": "local-synced-path", "status": "fail", "path": sync_path})
            checks.append({"check": "store-reachability", "status": "fail", "backend": store_backend})
            warnings.append("local-synced-path-validation-failed")
            verdict = "fail"
elif store_backend == "memory":
    from memory_sot import resolve_memory_provider

    provider = resolve_memory_provider(root) or ""
    if not provider:
        checks.append({
            "check": "memory-provider",
            "status": "degraded",
            "reason": "no-provider",
            "remediation": "set memory.provider in workflow.config.json or add .cursor/sw-memory.provider",
        })
        checks.append({
            "check": "store-reachability",
            "status": "degraded",
            "backend": store_backend,
            "remediation": "configure memory.provider or switch planning.store.backend to in-repo-public",
        })
        warnings.append("memory-backend-degrade-open-no-provider")
        if verdict == "ok":
            verdict = "degraded"
    else:
        checks.append({"check": "memory-provider", "status": "ok", "provider": provider})
        checks.append({"check": "store-reachability", "status": "ok", "backend": store_backend, "provider": provider})

# Config surfaces env-var names only (R27) — never token values
cfg_path = root / ".cursor/workflow.config.json"
if cfg_path.is_file():
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    memory = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}
    host = cfg.get("host") if isinstance(cfg.get("host"), dict) else {}
    checks.append({
        "check": "credential-surface",
        "status": "ok",
        "memoryProvider": memory.get("provider"),
        "hostTokenEnv": host.get("tokenEnv"),
        "note": "env-var names only; no secrets in config",
    })

# Orphan materialized sweep (R21)
swept: list[str] = []
if sweep:
    materialized_roots: list[Path] = []

    repo_mat = root / ".cursor" / "planning-materialized"
    if repo_mat.is_dir():
        materialized_roots.append(repo_mat)

    worktrees = root / ".sw-worktrees"
    if worktrees.is_dir():
        for wt in worktrees.iterdir():
            mat = wt / ".cursor" / "planning-materialized"
            if mat.is_dir():
                materialized_roots.append(mat)

    cursor = root / ".cursor"
    if cursor.is_dir():
        for state_file in cursor.glob("sw-deliver-state*.json"):
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            pin = state.get("planningStorePin") or {}
            for rel in pin.get("materializedPaths") or []:
                rel_path = Path(str(rel))
                if rel_path.parts and rel_path.parts[0] == ".cursor":
                    candidate = root / rel_path.parts[0]
                    for part in rel_path.parts[1:]:
                        if part == "planning-materialized":
                            candidate = candidate / part
                            break
                        candidate = candidate / part
                    if candidate.name == "planning-materialized" and candidate.is_dir():
                        materialized_roots.append(candidate)

    unique_roots = sorted({str(p.resolve()) for p in materialized_roots})
    if unique_roots:
        sweep_out = run_json([
            "python3", str(root / "scripts/planning_materialize.py"), "--root", str(root),
            "sweep-orphans", "--paths-json", json.dumps(unique_roots),
        ])
        swept = sweep_out.get("swept") or []
        checks.append({
            "check": "orphan-materialized-sweep",
            "status": "ok",
            "candidates": len(unique_roots),
            "swept": len(swept),
        })
    else:
        checks.append({"check": "orphan-materialized-sweep", "status": "ok", "candidates": 0, "swept": 0})

out = sanitize({
    "verdict": verdict,
    "backend": store_backend,
    "warnings": warnings,
    "checks": checks,
    "swept": swept,
    "notes": "local/synced is convenience-not-security; not the public-repo template default (R16)",
})
print(json.dumps(out, indent=2))
PY
