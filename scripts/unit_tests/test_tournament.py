"""Unit tests for tournament_lib (PRD 064 R5/R6)."""
from __future__ import annotations

import tournament_lib as lib


def test_resolve_tournament_defaults_disabled():
    cfg = lib.resolve_tournament_config({})
    assert cfg["enabled"] is False
    assert cfg["n"] == 3


def test_should_run_disabled_by_default():
    divergence = {"candidates": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
    out = lib.should_run_tournament(divergence, lib.resolve_tournament_config({}))
    assert out["useTournament"] is False


def test_should_run_when_enabled_with_candidates():
    divergence = {"candidates": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}
    cfg = lib.resolve_tournament_config({"tournament": {"enabled": True, "n": 3}})
    out = lib.should_run_tournament(divergence, cfg)
    assert out["useTournament"] is True


def test_build_bracket_deterministic_for_three():
    plan = lib.plan_attempts(
        {"candidates": [{"id": "a"}, {"id": "b"}, {"id": "c"}]},
        lib.resolve_tournament_config({"tournament": {"enabled": True}}),
    )
    bracket = lib.build_bracket(plan)
    assert bracket["pairings"][0]["a"] == "attempt-1"
    assert bracket["pairings"][0]["b"] == "attempt-2"


def test_advance_bracket_to_champion():
    bracket = {"round": 1, "attemptIds": ["attempt-1", "attempt-2"], "completedMatches": []}
    results = [{"matchId": "match-1", "winnerId": "attempt-1", "verdict": "complete"}]
    out = lib.advance_bracket(bracket, results)
    assert out["complete"] is True
    assert out["winnerId"] == "attempt-1"
