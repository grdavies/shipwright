"""PRD 081 R19 — next-action precedence class fixtures."""

from __future__ import annotations

import pytest

from wave_action_precedence import (
    ACTION_PRECEDENCE_CLASS,
    EXCLUSION,
    MUTATION,
    READ_ONLY,
    PrecedenceViolationError,
    UnclassifiedActionError,
    assert_action_classified,
    assert_monotonic_sequence,
    precedence_class,
)
from wave_deliver_loop import MECHANICAL_ACTIONS


def test_every_mechanical_action_is_classified() -> None:
    for action in sorted(MECHANICAL_ACTIONS):
        cls = assert_action_classified(action)
        assert cls in ACTION_PRECEDENCE_CLASS.values()


def test_unclassified_action_fails() -> None:
    with pytest.raises(UnclassifiedActionError):
        assert_action_classified("not-a-real-action")


def test_startup_sequence_is_monotonic() -> None:
    assert_monotonic_sequence(
        [
            "plan",
            "lock-acquire",
            "state-init",
            "base-capture",
            "spec-seed",
            "inflight-signal-write",
            "orchestrator-provision",
        ]
    )


def test_lock_after_mutation_fails() -> None:
    with pytest.raises(PrecedenceViolationError):
        assert_monotonic_sequence(["spec-seed", "lock-acquire"])


def test_validation_after_mutation_fails() -> None:
    with pytest.raises(PrecedenceViolationError):
        assert_monotonic_sequence(["base-capture", "plan"])


def test_spec_seed_is_mutating_class() -> None:
    assert precedence_class("spec-seed") == MUTATION
    assert precedence_class("lock-acquire") == EXCLUSION
    assert precedence_class("plan") == READ_ONLY


def test_emit_sequence_helper_rejects_unclassified_addition() -> None:
    sequence = ["plan", "lock-acquire"]
    with pytest.raises(UnclassifiedActionError):
        assert_monotonic_sequence([*sequence, "mystery-action"])
