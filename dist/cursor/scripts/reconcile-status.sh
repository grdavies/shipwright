#!/usr/bin/env bash
# Derive PRD living status from git + INDEX + task checkboxes; reconcile INDEX; append completion log.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  reconcile-status.sh derive [--json]     Compute status per PRD from git facts
  reconcile-status.sh reconcile [--dry-run]  Update docs/prds/INDEX.md Status column
  reconcile-status.sh append-log <prd> <phase> <notes>  Append COMPLETION-LOG entry
EOF
}

read_config() {
  python3 - "$ROOT" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
    if candidate.is_file():
        print(candidate.read_text(encoding="utf-8"))
        break
else:
    print('{"prdsDir":"docs/prds","tasksDir":"docs/prds","defaultBaseBranch":"main"}')
PY
}

cmd_derive() {
  local as_json="${1:-}"
  local cfg
  cfg="$(read_config)"
  python3 - "$ROOT" "$cfg" <<'PY'
import json
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
cfg = json.loads(sys.argv[2])
prds_dir = root / cfg.get("prdsDir", "prds")
index_path = prds_dir / "INDEX.md"
tasks_dir = root / cfg.get("tasksDir", "prds")
base_branch = cfg.get("defaultBaseBranch", "main")

def parse_index():
    rows = []
    if not index_path.is_file():
        return rows
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or line.startswith("| #") or line.startswith("|---"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) < 4 or not re.match(r"^\d{3}$", parts[0]):
            continue
        index_status = parts[4] if len(parts) >= 5 else parts[3]
        rows.append(
            {
                "prd": parts[0],
                "slug": parts[1],
                "prdLink": parts[2],
                "tasksLink": parts[3] if len(parts) >= 5 else "",
                "indexStatus": index_status,
            }
        )
    return rows

def task_checkbox_state(task_file: Path):
    if not task_file.is_file():
        return {"total": 0, "done": 0, "ratio": 0.0}
    text = task_file.read_text(encoding="utf-8")
    checked = len(re.findall(r"^- \[x\]", text, re.MULTILINE | re.IGNORECASE))
    unchecked = len(re.findall(r"^- \[ \]", text, re.MULTILINE))
    total = checked + unchecked
    return {"total": total, "done": checked, "ratio": (checked / total) if total else 0.0}

def merged_prs_for_slug(slug: str):
    merged = []
    feature_complete = False
    slug_esc = re.escape(slug)
    slug_lower = slug.lower()
    branch_prefixes = ("pf", "docs", "feat", "fix", "chore", "perf", "refactor", "test")
    branch_pats = [
        re.compile(rf"^{prefix}/{slug_esc}([/-]|$)", re.IGNORECASE) for prefix in branch_prefixes
    ]
    integration_pat = re.compile(rf"^pf/{slug_esc}$", re.IGNORECASE)
    prd_pat = re.compile(rf"prd:\s*{re.escape(slug_lower)}\b", re.IGNORECASE)
    prd_path_pat = re.compile(rf"prd/{re.escape(slug_lower)}\b", re.IGNORECASE)
    prd_num_pat = re.compile(rf"\bPRD\s+{re.escape(slug_lower)}\b", re.IGNORECASE)
    title_pat = re.compile(rf"\b{slug_esc}\b", re.IGNORECASE)
    try:
        out = subprocess.check_output(
            ["gh", "pr", "list", "--state", "merged", "--json", "number,title,headRefName,body", "--limit", "100"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        prs = json.loads(out)
    except Exception:
        prs = []
    for pr in prs:
        head = pr.get("headRefName", "") or ""
        body = pr.get("body", "") or ""
        title = pr.get("title", "") or ""
        if integration_pat.match(head):
            feature_complete = True
        if any(pat.search(head) for pat in branch_pats) or (
            prd_pat.search(body)
            or prd_path_pat.search(body)
            or prd_num_pat.search(title)
            or prd_num_pat.search(body)
            or title_pat.search(title)
            or title_pat.search(head)
        ):
            merged.append(pr["number"])
    return merged, feature_complete

def status_for(row):
    slug = row["slug"]
    task_candidates = list(tasks_dir.rglob(f"*{slug}*tasks*.md")) + list(tasks_dir.rglob(f"tasks*{slug}*.md"))
    task_file = task_candidates[0] if task_candidates else None
    tasks = task_checkbox_state(task_file) if task_file else {"total": 0, "done": 0, "ratio": 0.0}
    merged, feature_complete = merged_prs_for_slug(slug)
    open_branches = []
    try:
        out = subprocess.check_output(["git", "branch", "--list", f"*/*{slug}*"], cwd=root, text=True)
        open_branches = [b.strip().lstrip("* ") for b in out.splitlines() if b.strip()]
    except Exception:
        pass

    tasks_complete = tasks["total"] > 0 and tasks["done"] == tasks["total"]
    # INDEX vocabulary: not-started | complete (no in-progress per PRD 004 /sw-deliver R43).
    if feature_complete or (tasks_complete and merged) or (tasks_complete and row.get("indexStatus") == "complete"):
        status = "complete"
    else:
        status = "not-started"

    return {
        "prd": row["prd"],
        "slug": slug,
        "status": status,
        "taskFile": str(task_file.relative_to(root)) if task_file else None,
        "tasks": tasks,
        "mergedPrs": merged,
        "featureComplete": feature_complete,
        "activeBranches": open_branches,
    }

rows = parse_index()
result = [status_for(r) for r in rows]
print(json.dumps({"prds": result, "gapBacklog": str(prds_dir / "GAP-BACKLOG.md")}, indent=2))
PY
}

cmd_reconcile() {
  local dry=""
  [[ "${1:-}" == "--dry-run" ]] && dry="1"
  local derived
  derived="$(cmd_derive)"
  python3 - "$ROOT" "$derived" "$dry" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
data = json.loads(sys.argv[2])
dry = bool(sys.argv[3])
index_path = root / "docs" / "prds" / "INDEX.md"
text = index_path.read_text(encoding="utf-8")
status_map = {r["prd"]: r["status"] for r in data.get("prds", [])}
lines = []
for line in text.splitlines():
    if line.startswith("|") and not line.startswith("| #") and not line.startswith("|---"):
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) >= 4 and parts[0] in status_map:
            status_idx = 4 if len(parts) >= 5 else 3
            parts[status_idx] = status_map[parts[0]]
            line = "| " + " | ".join(parts) + " |"
    lines.append(line)
new_text = "\n".join(lines) + ("\n" if lines else "")
if dry:
    print(new_text)
else:
    index_path.write_text(new_text, encoding="utf-8")
    print(json.dumps({"verdict": "reconciled", "updated": list(status_map.keys())}))
PY
}

cmd_append_log() {
  local prd="${1:-}" phase="${2:-}" notes="${3:-}"
  [[ -n "$prd" && -n "$phase" ]] || { usage >&2; exit 1; }
  local log="$ROOT/docs/prds/COMPLETION-LOG.md"
  local date
  date="$(date -u +%Y-%m-%d)"
  python3 - "$log" "$date" "$prd" "$phase" "$notes" <<'PY'
import sys
from pathlib import Path

log = Path(sys.argv[1])
date, prd, phase, notes = sys.argv[2:6]
line = f"| {date} | {prd} | {phase} | {notes} |"
text = log.read_text(encoding="utf-8")
if "_No entries yet._" in text:
    text = text.replace("_No entries yet._\n", "")
marker = "| Date | PRD | Phase | Notes |"
idx = text.find(marker)
if idx == -1:
    raise SystemExit("COMPLETION-LOG header missing")
insert_at = text.find("\n", idx) + 1
insert_at = text.find("\n", insert_at) + 1
text = text[:insert_at] + line + "\n" + text[insert_at:]
log.write_text(text, encoding="utf-8")
print(line)
PY
}

main() {
  local cmd="${1:-}"
  shift || true
  case "$cmd" in
    derive) cmd_derive "$@" ;;
    reconcile) cmd_reconcile "$@" ;;
    append-log) cmd_append_log "$@" ;;
    -h | --help | "") usage ;;
    *)
      echo "unknown: $cmd" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
