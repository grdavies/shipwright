"""Property tests — stale generation cannot mutate durable state (PRD 323 R1)."""
from __future__ import annotations

import pytest

from unit_tests.resilience.property_model import PropertyHarness, PropertyTransitionRequest, new_fixture_root


def test_stale_generation_blocked_at_admission() -> None:
    root = new_fixture_root()
    harness = PropertyHarness(root)
    first = harness.transition(
        PropertyTransitionRequest(actor="writer", generation=2, cache_identity="cache-a")
    )
    assert first.verdict == "pass"
    harness.fixture.sync_from_disk()
    assert harness.fixture.generation == 2
    assert harness.fixture.finalized is True

    stale = harness.transition(
        PropertyTransitionRequest(actor="writer", generation=1, cache_identity="cache-a")
    )
    assert stale.verdict == "blocked"
    assert stale.cause == "stale-generation"
    harness.fixture.sync_from_disk()
    assert harness.fixture.generation == 2


@pytest.mark.parametrize("stale_generation", [0, 1])
def test_stale_generation_never_downgrades_durable_state(stale_generation: int) -> None:
    root = new_fixture_root()
    harness = PropertyHarness(root)
    harness.transition(
        PropertyTransitionRequest(actor="a", generation=3, cache_identity="cache-b")
    )
    before = harness.fixture.load()
    result = harness.transition(
        PropertyTransitionRequest(
            actor="b",
            generation=stale_generation,
            cache_identity="cache-b",
        )
    )
    assert result.verdict == "blocked"
    after = harness.fixture.load()
    assert after == before


def test_current_generation_may_advance() -> None:
    root = new_fixture_root()
    harness = PropertyHarness(root)
    harness.transition(
        PropertyTransitionRequest(actor="a", generation=1, cache_identity="cache-a")
    )
    harness.fixture.sync_from_disk()
    harness.fixture.finalized = False
    payload = harness.fixture.load()
    payload["finalized"] = False
    harness.fixture.save(payload)
    harness.fixture.sync_from_disk()

    advanced = harness.transition(
        PropertyTransitionRequest(actor="a", generation=2, cache_identity="cache-a")
    )
    assert advanced.verdict == "pass"
    harness.fixture.sync_from_disk()
    assert harness.fixture.generation == 2
