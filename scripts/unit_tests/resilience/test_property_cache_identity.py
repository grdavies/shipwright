#!/usr/bin/env python3
"""Property tests: invalid cache identity fails closed (PRD 323 R3)."""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from unit_tests.resilience.harness import (  # noqa: E402
    InjectionBoundary,
    ResilienceHarness,
    TransitionRequest,
    new_fixture_root,
)


@pytest.mark.parametrize("seed", [3, 33, 333, 3333])
def test_cache_identity_mismatch_blocks(seed: int) -> None:
    rng = random.Random(seed)
    root = new_fixture_root()
    # Seed fixture with an established cache identity without finalizing via direct save
    harness = ResilienceHarness(root)
    harness.fixture.cache_identity = f"canon-{seed}"
    harness.fixture.generation = 0
    harness.fixture.save(
        {
            "generation": 0,
            "leaseHolder": None,
            "cacheIdentity": f"canon-{seed}",
            "finalized": False,
        }
    )

    bad = f"other-{rng.randint(0, 10_000)}"
    result = harness.transition(
        TransitionRequest(
            actor="worker",
            generation=1,
            cache_identity=bad,
        )
    )
    assert result.verdict == "blocked"
    assert result.boundary == InjectionBoundary.CACHE
    assert result.cause == "cache-identity-mismatch"
    assert harness.fixture.load()["cacheIdentity"] == f"canon-{seed}"
    assert harness.fixture.load()["finalized"] is False


def test_matching_cache_identity_may_pass() -> None:
    root = new_fixture_root()
    harness = ResilienceHarness(root)
    harness.fixture.save(
        {
            "generation": 0,
            "leaseHolder": None,
            "cacheIdentity": "same",
            "finalized": False,
        }
    )
    result = harness.transition(
        TransitionRequest(actor="worker", generation=1, cache_identity="same")
    )
    assert result.verdict == "pass"
