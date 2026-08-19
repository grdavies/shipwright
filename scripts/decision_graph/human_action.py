"""Human-action node helpers and procedure template generation (PRD 280 R11)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from decision_graph.schema import NodeKind

HUMAN_ACTION_KIND = NodeKind.HUMAN_ACTION.value


@dataclass(frozen=True)
class HumanActionProcedure:
    """Normalized human-action procedure derived from a graph node."""

    node_id: str
    title: str
    steps: tuple[str, ...]
    artifacts: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "nodeId": self.node_id,
            "title": self.title,
            "steps": list(self.steps),
            "artifacts": list(self.artifacts),
        }


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def parse_human_action_node(node: Mapping[str, Any]) -> HumanActionProcedure:
    """Parse a DecisionGraph or WorkflowGraph human-action node."""
    node_id = str(node.get("id") or "")
    title = str(node.get("title") or "").strip()
    if not title:
        raise ValueError("human-action node requires title")

    procedure = node.get("procedure")
    steps: list[str] = []
    artifacts: list[str] = []
    if isinstance(procedure, Mapping):
        steps = _coerce_str_list(procedure.get("steps"))
        artifacts = _coerce_str_list(procedure.get("artifacts"))
    else:
        target = node.get("target")
        if isinstance(target, Mapping):
            data = target.get("data")
            if isinstance(data, Mapping):
                procedure_data = data.get("procedure")
                if isinstance(procedure_data, Mapping):
                    steps = _coerce_str_list(procedure_data.get("steps"))
                    artifacts = _coerce_str_list(procedure_data.get("artifacts"))

    if not steps:
        steps = [f"Complete: {title}"]

    return HumanActionProcedure(
        node_id=node_id,
        title=title,
        steps=tuple(steps),
        artifacts=tuple(artifacts),
    )


def render_procedure_markdown(node: Mapping[str, Any]) -> str:
    """Emit an operator-facing markdown procedure from a human-action node spec."""
    procedure = parse_human_action_node(node)
    lines = [
        f"# Human action: {procedure.title}",
        "",
        f"**Node:** `{procedure.node_id or 'unknown'}`",
        "",
        "## Steps",
        "",
    ]
    for index, step in enumerate(procedure.steps, start=1):
        lines.append(f"{index}. {step}")
    lines.append("")
    if procedure.artifacts:
        lines.extend(["## Artifacts", ""])
        for artifact in procedure.artifacts:
            lines.append(f"- {artifact}")
        lines.append("")
    lines.extend(
        [
            "## Receipt",
            "",
            "Record completion with actor attestation via `decision_graph.receipt`.",
            "",
        ]
    )
    return "\n".join(lines)


def is_human_action_node(node: Mapping[str, Any]) -> bool:
    return str(node.get("kind") or "") == HUMAN_ACTION_KIND
