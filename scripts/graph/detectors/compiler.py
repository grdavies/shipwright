#!/usr/bin/env python3
"""Compile detector injections to verification nodes/fragments (PRD 272 R2/R6)."""
from __future__ import annotations

from typing import Any

from graph.detectors.registry import capability_verification_step
from graph.detectors.result import DetectorResult, union_required_capability_ids


def compile_verification_nodes(
    results: tuple[DetectorResult, ...],
) -> list[dict[str, Any]]:
    """Compile required capabilities into concrete verifier node fragments."""
    capability_ids = union_required_capability_ids(results)
    nodes: list[dict[str, Any]] = []
    for capability_id in capability_ids:
        step = capability_verification_step(capability_id)
        node_id = f"detector-req-{capability_id.rsplit('.', 1)[-1]}"
        nodes.append(
            {
                "id": node_id,
                "kind": "verifier",
                "target": {"step": step},
                "metadata": {
                    "requiredCapabilityId": capability_id,
                    "source": "detector-injection",
                },
                "resources": {
                    "pool": "verifiers",
                    "slots": 1,
                    "timeoutSeconds": 600,
                },
                "isolation": {"mode": "process", "writeScope": "read-only"},
                "verification": {"required": True, "strategy": "evidence"},
            }
        )
    return nodes


def attach_injection_metadata(
    graph: dict[str, Any],
    results: tuple[DetectorResult, ...],
) -> dict[str, Any]:
    """Attach typed requiredCapabilityIds and detector evidence to graph metadata."""
    metadata = dict(graph.get("metadata") or {})
    metadata["requiredCapabilityIds"] = list(union_required_capability_ids(results))
    metadata["detectorResults"] = [result.to_dict() for result in results]
    graph = dict(graph)
    graph["metadata"] = metadata
    return graph
