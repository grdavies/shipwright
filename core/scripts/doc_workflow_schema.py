#!/usr/bin/env python3
"""Executable doc-loop stage schema + sw-doc doc generation (PRD 090 R4)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from doc_loop import (
    AGENT_STAGES,
    DOC_STAGE_SEQUENCE,
    HUMAN_STAGES,
    MECHANICAL_STAGES,
    TERMINAL_STAGES,
    UNREACHABLE_PUBLICATION_STAGES,
    next_stage_after,
    stage_skipped,
)

SW_DOC_REL = Path("core/commands/sw-doc.md")
TRANSITIONS_REL = Path("core/sw-reference/doc-workflow-transitions.json")

STAGE_TABLE_MARKER_START = "<!-- doc-stage-table:begin -->"
STAGE_TABLE_MARKER_END = "<!-- doc-stage-table:end -->"
STAGE_ORDER_MARKER_START = "<!-- doc-stage-order:begin -->"
STAGE_ORDER_MARKER_END = "<!-- doc-stage-order:end -->"

# Orchestrator guideline-pack steps that map to doc_loop driver stage ids (R4 drift fix).
ORCHESTRATOR_TO_DRIVER_STAGE: dict[str, str] = {
    "sw-triage": "triage",
    "sw-brainstorm": "brainstorm",
    "sw-prd": "prd",
    "sw-doc-review": "doc-review",
    "sw-freeze": "freeze-prd",
    "sw-tasks": "tasks",
}

DRIVER_TO_ORCHESTRATOR_STAGE: dict[str, str] = {
    driver: orch for orch, driver in ORCHESTRATOR_TO_DRIVER_STAGE.items()
}

STAGE_CATEGORY: dict[str, str] = {}
for _stage in AGENT_STAGES:
    STAGE_CATEGORY[_stage] = "agent"
for _stage in MECHANICAL_STAGES:
    STAGE_CATEGORY[_stage] = "mechanical"
for _stage in HUMAN_STAGES:
    STAGE_CATEGORY[_stage] = "human"
for _stage in TERMINAL_STAGES:
    STAGE_CATEGORY[_stage] = "terminal"
for _stage in UNREACHABLE_PUBLICATION_STAGES:
    STAGE_CATEGORY[_stage] = "unreachable"

STAGE_TIER_NOTES: dict[str, str] = {
    "brainstorm": "Full tier only",
    "related-work-checkpoint": "Human halt when related work pending",
    "afterTasks-checkpoint": "Human halt before implementation dispatch",
    "docs-commit": "Unreachable from driver",
    "docs-pr": "Unreachable from driver",
}


def repo_root(start: Path | None = None) -> Path:
    return (start or Path.cwd()).resolve()


def mock_state(tier: str = "Standard") -> dict[str, Any]:
    return {"tier": tier, "runId": "schema-fixture"}


def stage_category(stage: str) -> str:
    if stage in STAGE_CATEGORY:
        return STAGE_CATEGORY[stage]
    if stage in DOC_STAGE_SEQUENCE:
        return "driver"
    return "unknown"


def schema_stages() -> list[str]:
    return list(DOC_STAGE_SEQUENCE)


def transitions_for_tier(tier: str) -> dict[str, list[str]]:
    state = mock_state(tier)
    edges: dict[str, list[str]] = {}
    for stage in DOC_STAGE_SEQUENCE:
        if stage_skipped(state, stage):
            continue
        nxt = next_stage_after(state, stage)
        edges[stage] = [nxt] if nxt else []
    if "related-work-checkpoint" not in edges:
        edges["related-work-checkpoint"] = ["related-work"]
    return edges


def build_schema() -> dict[str, Any]:
    return {
        "version": 1,
        "source": "scripts/doc_loop.py",
        "stageSequence": schema_stages(),
        "stageCategories": {
            "agent": sorted(AGENT_STAGES),
            "mechanical": sorted(MECHANICAL_STAGES),
            "human": sorted(HUMAN_STAGES),
            "terminal": sorted(TERMINAL_STAGES),
            "unreachable": sorted(UNREACHABLE_PUBLICATION_STAGES),
        },
        "orchestratorToDriverStage": dict(ORCHESTRATOR_TO_DRIVER_STAGE),
        "transitions": {
            "Standard": transitions_for_tier("Standard"),
            "Full": transitions_for_tier("Full"),
        },
    }


def render_stage_order_prose(tier: str = "Standard") -> str:
    state = mock_state(tier)
    parts: list[str] = []
    for stage in DOC_STAGE_SEQUENCE:
        if stage_skipped(state, stage):
            continue
        parts.append(stage)
    body = " → ".join(parts)
    return f"{STAGE_ORDER_MARKER_START}\n{body}\n{STAGE_ORDER_MARKER_END}"


def render_stage_table() -> str:
    rows = [
        "| Stage | Category | Tier / halt |",
        "| --- | --- | --- |",
    ]
    state = mock_state("Standard")
    for stage in DOC_STAGE_SEQUENCE:
        if stage_skipped(state, stage):
            tier_note = STAGE_TIER_NOTES.get(stage, "Full tier only (skipped for Standard)")
        else:
            tier_note = STAGE_TIER_NOTES.get(stage, "—")
        rows.append(f"| `{stage}` | {stage_category(stage)} | {tier_note} |")
    for stage in sorted(HUMAN_STAGES):
        if stage in DOC_STAGE_SEQUENCE:
            continue
        tier_note = STAGE_TIER_NOTES.get(stage, "Human halt")
        rows.append(f"| `{stage}` | {stage_category(stage)} | {tier_note} |")
    body = "\n".join(rows)
    return f"{STAGE_TABLE_MARKER_START}\n{body}\n{STAGE_TABLE_MARKER_END}"


def sync_sw_doc_markers(root: Path) -> bool:
    cmd_path = root / SW_DOC_REL
    if not cmd_path.is_file():
        return False
    text = cmd_path.read_text(encoding="utf-8")
    updated = text
    order_block = render_stage_order_prose()
    table_block = render_stage_table()
    for start, end, block in (
        (STAGE_ORDER_MARKER_START, STAGE_ORDER_MARKER_END, order_block),
        (STAGE_TABLE_MARKER_START, STAGE_TABLE_MARKER_END, table_block),
    ):
        if start in updated and end in updated:
            pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
            updated = pattern.sub(block, updated, count=1)
    if updated != text:
        cmd_path.write_text(updated, encoding="utf-8")
        return True
    return False


def write_transitions_json(root: Path) -> Path:
    out = root / TRANSITIONS_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = build_schema()
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def check_sw_doc_parity(root: Path) -> tuple[bool, list[str]]:
    cmd_path = root / SW_DOC_REL
    if not cmd_path.is_file():
        return False, [f"missing {SW_DOC_REL}"]
    text = cmd_path.read_text(encoding="utf-8")
    reasons: list[str] = []
    if render_stage_order_prose() not in text:
        reasons.append("sw-doc.md doc-stage-order block drift from doc_workflow_schema")
    if render_stage_table() not in text:
        reasons.append("sw-doc.md doc-stage-table block drift from doc_workflow_schema")
    return (len(reasons) == 0, reasons)


def normalize_orchestrator_step(step: str) -> str:
    return ORCHESTRATOR_TO_DRIVER_STAGE.get(step, step)


def normalize_orchestrator_steps(steps: list[str]) -> list[str]:
    return [normalize_orchestrator_step(s) for s in steps]


def lint_guideline_pack_stage_ids(pack: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for key in ("canonicalFallbackChain", "candidateSteps", "requiredSteps", "optionalSteps"):
        for step in pack.get(key) or []:
            if not isinstance(step, str):
                continue
            if step in ORCHESTRATOR_TO_DRIVER_STAGE:
                reasons.append(f"{key} uses legacy orchestrator id {step!r}; expected {ORCHESTRATOR_TO_DRIVER_STAGE[step]!r}")
    for block in pack.get("forbiddenDeviations") or []:
        if not isinstance(block, dict):
            continue
        for field in ("omitStep", "reorderBefore", "reorderAfter"):
            val = block.get(field)
            if isinstance(val, str) and val in ORCHESTRATOR_TO_DRIVER_STAGE:
                reasons.append(
                    f"forbiddenDeviations references legacy id {val!r}; expected {ORCHESTRATOR_TO_DRIVER_STAGE[val]!r}"
                )
    for floor in pack.get("signalConditionalFloors") or []:
        if not isinstance(floor, dict):
            continue
        for step in floor.get("mandatorySteps") or []:
            if isinstance(step, str) and step in ORCHESTRATOR_TO_DRIVER_STAGE:
                reasons.append(
                    f"signalConditionalFloors references legacy id {step!r}; expected {ORCHESTRATOR_TO_DRIVER_STAGE[step]!r}"
                )
    return (len(reasons) == 0, reasons)


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Doc workflow schema sync and lint (PRD 090 R4)")
    parser.add_argument("command", choices=["sync", "check", "emit", "lint-pack"])
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--pack", type=Path, default=None, help="guideline pack JSON for lint-pack")
    args = parser.parse_args(argv)
    root = repo_root(args.root or SCRIPT_DIR.parent)

    if args.command == "emit":
        emit(build_schema())
    if args.command == "sync":
        changed = sync_sw_doc_markers(root)
        transitions_path = write_transitions_json(root)
        emit({"verdict": "pass", "changed": changed, "transitionsPath": str(transitions_path.relative_to(root))})
    if args.command == "check":
        ok_doc, doc_reasons = check_sw_doc_parity(root)
        transitions_path = root / TRANSITIONS_REL
        ok_json = transitions_path.is_file()
        reasons = list(doc_reasons)
        if not ok_json:
            reasons.append(f"missing {TRANSITIONS_REL}")
        elif json.loads(transitions_path.read_text(encoding="utf-8")) != build_schema():
            reasons.append(f"{TRANSITIONS_REL} drift from doc_workflow_schema")
        emit({"verdict": "pass" if ok_doc and ok_json and not reasons else "fail", "reasons": reasons})
    if args.command == "lint-pack":
        pack_path = args.pack or root / "core/sw-reference/guidelines/doc.pack.json"
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        ok, reasons = lint_guideline_pack_stage_ids(pack)
        emit({"verdict": "pass" if ok else "fail", "path": str(pack_path), "reasons": reasons})
    return 0


if __name__ == "__main__":
    main()
