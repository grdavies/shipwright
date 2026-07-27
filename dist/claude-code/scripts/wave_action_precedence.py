#!/usr/bin/env python3
"""Precedence classes for deliver-loop mechanical actions (PRD 081 R19)."""
from __future__ import annotations

from typing import Any

# Lower number = earlier in the mechanical sequence; never schedule a lower class after a higher one.
READ_ONLY = 1
EXCLUSION = 2
RUN_INIT = 3
MUTATION = 4

CLASS_LABELS: dict[int, str] = {
    READ_ONLY: "read-only",
    EXCLUSION: "exclusion",
    RUN_INIT: "run-init",
    MUTATION: "mutation",
}

ACTION_PRECEDENCE_CLASS: dict[str, int] = {
    "plan": READ_ONLY,
    "collect-status": READ_ONLY,
    "canonical-reemit": READ_ONLY,
    "collect-all-ready": READ_ONLY,
    "all-phases-complete": READ_ONLY,
    "lock-acquire": EXCLUSION,
    "state-init": RUN_INIT,
    "wave-plan-persist": MUTATION,
    "phase-plan-entry": MUTATION,
    "orchestrator-provision": MUTATION,
    "provision-phase": MUTATION,
    "inflight-signal-write": MUTATION,
    "base-capture": MUTATION,
    "spec-seed": MUTATION,
    "dispatch-ship": MUTATION,
    "dispatch-batch": MUTATION,
    "merge-enqueue": MUTATION,
    "merge-run-next": MUTATION,
    "post-merge-verify-remediate": MUTATION,
    "phase-teardown-run": MUTATION,
    "advance-wave": MUTATION,
    "write-blocker-report": MUTATION,
    "finalize-completion": MUTATION,
    "suggest-cleanup": MUTATION,
    "inflight-signal-clear": MUTATION,
}


class UnclassifiedActionError(ValueError):
    """Raised when a mechanical action lacks a precedence class."""


class PrecedenceViolationError(ValueError):
    """Raised when an emitted action sequence violates class ordering."""


def precedence_class(action: str) -> int:
    """Return the ordered precedence class for a mechanical action."""
    try:
        return ACTION_PRECEDENCE_CLASS[action]
    except KeyError as exc:
        raise UnclassifiedActionError(f"unclassified mechanical action: {action!r}") from exc


def assert_action_classified(action: str) -> int:
    return precedence_class(action)


def assert_monotonic_sequence(actions: list[str]) -> None:
    """Fail when a lower-numbered class follows a higher-numbered class."""
    max_seen = 0
    for action in actions:
        cls = assert_action_classified(action)
        if cls < max_seen:
            label = CLASS_LABELS.get(cls, str(cls))
            prior = CLASS_LABELS.get(max_seen, str(max_seen))
            raise PrecedenceViolationError(
                f"precedence violation: {action!r} ({label}) scheduled after {prior} class"
            )
        max_seen = max(max_seen, cls)


def record_action_precedence(steps_taken: list[dict[str, Any]], action: str) -> None:
    """Append an action to steps_taken and assert monotonic class ordering."""
    assert_action_classified(action)
    prior_actions = [str(step.get("action") or "") for step in steps_taken if step.get("action")]
    assert_monotonic_sequence([*prior_actions, action])
    steps_taken.append({"action": action, "precedenceClass": precedence_class(action)})
