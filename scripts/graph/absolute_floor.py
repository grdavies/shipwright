#!/usr/bin/env python3
"""Risk-class absolute floors and promotion anti-ratchet ceilings (PRD 272 R9)."""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from graph.detectors.registry import (
    CAPABILITY_API,
    CAPABILITY_AUTH,
    CAPABILITY_MIGRATION,
    CAPABILITY_STANDARD_REVIEW,
    CAPABILITY_SUPPLY_CHAIN,
    load_registry,
)

RISK_CLASS_FLOORS_REL = Path("core/sw-reference/risk-class-floors.json")
OPTIMIZATION_PROFILES = frozenset({"fast", "balanced", "thorough"})
REQUIRED_CAPABILITY_TOKENS = (
    "merge-gate",
    "human-merge-gate",
    "human-terminal-merge-gate",
    "credential-broker",
    "write-isolation-lease",
    "mechanical-verification",
    "verification-gate",
)


class AbsoluteFloorError(ValueError):
    """Raised when profile or promotion violates absolute floor or anti-ratchet."""


def _is_required_capability_node(node: Mapping[str, Any]) -> bool:
    kind = str(node.get("kind") or "")
    if kind in {"gate", "verifier"}:
        return True
    node_id = str(node.get("id") or "")
    step = str((node.get("target") or {}).get("step") or "")
    blob = f"{node_id} {step}"
    return any(token in blob for token in REQUIRED_CAPABILITY_TOKENS)


def required_capabilities_from_graph(graph: Mapping[str, Any]) -> frozenset[str]:
    """Collect typed required capability ids declared on graph nodes."""
    caps: set[str] = set()
    metadata = graph.get("metadata") or {}
    for cap_id in metadata.get("requiredCapabilityIds") or ():
        if isinstance(cap_id, str) and cap_id:
            caps.add(cap_id)
    for node in graph["spec"]["nodes"]:
        node_metadata = node.get("metadata") or {}
        cap_id = node_metadata.get("requiredCapabilityId")
        if isinstance(cap_id, str) and cap_id:
            caps.add(cap_id)
            continue
        if _is_required_capability_node(node):
            step = str((node.get("target") or {}).get("step") or "")
            if "auth" in step:
                caps.add(CAPABILITY_AUTH)
    return frozenset(caps)


def load_risk_class_floors(root: Path) -> dict[str, Any]:
    path = root / RISK_CLASS_FLOORS_REL
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid risk-class floors document: {path}")
    return payload


def capability_risk_class_map(
    registry_payload: Mapping[str, Any] | None = None,
    *,
    repo_root: Path | None = None,
) -> dict[str, str]:
    """Map required capability ids to risk classes from the capability registry."""
    payload = registry_payload
    if payload is None:
        if repo_root is None:
            raise ValueError("repo_root or registry_payload is required")
        payload = load_registry(repo_root)
    family = (payload.get("families") or {}).get("workflow.requiredCapabilities") or {}
    rows = family.get("rows") or []
    mapping: dict[str, str] = {
        CAPABILITY_MIGRATION: "data",
        CAPABILITY_AUTH: "security",
        CAPABILITY_API: "interface",
        CAPABILITY_SUPPLY_CHAIN: "supply-chain",
        CAPABILITY_STANDARD_REVIEW: "unclassified",
    }
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            cap_id = str(row.get("id") or "")
            risk_class = str(row.get("riskClass") or "")
            if cap_id and risk_class:
                mapping[cap_id] = risk_class
    return mapping


def active_risk_classes(
    capability_ids: frozenset[str],
    *,
    risk_map: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> frozenset[str]:
    """Risk classes in scope for injected or pinned capabilities."""
    resolved = risk_map or capability_risk_class_map(repo_root=repo_root)
    return frozenset(
        resolved[cap_id]
        for cap_id in capability_ids
        if cap_id in resolved
    )


def absolute_floor_capabilities(
    capability_ids: frozenset[str],
    *,
    floors_config: Mapping[str, Any] | None = None,
    risk_map: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> frozenset[str]:
    """Minimum capabilities for active risk classes — independent of profile/history."""
    if repo_root is None and floors_config is None:
        raise ValueError("repo_root or floors_config is required")
    config = floors_config or load_risk_class_floors(repo_root)  # type: ignore[arg-type]
    classes = active_risk_classes(
        capability_ids,
        risk_map=risk_map,
        repo_root=repo_root,
    )
    floors = config.get("floors") or {}
    required: set[str] = set()
    for risk_class in classes:
        entry = floors.get(risk_class) or {}
        for cap_id in entry.get("minimumCapabilityIds") or ():
            required.add(str(cap_id))
    return frozenset(required)


def apply_optimization_profile(
    capability_ids: frozenset[str],
    profile: str,
) -> frozenset[str]:
    """Vary optional reviewers only; absolute floor enforced separately."""
    if profile not in OPTIMIZATION_PROFILES:
        raise AbsoluteFloorError(f"unknown optimization profile: {profile}")
    caps = set(capability_ids)
    if profile == "fast":
        caps.discard(CAPABILITY_STANDARD_REVIEW)
    elif profile == "thorough":
        caps.add(CAPABILITY_STANDARD_REVIEW)
    return frozenset(caps)


def enforce_absolute_floor(
    *,
    injected_capability_ids: frozenset[str],
    profile_adjusted_capability_ids: frozenset[str],
    profile: str,
    floors_config: Mapping[str, Any] | None = None,
    risk_map: Mapping[str, str] | None = None,
    repo_root: Path | None = None,
) -> None:
    """Evaluate floor after profile+inject; profile cannot lower risk-class floor."""
    floor = absolute_floor_capabilities(
        injected_capability_ids,
        floors_config=floors_config,
        risk_map=risk_map,
        repo_root=repo_root,
    )
    dropped = floor - profile_adjusted_capability_ids
    if dropped:
        raise AbsoluteFloorError(
            f"profile {profile!r} cannot lower absolute floor; "
            f"missing capabilities: {sorted(dropped)}"
        )


def evaluate_after_profile_and_inject(
    *,
    injected_capability_ids: frozenset[str],
    profile: str,
    repo_root: Path | None = None,
    floors_config: Mapping[str, Any] | None = None,
    risk_map: Mapping[str, str] | None = None,
) -> frozenset[str]:
    """Apply profile to injected capabilities, then enforce the absolute floor."""
    adjusted = apply_optimization_profile(injected_capability_ids, profile)
    enforce_absolute_floor(
        injected_capability_ids=injected_capability_ids,
        profile_adjusted_capability_ids=adjusted,
        profile=profile,
        floors_config=floors_config,
        risk_map=risk_map,
        repo_root=repo_root,
    )
    return adjusted


def assert_anti_ratchet_ceiling(
    *,
    pinned_reference: frozenset[str],
    candidate: frozenset[str],
    floors_config: Mapping[str, Any] | None = None,
    repo_root: Path | None = None,
) -> None:
    """Bound cumulative capability reduction vs a pinned promotion reference."""
    if repo_root is None and floors_config is None:
        raise ValueError("repo_root or floors_config is required")
    config = floors_config or load_risk_class_floors(repo_root)  # type: ignore[arg-type]
    anti = config.get("antiRatchet") or {}
    max_reduction = int(anti.get("maxCapabilityReduction", 0))
    removed = pinned_reference - candidate
    if len(removed) > max_reduction:
        raise AbsoluteFloorError(
            "promotion anti-ratchet ceiling exceeded: "
            f"removed {sorted(removed)} vs pinned reference "
            f"(max reduction {max_reduction})"
        )
