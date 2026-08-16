#!/usr/bin/env python3
"""PRD 272 phase-3 absolute floor and promotion anti-ratchet tests (R9)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
_REPO_ROOT = _SCRIPTS.parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.absolute_floor import (  # noqa: E402
    AbsoluteFloorError,
    apply_optimization_profile,
    assert_anti_ratchet_ceiling,
    enforce_absolute_floor,
    evaluate_after_profile_and_inject,
)
from graph.detectors.registry import (  # noqa: E402
    CAPABILITY_AUTH,
    CAPABILITY_STANDARD_REVIEW,
)
from graph.workflow_library import (  # noqa: E402
    WorkflowLibraryError,
    apply_profile_to_required_capabilities,
    assert_promotion_anti_ratchet,
    required_capabilities_from_graph,
)


def _node(node_id: str, kind: str = "command") -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "target": {"step": f"sw-{node_id}"},
        "resources": {
            "pool": "code-writers",
            "slots": 1,
            "timeoutSeconds": 30,
        },
        "isolation": {"mode": "worktree", "writeScope": "worktree"},
        "verification": {"required": True, "strategy": "mechanical"},
    }


def _auth_graph(*cap_ids: str) -> dict[str, Any]:
    nodes = [_node("prepare")]
    edges: list[dict[str, Any]] = []
    previous = "prepare"
    for index, cap_id in enumerate(cap_ids):
        node_id = f"cap-{index}"
        nodes.append(
            {
                **_node(node_id, "verifier"),
                "metadata": {"requiredCapabilityId": cap_id},
                "target": {"step": f"sw-verify-{index}"},
            }
        )
        edges.append({"from": previous, "to": node_id, "required": True})
        previous = node_id
    nodes.extend(
        [
            _node("merge-gate", "gate"),
            _node("credential-broker"),
            _node("write-isolation-lease"),
        ]
    )
    edges.extend(
        [
            {"from": previous, "to": "merge-gate", "required": True},
            {"from": "merge-gate", "to": "credential-broker", "required": True},
            {"from": "credential-broker", "to": "write-isolation-lease", "required": True},
        ]
    )
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "absolute-floor-fixture"},
        "spec": {
            "nodes": nodes,
            "edges": edges,
            "resourceLimits": {
                "maxConcurrency": 2,
                "maxDurationSeconds": 120,
            },
            "verification": {"required": True, "failClosed": True},
        },
    }


def test_absolute_floor_and_anti_ratchet_ceiling() -> None:
    injected = frozenset({CAPABILITY_AUTH, CAPABILITY_STANDARD_REVIEW})
    fast_adjusted = apply_optimization_profile(injected, "fast")
    assert CAPABILITY_STANDARD_REVIEW not in fast_adjusted

    with pytest.raises(AbsoluteFloorError, match="cannot lower absolute floor"):
        evaluate_after_profile_and_inject(
            injected_capability_ids=injected,
            profile="fast",
            repo_root=_REPO_ROOT,
        )

    adjusted = evaluate_after_profile_and_inject(
        injected_capability_ids=injected,
        profile="balanced",
        repo_root=_REPO_ROOT,
    )
    assert CAPABILITY_AUTH in adjusted

    with pytest.raises(WorkflowLibraryError, match="cannot lower absolute floor"):
        apply_profile_to_required_capabilities(
            injected_capability_ids=injected,
            profile="fast",
            root=_REPO_ROOT,
        )


def test_promotion_anti_ratchet_blocks_capability_regression() -> None:
    pinned = _auth_graph(CAPABILITY_AUTH, CAPABILITY_STANDARD_REVIEW)
    candidate = _auth_graph(CAPABILITY_AUTH)
    assert CAPABILITY_STANDARD_REVIEW in required_capabilities_from_graph(pinned)
    assert CAPABILITY_STANDARD_REVIEW not in required_capabilities_from_graph(candidate)

    with pytest.raises(AbsoluteFloorError, match="anti-ratchet"):
        assert_anti_ratchet_ceiling(
            pinned_reference=required_capabilities_from_graph(pinned),
            candidate=required_capabilities_from_graph(candidate),
            repo_root=_REPO_ROOT,
        )

    with pytest.raises(WorkflowLibraryError, match="anti-ratchet"):
        assert_promotion_anti_ratchet(
            pinned_reference_graph=pinned,
            candidate_graph=candidate,
            root=_REPO_ROOT,
        )

    enforce_absolute_floor(
        injected_capability_ids=frozenset({CAPABILITY_AUTH}),
        profile_adjusted_capability_ids=frozenset({CAPABILITY_AUTH}),
        profile="balanced",
        repo_root=_REPO_ROOT,
    )
