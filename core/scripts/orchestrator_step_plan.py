#!/usr/bin/env python3
"""Load orchestrator-step-plan vocabulary + lint helpers (PRD 024 TR1, TR8)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from kernel_classification import normalize_step

ORCHESTRATOR_PLAN_REL = Path("core/sw-reference/orchestrator-step-plan.json")
SCHEMA_REL = Path("core/sw-reference/schemas/orchestrator-step-plan.schema.json")
VALID_ORCHESTRATOR_TYPES = frozenset({"debug", "doc", "feedback"})


def orchestrator_plan_path(root: Path) -> Path:
    return root / ORCHESTRATOR_PLAN_REL


@lru_cache(maxsize=8)
def _load_raw(path_str: str) -> dict[str, Any]:
    path = Path(path_str)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"orchestrator-step-plan must be an object: {path}")
    return data


def load_orchestrator_step_plan(root: Path) -> dict[str, Any]:
    path = orchestrator_plan_path(root)
    if not path.is_file():
        raise FileNotFoundError(f"missing orchestrator-step-plan: {path}")
    return _load_raw(str(path.resolve()))


def orchestrator_type_spec(root: Path, orchestrator_type: str) -> dict[str, Any]:
    data = load_orchestrator_step_plan(root)
    spec = (data.get("orchestratorTypes") or {}).get(orchestrator_type)
    if not isinstance(spec, dict):
        raise KeyError(f"unknown orchestrator type: {orchestrator_type!r}")
    return spec


def closed_world_vocabulary(root: Path, orchestrator_type: str) -> set[str]:
    spec = orchestrator_type_spec(root, orchestrator_type)
    return {normalize_step(str(s)) for s in spec.get("candidateSteps") or [] if isinstance(s, str)}


def canonical_orchestrator_chain(root: Path, orchestrator_type: str) -> list[str]:
    spec = orchestrator_type_spec(root, orchestrator_type)
    chain = spec.get("canonicalChain") or []
    return [normalize_step(str(s)) for s in chain if isinstance(s, str)]


def all_orchestrator_step_ids(root: Path) -> set[str]:
    """Candidate step ids that must appear in kernel planPolicySteps (forbidden steps excluded)."""
    data = load_orchestrator_step_plan(root)
    ids: set[str] = set()
    for spec in (data.get("orchestratorTypes") or {}).values():
        if not isinstance(spec, dict):
            continue
        for step in spec.get("candidateSteps") or []:
            if isinstance(step, str):
                ids.add(normalize_step(step))
    return ids


def validate_ordering_invariants(steps: list[str], invariants: list[dict[str, Any]]) -> list[str]:
    reasons: list[str] = []
    positions = {step: idx for idx, step in enumerate(steps)}
    for raw in invariants:
        if not isinstance(raw, dict):
            continue
        before = raw.get("before")
        after = raw.get("after")
        if not isinstance(before, str) or not isinstance(after, str):
            continue
        b, a = normalize_step(before), normalize_step(after)
        if b not in positions or a not in positions:
            continue
        if positions[b] >= positions[a]:
            reasons.append(f"ordering invariant violated: {b} must precede {a}")
    return reasons


def lint_orchestrator_kernel_completeness(root: Path) -> tuple[bool, list[str]]:
    """Ensure every orchestrator candidate step is classified in kernel planPolicySteps."""
    from kernel_classification import classified_step_ids, load_classification

    classification = load_classification(root)
    classified = classified_step_ids(classification)
    missing = sorted(step for step in all_orchestrator_step_ids(root) if step not in classified)
    return (len(missing) == 0, missing)
