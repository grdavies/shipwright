#!/usr/bin/env python3
"""Expansion tuple approval for kernel compile (PRD 272 R22)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

DEFAULT_KERNEL_VERSION = "1.0.0"


class ExpansionApprovalError(RuntimeError):
    """Raised when expansion approval is missing or stale."""


@dataclass(frozen=True)
class ExpansionTuple:
    pack_digest: str
    profile_id: str
    requirement_set_digest: str
    kernel_version: str

    def to_dict(self) -> dict[str, str]:
        return {
            "packDigest": self.pack_digest,
            "profileId": self.profile_id,
            "requirementSetDigest": self.requirement_set_digest,
            "kernelVersion": self.kernel_version,
        }


@dataclass(frozen=True)
class ExpansionApproval:
    tuple_digest: str
    approved_by: str
    approved_at: str
    tuple: ExpansionTuple

    def to_dict(self) -> dict[str, Any]:
        return {
            "approved": True,
            "tupleDigest": self.tuple_digest,
            "approvedBy": self.approved_by,
            "approvedAt": self.approved_at,
            "expansionTuple": self.tuple.to_dict(),
        }


def compute_expansion_tuple_digest(expansion_tuple: ExpansionTuple) -> str:
    """Pure digest over (pack, profile, reqSet, kernel) (R22)."""
    canonical = (
        json.dumps(
            expansion_tuple.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def approve_expansion_tuple(
    expansion_tuple: ExpansionTuple,
    *,
    approved_by: str,
    approved_at: str,
) -> ExpansionApproval:
    if not approved_by or not approved_at:
        raise ExpansionApprovalError("approval actor and timestamp are required")
    digest = compute_expansion_tuple_digest(expansion_tuple)
    return ExpansionApproval(
        tuple_digest=digest,
        approved_by=approved_by,
        approved_at=approved_at,
        tuple=expansion_tuple,
    )


def assert_expansion_approved(
    approval: Mapping[str, Any] | None,
    expansion_tuple: ExpansionTuple,
) -> ExpansionApproval:
    if not isinstance(approval, Mapping) or approval.get("approved") is not True:
        raise ExpansionApprovalError("expansion tuple approval required before compile")
    expected = compute_expansion_tuple_digest(expansion_tuple)
    if str(approval.get("tupleDigest") or "") != expected:
        raise ExpansionApprovalError("expansion tuple changed after approval")
    tuple_body = approval.get("expansionTuple")
    if not isinstance(tuple_body, Mapping):
        raise ExpansionApprovalError("expansion approval missing tuple body")
    recorded = ExpansionTuple(
        pack_digest=str(tuple_body.get("packDigest") or ""),
        profile_id=str(tuple_body.get("profileId") or ""),
        requirement_set_digest=str(tuple_body.get("requirementSetDigest") or ""),
        kernel_version=str(tuple_body.get("kernelVersion") or DEFAULT_KERNEL_VERSION),
    )
    if recorded != expansion_tuple:
        raise ExpansionApprovalError("expansion tuple body mismatch")
    return ExpansionApproval(
        tuple_digest=expected,
        approved_by=str(approval.get("approvedBy") or ""),
        approved_at=str(approval.get("approvedAt") or ""),
        tuple=recorded,
    )


def _node_signature(node: Mapping[str, Any]) -> tuple[str, str, bool, str]:
    verification = node.get("verification") or {}
    target = node.get("target") or {}
    return (
        str(node.get("id") or ""),
        str(node.get("kind") or ""),
        bool(verification.get("required")),
        str(target.get("step") or ""),
    )


def expansion_is_additive(
    baseline_nodes: Sequence[Mapping[str, Any]],
    expanded_nodes: Sequence[Mapping[str, Any]],
) -> bool:
    """Detector-injected required capabilities may only add nodes (R22)."""
    baseline = {_node_signature(node) for node in baseline_nodes}
    expanded = {_node_signature(node) for node in expanded_nodes}
    return baseline.issubset(expanded)


def expansion_requires_reapproval(
    baseline_nodes: Sequence[Mapping[str, Any]],
    expanded_nodes: Sequence[Mapping[str, Any]],
) -> bool:
    """Any removal or weakening relative to the approved expansion needs re-approval."""
    return not expansion_is_additive(baseline_nodes, expanded_nodes)


def record_expansion_tuple_on_receipt(
    receipt: Mapping[str, Any],
    approval: ExpansionApproval,
) -> dict[str, Any]:
    """Attach resolved expansion tuple to the run receipt (R22)."""
    updated = dict(receipt)
    updated["expansionTuple"] = approval.tuple.to_dict()
    updated["expansionTupleDigest"] = approval.tuple_digest
    updated["expansionApprovedBy"] = approval.approved_by
    updated["expansionApprovedAt"] = approval.approved_at
    return updated
