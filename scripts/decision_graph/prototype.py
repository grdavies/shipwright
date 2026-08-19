"""Prototype worktree provision and merge-refusal hooks (PRD 280 R9)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from decision_graph.schema import NodeKind

PROTOTYPE_BRANCH_PREFIX = "feat/prototype-"
PROTOTYPE_MARKER_REL = ".cursor/sw-prototype.json"
CAUSE_MERGE_REFUSED = "prototype:merge-refused"


def prototype_branch_name(node_id: str) -> str:
    slug = node_id.strip().lower().replace("_", "-")
    return f"{PROTOTYPE_BRANCH_PREFIX}{slug}"


def is_prototype_branch(branch: str) -> bool:
    return str(branch or "").startswith(PROTOTYPE_BRANCH_PREFIX)


def prototype_worktree_name(node_id: str) -> str:
    return f"prototype-{node_id.strip().lower().replace('_', '-')}"


def prototype_marker_path(worktree: Path) -> Path:
    return worktree / PROTOTYPE_MARKER_REL


def refuse_merge_enqueue(branch: str, target_branch: str) -> dict[str, Any]:
    """Prototype branches may not merge-enqueue onto integration or main."""
    if not is_prototype_branch(branch):
        return {"verdict": "pass", "branch": branch, "target": target_branch}
    normalized_target = str(target_branch or "").strip()
    if normalized_target in {"", "main", "master"} or normalized_target.startswith("feat/"):
        return {
            "verdict": "fail",
            "cause": CAUSE_MERGE_REFUSED,
            "branch": branch,
            "target": normalized_target,
            "note": "prototype branches cannot merge-enqueue to integration or main",
        }
    return {"verdict": "pass", "branch": branch, "target": normalized_target}


def write_prototype_marker(
    worktree: Path,
    *,
    node_id: str,
    parent_decision_id: str,
    branch: str,
    parent_branch: str,
) -> Path:
    marker = prototype_marker_path(worktree)
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "prototype-worktree",
        "nodeId": node_id,
        "parentDecisionId": parent_decision_id,
        "branch": branch,
        "parentBranch": parent_branch,
    }
    marker.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return marker


def read_prototype_marker(worktree: Path) -> dict[str, Any] | None:
    marker = prototype_marker_path(worktree)
    if not marker.is_file():
        return None
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def find_prototype_parent(document: dict[str, Any], prototype_node_id: str) -> str | None:
    spec = document.get("spec") if isinstance(document.get("spec"), dict) else {}
    edges = spec.get("edges") if isinstance(spec.get("edges"), list) else []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        if str(edge.get("to") or "") == prototype_node_id:
            parent = str(edge.get("from") or "")
            if parent:
                return parent
    return None


def provision_prototype_worktree(
    root: Path,
    document: dict[str, Any],
    prototype_node_id: str,
    *,
    base_branch: str,
) -> dict[str, Any]:
    spec = document.get("spec") if isinstance(document.get("spec"), dict) else {}
    nodes = spec.get("nodes") if isinstance(spec.get("nodes"), list) else []
    prototype_node = next(
        (
            n
            for n in nodes
            if isinstance(n, dict)
            and str(n.get("id") or "") == prototype_node_id
            and n.get("kind") == NodeKind.PROTOTYPE.value
        ),
        None,
    )
    if prototype_node is None:
        return {
            "verdict": "fail",
            "cause": "prototype:node-missing",
            "nodeId": prototype_node_id,
        }

    parent_decision_id = find_prototype_parent(document, prototype_node_id) or prototype_node_id
    branch = prototype_branch_name(prototype_node_id)
    name = prototype_worktree_name(prototype_node_id)
    worktree_script = SCRIPTS_DIR / "worktree.py"

    proc = subprocess.run(
        [
            sys.executable,
            str(worktree_script),
            "provision",
            name,
            "--branch",
            branch,
            "--base",
            base_branch,
            "--worktree-role",
            "prototype",
            "--counts-toward-ceiling",
            "false",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return {
            "verdict": "fail",
            "cause": "prototype:provision-failed",
            "exitCode": proc.returncode,
            "stderr": (proc.stderr or proc.stdout or "").strip(),
        }

    git_top = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    top = Path(git_top.stdout.strip()) if git_top.returncode == 0 else root
    wt_path = top / ".sw-worktrees" / name
    if wt_path.is_dir():
        write_prototype_marker(
            wt_path,
            node_id=prototype_node_id,
            parent_decision_id=parent_decision_id,
            branch=branch,
            parent_branch=base_branch,
        )

    return {
        "verdict": "pass",
        "nodeId": prototype_node_id,
        "parentDecisionId": parent_decision_id,
        "branch": branch,
        "worktree": str(wt_path),
        "worktreeName": name,
    }
