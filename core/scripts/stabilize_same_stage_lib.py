"""Same-stage failure counter with tier/persona escalation (PRD 064 R31)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from check_gate_lib import cfg_value, load_workflow_config

TIER_ORDER = ["cheap", "build", "mid", "deep"]

DEFAULT_SAME_STAGE_CONFIG: dict[str, Any] = {
    "enabled": True,
    "escalateAfterFailures": 2,
    "personaFallback": "adversarial",
}


@dataclass(frozen=True)
class SameStageConfig:
    enabled: bool
    escalate_after_failures: int
    persona_fallback: str


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_same_stage_config(root: Path) -> SameStageConfig:
    cfg = load_workflow_config(root)
    block = cfg_value(cfg, "stabilizeLoop", "sameStageEscalation", default={}) or {}
    if not isinstance(block, dict):
        block = {}
    merged = {**DEFAULT_SAME_STAGE_CONFIG, **block}
    return SameStageConfig(
        enabled=bool(merged.get("enabled", True)),
        escalate_after_failures=max(1, int(merged.get("escalateAfterFailures", 2))),
        persona_fallback=str(merged.get("personaFallback") or "adversarial"),
    )


def tier_rank(name: str | None) -> int | None:
    if not name or name not in TIER_ORDER:
        return None
    return TIER_ORDER.index(name)


def escalate_tier(current_tier: str) -> str | None:
    rank = tier_rank(current_tier)
    if rank is None or rank >= len(TIER_ORDER) - 1:
        return None
    return TIER_ORDER[rank + 1]


def resolve_persona_tier(config: dict[str, Any], persona: str) -> str | None:
    routing = config.get("models", {}).get("routing", {})
    agents = routing.get("agents") if isinstance(routing, dict) else {}
    if not isinstance(agents, dict):
        return None
    tier = agents.get(persona)
    return str(tier) if tier else None


def resolve_escalation(
    root: Path,
    *,
    failure_count: int,
    current_tier: str,
    cfg: SameStageConfig | None = None,
) -> dict[str, Any]:
    """Escalate to a higher tier or routing persona; never alters hard-stop semantics."""
    cfg = cfg or load_same_stage_config(root)
    if not cfg.enabled or failure_count < cfg.escalate_after_failures:
        return {
            "escalated": False,
            "failureCount": failure_count,
            "currentTier": current_tier,
            "chosenTier": current_tier,
            "persona": None,
        }

    next_tier = escalate_tier(current_tier)
    if next_tier:
        return {
            "escalated": True,
            "failureCount": failure_count,
            "currentTier": current_tier,
            "chosenTier": next_tier,
            "persona": None,
            "reason": "tier-escalation",
        }

    workflow = load_workflow_config(root)
    persona = cfg.persona_fallback
    persona_tier = resolve_persona_tier(workflow, persona)
    return {
        "escalated": True,
        "failureCount": failure_count,
        "currentTier": current_tier,
        "chosenTier": persona_tier or current_tier,
        "persona": persona,
        "reason": "persona-fallback",
    }


def empty_state() -> dict[str, Any]:
    return {
        "version": 1,
        "failureCount": 0,
        "lastHeadSha": None,
        "lastStage": None,
        "lastFailureSet": None,
        "escalations": [],
        "updatedAt": None,
    }


def record_same_stage_outcome(
    state: dict[str, Any],
    *,
    head_sha: str,
    stage: str,
    failure_set: frozenset[str] | set[str],
    progressed: bool,
) -> dict[str, Any]:
    """Track same-stage failures independently of the no-progress SHA signature."""
    out = dict(state or empty_state())
    failure_key = "|".join(sorted(str(x) for x in failure_set))

    if progressed:
        out["failureCount"] = 0
        out["lastHeadSha"] = head_sha
        out["lastStage"] = stage
        out["lastFailureSet"] = failure_key
        out["updatedAt"] = utc_now()
        return out

    if not failure_set:
        out["lastHeadSha"] = head_sha
        out["updatedAt"] = utc_now()
        return out

    same_signature = (
        out.get("lastHeadSha") == head_sha
        and out.get("lastStage") == stage
        and out.get("lastFailureSet") == failure_key
    )

    if same_signature:
        out["failureCount"] = int(out.get("failureCount") or 0) + 1
    else:
        out["failureCount"] = 1
        out["lastStage"] = stage
        out["lastFailureSet"] = failure_key

    out["lastHeadSha"] = head_sha
    out["updatedAt"] = utc_now()
    return out


def record_escalation_event(
    state: dict[str, Any],
    escalation: dict[str, Any],
) -> dict[str, Any]:
    out = dict(state or empty_state())
    events = list(out.get("escalations") or [])
    events.append({**escalation, "recordedAt": utc_now()})
    out["escalations"] = events[-20:]
    out["updatedAt"] = utc_now()
    return out


def no_progress_signature_fields(state: dict[str, Any]) -> dict[str, Any]:
    """Explicit exclusion contract: same-stage counter is never in no-progress signature."""
    return {
        "headSha": state.get("lastHeadSha"),
        "stage": state.get("lastStage"),
        "failureSet": state.get("lastFailureSet"),
    }
