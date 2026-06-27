#!/usr/bin/env python3
"""Minimal capability manifest schema validation (PRD 021 R27)."""

from __future__ import annotations

from typing import Any

VALID_TRIGGER_TYPES = frozenset(
    {
        "always_on",
        "phase_default",
        "triage_tag",
        "text_token",
        "heading",
        "link_pattern",
        "path_glob",
        "change_digest",
        "config_flag",
        "file_count",
        "conductor_mode",
        "any_of",
        "all_of",
    }
)


def validate_capability_block(capability: Any, *, source: str = "") -> list[str]:
    errors: list[str] = []
    prefix = f"{source}: " if source else ""
    if not isinstance(capability, dict):
        return [f"{prefix}capability block must be an object"]
    version = capability.get("version")
    if version != 1:
        errors.append(f"{prefix}capability.version must be 1")
    triggers = capability.get("triggers")
    if not isinstance(triggers, list) or not triggers:
        errors.append(f"{prefix}capability.triggers must be a non-empty array")
        return errors
    for index, trigger in enumerate(triggers):
        errors.extend(_validate_trigger(trigger, path=f"{prefix}triggers[{index}]"))
    precedence = capability.get("precedence")
    if precedence is not None:
        if not isinstance(precedence, dict):
            errors.append(f"{prefix}capability.precedence must be an object")
        else:
            tier = precedence.get("tier")
            if tier is not None and tier not in {"override", "signal", "default"}:
                errors.append(f"{prefix}capability.precedence.tier invalid: {tier!r}")
    metadata = capability.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        errors.append(f"{prefix}capability.metadata must be an object")
    return errors


def _validate_trigger(trigger: Any, *, path: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(trigger, dict):
        return [f"{path} must be an object"]
    trigger_type = trigger.get("type")
    if trigger_type not in VALID_TRIGGER_TYPES:
        errors.append(f"{path}.type invalid or missing: {trigger_type!r}")
        return errors
    if trigger_type == "text_token":
        tokens = trigger.get("tokens")
        if not isinstance(tokens, list) or not tokens:
            errors.append(f"{path}.tokens must be a non-empty array")
    if trigger_type == "triage_tag":
        tags = trigger.get("tags")
        if not isinstance(tags, list) or not tags:
            errors.append(f"{path}.tags must be a non-empty array")
    if trigger_type == "config_flag":
        if not trigger.get("key"):
            errors.append(f"{path}.key required for config_flag")
    if trigger_type in {"any_of", "all_of"}:
        children = trigger.get("triggers") or trigger.get("predicates")
        if not isinstance(children, list) or not children:
            errors.append(f"{path}.triggers must be a non-empty array")
        else:
            for index, child in enumerate(children):
                errors.extend(_validate_trigger(child, path=f"{path}.triggers[{index}]"))
    return errors
