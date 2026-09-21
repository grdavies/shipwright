"""Optional reasoning effort carried alongside a concrete model dispatch ID."""
from __future__ import annotations

VALID_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"})
ASTRA_EFFORTS = VALID_EFFORTS - {"none", "minimal"}


def resolve_reasoning_effort(models: dict, tier: str, model_id: str) -> str | None:
    mapping = models.get("reasoningEffortByTier", {})
    if not isinstance(mapping, dict):
        raise ValueError("models.reasoningEffortByTier must be an object")
    if tier not in mapping:
        return None
    effort = mapping[tier]
    allowed = ASTRA_EFFORTS if model_id == "gpt-6-astra" else VALID_EFFORTS
    if not isinstance(effort, str) or effort not in allowed:
        raise ValueError(f"invalid reasoning effort for {model_id} at tier {tier}: {effort!r}")
    return effort
