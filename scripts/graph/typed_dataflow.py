#!/usr/bin/env python3
"""Typed artifact edges and least-context node dispatch."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from graph.artifact_registry import ArtifactRegistry


class DataflowError(ValueError):
    """Raised when a required typed input cannot be resolved safely."""


@dataclass(frozen=True)
class TypedEdge:
    edge_id: str
    source: str
    target: str
    artifact_id: str
    schema: str
    selector: str = ""
    required: bool = True


@dataclass(frozen=True)
class DispatchContext:
    node_id: str
    inputs: Mapping[str, Any]
    artifact_hashes: Mapping[str, str]


def _select(content: Any, selector: str) -> Any:
    if not selector:
        return content
    current = content
    parts = selector.split("/")[1:] if selector.startswith("/") else selector.split(".")
    for raw_part in parts:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        try:
            current = current[int(part)] if isinstance(current, list) else current[part]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DataflowError(f"selector {selector!r} did not match artifact") from exc
    return current


def build_dispatch_context(
    node_id: str,
    edges: Iterable[TypedEdge],
    registry: ArtifactRegistry,
) -> DispatchContext:
    """Resolve only edges declared for this node, failing closed on required gaps."""
    inputs: dict[str, Any] = {}
    hashes: dict[str, str] = {}
    for edge in edges:
        if edge.target != node_id:
            continue
        try:
            artifact = registry.read(edge.artifact_id)
        except KeyError:
            if edge.required:
                raise DataflowError(
                    f"required artifact {edge.artifact_id!r} is missing for {node_id}"
                ) from None
            continue
        if artifact.schema != edge.schema:
            raise DataflowError(
                f"artifact {edge.artifact_id!r} schema mismatch: "
                f"expected {edge.schema!r}, got {artifact.schema!r}"
            )
        inputs[edge.edge_id] = _select(artifact.content, edge.selector)
        hashes[edge.edge_id] = artifact.content_hash
    return DispatchContext(node_id=node_id, inputs=inputs, artifact_hashes=hashes)


def unnecessary_edge_report(
    edges: Iterable[TypedEdge],
    consumed_edge_ids: Iterable[str],
) -> tuple[dict[str, str], ...]:
    """Return an advisory only; the caller's edge collection is never mutated."""
    consumed = set(consumed_edge_ids)
    return tuple(
        {
            "edgeId": edge.edge_id,
            "source": edge.source,
            "target": edge.target,
            "reason": "declared edge was not consumed",
            "action": "review-only",
        }
        for edge in edges
        if edge.edge_id not in consumed and not edge.required
    )
