"""Injection port coverage for hermetic resilience harness (PRD 323 R7, R22)."""
from __future__ import annotations

from pathlib import Path

import pytest

from unit_tests.resilience.fuzz_transitions import DEFAULT_SEED, fuzz_transitions
from unit_tests.resilience.harness import (
    BOUNDARY_ORDER,
    InjectionBoundary,
    InjectionPlan,
    ResilienceHarness,
    TransitionRequest,
    new_fixture_root,
)


@pytest.mark.parametrize("boundary", BOUNDARY_ORDER)
def test_injection_port_observable(boundary: InjectionBoundary) -> None:
    root = new_fixture_root()
    harness = ResilienceHarness(root, plan=InjectionPlan(inject_at=frozenset({boundary})))
    result = harness.transition(
        TransitionRequest(actor="tester", generation=1, cache_identity="cache-a")
    )
    assert result.verdict == "injected"
    assert result.boundary == boundary
    journal = result.journal or {}
    assert boundary.value in journal.get("reached", [])
    assert boundary.value in journal.get("fired", [])


def test_injection_ports_without_plan_do_not_fire() -> None:
    root = new_fixture_root()
    harness = ResilienceHarness(root)
    result = harness.transition(
        TransitionRequest(actor="tester", generation=1, cache_identity="cache-a")
    )
    assert result.verdict == "pass"
    journal = result.journal or {}
    assert journal.get("fired") == []
    assert [item.value for item in BOUNDARY_ORDER] == journal.get("reached")


def test_fuzz_transitions_deterministic_seed() -> None:
    first = fuzz_transitions(seed=DEFAULT_SEED, max_depth=24, max_seconds=0.5)
    second = fuzz_transitions(seed=DEFAULT_SEED, max_depth=24, max_seconds=0.5)
    assert first.sequence == second.sequence
    assert first.transitions > 0


def test_check_gate_resilience_scope_ready(repo_root: Path) -> None:
    """PRD 323 R22 — check-gate readiness path recognizes resilience verify scope."""
    import check_gate_lib as gate

    runner = repo_root / "scripts/test/_runner.py"
    assert runner.is_file()
    text = runner.read_text(encoding="utf-8")
    assert '"resilience"' in text
    assert "run_resilience_verify" in text

    err = gate.validate_resilience_verify_scope(repo_root, {})
    assert err is None, err
