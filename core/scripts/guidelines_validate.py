#!/usr/bin/env python3
"""Guidelines artifact validation — shared harness with capability manifest lint (PRD 022 R30)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

STEP_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
GUIDELINES_REL = Path("core/sw-reference/guidelines.json")


def guidelines_path(root: Path) -> Path:
    return root / GUIDELINES_REL


def load_guidelines(root: Path) -> dict[str, Any]:
    path = guidelines_path(root)
    if not path.is_file():
        raise FileNotFoundError(f"missing guidelines artifact: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"guidelines must be an object: {path}")
    return data


def validate_guidelines_artifact(data: Any, *, source: str = "") -> list[str]:
    prefix = f"{source}: " if source else ""
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"{prefix}guidelines must be an object"]
    if data.get("version") != 1:
        errors.append(f"{prefix}version must be 1")
    gv = data.get("guidelineVersion")
    if not isinstance(gv, str) or not re.match(r"^[0-9]+\.[0-9]+\.[0-9]+$", gv):
        errors.append(f"{prefix}guidelineVersion must be semver x.y.z")
    phase_types = data.get("phaseTypes")
    if not isinstance(phase_types, dict) or not phase_types:
        errors.append(f"{prefix}phaseTypes must be a non-empty object")
        return errors
    for phase_type, guideline in phase_types.items():
        errors.extend(_validate_phase_guideline(guideline, path=f"{prefix}phaseTypes.{phase_type}"))
    return errors


def _validate_phase_guideline(guideline: Any, *, path: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(guideline, dict):
        return [f"{path} must be an object"]
    for key in (
        "candidateSteps",
        "requiredSteps",
        "optionalSteps",
        "allowedReorderings",
        "forbiddenDeviations",
        "floorRuleRefs",
    ):
        if key not in guideline:
            errors.append(f"{path}.{key} is required")
    if errors:
        return errors
    candidate = _step_list(guideline.get("candidateSteps"), f"{path}.candidateSteps", errors)
    required = _step_list(guideline.get("requiredSteps"), f"{path}.requiredSteps", errors)
    optional = _step_list(guideline.get("optionalSteps"), f"{path}.optionalSteps", errors)
    if candidate and required:
        missing = sorted(set(required) - set(candidate))
        if missing:
            errors.append(f"{path}.requiredSteps not subset of candidateSteps: {', '.join(missing)}")
    if candidate and optional:
        overlap = sorted(set(required) & set(optional))
        if overlap:
            errors.append(f"{path} required/optional overlap: {', '.join(overlap)}")
        extra = sorted(set(optional) - set(candidate))
        if extra:
            errors.append(f"{path}.optionalSteps not subset of candidateSteps: {', '.join(extra)}")
    reorderings = guideline.get("allowedReorderings")
    if not isinstance(reorderings, list):
        errors.append(f"{path}.allowedReorderings must be an array")
    else:
        for index, block in enumerate(reorderings):
            errors.extend(_validate_reordering(block, path=f"{path}.allowedReorderings[{index}]"))
    forbidden = guideline.get("forbiddenDeviations")
    if not isinstance(forbidden, list):
        errors.append(f"{path}.forbiddenDeviations must be an array")
    else:
        for index, block in enumerate(forbidden):
            errors.extend(_validate_forbidden(block, path=f"{path}.forbiddenDeviations[{index}]"))
    floor_refs = guideline.get("floorRuleRefs")
    if not isinstance(floor_refs, list):
        errors.append(f"{path}.floorRuleRefs must be an array")
    elif not all(isinstance(ref, str) and ref.strip() for ref in floor_refs):
        errors.append(f"{path}.floorRuleRefs must be non-empty strings")
    return errors


def _step_list(value: Any, path: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not value:
        errors.append(f"{path} must be a non-empty array")
        return []
    steps: list[str] = []
    for index, step in enumerate(value):
        if not isinstance(step, str) or not STEP_ID_RE.match(step):
            errors.append(f"{path}[{index}] invalid step id: {step!r}")
        else:
            steps.append(step)
    return steps


def _validate_reordering(block: Any, *, path: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(block, dict):
        return [f"{path} must be an object"]
    steps = block.get("steps")
    if not isinstance(steps, list) or len(steps) < 2:
        errors.append(f"{path}.steps must be an array with at least 2 items")
    elif not all(isinstance(s, str) and STEP_ID_RE.match(s) for s in steps):
        errors.append(f"{path}.steps contains invalid step ids")
    for anchor in ("anchorBefore", "anchorAfter"):
        val = block.get(anchor)
        if val is not None and (not isinstance(val, str) or not STEP_ID_RE.match(val)):
            errors.append(f"{path}.{anchor} invalid step id: {val!r}")
    return errors


def _validate_forbidden(block: Any, *, path: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(block, dict):
        return [f"{path} must be an object"]
    if not isinstance(block.get("id"), str) or not block.get("id"):
        errors.append(f"{path}.id required")
    if not isinstance(block.get("reason"), str) or not block.get("reason"):
        errors.append(f"{path}.reason required")
    for key in ("omitStep", "reorderBefore", "reorderAfter"):
        val = block.get(key)
        if val is not None and (not isinstance(val, str) or not STEP_ID_RE.match(val)):
            errors.append(f"{path}.{key} invalid step id: {val!r}")
    return errors


def check_floor_rule_refs(root: Path, guidelines: dict[str, Any]) -> list[str]:
    from kernel_classification import load_classification

    try:
        classification = load_classification(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot load kernel classification for floor refs: {exc}"]
    matrix = classification.get("floorMatrix") or {}
    rules = matrix.get("rules") or []
    known = {rule.get("id") for rule in rules if isinstance(rule, dict) and isinstance(rule.get("id"), str)}
    errors: list[str] = []
    for phase_type, guideline in (guidelines.get("phaseTypes") or {}).items():
        if not isinstance(guideline, dict):
            continue
        for ref in guideline.get("floorRuleRefs") or []:
            if ref not in known:
                errors.append(f"phaseTypes.{phase_type}.floorRuleRefs unknown rule: {ref!r}")
    return errors


def lint_guidelines(root: Path) -> tuple[bool, list[str]]:
    try:
        data = load_guidelines(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return False, [str(exc)]
    source = str(GUIDELINES_REL)
    errors = validate_guidelines_artifact(data, source=source)
    errors.extend(check_floor_rule_refs(root, data))
    return (len(errors) == 0, errors)
