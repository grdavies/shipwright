#!/usr/bin/env python3
"""Signal-conditional floor evaluator for plan proposals (PRD 022 R33)."""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath
from typing import Any

from kernel_classification import load_classification, normalize_step


def _collect_paths(signal_context: dict[str, Any] | None, task_file_paths: list[str] | None) -> list[str]:
    paths: list[str] = []
    if task_file_paths:
        paths.extend(str(p) for p in task_file_paths if p)
    if signal_context:
        for p in signal_context.get("file_paths") or []:
            if isinstance(p, str) and p:
                paths.append(p)
        digest = signal_context.get("change_digest")
        if isinstance(digest, dict):
            for item in digest.get("files") or []:
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    paths.append(item["path"])
    return paths


def _path_matches_glob(path: str, glob: str) -> bool:
    norm = PurePosixPath(path.replace("\\", "/")).as_posix()
    pattern = glob.replace("\\", "/")
    if fnmatch.fnmatch(norm, pattern):
        return True
    return fnmatch.fnmatch(norm, f"**/{pattern}" if not pattern.startswith("**") else pattern)


def _trigger_matches(trigger: dict[str, Any], paths: list[str], signal_context: dict[str, Any] | None) -> bool:
    if "anyOf" in trigger and "type" not in trigger:
        children = trigger.get("anyOf") or []
        return any(_trigger_matches(child, paths, signal_context) for child in children if isinstance(child, dict))
    if "allOf" in trigger and "type" not in trigger:
        children = trigger.get("allOf") or []
        return all(_trigger_matches(child, paths, signal_context) for child in children if isinstance(child, dict))
    trigger_type = trigger.get("type")
    if trigger_type == "path_glob":
        globs = trigger.get("globs") or []
        if not isinstance(globs, list):
            return False
        return any(_path_matches_glob(path, glob) for path in paths for glob in globs if isinstance(glob, str))
    if trigger_type == "triage_tag":
        # Triage tags alone never satisfy a floor trigger (R33).
        return False
    if trigger_type == "signal_context":
        field = trigger.get("field")
        if field == "derived_tags":
            return False
        if field == "file_paths" and isinstance(signal_context, dict):
            globs = trigger.get("globs") or []
            sc_paths = [str(p) for p in (signal_context.get("file_paths") or []) if p]
            return any(_path_matches_glob(path, glob) for path in sc_paths for glob in globs if isinstance(glob, str))
    if trigger_type in {"any_of", "all_of"}:
        children = trigger.get("triggers") or trigger.get("predicates") or []
        if not isinstance(children, list) or not children:
            return False
        results = [_trigger_matches(child, paths, signal_context) for child in children if isinstance(child, dict)]
        if trigger_type == "any_of":
            return any(results)
        return all(results)
    return False


def rule_triggered(rule: dict[str, Any], signal_context: dict[str, Any] | None, task_file_paths: list[str] | None) -> bool:
    if rule.get("triageTagsAloneInsufficient"):
        tags = []
        if signal_context and isinstance(signal_context.get("derived_tags"), list):
            tags = [t for t in signal_context["derived_tags"] if isinstance(t, str)]
        paths = _collect_paths(signal_context, task_file_paths)
        if not paths:
            return False
        if tags and not paths:
            return False
    triggers = rule.get("triggers")
    if not isinstance(triggers, dict):
        return False
    paths = _collect_paths(signal_context, task_file_paths)
    return _trigger_matches(triggers, paths, signal_context)


def floor_mandatory_steps(
    classification: dict[str, Any],
    signal_context: dict[str, Any] | None,
    task_file_paths: list[str] | None,
) -> list[str]:
    matrix = classification.get("floorMatrix") or {}
    rules = matrix.get("rules") or []
    mandatory: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        if not rule_triggered(rule, signal_context, task_file_paths):
            continue
        for step in rule.get("mandatorySteps") or []:
            if isinstance(step, str):
                norm = normalize_step(step)
                if norm not in mandatory:
                    mandatory.append(norm)
    return mandatory


def validate_plan_against_floor(
    classification: dict[str, Any],
    proposed_steps: list[str],
    signal_context: dict[str, Any] | None,
    task_file_paths: list[str] | None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    plan = [normalize_step(s) for s in proposed_steps]
    positions = {step: idx for idx, step in enumerate(plan)}
    matrix = classification.get("floorMatrix") or {}
    for rule in matrix.get("rules") or []:
        if not isinstance(rule, dict) or not rule_triggered(rule, signal_context, task_file_paths):
            continue
        rule_id = rule.get("id", "unknown")
        for step in rule.get("mandatorySteps") or []:
            if not isinstance(step, str):
                continue
            norm = normalize_step(step)
            if norm not in positions:
                reasons.append(f"floor rule {rule_id!r} requires step {norm!r}")
        for constraint in rule.get("orderingConstraints") or []:
            if not isinstance(constraint, dict):
                continue
            step = constraint.get("step")
            after = constraint.get("mustPrecede")
            if not isinstance(step, str) or not isinstance(after, str):
                continue
            s = normalize_step(step)
            a = normalize_step(after)
            if s not in positions or a not in positions:
                continue
            if positions[s] >= positions[a]:
                reasons.append(f"floor rule {rule_id!r}: {s} must precede {a}")
    return (len(reasons) == 0, reasons)


def evaluate_floor_from_root(
    root,
    proposed_steps: list[str],
    signal_context: dict[str, Any] | None,
    task_file_paths: list[str] | None,
) -> tuple[bool, list[str]]:
    from pathlib import Path

    classification = load_classification(Path(root))
    return validate_plan_against_floor(classification, proposed_steps, signal_context, task_file_paths)
