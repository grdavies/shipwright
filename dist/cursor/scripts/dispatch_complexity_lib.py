"""Optional complexity probe within a config-declared tier band (PRD 064 R11)."""
from __future__ import annotations

from typing import Any

TIER_ORDER = ["cheap", "build", "mid", "deep"]


def tier_rank(name: str | None) -> int | None:
    if not name or name not in TIER_ORDER:
        return None
    return TIER_ORDER.index(name)


def clamp_tier(tier: str, floor: str, ceiling: str) -> str:
    floor_rank = tier_rank(floor)
    ceiling_rank = tier_rank(ceiling)
    tier_value = tier_rank(tier)
    if floor_rank is None or ceiling_rank is None or tier_value is None:
        return tier
    if floor_rank > ceiling_rank:
        floor_rank, ceiling_rank = ceiling_rank, floor_rank
    clamped = max(floor_rank, min(ceiling_rank, tier_value))
    return TIER_ORDER[clamped]


def load_complexity_probe_config(config: dict[str, Any]) -> dict[str, Any]:
    dispatch = config.get("dispatch")
    if not isinstance(dispatch, dict):
        return {}
    probe = dispatch.get("complexityProbe")
    return probe if isinstance(probe, dict) else {}


def probe_complexity(
    *,
    static_tier: str,
    signal_context: dict[str, Any] | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Reuse inline-execute signals; disabled keeps static binding as floor and ceiling."""
    probe_cfg = load_complexity_probe_config(config)
    enabled = bool(probe_cfg.get("enabled"))
    if not enabled:
        return {
            "enabled": False,
            "staticTier": static_tier,
            "chosenTier": static_tier,
            "inputs": {},
        }

    ctx = signal_context if isinstance(signal_context, dict) else {}
    file_paths = list(ctx.get("file_paths") or [])
    file_count = len(file_paths)
    band_floor = str(probe_cfg.get("bandFloor") or static_tier)
    band_ceiling = str(probe_cfg.get("bandCeiling") or static_tier)

    if file_count <= 1:
        raw_choice = band_floor
    elif file_count <= 3:
        raw_choice = static_tier
    else:
        raw_choice = band_ceiling
    chosen = clamp_tier(raw_choice, band_floor, band_ceiling)

    return {
        "enabled": True,
        "staticTier": static_tier,
        "chosenTier": chosen,
        "inputs": {
            "fileCount": file_count,
            "filePaths": file_paths,
            "bandFloor": band_floor,
            "bandCeiling": band_ceiling,
            "inlineExecuteSignal": file_count <= 3,
        },
    }
