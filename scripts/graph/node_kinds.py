"""WorkflowGraph node kind registry (PRD 280 R13)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

HUMAN_ACTION_KIND = "human-action"

# Converge phase (PRD 342 R55) compiles onto existing closed kinds only.
# Assessor → read-only gate; phase body → command. Never map converge onto the
# pre-existing execution-retry kind (convergence-loop).
CONVERGE_ASSESSOR_KIND = "gate"
CONVERGE_PHASE_BODY_KIND = "command"
CONVERGE_FORBIDDEN_RETRY_KIND = "convergence-loop"

BASE_WORKFLOW_NODE_KINDS = frozenset(
    {
        "barrier",
        "command",
        "convergence-loop",
        "gate",
        "router",
        "transform",
        "verifier",
    }
)

CLOSED_NODE_KINDS = BASE_WORKFLOW_NODE_KINDS | {HUMAN_ACTION_KIND}


@dataclass(frozen=True)
class NodeKindSpec:
    """Closed-world metadata for a WorkflowGraph node kind."""

    id: str
    shadow_policy: str
    await_human: bool = False
    read_only: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "shadowPolicy": self.shadow_policy,
            "awaitHuman": self.await_human,
            "readOnly": self.read_only,
        }


NODE_KIND_REGISTRY: dict[str, NodeKindSpec] = {
    "barrier": NodeKindSpec("barrier", "read-only", read_only=True),
    "command": NodeKindSpec("command", "mutating"),
    "convergence-loop": NodeKindSpec("convergence-loop", "mutating"),
    "gate": NodeKindSpec("gate", "read-only", read_only=True),
    "router": NodeKindSpec("router", "read-only", read_only=True),
    "transform": NodeKindSpec("transform", "read-only", read_only=True),
    "verifier": NodeKindSpec("verifier", "read-only", read_only=True),
    HUMAN_ACTION_KIND: NodeKindSpec(
        HUMAN_ACTION_KIND,
        "read-only",
        await_human=True,
        read_only=True,
    ),
}


def is_closed_node_kind(kind: str) -> bool:
    return kind in CLOSED_NODE_KINDS


def lookup_node_kind(kind: str) -> NodeKindSpec | None:
    return NODE_KIND_REGISTRY.get(kind)


def is_human_action_kind(kind: str) -> bool:
    return kind == HUMAN_ACTION_KIND


def node_awaits_human(node: Mapping[str, Any]) -> bool:
    kind = str(node.get("kind") or "")
    spec = lookup_node_kind(kind)
    return bool(spec and spec.await_human)


def kernel_node_kinds_payload() -> list[dict[str, str]]:
    """Projection shape for kernel-classification graphNodeKinds."""
    return [
        {"id": spec.id, "shadowPolicy": spec.shadow_policy}
        for spec in sorted(NODE_KIND_REGISTRY.values(), key=lambda item: item.id)
    ]


def converge_compile_kinds() -> dict[str, str]:
    """Kinds used when compiling the opt-in converge phase (PRD 342 R55)."""
    return {
        "assessor": CONVERGE_ASSESSOR_KIND,
        "phaseBody": CONVERGE_PHASE_BODY_KIND,
        "forbiddenRetryKind": CONVERGE_FORBIDDEN_RETRY_KIND,
    }
