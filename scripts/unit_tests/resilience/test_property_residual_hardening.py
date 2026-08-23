#!/usr/bin/env python3
"""Residual property assertions for widened resilience state space (PRD 326 R4)."""
from __future__ import annotations

import random

import pytest

from unit_tests.resilience.harness import InjectionBoundary, InjectionPlan
from unit_tests.resilience.fuzz_transitions import (
    DEFAULT_SEED,
    FuzzFailureReport,
    fuzz_transitions,
    replay_fuzz,
    shrink_sequence,
)
from unit_tests.resilience.property_model import (
    PropertyHarness,
    PropertyTransitionKind,
    PropertyTransitionRequest,
    RESIDUAL_TRANSITION_KINDS,
    assurance_non_decreasing,
    new_fixture_root,
)


def test_cancel_during_finalize_blocks_at_finalize() -> None:
    root = new_fixture_root()
    harness = PropertyHarness(root)
    result = harness.transition(
        PropertyTransitionRequest(
            actor="worker",
            generation=1,
            cache_identity="cache-a",
            node_id="node-cancel",
            kind=PropertyTransitionKind.CANCEL_DURING_FINALIZE,
        )
    )
    assert result.verdict == "blocked"
    assert result.cause == "cancel-during-finalize"
    assert result.boundary == InjectionBoundary.FINALIZE
    harness.fixture.sync_from_disk()
    assert harness.fixture.finalized is not True


def test_generation_fence_cache_race_blocks() -> None:
    root = new_fixture_root()
    harness = PropertyHarness(root)
    first = harness.transition(
        PropertyTransitionRequest(actor="worker", generation=1, cache_identity="cache-a")
    )
    assert first.verdict == "pass"
    harness.fixture.sync_from_disk()
    harness.fixture.finalized = False
    payload = harness.fixture.load()
    payload["finalized"] = False
    harness.fixture.save(payload)

    raced = harness.transition(
        PropertyTransitionRequest(
            actor="worker",
            generation=2,
            cache_identity="cache-b",
            kind=PropertyTransitionKind.GENERATION_FENCE_CACHE_RACE,
        )
    )
    assert raced.verdict == "blocked"
    assert raced.cause == "generation-fence-cache-race"
    assert raced.boundary == InjectionBoundary.CACHE


def test_merge_conflict_after_checkpoint_blocks() -> None:
    root = new_fixture_root()
    harness = PropertyHarness(root)
    result = harness.transition(
        PropertyTransitionRequest(
            actor="merger",
            generation=1,
            cache_identity="cache-merge",
            kind=PropertyTransitionKind.MERGE_CONFLICT_AFTER_CHECKPOINT,
        )
    )
    assert result.verdict == "blocked"
    assert result.cause == "merge-conflict-after-checkpoint"
    assert result.boundary == InjectionBoundary.FINALIZE
    harness.property.sync(root)
    assert harness.property.merge_conflict_open is True
    meta = harness.property.load(root)
    assert isinstance(meta.get("checkpoint"), dict)


@pytest.mark.parametrize("kind", RESIDUAL_TRANSITION_KINDS)
def test_residual_kinds_are_first_class(kind: PropertyTransitionKind) -> None:
    assert kind.value in {
        "cancel-during-finalize",
        "generation-fence-cache-race",
        "merge-conflict-after-checkpoint",
    }


def test_residual_transitions_preserve_assurance_via_injection_ports() -> None:
    root = new_fixture_root()
    harness = PropertyHarness(
        root,
        plan=InjectionPlan(inject_at=frozenset({InjectionBoundary.FINALIZE})),
    )
    before = harness.property.assurance_level
    harness.transition(
        PropertyTransitionRequest(
            actor="worker",
            generation=1,
            cache_identity="cache-assure",
            assurance_after=before + 1,
            kind=PropertyTransitionKind.CANCEL_DURING_FINALIZE,
        )
    )
    after = harness.property.assurance_level
    assert assurance_non_decreasing(before, after)
    assert after >= before


@pytest.mark.parametrize("seed", [11, 22, 33])
def test_widened_state_space_assurance_non_decrease(seed: int) -> None:
    rng = random.Random(seed)
    root = new_fixture_root()
    harness = PropertyHarness(root)
    assurance = harness.property.assurance_level
    for _ in range(8):
        generation = rng.randint(1, 4)
        cache_identity = f"cache-{rng.randint(0, 2)}"
        kind = rng.choice((*RESIDUAL_TRANSITION_KINDS, PropertyTransitionKind.STANDARD))
        before = harness.property.assurance_level
        harness.transition(
            PropertyTransitionRequest(
                actor=f"actor-{rng.randint(0, 2)}",
                generation=generation,
                cache_identity=cache_identity,
                assurance_after=before,
                kind=kind,
            )
        )
        after = harness.property.assurance_level
        assert assurance_non_decreasing(assurance, after)
        assurance = after


def test_fuzz_failure_report_records_seed_and_replay() -> None:
    report = fuzz_transitions(seed=DEFAULT_SEED, max_depth=12, max_seconds=0.25, include_residuals=True)
    assert report.seed == DEFAULT_SEED
    if isinstance(report, FuzzFailureReport):
        replayed = replay_fuzz(seed=report.seed, sequence=report.shrunkSequence)
        assert isinstance(replayed, FuzzFailureReport)
        assert replayed.seed == report.seed
        assert replayed.cause == report.cause
    else:
        replayed = replay_fuzz(seed=report.seed, sequence=tuple("standard" for _ in report.sequence))
        assert replayed.seed == DEFAULT_SEED


def test_shrink_sequence_is_minimal_or_singleton() -> None:
    steps = ("standard", "residual:cancel-during-finalize", "standard")
    shrunk = shrink_sequence(99, steps)
    assert len(shrunk) <= len(steps)
    assert len(shrunk) >= 1
