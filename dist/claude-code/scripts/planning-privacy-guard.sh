#!/usr/bin/env bash
# Interim privacy guard — fails closed if formerly-gitignored bodies would become tracked (PRD 031 R18).
# Usage: planning-privacy-guard.py [--repo-root ROOT] [--staged] [--migration-staging] [--scan-private]
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$PLUGIN_ROOT"
MODE="staged"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root) ROOT="${2:-}"; shift 2 ;;
    --staged) MODE="staged"; shift ;;
    --migration-staging) MODE="migration-staging"; shift ;;
    --scan-private) MODE="scan-private"; shift ;;
    -h|--help)
      sed -n '2,4p' "$0"; exit 0 ;;
    *) echo '{"verdict":"fail","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done

exec python3 - "$PLUGIN_ROOT" "$ROOT" "$MODE" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

plugin_root, repo_root, mode = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]

STAGING_PREFIX = ".cursor/planning-migration-staging/"


def normalize_rel(rel: str) -> str:
    if rel.startswith(STAGING_PREFIX):
        return rel[len(STAGING_PREFIX) :]
    return rel


def is_private_source(rel: str) -> bool:
    norm = rel.replace("\\", "/")
    if norm.startswith("docs/brainstorms/"):
        return True
    if norm.startswith("docs/decisions/") and not norm.endswith("INDEX.md") and not norm.endswith(
        "SUPERSEDED.log"
    ):
        return True
    if norm.startswith("docs/planning/brainstorm/"):
        return True
    if norm.startswith("docs/planning/decision/") and not norm.endswith("INDEX.md"):
        return True
    return False


def collect_paths(root: Path, mode: str) -> list[str]:
    if mode == "scan-private":
        out: list[str] = []
        for prefix in ("docs/planning/brainstorm/", "docs/planning/decision/"):
            base = root / prefix
            if not base.is_dir():
                continue
            for path in base.rglob("*.md"):
                if path.name == "INDEX.md":
                    continue
                out.append(str(path.relative_to(root)).replace("\\", "/"))
        return out
    if mode == "migration-staging":
        staging = root / ".cursor/planning-migration-staging"
        if not staging.is_dir():
            return []
        return [str(p.relative_to(root)).replace("\\", "/") for p in staging.rglob("*") if p.is_file()]
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only", "--diff-filter=A"],
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


violations = []
for rel in collect_paths(repo_root, mode):
    rel = normalize_rel(rel)
    if not is_private_source(rel):
        continue
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "check-ignore", "-q", rel],
        capture_output=True,
    )
    if proc.returncode != 0:
        violations.append(rel)

if violations:
    print(
        json.dumps(
            {
                "verdict": "fail",
                "error": "formerly-private body would become tracked",
                "paths": violations,
            }
        )
    )
    sys.exit(20)
print(
    json.dumps(
        {
            "verdict": "pass",
            "action": "planning-privacy-guard",
            "checked": len(collect_paths(repo_root, mode)),
        }
    )
)
PY
