#!/usr/bin/env bash
# Derive PRD living status from git + INDEX + task checkboxes; reconcile INDEX; append completion log.
set -euo pipefail

_PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(git -C "${PWD}" rev-parse --show-toplevel 2>/dev/null || echo "$_PLUGIN_ROOT")"

usage() {
  cat <<'EOF'
Usage:
  reconcile-status.py derive [--json]     Compute status per PRD from git facts
  reconcile-status.py reconcile [--dry-run] [--require-merge]  Update INDEX Status (complete only when merged if --require-merge; R11 — required for pre-merge /sw-retrospective even when compound.autonomy is auto)
  reconcile-status.py set-index-status --prd <NNN> --status <not-started|in-progress|complete>  Set one INDEX row (R47)
  reconcile-status.py append-log <prd> <phase> <notes>  Append COMPLETION-LOG entry (legacy)
  reconcile-status.py append-log-idempotent --prd <NNN> --phase <name> [--pr N] [--sha SHA] [--notes text]  Idempotent append (R48)
  reconcile-status.py gap-resolve --absorbing-prd <NNN> [--pr N]  Flip matching open gaps to resolved (R49)
  reconcile-status.py append-superseded --path <repo-rel> [--replacement <repo-rel>]  Append to docs/decisions/SUPERSEDED.log (idempotent)
  reconcile-status.py supersede-reconcile [--json] [--dry-run]  Emit best-effort re-point plan for non-authoritative side (R7)
  reconcile-status.py deliver-runs [--json]       List live scoped deliver runs (PRD 013 R10)
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
import os
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



def load_authoring_handoffs(root: Path):
    path = root / ".cursor" / "authoring-handoffs.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    items = data.get("handoffs")
    return items if isinstance(items, list) else []


def pull_in_scan_targets(root: Path):
    return [h.get("artifact") for h in load_authoring_handoffs(root) if h.get("artifact")]

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
    branch_prefixes = ("docs", "feat", "fix", "chore", "perf", "refactor", "revert", "test")
    branch_pats = [
        re.compile(rf"^{prefix}/{slug_esc}([/-]|$)", re.IGNORECASE) for prefix in branch_prefixes
    ]
    integration_pat = re.compile(
        rf"^(?:feat|fix|perf|revert|docs|chore|refactor|test)/{slug_esc}$", re.IGNORECASE
    )
    prd_pat = re.compile(rf"prd:\s*{re.escape(slug_lower)}\b", re.IGNORECASE)
    prd_path_pat = re.compile(rf"prd/{re.escape(slug_lower)}\b", re.IGNORECASE)
    prd_num_pat = re.compile(rf"\bPRD\s+{re.escape(slug_lower)}\b", re.IGNORECASE)
    title_pat = re.compile(rf"\b{slug_esc}\b", re.IGNORECASE)
    try:
        proc = subprocess.run(
            ["bash", str(Path(root) / "scripts" / "host.sh"), "--root", root, "pr-list", "--state", "closed", "--limit", "100"],
            cwd=root,
            text=True,
            capture_output=True,
            stderr=subprocess.DEVNULL,
        )
        payload = json.loads(proc.stdout or "{}")
        prs = payload.get("data") if payload.get("verdict") == "ok" else []
        if not isinstance(prs, list):
            prs = []
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
    require_merge = os.environ.get("SW_RECONCILE_REQUIRE_MERGE") == "1"
    index_terminal = row.get("indexStatus") in ("complete", "superseded")
    # INDEX vocabulary: not-started | in-progress | complete (R47 — single-sourced in living-status skill).
    # Stale local branches must not downgrade terminal rows (R32).
    if require_merge:
        status = "complete" if feature_complete else row.get("indexStatus", "not-started")
        if status != "complete":
            status = "not-started"
    elif feature_complete or index_terminal:
        status = "complete"
    elif tasks_complete and merged:
        status = "complete"
    elif tasks["done"] > 0 or (open_branches and not feature_complete) or merged:
        status = "in-progress"
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
sys.path.insert(0, str(root / "scripts"))
from wave_state import enumerate_scoped_runs, utc_now

deliver_runs = enumerate_scoped_runs(root)
index_path = root / ".cursor" / "sw-deliver-runs" / "index.json"
index_path.parent.mkdir(parents=True, exist_ok=True)
index_path.write_text(
    json.dumps({"updatedAt": utc_now(), "runs": deliver_runs}, indent=2) + "\n",
    encoding="utf-8",
)
from wave_living_docs import live_phase_status_rows

live_phase_status = []
for run in deliver_runs:
    state_path = root / run.get("statePath", "")
    if not state_path.is_file():
        continue
    try:
        run_state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        continue
    if run_state.get("verdict") != "running":
        continue
    live_phase_status.append(
        {
            "slug": run.get("slug"),
            "target": run.get("target"),
            "phases": live_phase_status_rows(run_state),
        }
    )
print(
    json.dumps(
        {
            "prds": result,
            "gapBacklog": str(prds_dir / "GAP-BACKLOG.md"),
            "deliverRuns": deliver_runs,
            "livePhaseStatus": live_phase_status,
            "authoringHandoffs": load_authoring_handoffs(root),
            "pullInScan": pull_in_scan_targets(root),
        },
        indent=2,
    )
)
PY
}

cmd_deliver_runs() {
  local as_json="${1:-}"
  if [[ "$as_json" == "--json" ]]; then
    python3 "$ROOT/scripts/wave_state.py" "$ROOT" runs index 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps({'deliverRuns': d.get('runs', []), 'indexPath': d.get('path')}, indent=2))"
  else
    python3 "$ROOT/scripts/wave_state.py" "$ROOT" runs index 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
for r in d.get('runs', []):
    print(f\"{r.get('slug')}: {r.get('target')} verdict={r.get('verdict')} lock={r.get('lockHeld')}\")
"
  fi
}

cmd_reconcile() {
  local dry=""
  local require_merge=""
  local allow_default=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run) dry="1"; shift ;;
      --require-merge) require_merge="1"; shift ;;
      --allow-default-branch) allow_default="1"; shift ;;
      *) break ;;
    esac
  done
  [[ -n "$require_merge" ]] && export SW_RECONCILE_REQUIRE_MERGE=1
  if [[ -z "$dry" && -z "$allow_default" ]]; then
    local cfg branch base
    cfg="$(read_config)"
    branch="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")"
    base="$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('defaultBaseBranch','main'))" "$cfg")"
    if [[ "$branch" == "$base" ]]; then
      python3 -c "import json; print(json.dumps({'verdict':'fail','error':'reconcile refuses default branch commits (R31)','branch':'$branch','remediation':'use set-index-status + append-log-idempotent on a docs branch'}))" >&2
      exit 20
    fi
  fi
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

cmd_set_index_status() {
  local prd="" status=""
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --prd) prd="${2:-}"; shift 2 ;;
      --status) status="${2:-}"; shift 2 ;;
      *) break ;;
    esac
  done
  [[ -n "$prd" && -n "$status" ]] || { usage >&2; exit 1; }
  python3 - "$ROOT" "$prd" "$status" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
prd = sys.argv[2].zfill(3)
status = sys.argv[3]
allowed = {"not-started", "in-progress", "complete"}
if status not in allowed:
    raise SystemExit(f"invalid status {status!r}; one of {sorted(allowed)}")
index_path = root / "docs" / "prds" / "INDEX.md"
text = index_path.read_text(encoding="utf-8")
lines = []
updated = False
for line in text.splitlines():
    if line.startswith("|") and not line.startswith("| #") and not line.startswith("|---"):
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) >= 4 and parts[0].zfill(3) == prd:
            status_idx = 4 if len(parts) >= 5 else 3
            parts[status_idx] = status
            line = "| " + " | ".join(parts) + " |"
            updated = True
    lines.append(line)
if not updated:
  raise SystemExit(f"INDEX row not found for PRD {prd}")
index_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
print(json.dumps({"verdict": "pass", "action": "set-index-status", "prd": prd, "status": status}))
PY
}

cmd_append_log_idempotent() {
  python3 - "$ROOT" "$@" <<'PY'
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
args = sys.argv[2:]
prd = phase = notes = pr = sha = ""
i = 0
while i < len(args):
    if args[i] == "--prd" and i + 1 < len(args):
        prd = args[i + 1].zfill(3)
        i += 2
    elif args[i] == "--phase" and i + 1 < len(args):
        phase = args[i + 1]
        i += 2
    elif args[i] == "--notes" and i + 1 < len(args):
        notes = args[i + 1]
        i += 2
    elif args[i] == "--pr" and i + 1 < len(args):
        pr = args[i + 1]
        i += 2
    elif args[i] == "--sha" and i + 1 < len(args):
        sha = args[i + 1]
        i += 2
    else:
        i += 1
if not prd or not phase:
    raise SystemExit("--prd and --phase required")
log = root / "docs" / "prds" / "COMPLETION-LOG.md"
text = log.read_text(encoding="utf-8")
id_key = f"| {prd} | {phase} |"
sha_key = sha[:7] if sha else ""
if id_key in text and (not sha_key or sha_key in text):
    print(json.dumps({"verdict": "pass", "action": "append-log-idempotent", "skipped": True, "reason": "already-present"}))
    raise SystemExit(0)
date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
detail_parts = [notes or "deliver complete"]
if pr:
    detail_parts.append(f"PR #{pr}")
if sha:
    detail_parts.append(f"SHA {sha[:7]}")
detail = "; ".join(p for p in detail_parts if p)
line = f"| {date} | {prd} | {phase} | {detail} |"
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
print(json.dumps({"verdict": "pass", "action": "append-log-idempotent", "appended": True, "line": line}))
PY
}

cmd_gap_resolve() {
  local args=()
  while [[ $# -gt 0 ]]; do args+=("$1"); shift; done
  exec bash "$ROOT/scripts/living-status-gap-resolve.py" "${args[@]}"
}

cmd_append_superseded() {
  python3 - "$ROOT" "$@" <<'PY'
import json
import re
import sys
from datetime import date
from pathlib import Path

root = Path(sys.argv[1])
args = sys.argv[2:]
superseded = replacement = ""
i = 0
while i < len(args):
    if args[i] == "--path" and i + 1 < len(args):
        superseded = args[i + 1].strip()
        i += 2
    elif args[i] == "--replacement" and i + 1 < len(args):
        replacement = args[i + 1].strip()
        i += 2
    else:
        i += 1
if not superseded:
    raise SystemExit("--path required")
if not superseded.startswith("docs/decisions/") or superseded.endswith("INDEX.md"):
    raise SystemExit("path must be a decision record under docs/decisions/")
log_path = root / "docs" / "decisions" / "SUPERSEDED.log"
header = (
    "# SUPERSEDED.log — append-only manifest (decision record-level supersede)\n"
    "# date<TAB>superseded_path<TAB>replacement_path\n"
)
if log_path.is_file():
    text = log_path.read_text(encoding="utf-8")
else:
    text = header
    log_path.parent.mkdir(parents=True, exist_ok=True)
for line in text.splitlines():
    if line.startswith("#") or not line.strip():
        continue
    parts = line.split("\t")
    path_col = parts[1] if len(parts) > 1 and re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]) else parts[0]
    if path_col.strip() == superseded:
        print(json.dumps({"verdict": "pass", "action": "append-superseded", "skipped": True, "path": superseded}))
        raise SystemExit(0)
entry = f"{date.today().isoformat()}\t{superseded}\t{replacement}\n"
if not text.endswith("\n") and text:
    text += "\n"
text += entry
log_path.write_text(text, encoding="utf-8")
print(json.dumps({"verdict": "pass", "action": "append-superseded", "appended": True, "path": superseded, "replacement": replacement or None}))
PY
}

cmd_supersede_reconcile() {
  python3 - "$ROOT" "$@" <<'PY'
import json
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
args = sys.argv[2:]
as_json = "--json" in args
dry_run = "--dry-run" in args

log_path = root / "docs" / "decisions" / "SUPERSEDED.log"
entries = []
if log_path.is_file():
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        date_part = parts[0] if re.match(r"^\d{4}-\d{2}-\d{2}$", parts[0]) else ""
        if date_part:
            superseded, replacement = parts[1], parts[2] if len(parts) > 2 else ""
        else:
            superseded, replacement = parts[0], parts[1] if len(parts) > 1 else ""
        entries.append({"superseded": superseded.strip(), "replacement": replacement.strip() or None})

proc = subprocess.run(
    ["bash", str(root / "scripts/memory-sot.py"), "resolve", "--class", "decision", "--json"],
    cwd=str(root),
    text=True,
    capture_output=True,
)
if proc.returncode != 0:
    print(json.dumps({"verdict": "fail", "error": "memory-sot resolve failed", "stderr": proc.stderr.strip()}))
    raise SystemExit(2)
sot = json.loads(proc.stdout)
effective = sot.get("effective", "repo")
non_auth = "provider" if effective == "repo" else "git"

def scan_in_repo_pointers(superseded: str):
    store = root / ".cursor" / "sw-memory" / "memories"
    hits = []
    if not store.is_dir():
        return hits
    for mem in store.glob("*.md"):
        text = mem.read_text(encoding="utf-8")
        if superseded in text:
            hits.append(mem.as_posix())
    return hits

actions = []
for entry in entries:
    superseded = entry["superseded"]
    replacement = entry["replacement"]
    item = {
        "superseded": superseded,
        "replacement": replacement,
        "effective": effective,
        "reconcileTarget": non_auth,
    }
    if effective == "repo":
        item["action"] = "repoint-provider-pointer"
        item["providerRecipe"] = {
            "category": "decision",
            "contentBearing": False,
            "relatedFiles": [replacement] if replacement else [],
        }
        item["inRepoMatches"] = scan_in_repo_pointers(superseded)
    else:
        item["action"] = "refresh-git-snapshot-pointer"
        item["gitRecipe"] = {
            "path": superseded,
            "snapshotRole": "pointer",
            "replacementPath": replacement,
        }
    actions.append(item)

out = {
    "verdict": "pass",
    "action": "supersede-reconcile",
    "effective": effective,
    "nonAuthoritative": non_auth,
    "dryRun": dry_run,
    "entries": len(entries),
    "reconcile": actions,
}
if dry_run:
    out["note"] = "plan only — apply via /sw-memory-sync or memory-preflight modify"
print(json.dumps(out, indent=2) if as_json else json.dumps(out))
PY
}

main() {
  local cmd="${1:-}"
  shift || true
  case "$cmd" in
    derive) cmd_derive "$@" ;;
    reconcile) cmd_reconcile "$@" ;;
    set-index-status) cmd_set_index_status "$@" ;;
    append-log) cmd_append_log "$@" ;;
    append-log-idempotent) cmd_append_log_idempotent "$@" ;;
    gap-resolve) cmd_gap_resolve "$@" ;;
    append-superseded) cmd_append_superseded "$@" ;;
    supersede-reconcile) cmd_supersede_reconcile "$@" ;;
    deliver-runs) cmd_deliver_runs "$@" ;;
    -h | --help | "") usage ;;
    *)
      echo "unknown: $cmd" >&2
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
