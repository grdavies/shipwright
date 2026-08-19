"""Human-action receipt envelope validation (PRD 280 R12/R14/D3)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from decision_graph.human_action import HUMAN_ACTION_KIND, is_human_action_node

RECEIPT_API_VERSION = "decision-graph-receipt/v1"
RECEIPT_STATUSES = frozenset({"pending", "verified", "rejected"})


class ReceiptValidationError(ValueError):
    """Raised when a receipt envelope fails validation."""


@dataclass(frozen=True)
class ReceiptEnvelope:
    """Hash-linked human-action completion receipt (phase-1 hash + actor)."""

    node_id: str
    actor: str
    content_hash: str
    status: str
    attested_at: str
    outcome: str = ""
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "apiVersion": RECEIPT_API_VERSION,
            "nodeId": self.node_id,
            "actor": self.actor,
            "contentHash": self.content_hash,
            "status": self.status,
            "attestedAt": self.attested_at,
        }
        if self.outcome:
            payload["outcome"] = self.outcome
        if self.rationale:
            payload["rationale"] = self.rationale
        return payload


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_content_hash(payload: Mapping[str, Any]) -> str:
    """Deterministic SHA-256 over canonical receipt body fields."""
    body = {
        "nodeId": str(payload.get("nodeId") or ""),
        "outcome": str(payload.get("outcome") or ""),
        "rationale": str(payload.get("rationale") or ""),
    }
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def build_receipt_envelope(
    *,
    node_id: str,
    actor: str,
    outcome: str,
    rationale: str = "",
    status: str = "verified",
    attested_at: str | None = None,
) -> ReceiptEnvelope:
    content_hash = compute_content_hash(
        {"nodeId": node_id, "outcome": outcome, "rationale": rationale}
    )
    return ReceiptEnvelope(
        node_id=node_id,
        actor=actor.strip(),
        content_hash=content_hash,
        status=status,
        attested_at=attested_at or utc_now(),
        outcome=outcome,
        rationale=rationale,
    )


def parse_receipt_envelope(document: Mapping[str, Any]) -> ReceiptEnvelope:
    node_id = str(document.get("nodeId") or "")
    actor = str(document.get("actor") or "").strip()
    content_hash = str(document.get("contentHash") or "")
    status = str(document.get("status") or "")
    attested_at = str(document.get("attestedAt") or "")
    if not node_id or not actor or not content_hash or not attested_at:
        raise ReceiptValidationError("receipt missing required fields")
    if status not in RECEIPT_STATUSES:
        raise ReceiptValidationError(f"invalid receipt status: {status!r}")
    return ReceiptEnvelope(
        node_id=node_id,
        actor=actor,
        content_hash=content_hash,
        status=status,
        attested_at=attested_at,
        outcome=str(document.get("outcome") or ""),
        rationale=str(document.get("rationale") or ""),
    )


def validate_receipt(
    document: Mapping[str, Any],
    *,
    expected_node_id: str | None = None,
) -> dict[str, Any]:
    """Validate a receipt envelope; returns pass/fail JSON."""
    try:
        envelope = parse_receipt_envelope(document)
    except ReceiptValidationError as exc:
        return {"verdict": "fail", "code": "receipt:invalid-envelope", "message": str(exc)}

    if expected_node_id is not None and envelope.node_id != expected_node_id:
        return {
            "verdict": "fail",
            "code": "receipt:node-mismatch",
            "message": f"expected node {expected_node_id!r}, got {envelope.node_id!r}",
        }

    expected_hash = compute_content_hash(
        {
            "nodeId": envelope.node_id,
            "outcome": envelope.outcome,
            "rationale": envelope.rationale,
        }
    )
    if envelope.content_hash != expected_hash:
        return {
            "verdict": "fail",
            "code": "receipt:hash-mismatch",
            "message": "content hash does not match receipt body",
        }

    if envelope.status != "verified":
        return {
            "verdict": "fail",
            "code": "receipt:not-verified",
            "message": f"receipt status is {envelope.status!r}",
        }

    if not envelope.actor:
        return {
            "verdict": "fail",
            "code": "receipt:missing-actor",
            "message": "actor attestation required",
        }

    return {"verdict": "pass", "receipt": envelope.as_dict()}


def _node_index(graph: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    spec = graph.get("spec")
    if not isinstance(spec, Mapping):
        return {}
    nodes = spec.get("nodes")
    if not isinstance(nodes, list):
        return {}
    indexed: dict[str, dict[str, Any]] = {}
    for node in nodes:
        if isinstance(node, Mapping) and isinstance(node.get("id"), str):
            indexed[node["id"]] = dict(node)
    return indexed


def _predecessors(graph: Mapping[str, Any]) -> dict[str, set[str]]:
    nodes = _node_index(graph)
    preds: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    spec = graph.get("spec")
    if not isinstance(spec, Mapping):
        return preds
    edges = spec.get("edges")
    if not isinstance(edges, list):
        return preds
    for edge in edges:
        if not isinstance(edge, Mapping):
            continue
        from_id = edge.get("from")
        to_id = edge.get("to")
        if isinstance(from_id, str) and isinstance(to_id, str) and to_id in preds:
            preds[to_id].add(from_id)
    return preds


def human_action_requires_receipt(node: Mapping[str, Any]) -> bool:
    if not is_human_action_node(node):
        return False
    status = str(node.get("status") or "open")
    return status == "open"


def receipt_blocks_node(
    node: Mapping[str, Any],
    receipts_by_node: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Return True when an open human-action node lacks a verified receipt."""
    if not human_action_requires_receipt(node):
        return False
    node_id = str(node.get("id") or "")
    receipt = receipts_by_node.get(node_id)
    if receipt is None:
        return True
    return validate_receipt(receipt, expected_node_id=node_id).get("verdict") != "pass"


def blocked_dependents(
    graph: Mapping[str, Any],
    receipts_by_node: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """Return node ids that cannot advance because a predecessor lacks a receipt."""
    nodes = _node_index(graph)
    preds = _predecessors(graph)
    blocked: list[str] = []
    for node_id, node in nodes.items():
        for pred_id in sorted(preds.get(node_id, ())):
            pred = nodes.get(pred_id)
            if pred is None:
                continue
            if receipt_blocks_node(pred, receipts_by_node):
                blocked.append(node_id)
                break
    return blocked


def admission_allowed(
    graph: Mapping[str, Any],
    node_id: str,
    receipts_by_node: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Frontier admission check for a candidate node id."""
    nodes = _node_index(graph)
    node = nodes.get(node_id)
    if node is None:
        return {"verdict": "fail", "code": "frontier:unknown-node", "nodeId": node_id}

    for pred_id in sorted(_predecessors(graph).get(node_id, ())):
        pred = nodes.get(pred_id)
        if pred is None:
            continue
        if receipt_blocks_node(pred, receipts_by_node):
            return {
                "verdict": "fail",
                "code": "frontier:blocked-by-receipt",
                "nodeId": node_id,
                "blockedBy": pred_id,
                "blockedKind": str(pred.get("kind") or ""),
            }

    if receipt_blocks_node(node, receipts_by_node):
        return {
            "verdict": "fail",
            "code": "frontier:receipt-required",
            "nodeId": node_id,
        }

    return {"verdict": "pass", "nodeId": node_id}
