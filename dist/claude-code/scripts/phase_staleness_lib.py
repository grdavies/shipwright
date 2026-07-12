"""Multi-signal staleness classifier for background phases (PRD 064 R32)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from check_gate_lib import cfg_value, load_workflow_config

CLASSIFICATIONS = (
    "waiting-on-human",
    "actively-working",
    "genuinely-stuck",
    "indeterminate",
)

CONFIDENCE_TIERS = ("high", "medium", "low")

DEFAULT_STALENESS_CONFIG: dict[str, Any] = {
    "enabled": True,
    "stuckThresholdMinutes": 30,
    "workingThresholdMinutes": 5,
    "waitingOnHumanBoost": 0.35,
}


@dataclass(frozen=True)
class StalenessConfig:
    enabled: bool
    stuck_threshold_minutes: float
    working_threshold_minutes: float
    waiting_on_human_boost: float


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def minutes_since(ts: datetime | None, now: datetime) -> float | None:
    if ts is None:
        return None
    return max(0.0, (now - ts).total_seconds() / 60.0)


def load_staleness_config(root: Path) -> StalenessConfig:
    cfg = load_workflow_config(root)
    block = cfg_value(cfg, "deliver", "watchdog", "stalenessClassifier", default={}) or {}
    if not isinstance(block, dict):
        block = {}
    merged = {**DEFAULT_STALENESS_CONFIG, **block}
    return StalenessConfig(
        enabled=bool(merged.get("enabled", True)),
        stuck_threshold_minutes=float(merged.get("stuckThresholdMinutes", 30)),
        working_threshold_minutes=float(merged.get("workingThresholdMinutes", 5)),
        waiting_on_human_boost=float(merged.get("waitingOnHumanBoost", 0.35)),
    )


def _confidence_tier(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def classify_staleness(
    signals: dict[str, Any],
    *,
    cfg: StalenessConfig | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Combine liveness signals into a confidence-scored waiting-vs-stuck classification."""
    if root is not None and cfg is None:
        cfg = load_staleness_config(root)
    cfg = cfg or StalenessConfig(True, 30.0, 5.0, 0.35)

    now = parse_ts(signals.get("now")) or utc_now()
    last_tool = parse_ts(signals.get("lastToolCallAt"))
    last_commit = parse_ts(signals.get("lastCommitAt"))
    last_status = parse_ts(signals.get("lastStatusWriteAt"))
    pending_human = bool(signals.get("pendingHumanReply"))

    tool_age = minutes_since(last_tool, now)
    commit_age = minutes_since(last_commit, now)
    status_age = minutes_since(last_status, now)

    recent_activity = any(
        age is not None and age <= cfg.working_threshold_minutes
        for age in (tool_age, commit_age, status_age)
    )

    stale_signals = [
        age
        for age in (tool_age, commit_age, status_age)
        if age is None or age >= cfg.stuck_threshold_minutes
    ]
    all_stale = len(stale_signals) == 3

    score = 0.2
    classification = "indeterminate"
    reasons: list[str] = []

    if pending_human:
        score += cfg.waiting_on_human_boost
        reasons.append("pending-human-reply")
        if recent_activity:
            classification = "waiting-on-human"
            score += 0.25
        elif not all_stale:
            classification = "waiting-on-human"
            score += 0.15
        else:
            classification = "waiting-on-human"
            score += 0.05
    elif recent_activity:
        classification = "actively-working"
        score = 0.85
        reasons.append("recent-activity")
    elif all_stale:
        classification = "genuinely-stuck"
        score = 0.8
        reasons.append("all-signals-stale")
    else:
        classification = "indeterminate"
        score = 0.35
        reasons.append("mixed-signals")

    score = min(1.0, max(0.0, score))

    return {
        "classification": classification,
        "confidenceTier": _confidence_tier(score),
        "confidenceScore": round(score, 3),
        "enabled": cfg.enabled,
        "signals": {
            "lastToolCallMinutes": None if tool_age is None else round(tool_age, 2),
            "lastCommitMinutes": None if commit_age is None else round(commit_age, 2),
            "lastStatusWriteMinutes": None if status_age is None else round(status_age, 2),
            "pendingHumanReply": pending_human,
        },
        "reasons": reasons,
    }


def should_defer_phase_timeout(classification: dict[str, Any]) -> bool:
    """Defer watchdog hard-stop when confidently waiting on human input."""
    if not classification.get("enabled", True):
        return False
    return (
        classification.get("classification") == "waiting-on-human"
        and classification.get("confidenceTier") in {"high", "medium"}
    )
