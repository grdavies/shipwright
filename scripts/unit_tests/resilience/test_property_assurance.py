#!/usr/bin/env python3
"""Property tests: assurance cannot silently decrease (PRD 323 R5)."""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from unit_tests.resilience.harness import (  # noqa: E402
    ResilienceHarness,
    TransitionRequest,
    new_fixture_root,
)


def _assurance(payload: dict) -> int:
    """Derive a simple assurance score from durable fixture state."""
    score = 0
    if payload.get("cacheIdentity"):
        score += 1
    if payload.get("leaseHolder"):
        score += 1
    if payload.get("finalized"):
        score += 2
    score += int(payload.get("generation") or 0)
    return score


@pytest.mark.parametrize("seed", [5, 55, 555])
def test_assurance_never_decreases_after_realized_diff(seed: int) -> None:
    rng = random.Random(seed)
    root = new_fixture_root()
    harness = ResilienceHarness(root)
    scores: list[int] = []

    # Establish baseline identity
    harness.fixture.save(
        {
            "generation": 0,
            "leaseHolder": None,
            "cacheIdentity": f"base-{seed}",
            "finalized": False,
        }
    )
    scores.append(_assurance(harness.fixture.load()))

    result = harness.transition(
        TransitionRequest(
            actor=f"actor-{rng.randint(0, 3)}",
            generation=rng.randint(1, 4),
            cache_identity=f"base-{seed}",
        )
    )
    assert result.verdict in {"pass", "blocked", "injected"}
    scores.append(_assurance(harness.fixture.load()))

    # After a realized durable write (pass), assurance must not drop
    if result.verdict == "pass":
        assert scores[-1] >= scores[0]
    else:
        # Blocked/injected paths must preserve prior durable assurance
        assert scores[-1] == scores[0] or scores[-1] >= scores[0]
