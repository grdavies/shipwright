"""Property tests — finalize checkpoint crash resume or typed halt (PRD 323 R4)."""
from __future__ import annotations

from unit_tests.resilience.harness import InjectionBoundary, InjectionPlan
from unit_tests.resilience.property_model import PropertyHarness, PropertyTransitionRequest, new_fixture_root


def test_finalize_injection_resumes_from_checkpoint() -> None:
    root = new_fixture_root()
    harness = PropertyHarness(
        root,
        plan=InjectionPlan(inject_at=frozenset({InjectionBoundary.FINALIZE})),
    )
    result = harness.transition(
        PropertyTransitionRequest(actor="worker", generation=1, cache_identity="cache-a")
    )
    assert result.verdict == "pass"
    harness.fixture.sync_from_disk()
    assert harness.fixture.finalized is True


def test_checkpoint_written_before_finalize_attempt() -> None:
    root = new_fixture_root()
    harness = PropertyHarness(root)
    harness.transition(
        PropertyTransitionRequest(
            actor="worker",
            generation=2,
            cache_identity="cache-x",
            node_id="n1",
        )
    )
    meta = harness.property.load(root)
    checkpoint = meta.get("checkpoint")
    assert isinstance(checkpoint, dict)
    assert checkpoint.get("generation") == 2
    assert checkpoint.get("cacheIdentity") == "cache-x"


def test_missing_checkpoint_halts_typed_on_finalize_crash() -> None:
    root = new_fixture_root()
    harness = PropertyHarness(root)
    harness.property.checkpoint = None
    harness.property.persist(root)
    result = harness._resume_from_checkpoint()
    assert result.verdict == "blocked"
    assert result.cause == "checkpoint-missing"
    assert result.boundary == InjectionBoundary.FINALIZE
