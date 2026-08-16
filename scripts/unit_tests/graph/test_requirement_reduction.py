#!/usr/bin/env python3
"""PRD 272 phase-2 requirement reduction authorization tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.detectors import (  # noqa: E402
    CAPABILITY_SUPPLY_CHAIN,
    authorize_reduction,
    compute_requirement_set,
    evaluate_redetect_gate,
    mechanical_no_fire_for_paths,
    record_human_waiver,
    run_detectors,
    union_required_capability_ids,
)
from graph.detectors.redetect import docs_only_paths, docs_only_then_migration_paths  # noqa: E402
from graph.detectors.registry import CAPABILITY_MIGRATION, DETECTOR_SUPPLY_CHAIN  # noqa: E402


def test_model_narrative_reduction_refused() -> None:
    auth = authorize_reduction(
        CAPABILITY_SUPPLY_CHAIN,
        model_narrative="no supply-chain review needed",
    )
    assert auth.authorized is False
    assert "model" in auth.reason

    waiver = record_human_waiver(
        capability_id=CAPABILITY_SUPPLY_CHAIN,
        actor="operator@test",
        reason="fixture waiver",
    )
    waived = authorize_reduction(
        CAPABILITY_SUPPLY_CHAIN,
        waivers=(waiver,),
        model_narrative="still ignored when waiver present",
    )
    assert waived.authorized is True
    assert waived.path == "human-waiver"
    assert waived.receipt is not None


def test_mechanical_no_fire_path_audited() -> None:
    no_fire = mechanical_no_fire_for_paths(
        CAPABILITY_SUPPLY_CHAIN,
        DETECTOR_SUPPLY_CHAIN,
        "1.0.0",
        ("README.md",),
        diff_digest="abc123",
    )
    assert no_fire is not None
    auth = authorize_reduction(CAPABILITY_SUPPLY_CHAIN, no_fire=(no_fire,))
    assert auth.authorized is True
    assert auth.receipt is not None
    assert auth.receipt["kind"] == "mechanical-no-fire"


def test_redetect_docs_only_grows_migration_blocks_ready() -> None:
    initial_paths = docs_only_paths()
    initial = compute_requirement_set(initial_paths)
    assert CAPABILITY_MIGRATION not in initial.required_capability_ids

    grown_paths = docs_only_then_migration_paths()
    verdict = evaluate_redetect_gate(
        changed_paths=grown_paths,
        dispatched=initial,
        satisfied_capability_ids=frozenset(),
        gate="barrier",
    )
    assert verdict.verdict == "fail"
    assert CAPABILITY_MIGRATION in verdict.unsatisfied

    satisfied = frozenset({CAPABILITY_MIGRATION})
    passing = evaluate_redetect_gate(
        changed_paths=grown_paths,
        dispatched=initial,
        satisfied_capability_ids=satisfied,
        gate="merge",
    )
    assert passing.verdict == "pass"
    assert CAPABILITY_MIGRATION in passing.dispatched.required_capability_ids


def test_automation_cannot_remove_dispatched_requirements() -> None:
    results, _ = run_detectors(("package.json",))
    dispatched = compute_requirement_set(("package.json",))
    assert union_required_capability_ids(results)

    shrunk_paths = ("README.md",)
    verdict = evaluate_redetect_gate(
        changed_paths=shrunk_paths,
        dispatched=dispatched,
        satisfied_capability_ids=frozenset(),
        gate="barrier",
    )
    assert verdict.verdict == "fail"
    assert verdict.removed
