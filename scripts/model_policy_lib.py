"""Shared ModelPolicy — semantic tier order and escalation floors (PRD 269 R8/R9)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

CANONICAL_TIER_ORDER: tuple[str, ...] = ("cheap", "build", "mid", "deep")

ESCALATION_TRIGGERS = frozenset(
    {"schema-failure", "low-confidence", "verifier-disagreement"}
)
DEEP_FLOOR_TRIGGERS = frozenset({"schema-failure", "verifier-disagreement"})


@dataclass(frozen=True)
class ModelPolicy:
    """Semantic tier order derived from workflow ``models.tiers`` keys only."""

    tier_order: tuple[str, ...]
    tiers: dict[str, str]

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None) -> ModelPolicy:
        models = (config or {}).get("models", {})
        tiers = models.get("tiers", {}) if isinstance(models, dict) else {}
        if not isinstance(tiers, dict):
            tiers = {}
        normalized, _ = ensure_mid_tier({str(k): str(v) for k, v in tiers.items()})
        return cls.from_tiers(normalized)

    @classmethod
    def from_tiers(cls, tiers: Mapping[str, str]) -> ModelPolicy:
        return cls(tier_order=ordered_tiers(tiers), tiers=dict(tiers))

    def tier_rank(self, name: str | None) -> int | None:
        return tier_rank(name, self)

    def next_tier(self, current_tier: str) -> str | None:
        rank = self.tier_rank(current_tier)
        if rank is None or rank >= len(self.tier_order) - 1:
            return None
        return self.tier_order[rank + 1]

    def escalate_one_step(self, current_tier: str) -> str | None:
        return self.next_tier(current_tier)


def ordered_tiers(tiers: Mapping[str, str]) -> tuple[str, ...]:
    """Order tiers from ``models.tiers`` keys; insert ``mid`` between ``build`` and ``deep``."""
    if not tiers:
        return CANONICAL_TIER_ORDER

    out: list[str] = [name for name in CANONICAL_TIER_ORDER if name in tiers]
    if "mid" not in tiers and "build" in out and "deep" in out:
        build_idx = out.index("build")
        out.insert(build_idx + 1, "mid")
    for name in sorted(tiers):
        if name not in out:
            out.append(name)
    return tuple(out)


def ensure_mid_tier(tiers: dict[str, str]) -> tuple[dict[str, str], bool]:
    """Default a missing ``mid`` tier to the ``build`` model id."""
    if "mid" in tiers:
        return tiers, False
    if "build" in tiers:
        return {**tiers, "mid": tiers["build"]}, True
    return tiers, False


def tier_rank(name: str | None, policy: ModelPolicy) -> int | None:
    if not name or name not in policy.tier_order:
        return None
    return policy.tier_order.index(name)


def preflight_missing_mid(tiers: Mapping[str, str]) -> dict[str, Any] | None:
    """Advisory payload when ``models.tiers`` omits ``mid`` (R8/R9 preflight)."""
    if "mid" in tiers:
        return None
    if "build" not in tiers:
        return {
            "advisory": "model-policy:missing-mid",
            "remediation": "add models.tiers.mid or define models.tiers.build for defaulting",
        }
    return {
        "advisory": "model-policy:missing-mid-defaulted",
        "defaultedFrom": "build",
        "remediation": "declare models.tiers.mid explicitly; build model used as default",
    }


def next_model_tier(
    current_tier: str,
    triggers: Iterable[str],
    *,
    allowed_tiers: Iterable[str],
    tiers: Mapping[str, str] | None = None,
) -> str:
    """Escalate within policy order; deep-floor triggers jump to at least ``deep``."""
    trigger_set = set(triggers)
    unknown = trigger_set - ESCALATION_TRIGGERS
    if unknown:
        raise ValueError("unsupported escalation trigger(s): " + ", ".join(sorted(unknown)))

    normalized, _ = ensure_mid_tier(dict(tiers or {}))
    policy = ModelPolicy.from_tiers(normalized)
    allowed = tuple(dict.fromkeys(allowed_tiers))

    if current_tier not in allowed:
        raise ValueError(f"current tier {current_tier!r} is not allowlisted")
    if policy.tier_rank(current_tier) is None:
        raise ValueError(f"unknown tier {current_tier!r}")

    if not trigger_set:
        return current_tier

    current_rank = policy.tier_rank(current_tier)
    assert current_rank is not None

    if trigger_set & DEEP_FLOOR_TRIGGERS:
        deep_rank = policy.tier_rank("deep")
        if deep_rank is None:
            raise ValueError("unknown tier 'deep'")
        target_rank = max(current_rank + 1, deep_rank)
    else:
        target_rank = min(current_rank + 1, len(policy.tier_order) - 1)

    target = policy.tier_order[target_rank]
    if target not in allowed:
        raise PermissionError(f"escalation to {target!r} is outside the model-tier allowlist")
    return target
