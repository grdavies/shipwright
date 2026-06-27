"""Precedence tiers and deterministic total-order tie-break for capability selection (R11)."""

from __future__ import annotations

from typing import Any

TIER_RANK = {"override": 0, "signal": 1, "default": 2}
DEFAULT_TIER_BY_TRIGGER = {
    "always_on": "default",
    "phase_default": "default",
}
DEFAULT_PRIORITY = 1000


def effective_tier(capability: dict[str, Any], trigger: dict[str, Any] | None = None) -> str:
    precedence = capability.get("precedence")
    if isinstance(precedence, dict) and precedence.get("tier") in TIER_RANK:
        return str(precedence["tier"])
    trigger_type = (trigger or {}).get("type")
    if trigger_type in DEFAULT_TIER_BY_TRIGGER:
        return DEFAULT_TIER_BY_TRIGGER[trigger_type]
    return "signal"


def effective_priority(capability: dict[str, Any]) -> int:
    precedence = capability.get("precedence")
    if isinstance(precedence, dict) and "priority" in precedence:
        return int(precedence["priority"])
    return DEFAULT_PRIORITY


def precedence_key(capability: dict[str, Any], trigger: dict[str, Any] | None = None) -> tuple[int, int]:
    tier = effective_tier(capability, trigger)
    return (TIER_RANK[tier], effective_priority(capability))


def compare_precedence(
    left_id: str,
    left_capability: dict[str, Any],
    right_id: str,
    right_capability: dict[str, Any],
    *,
    trigger: dict[str, Any] | None = None,
) -> int:
    left_key = precedence_key(left_capability, trigger)
    right_key = precedence_key(right_capability, trigger)
    if left_key != right_key:
        return -1 if left_key < right_key else 1
    if left_id == right_id:
        return 0
    return -1 if left_id < right_id else 1


def total_order_key(
    capability_id: str,
    capability: dict[str, Any],
    *,
    trigger: dict[str, Any] | None = None,
) -> tuple[int, int, str]:
    tier_rank, priority = precedence_key(capability, trigger)
    return (tier_rank, priority, capability_id)


def has_precedence_resolution(
    left_capability: dict[str, Any],
    right_capability: dict[str, Any],
    *,
    trigger: dict[str, Any] | None = None,
) -> bool:
    left_key = precedence_key(left_capability, trigger)
    right_key = precedence_key(right_capability, trigger)
    return left_key != right_key
