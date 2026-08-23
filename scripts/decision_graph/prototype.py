"""Prototype worktree provision and merge-refusal hooks (PRD 280 R9)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = SCRIPT_DIR.parent
ROOT = SCRIPTS_DIR.parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from decision_graph.evidence import (  # noqa: E402
    KIND_PROTOTYPE,
    collect_linked_evidence_hashes,
    extract_and_link,
    has_linked_evidence_kind,
    node_requires_evidence,
)
from decision_graph.journal import DecisionRunJournal  # noqa: E402
from decision_graph.receipt import build_prototype_teardown_receipt  # noqa: E402
from decision_graph.schema import NodeKind

PROTOTYPE_BRANCH_PREFIX = "feat/prototype-"
PROTOTYPE_MARKER_REL = ".cursor/sw-prototype.json"
CAUSE_MERGE_REFUSED = "prototype:merge-refused"
CAUSE_MARKER_INVALID = "prototype:marker-invalid"
CAUSE_EVIDENCE_MISSING = "prototype:evidence-missing"


def prototype_branch_name(node_id: str) -> str:
    slug = node_id.strip().lower().replace("_", "-")
    return f"{PROTOTYPE_BRANCH_PREFIX}{slug}"


def is_prototype_branch(branch: str) -> bool:
    return str(branch or "").startswith(PROTOTYPE_BRANCH_PREFIX)


def prototype_worktree_name(node_id: str) -> str:
    return f"prototype-{node_id.strip().lower().replace('_', '-')}"


def prototype_marker_path(worktree: Path) -> Path:
    return worktree / PROTOTYPE_MARKER_REL


def _integration_merge_target(target_branch: str) -> bool:
    normalized_target = str(target_branch or "").strip()
    return normalized_target in {"", "main", "master"} or normalized_target.startswith("feat/")


def _marker_has_evidence_contract(data: Mapping[str, Any]) -> bool:
    contract = data.get("evidenceContract")
    if not isinstance(contract, Mapping):
        return False
    parent_requires = contract.get("parentRequiresEvidence")
    if not isinstance(parent_requires, bool):
        return False
    required_kind = contract.get("requiredEvidenceKind")
    if not isinstance(required_kind, str) or not required_kind.strip():
        return False
    return True


def _evidence_contract_from_marker(marker: Mapping[str, Any]) -> dict[str, Any]:
    contract = marker.get("evidenceContract")
    if not isinstance(contract, Mapping):
        return {}
    return {
        "parentRequiresEvidence": contract.get("parentRequiresEvidence"),
        "requiredEvidenceKind": str(contract.get("requiredEvidenceKind") or ""),
    }


def refuse_merge_enqueue(
    branch: str,
    target_branch: str,
    *,
    root: Path | None = None,
    worktree: Path | None = None,
    marker: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Refuse merge-enqueue when prototype evidence contract is unsatisfied."""
    if not is_prototype_branch(branch):
        return {"verdict": "pass", "branch": branch, "target": target_branch}

    normalized_target = str(target_branch or "").strip()
    if not _integration_merge_target(normalized_target):
        return {"verdict": "pass", "branch": branch, "target": normalized_target}

    marker_data: Mapping[str, Any] | None = marker
    if marker_data is None and worktree is not None:
        marker_data = read_prototype_marker(worktree)

    if marker_data is None or not _marker_has_evidence_contract(marker_data):
        return {
            "verdict": "fail",
            "cause": CAUSE_MARKER_INVALID,
            "branch": branch,
            "target": normalized_target,
            "note": "prototype marker missing or invalid evidence contract",
        }

    contract = _evidence_contract_from_marker(marker_data)
    parent_requires = contract.get("parentRequiresEvidence")
    required_kind = str(contract.get("requiredEvidenceKind") or "")
    parent_decision_id = str(marker_data.get("parentDecisionId") or "")

    if parent_requires is True:
        if root is None:
            return {
                "verdict": "fail",
                "cause": CAUSE_EVIDENCE_MISSING,
                "branch": branch,
                "target": normalized_target,
                "missingEvidenceKind": required_kind,
                "parentDecisionId": parent_decision_id,
                "note": "cannot verify linked evidence without repo root",
            }
        if not has_linked_evidence_kind(root, parent_decision_id, required_kind):
            return {
                "verdict": "fail",
                "cause": CAUSE_EVIDENCE_MISSING,
                "branch": branch,
                "target": normalized_target,
                "missingEvidenceKind": required_kind,
                "parentDecisionId": parent_decision_id,
            }

    return {"verdict": "pass", "branch": branch, "target": normalized_target}


def write_prototype_marker(
    worktree: Path,
    *,
    node_id: str,
    parent_decision_id: str,
    branch: str,
    parent_branch: str,
    parent_requires_evidence: bool,
    required_evidence_kind: str,
) -> Path:
    marker = prototype_marker_path(worktree)
    marker.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "kind": "prototype-worktree",
        "nodeId": node_id,
        "parentDecisionId": parent_decision_id,
        "branch": branch,
        "parentBranch": parent_branch,
        "evidenceContract": {
            "requiredEvidenceKind": required_evidence_kind,
            "parentRequiresEvidence": parent_requires_evidence,
        },
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
    if not isinstance(data, dict):
        return None
    if not _marker_has_evidence_contract(data):
        return None
    return data


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


def _parent_decision_node(document: dict[str, Any], parent_decision_id: str) -> dict[str, Any] | None:
    spec = document.get("spec") if isinstance(document.get("spec"), dict) else {}
    nodes = spec.get("nodes") if isinstance(spec.get("nodes"), list) else []
    for node in nodes:
        if isinstance(node, dict) and str(node.get("id") or "") == parent_decision_id:
            return node
    return None


def teardown_prototype_worktree(
    root: Path,
    worktree: Path,
    document: dict[str, Any],
    *,
    run_id: str,
    actor: str = "sw-phase-executor",
    base_ref: str = "HEAD~1",
) -> dict[str, Any]:
    """Extract evidence, emit teardown receipt + journal entry (survives worktree removal)."""
    marker = read_prototype_marker(worktree)
    if marker is None:
        return {
            "verdict": "fail",
            "cause": CAUSE_MARKER_INVALID,
            "note": "prototype marker missing or invalid evidence contract",
        }

    parent_decision_id = str(marker.get("parentDecisionId") or "")
    node_id = str(marker.get("nodeId") or "")
    branch = str(marker.get("branch") or "")
    contract = _evidence_contract_from_marker(marker)
    required_kind = str(contract.get("requiredEvidenceKind") or KIND_PROTOTYPE)

    linked = extract_and_link(
        root,
        document,
        worktree,
        parent_decision_id=parent_decision_id,
        prototype_node_id=node_id,
        branch=branch,
        base_ref=base_ref,
    )
    if linked.get("verdict") != "pass":
        return linked

    evidence_hashes = collect_linked_evidence_hashes(root, parent_decision_id, required_kind)
    receipt = build_prototype_teardown_receipt(
        node_id=node_id,
        parent_decision_id=parent_decision_id,
        actor=actor,
        evidence_hashes=evidence_hashes,
        branch=branch,
    )
    journal = DecisionRunJournal(root, run_id)
    event_id = f"prototype-teardown:{node_id}"
    journal_entry = journal.append_prototype_teardown(
        event_id,
        node_id=node_id,
        receipt=receipt,
        actor=actor,
    )

    return {
        "verdict": "pass",
        "nodeId": node_id,
        "parentDecisionId": parent_decision_id,
        "evidenceHashes": evidence_hashes,
        "receipt": receipt,
        "journalEntry": journal_entry,
        "journalRunId": run_id,
    }


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
    parent_node = _parent_decision_node(document, parent_decision_id)
    parent_requires_evidence = bool(parent_node and node_requires_evidence(parent_node))
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
            parent_requires_evidence=parent_requires_evidence,
            required_evidence_kind=KIND_PROTOTYPE,
        )

    return {
        "verdict": "pass",
        "nodeId": prototype_node_id,
        "parentDecisionId": parent_decision_id,
        "branch": branch,
        "worktree": str(wt_path),
        "worktreeName": name,
    }
