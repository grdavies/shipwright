#!/usr/bin/env python3
"""Guidelines artifact validation — shared harness with capability manifest lint (PRD 022 R30)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

STEP_ID_RE = re.compile(r"^[a-z][a-zA-Z0-9-]*$")
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

ORCHESTRATOR_PACK_TYPES = frozenset({"debug", "doc", "feedback"})
GUIDELINES_DIR_REL = Path("core/sw-reference/guidelines")
REQUIRED_FORBIDDEN_DELIVER_STEPS = frozenset({
    "merge-enqueue",
    "merge-run-next",
    "terminal-ship",
    "git-push",
    "main-merge",
    "sw-execute",
    "lock-acquire",
    "phase-merge",
    "wave-plan-validate",
})


def orchestrator_pack_path(root: Path, orchestrator_type: str) -> Path:
    return root / GUIDELINES_DIR_REL / f"{orchestrator_type}.pack.json"


def load_orchestrator_pack(root: Path, orchestrator_type: str) -> dict[str, Any]:
    if orchestrator_type not in ORCHESTRATOR_PACK_TYPES:
        raise KeyError(f"unknown orchestrator pack type: {orchestrator_type!r}")
    path = orchestrator_pack_path(root, orchestrator_type)
    if not path.is_file():
        raise FileNotFoundError(f"missing orchestrator guideline pack: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"orchestrator pack must be an object: {path}")
    return data



def validate_guideline_constraints(
    guideline: dict[str, Any],
    steps: list[str],
) -> list[str]:
    from kernel_classification import normalize_step

    reasons: list[str] = []
    positions = {step: idx for idx, step in enumerate(steps)}
    for req in guideline.get("requiredSteps") or []:
        norm = normalize_step(str(req))
        if norm not in positions:
            reasons.append(f"required step missing: {norm}")
    for block in guideline.get("forbiddenDeviations") or []:
        if not isinstance(block, dict):
            continue
        omit = block.get("omitStep")
        if isinstance(omit, str) and normalize_step(omit) not in positions:
            reasons.append(f"forbidden omission: {block.get('id', omit)}")
        before = block.get("reorderBefore")
        after = block.get("reorderAfter")
        if isinstance(before, str) and isinstance(after, str):
            b, a = normalize_step(before), normalize_step(after)
            if b in positions and a in positions and positions[b] < positions[a]:
                reasons.append(f"forbidden reorder: {block.get('id', before)}")
    return reasons

def validate_orchestrator_pack_artifact(data: Any, *, source: str = "") -> list[str]:
    prefix = f"{source}: " if source else ""
    errors: list[str] = []
    if not isinstance(data, dict):
        return [f"{prefix}orchestrator pack must be an object"]
    if data.get("version") != 1:
        errors.append(f"{prefix}version must be 1")
    gv = data.get("guidelineVersion")
    if not isinstance(gv, str) or not re.match(r"^[0-9]+\.[0-9]+\.[0-9]+$", gv):
        errors.append(f"{prefix}guidelineVersion must be semver x.y.z")
    orch_type = data.get("orchestratorType")
    if orch_type not in ORCHESTRATOR_PACK_TYPES:
        errors.append(f"{prefix}orchestratorType must be debug|doc|feedback")
    pack_id = data.get("packId")
    if not isinstance(pack_id, str) or not STEP_ID_RE.match(pack_id):
        errors.append(f"{prefix}packId invalid")
    if isinstance(orch_type, str) and isinstance(pack_id, str) and pack_id != orch_type:
        errors.append(f"{prefix}packId must match orchestratorType")
    for key in (
        "canonicalFallbackChain",
        "candidateSteps",
        "requiredSteps",
        "optionalSteps",
        "forbiddenDeliverOnlySteps",
        "forbiddenDeviations",
        "signalConditionalFloors",
        "floorRuleRefs",
    ):
        if key not in data:
            errors.append(f"{prefix}{key} is required")
    if errors:
        return errors
    candidate = _step_list(data.get("candidateSteps"), f"{prefix}candidateSteps", errors)
    required = _step_list(data.get("requiredSteps"), f"{prefix}requiredSteps", errors)
    optional = _step_list(data.get("optionalSteps"), f"{prefix}optionalSteps", errors)
    canonical = _step_list(data.get("canonicalFallbackChain"), f"{prefix}canonicalFallbackChain", errors)
    forbidden = _step_list(data.get("forbiddenDeliverOnlySteps"), f"{prefix}forbiddenDeliverOnlySteps", errors)
    if forbidden:
        missing_forbidden = sorted(REQUIRED_FORBIDDEN_DELIVER_STEPS - set(forbidden))
        if missing_forbidden:
            errors.append(f"{prefix}forbiddenDeliverOnlySteps missing: {', '.join(missing_forbidden)}")
    if candidate and required:
        missing = sorted(set(required) - set(candidate))
        if missing:
            errors.append(f"{prefix}requiredSteps not subset of candidateSteps: {', '.join(missing)}")
    if candidate and canonical:
        extra = sorted(set(canonical) - set(candidate))
        if extra:
            errors.append(f"{prefix}canonicalFallbackChain not subset of candidateSteps: {', '.join(extra)}")
    reorderings = data.get("allowedReorderings")
    if reorderings is not None:
        if not isinstance(reorderings, list):
            errors.append(f"{prefix}allowedReorderings must be an array")
        else:
            for index, block in enumerate(reorderings):
                errors.extend(_validate_reordering(block, path=f"{prefix}allowedReorderings[{index}]"))
    for index, block in enumerate(data.get("forbiddenDeviations") or []):
        errors.extend(_validate_forbidden(block, path=f"{prefix}forbiddenDeviations[{index}]"))
    floors = data.get("signalConditionalFloors")
    if not isinstance(floors, list):
        errors.append(f"{prefix}signalConditionalFloors must be an array")
    else:
        for index, floor in enumerate(floors):
            errors.extend(_validate_signal_floor(floor, path=f"{prefix}signalConditionalFloors[{index}]"))
    floor_refs = data.get("floorRuleRefs")
    if not isinstance(floor_refs, list):
        errors.append(f"{prefix}floorRuleRefs must be an array")
    elif not all(isinstance(ref, str) and ref.strip() for ref in floor_refs):
        errors.append(f"{prefix}floorRuleRefs must be non-empty strings")
    return errors


def _validate_signal_floor(floor: Any, *, path: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(floor, dict):
        return [f"{path} must be an object"]
    if not isinstance(floor.get("id"), str) or not floor.get("id"):
        errors.append(f"{path}.id required")
    mandatory = floor.get("mandatorySteps")
    if not isinstance(mandatory, list) or not mandatory:
        errors.append(f"{path}.mandatorySteps must be a non-empty array")
    elif not all(isinstance(s, str) and STEP_ID_RE.match(s) for s in mandatory):
        errors.append(f"{path}.mandatorySteps contains invalid step ids")
    triggers = floor.get("triggers")
    if not isinstance(triggers, dict):
        errors.append(f"{path}.triggers must be an object")
    return errors


def check_orchestrator_pack_floor_refs(root: Path, pack: dict[str, Any], *, orchestrator_type: str) -> list[str]:
    from kernel_classification import load_classification

    try:
        classification = load_classification(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"cannot load kernel classification for pack floor refs: {exc}"]
    matrix = classification.get("floorMatrix") or {}
    rules = matrix.get("rules") or []
    known = {rule.get("id") for rule in rules if isinstance(rule, dict) and isinstance(rule.get("id"), str)}
    errors: list[str] = []
    for ref in pack.get("floorRuleRefs") or []:
        if ref not in known:
            errors.append(f"guidelines/{orchestrator_type}.pack.json floorRuleRefs unknown rule: {ref!r}")
    return errors


def check_orchestrator_pack_parity(root: Path, pack: dict[str, Any], *, orchestrator_type: str) -> list[str]:
    from orchestrator_step_plan import orchestrator_type_spec

    errors: list[str] = []
    try:
        spec = orchestrator_type_spec(root, orchestrator_type)
    except (OSError, ValueError, KeyError) as exc:
        return [f"cannot load orchestrator-step-plan for {orchestrator_type}: {exc}"]
    for key in ("candidateSteps", "requiredSteps", "optionalSteps", "canonicalChain"):
        pack_key = "canonicalFallbackChain" if key == "canonicalChain" else key
        if list(pack.get(pack_key) or []) != list(spec.get(key) or []):
            errors.append(
                f"guidelines/{orchestrator_type}.pack.json {pack_key} diverges from orchestrator-step-plan.json"
            )
    spec_forbidden = set(spec.get("forbiddenSteps") or [])
    pack_forbidden = set(pack.get("forbiddenDeliverOnlySteps") or [])
    if spec_forbidden != pack_forbidden:
        errors.append(
            f"guidelines/{orchestrator_type}.pack.json forbiddenDeliverOnlySteps diverges from orchestrator-step-plan.json"
        )
    return errors


def lint_orchestrator_packs(root: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []
    for orchestrator_type in sorted(ORCHESTRATOR_PACK_TYPES):
        rel = f"core/sw-reference/guidelines/{orchestrator_type}.pack.json"
        try:
            data = load_orchestrator_pack(root, orchestrator_type)
        except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
            errors.append(str(exc))
            continue
        errors.extend(validate_orchestrator_pack_artifact(data, source=rel))
        errors.extend(check_orchestrator_pack_floor_refs(root, data, orchestrator_type=orchestrator_type))
        errors.extend(check_orchestrator_pack_parity(root, data, orchestrator_type=orchestrator_type))
    return (len(errors) == 0, errors)


def signal_context_floor_triggered(trigger: dict[str, Any], signal_context: dict[str, Any] | None) -> bool:
    if not isinstance(trigger, dict) or not isinstance(signal_context, dict):
        return False
    if trigger.get("type") != "signal_context":
        return False
    field = trigger.get("field")
    if not isinstance(field, str):
        return False
    expected = trigger.get("equals")
    if not isinstance(expected, list):
        return False
    actual = signal_context.get(field)
    if isinstance(actual, list):
        return any(item in expected for item in actual if isinstance(item, str))
    return actual in expected


def pack_signal_conditional_mandatory_steps(
    pack: dict[str, Any],
    signal_context: dict[str, Any] | None,
) -> list[str]:
    mandatory: list[str] = []
    for floor in pack.get("signalConditionalFloors") or []:
        if not isinstance(floor, dict):
            continue
        triggers = floor.get("triggers")
        if not isinstance(triggers, dict):
            continue
        if not signal_context_floor_triggered(triggers, signal_context):
            continue
        for step in floor.get("mandatorySteps") or []:
            if isinstance(step, str):
                mandatory.append(step)
    return mandatory


def validate_pack_constraints(pack: dict[str, Any], steps: list[str]) -> list[str]:
    reasons: list[str] = []
    positions = {step: idx for idx, step in enumerate(steps)}
    for forbidden in pack.get("forbiddenDeliverOnlySteps") or []:
        norm = str(forbidden)
        if norm in positions:
            reasons.append(f"forbidden deliver-only step present: {norm}")
    reasons.extend(validate_guideline_constraints(pack, steps))
    return reasons
