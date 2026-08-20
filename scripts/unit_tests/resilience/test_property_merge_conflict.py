#!/usr/bin/env python3
"""Property tests: merge conflicts never become implicit success (PRD 323 R6)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from unit_tests.resilience.harness import (  # noqa: E402
    InjectionBoundary,
    InjectionPlan,
    ResilienceHarness,
    TransitionRequest,
    new_fixture_root,
)


@pytest.mark.parametrize(
    "inject",
    [
        InjectionBoundary.ADMISSION,
        InjectionBoundary.LEASE,
        InjectionBoundary.CACHE,
        InjectionBoundary.FINALIZE,
    ],
)
def test_injected_conflict_boundary_not_pass(inject: InjectionBoundary) -> None:
    root = new_fixture_root()
    harness = ResilienceHarness(
        root,
        plan=InjectionPlan(inject_at=frozenset({inject})),
    )
    result = harness.transition(
        TransitionRequest(actor="merger", generation=1, cache_identity="c1")
    )
    assert result.verdict != "pass"
    assert result.verdict == "injected"
    assert result.boundary == inject
    # Durable finalize must not land on injected conflict
    assert harness.fixture.load().get("finalized") is not True


def test_lease_conflict_is_explicit_block() -> None:
    root = new_fixture_root()
    first = ResilienceHarness(root)
    # Hold lease without finalize by saving mid-state
    first.fixture.save(
        {
            "generation": 0,
            "leaseHolder": "owner-a",
            "cacheIdentity": "c1",
            "finalized": False,
        }
    )
    second = ResilienceHarness(root)
    result = second.transition(
        TransitionRequest(actor="owner-b", generation=1, cache_identity="c1")
    )
    assert result.verdict == "blocked"
    assert result.cause == "lease-held"
    assert result.verdict != "pass"
