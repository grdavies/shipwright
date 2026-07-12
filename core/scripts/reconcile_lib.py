"""Shared INDEX reconciler helpers — PRD INDEX + planning INDEX (PRD 042 R22)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from _sw.completion_log import append_log_idempotent

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def read_config(root: Path) -> dict[str, Any]:
    for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
        if candidate.is_file():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return {"prdsDir": "docs/prds", "tasksDir": "docs/prds", "defaultBaseBranch": "main"}


def git_root(start: Path | None = None) -> Path:
    start = start or Path.cwd()
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    return Path(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip() else start


def parse_prd_index(index_path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
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


def task_checkbox_state(task_file: Path) -> dict[str, Any]:
    if not task_file.is_file():
        return {"total": 0, "done": 0, "ratio": 0.0}
    text = task_file.read_text(encoding="utf-8")
    checked = len(re.findall(r"^- \[x\]", text, re.MULTILINE | re.IGNORECASE))
    unchecked = len(re.findall(r"^- \[ \]", text, re.MULTILINE))
    total = checked + unchecked
    return {"total": total, "done": checked, "ratio": (checked / total) if total else 0.0}


def host_pr_list(root: Path) -> list[dict[str, Any]]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "host.py"), "--root", str(root), "pr-list", "--state", "closed", "--limit", "100"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return []
    if payload.get("verdict") != "ok":
        return []
    prs = payload.get("data")
    return prs if isinstance(prs, list) else []


def merged_prs_for_slug(root: Path, slug: str) -> tuple[list[int], bool]:
    merged: list[int] = []
    feature_complete = False
    slug_esc = re.escape(slug)
    slug_lower = slug.lower()
    branch_prefixes = ("docs", "feat", "fix", "chore", "perf", "refactor", "revert", "test")
    branch_pats = [re.compile(rf"^{prefix}/{slug_esc}([/-]|$)", re.IGNORECASE) for prefix in branch_prefixes]
    integration_pat = re.compile(
        rf"^(?:feat|fix|perf|revert|docs|chore|refactor|test)/{slug_esc}$", re.IGNORECASE
    )
    prd_pat = re.compile(rf"prd:\s*{re.escape(slug_lower)}\b", re.IGNORECASE)
    prd_path_pat = re.compile(rf"prd/{re.escape(slug_lower)}\b", re.IGNORECASE)
    prd_num_pat = re.compile(rf"\bPRD\s+{re.escape(slug_lower)}\b", re.IGNORECASE)
    title_pat = re.compile(rf"\b{slug_esc}\b", re.IGNORECASE)
    for pr in host_pr_list(root):
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
            merged.append(int(pr["number"]))
    return merged, feature_complete


def status_for_row(root: Path, row: dict[str, str], tasks_dir: Path) -> dict[str, Any]:
    slug = row["slug"]
    task_candidates = list(tasks_dir.rglob(f"*{slug}*tasks*.md")) + list(tasks_dir.rglob(f"tasks*{slug}*.md"))
    task_file = task_candidates[0] if task_candidates else None
    tasks = task_checkbox_state(task_file) if task_file else {"total": 0, "done": 0, "ratio": 0.0}
    merged, feature_complete = merged_prs_for_slug(root, slug)
    open_branches: list[str] = []
    try:
        out = subprocess.check_output(["git", "branch", "--list", f"*/*{slug}*"], cwd=str(root), text=True)
        open_branches = [b.strip().lstrip("* ") for b in out.splitlines() if b.strip()]
    except Exception:
        pass
    tasks_complete = tasks["total"] > 0 and tasks["done"] == tasks["total"]
    require_merge = os.environ.get("SW_RECONCILE_REQUIRE_MERGE") == "1"
    index_terminal = row.get("indexStatus") in ("complete", "superseded")
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


def derive_prd_status(root: Path) -> dict[str, Any]:
    cfg = read_config(root)
    prds_dir = root / cfg.get("prdsDir", "docs/prds")
    tasks_dir = root / cfg.get("tasksDir", "docs/prds")
    index_path = prds_dir / "INDEX.md"
    rows = parse_prd_index(index_path)
    result = [status_for_row(root, row, tasks_dir) for row in rows]
    from wave_state import enumerate_scoped_runs, utc_now
    from wave_living_docs import live_phase_status_rows

    deliver_runs = enumerate_scoped_runs(root)
    index_out = root / ".cursor/sw-deliver-runs/index.json"
    index_out.parent.mkdir(parents=True, exist_ok=True)
    index_out.write_text(json.dumps({"updatedAt": utc_now(), "runs": deliver_runs}, indent=2) + "\n", encoding="utf-8")
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
            {"slug": run.get("slug"), "target": run.get("target"), "phases": live_phase_status_rows(run_state)}
        )
    handoffs_path = root / ".cursor/authoring-handoffs.json"
    handoffs: list[Any] = []
    if handoffs_path.is_file():
        try:
            data = json.loads(handoffs_path.read_text(encoding="utf-8"))
            items = data.get("handoffs")
            handoffs = items if isinstance(items, list) else []
        except json.JSONDecodeError:
            handoffs = []
    pull_in = [h.get("artifact") for h in handoffs if h.get("artifact")]
    return {
        "prds": result,
        "gapBacklog": str(prds_dir / "GAP-BACKLOG.md"),
        "deliverRuns": deliver_runs,
        "livePhaseStatus": live_phase_status,
        "authoringHandoffs": handoffs,
        "pullInScan": pull_in,
    }


def apply_prd_index_status(index_path: Path, status_map: dict[str, str]) -> str:
    text = index_path.read_text(encoding="utf-8")
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("|") and not line.startswith("| #") and not line.startswith("|---"):
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) >= 4 and parts[0] in status_map:
                status_idx = 4 if len(parts) >= 5 else 3
                parts[status_idx] = status_map[parts[0]]
                line = "| " + " | ".join(parts) + " |"
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")




def _refuse_banned_living_doc_write(root: Path, *, action: str) -> dict[str, Any] | None:
    from planning_store import refuse_banned_living_doc_write

    return refuse_banned_living_doc_write(root, action=action)

def reconcile_prd_index(root: Path, *, dry_run: bool = False, require_merge: bool = False, allow_default: bool = False) -> dict[str, Any]:
    refusal = _refuse_banned_living_doc_write(root, action="reconcile-prd-index")
    if refusal:
        return refusal
    if require_merge:
        os.environ["SW_RECONCILE_REQUIRE_MERGE"] = "1"
    cfg = read_config(root)
    branch = subprocess.run(["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True)
    branch_name = branch.stdout.strip() if branch.returncode == 0 else ""
    base = str(cfg.get("defaultBaseBranch") or "main")
    if not dry_run and not allow_default and branch_name == base:
        return {
            "verdict": "fail",
            "error": "reconcile refuses default branch commits (R31)",
            "branch": branch_name,
            "remediation": "use set-index-status + append-log-idempotent on a docs branch",
        }
    derived = derive_prd_status(root)
    status_map = {r["prd"]: r["status"] for r in derived.get("prds", [])}
    index_path = root / "docs/prds/INDEX.md"
    new_text = apply_prd_index_status(index_path, status_map)
    if dry_run:
        return {"verdict": "dry-run", "text": new_text, "updated": list(status_map.keys())}
    index_path.write_text(new_text, encoding="utf-8")
    return {"verdict": "reconciled", "updated": list(status_map.keys())}


def set_index_status(root: Path, prd: str, status: str) -> dict[str, Any]:
    refusal = _refuse_banned_living_doc_write(root, action="set-index-status")
    if refusal:
        return refusal
    allowed = {"not-started", "in-progress", "complete"}
    if status not in allowed:
        raise SystemExit(f"invalid status {status!r}; one of {sorted(allowed)}")
    prd = prd.zfill(3)
    cfg = read_config(root)
    branch = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
    )
    branch_name = branch.stdout.strip() if branch.returncode == 0 else ""
    base = str(cfg.get("defaultBaseBranch") or "main")
    from default_branch_commit_guard import refuse_default_branch

    try:
        refuse_default_branch(branch_name, base)
    except ValueError as exc:
        return {
            "verdict": "fail",
            "error": str(exc),
            "branch": branch_name,
            "remediation": "use set-index-status on a non-default branch worktree",
        }
    index_path = root / "docs/prds/INDEX.md"
    text = index_path.read_text(encoding="utf-8")
    lines: list[str] = []
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
    result: dict[str, Any] = {"verdict": "pass", "action": "set-index-status", "prd": prd, "status": status}
    if status == "complete":
        import gap_backlog

        flip_result = gap_backlog.resolve_for_prd(root, prd)
        result["flipped"] = flip_result.get("flipped", [])
        if flip_result.get("verdict") != "pass":
            # PRD 057 R4: propagate whatever verdict the resolver returns —
            # "resolution-partial" under issue-store separate-project (a gap
            # issue close/label failure) is distinct from the generic
            # exception-based "partial" the same-repo file path can still raise.
            result["verdict"] = flip_result.get("verdict", "partial")
            result["error"] = flip_result.get("error")
    return result



def superseded_log_path(root: Path) -> Path:
    return root / "docs" / "decisions" / "SUPERSEDED.log"


def append_superseded(root: Path, *, path: str, replacement: str) -> dict[str, Any]:
    """append-superseded: idempotent SUPERSEDED.log row (R7)."""
    log = superseded_log_path(root)
    log.parent.mkdir(parents=True, exist_ok=True)
    row = f"{date.today().isoformat()}\t{path}\t{replacement}"
    existing = log.read_text(encoding="utf-8") if log.is_file() else ""
    if row not in existing.splitlines():
        with log.open("a", encoding="utf-8") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(row + "\n")
    return {"verdict": "pass", "action": "append-superseded", "path": path, "replacement": replacement}


def _memory_store_dir(root: Path) -> Path | None:
    store = root / ".cursor" / "sw-memory"
    return store if store.is_dir() else None


def supersede_reconcile(root: Path) -> dict[str, Any]:
    """Reconcile superseded decision pointers from SUPERSEDED.log (R7/R22)."""
    log = superseded_log_path(root)
    if not log.is_file():
        return {"verdict": "pass", "action": "supersede-reconcile", "entries": 0, "reconciled": 0}
    entries = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    store = _memory_store_dir(root)
    reconciled = 0
    actions: list[dict[str, str]] = []
    if store is not None:
        import subprocess
        proc = subprocess.run(
            [
                sys.executable,
                str(root / "scripts" / "in-repo-memory-search.py"),
                "reconcile-supersede",
                "--store",
                str(store),
                "--log",
                str(log),
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                payload = json.loads(proc.stdout)
                reconciled = int(payload.get("reconciled") or 0)
                actions = payload.get("actions") or []
            except json.JSONDecodeError:
                pass
    return {
        "verdict": "pass",
        "action": "supersede-reconcile",
        "entries": len(entries),
        "reconciled": reconciled,
        "actions": actions,
    }
    entries = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    return {"verdict": "pass", "action": "supersede-reconcile", "entries": len(entries), "reconciled": len(entries)}
