#!/usr/bin/env bash
# R-ID → task → test traceability gate (pre-task-freeze).
# Usage: traceability-check.sh --prd PRD --tasks TASKS
# Exit: 0 complete, 20 gaps
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRD_PATH=""
TASKS_PATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --prd) PRD_PATH="${2:-}"; shift 2 ;;
    --tasks) TASKS_PATH="${2:-}"; shift 2 ;;
    -h|--help)
      echo "usage: traceability-check.sh --prd PRD --tasks TASKS"
      exit 0
      ;;
    *) echo '{"verdict":"gaps","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done

if [[ -z "$PRD_PATH" || -z "$TASKS_PATH" ]]; then
  echo '{"verdict":"gaps","error":"--prd and --tasks required"}' >&2
  exit 2
fi

if [[ ! -f "$PRD_PATH" || ! -f "$TASKS_PATH" ]]; then
  echo '{"verdict":"gaps","error":"prd or tasks file not found"}' >&2
  exit 2
fi

# Pre-freeze structural check (R13) on tasks before traceability parse.
for STRUCT_PATH in "$PRD_PATH" "$TASKS_PATH"; do
  if ! STRUCT_OUT=$(bash "$ROOT/scripts/doc-format-normalize.sh" --check "$STRUCT_PATH" 2>&1); then
    echo "$STRUCT_OUT"
    exit 20
  fi
done

exec python3 - "$ROOT" "$PRD_PATH" "$TASKS_PATH" <<'PY'
import json, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
import doc_format

root, prd_path, tasks_path = sys.argv[1:4]
tasks_text = Path(tasks_path).read_text()

union = json.loads(
    subprocess.check_output(["bash", str(Path(root) / "scripts/spec-union.sh"), prd_path], text=True)
)
union_ids = [r["id"] for r in union.get("requirements", [])]

rows = doc_format.extract_traceability_rows(tasks_text)

covered = {r["rid"]: r for r in rows if r["testScenario"] and r["testScenario"].lower() not in ("tbd", "todo", "n/a")}
uncovered = [rid for rid in union_ids if rid not in covered or not covered[rid]["testScenario"].strip()]
incomplete = [r["rid"] for r in rows if r["rid"] in union_ids and (not r["testScenario"] or r["testScenario"].lower() in ("tbd", "todo", "n/a"))]

verdict = "complete" if not uncovered and not incomplete else "gaps"
out = {
    "verdict": verdict,
    "unionRids": union_ids,
    "rows": rows,
    "uncovered": sorted(set(uncovered + incomplete)),
}
print(json.dumps(out, ensure_ascii=False))
sys.exit(0 if verdict == "complete" else 20)
PY
