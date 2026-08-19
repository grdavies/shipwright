"""Prototype evidence extraction and decision-node link-back (PRD 280 R10)."""
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

from gate_evidence import digest_bytes, digest_text, utc_now


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def resolve_head_sha(worktree: Path) -> str:
    proc = _git(worktree, "rev-parse", "HEAD")
    return proc.stdout.strip() if proc.returncode == 0 else ""


def diff_digest(worktree: Path, base_ref: str) -> str:
    proc = _git(worktree, "diff", base_ref, "--binary")
    if proc.returncode != 0:
        return digest_text("")
    return digest_bytes((proc.stdout or "").encode("utf-8"))


def build_evidence_record(
    *,
    parent_decision_id: str,
    prototype_node_id: str,
    head_sha: str,
    content_hash: str,
    branch: str,
    worktree: str | None = None,
) -> dict[str, Any]:
    return {
        "apiVersion": "decision-evidence/v1",
        "kind": "PrototypeEvidence",
        "metadata": {
            "parentDecisionId": parent_decision_id,
            "prototypeNodeId": prototype_node_id,
            "linkedAt": utc_now(),
        },
        "spec": {
            "headSha": head_sha,
            "contentHash": content_hash,
            "branch": branch,
            "worktree": worktree,
            "linkBack": {
                "decisionNodeId": parent_decision_id,
                "hashLinked": True,
            },
        },
    }


def extract_prototype_evidence(
    worktree: Path,
    *,
    parent_decision_id: str,
    prototype_node_id: str,
    branch: str,
    base_ref: str = "HEAD~1",
) -> dict[str, Any]:
    head = resolve_head_sha(worktree)
    content_hash = diff_digest(worktree, base_ref)
    record = build_evidence_record(
        parent_decision_id=parent_decision_id,
        prototype_node_id=prototype_node_id,
        head_sha=head,
        content_hash=content_hash,
        branch=branch,
        worktree=str(worktree),
    )
    return {"verdict": "pass", "record": record}


def evidence_store_path(root: Path, parent_decision_id: str) -> Path:
    return root / ".cursor" / "sw-decision-evidence" / f"{parent_decision_id}.json"


def write_evidence_record(root: Path, record: dict[str, Any]) -> Path:
    parent = str(record.get("metadata", {}).get("parentDecisionId") or "unknown")
    out = evidence_store_path(root, parent)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return out


def link_evidence_to_decision(
    document: dict[str, Any],
    parent_decision_id: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    """Attach hash-linked evidence summary onto the parent decision node resolution."""
    spec = document.get("spec") if isinstance(document.get("spec"), dict) else {}
    nodes = spec.get("nodes") if isinstance(spec.get("nodes"), list) else []
    linked = False
    for node in nodes:
        if not isinstance(node, dict):
            continue
        if str(node.get("id") or "") != parent_decision_id:
            continue
        spec_block = record.get("spec") if isinstance(record.get("spec"), dict) else {}
        outcome = (
            f"evidence:{spec_block.get('contentHash') or ''}:head:{spec_block.get('headSha') or ''}"
        )
        node["resolution"] = {
            "outcome": outcome,
            "rationale": json.dumps(
                {
                    "evidenceRecord": record.get("apiVersion"),
                    "contentHash": spec_block.get("contentHash"),
                    "headSha": spec_block.get("headSha"),
                },
                sort_keys=True,
            ),
        }
        if node.get("status") == "open":
            node["status"] = "resolved"
        linked = True
        break
    if not linked:
        return {
            "verdict": "fail",
            "cause": "evidence:parent-decision-missing",
            "parentDecisionId": parent_decision_id,
        }
    return {"verdict": "pass", "parentDecisionId": parent_decision_id, "graph": document}


def extract_and_link(
    root: Path,
    graph_document: dict[str, Any],
    worktree: Path,
    *,
    parent_decision_id: str,
    prototype_node_id: str,
    branch: str,
    base_ref: str = "HEAD~1",
) -> dict[str, Any]:
    extracted = extract_prototype_evidence(
        worktree,
        parent_decision_id=parent_decision_id,
        prototype_node_id=prototype_node_id,
        branch=branch,
        base_ref=base_ref,
    )
    if extracted.get("verdict") != "pass":
        return extracted
    record = extracted["record"]
    path = write_evidence_record(root, record)
    linked = link_evidence_to_decision(graph_document, parent_decision_id, record)
    if linked.get("verdict") != "pass":
        return linked
    return {
        "verdict": "pass",
        "evidencePath": str(path),
        "parentDecisionId": parent_decision_id,
        "record": record,
        "graph": linked.get("graph"),
    }
