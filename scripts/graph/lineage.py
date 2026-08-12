#!/usr/bin/env python3
"""Artifact lineage queries and non-destructive edge-reduction advice."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from graph.artifact_registry import ArtifactRegistry
from graph.typed_dataflow import TypedEdge


class LineageError(ValueError):
    """Raised when durable provenance is missing or internally inconsistent."""


@dataclass(frozen=True)
class LineageRecord:
    artifact_id: str
    producing_node: str
    model: str
    input_revision: str
    content_hash: str
    input_artifacts: tuple[str, ...]
    verification_evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifactId": self.artifact_id,
            "producingNode": self.producing_node,
            "model": self.model,
            "inputRevision": self.input_revision,
            "contentHash": self.content_hash,
            "inputArtifacts": list(self.input_artifacts),
            "verificationEvidence": list(self.verification_evidence),
        }


def _receipt_models(
    receipts: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[str, ...]]:
    models: dict[str, list[str]] = {}
    for receipt in receipts:
        node_id = receipt.get("nodeId")
        if not isinstance(node_id, str) or not node_id:
            raise LineageError("receipt is missing nodeId")
        model = receipt.get("model")
        if not isinstance(model, str) or not model:
            raise LineageError(f"receipt for {node_id} is missing model")
        models.setdefault(node_id, []).append(model)
    return {
        node_id: tuple(dict.fromkeys(values))
        for node_id, values in models.items()
    }


class ArtifactLineageView:
    """Join immutable artifact, typed-edge, and execution-receipt provenance."""

    def __init__(
        self,
        registry: ArtifactRegistry,
        edges: Iterable[TypedEdge],
        receipts: Iterable[Mapping[str, Any]],
    ) -> None:
        self._registry = registry
        self._edges = tuple(edges)
        self._models = _receipt_models(receipts)

    def query(self, artifact_id: str) -> LineageRecord:
        artifact = self._registry.read(artifact_id)
        models = self._models.get(artifact.producing_node, ())
        if not models:
            raise LineageError(
                f"no receipt model for producing node {artifact.producing_node}"
            )
        model = models[-1]
        inputs = tuple(
            dict.fromkeys(
                edge.artifact_id
                for edge in self._edges
                if edge.target == artifact.producing_node and edge.artifact_id
            )
        )
        return LineageRecord(
            artifact_id=artifact.artifact_id,
            producing_node=artifact.producing_node,
            model=model,
            input_revision=artifact.input_revision,
            content_hash=artifact.content_hash,
            input_artifacts=inputs,
            verification_evidence=artifact.verification_evidence,
        )

    def chain(self, artifact_id: str) -> tuple[LineageRecord, ...]:
        """Return a depth-first input-to-output chain, rejecting provenance cycles."""
        ordered: list[LineageRecord] = []
        visited: set[str] = set()
        active: set[str] = set()

        def visit(current_id: str) -> None:
            if current_id in active:
                raise LineageError(f"artifact lineage cycle at {current_id}")
            if current_id in visited:
                return
            active.add(current_id)
            record = self.query(current_id)
            for input_id in record.input_artifacts:
                visit(input_id)
            active.remove(current_id)
            visited.add(current_id)
            ordered.append(record)

        visit(artifact_id)
        return tuple(ordered)


def edge_reduction_advisory(
    edges: Iterable[TypedEdge],
    *,
    consumed_edge_ids: Iterable[str] = (),
    contention_relevant_edge_ids: Iterable[str] = (),
    kernel_required_edge_ids: Iterable[str] = (),
) -> tuple[dict[str, str], ...]:
    """Report possible reductions without mutating or authorizing edge deletion."""
    edge_list = tuple(edges)
    consumed = set(consumed_edge_ids)
    protected_contention = set(contention_relevant_edge_ids)
    protected_kernel = set(kernel_required_edge_ids)
    first_by_payload: dict[tuple[str, str, str, str, str], str] = {}
    advice: list[dict[str, str]] = []

    for edge in edge_list:
        protection = ""
        if edge.edge_id in protected_kernel:
            protection = "kernel-required"
        elif edge.edge_id in protected_contention:
            protection = "contention-relevant"

        signature = (
            edge.source,
            edge.target,
            edge.artifact_id,
            edge.schema,
            edge.selector,
        )
        duplicate_of = first_by_payload.get(signature)
        first_by_payload.setdefault(signature, edge.edge_id)

        reason = ""
        if not edge.artifact_id:
            reason = "edge carries no artifact"
        elif duplicate_of is not None:
            reason = f"duplicates artifact payload of {duplicate_of}"
        elif edge.edge_id not in consumed and not edge.required:
            reason = "optional artifact edge was not consumed"

        if protection:
            advice.append(
                {
                    "edgeId": edge.edge_id,
                    "reason": protection,
                    "recommendation": "keep",
                    "action": "advisory-only",
                }
            )
        elif reason:
            advice.append(
                {
                    "edgeId": edge.edge_id,
                    "reason": reason,
                    "recommendation": "review-for-removal",
                    "action": "advisory-only",
                }
            )
    return tuple(advice)
