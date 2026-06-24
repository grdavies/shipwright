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

exec python3 - "$ROOT" "$PRD_PATH" "$TASKS_PATH" <<'PY'
import json, re, subprocess, sys
from pathlib import Path

root, prd_path, tasks_path = sys.argv[1:4]
tasks_text = Path(tasks_path).read_text()

union = json.loads(
    subprocess.check_output(["bash", str(Path(root) / "scripts/spec-union.sh"), prd_path], text=True)
)
union_ids = [r["id"] for r in union.get("requirements", [])]

rows = []
in_table = False
for line in tasks_text.splitlines():
    if re.match(r"^##\s+Traceability\s*$", line, re.I):
        in_table = True
        continue
    if in_table and line.startswith("## "):
        break
    if not in_table:
        continue
    if not line.strip().startswith("|"):
        continue
    if re.match(r"^\|\s*R-ID\s*\|", line, re.I) or re.match(r"^\|[-:\s|]+\|$", line):
        continue
    parts = [p.strip() for p in line.strip().strip("|").split("|")]
    if len(parts) < 3:
        continue
    rid, task_ref, scenario = parts[0], parts[1], parts[2]
    if not re.match(r"^R\d+$", rid):
        continue
    rows.append({"rid": rid, "task": task_ref, "testScenario": scenario})

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
