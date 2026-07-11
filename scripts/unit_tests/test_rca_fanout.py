"""Unit tests for rca_fanout_lib (PRD 064 R1/R2)."""
from __future__ import annotations

import rca_fanout_lib as lib


def test_resolve_fanout_defaults_disabled():
    cfg = lib.resolve_fanout_config({})
    assert cfg["enabled"] is False
    assert cfg["min_hypotheses"] == 3
    assert cfg["max_width"] == 4


def test_should_fanout_disabled_by_default():
    signal = {"type": "sentry", "excerpt": "Error: boom\nError: other"}
    out = lib.should_fanout(signal, lib.resolve_fanout_config({}))
    assert out["useFanout"] is False
    assert out["d5Gate"] == "single-context-default"


def test_should_fanout_when_enabled_and_ambiguous():
    signal = {"type": "user_report", "description": "broken", "ambiguous": True}
    cfg = lib.resolve_fanout_config({"rca": {"fanout": {"enabled": True}}})
    out = lib.should_fanout(signal, cfg)
    assert out["useFanout"] is True
    assert out["d5Gate"] == "fan-out"


def test_plan_generators_caps_at_four():
    signal = {
        "excerpt": "Error: one",
        "diff": "sha123",
        "data": {"q": 1},
        "config": {"env": "prod"},
    }
    cfg = lib.resolve_fanout_config({"rca": {"fanout": {"enabled": True, "max_width": 4}}})
    plan = lib.plan_generators(signal, cfg)
    assert plan["generatorCount"] <= 4
    assert plan["mode"] == "fan-out"


def test_synthesize_dedupes_hypotheses():
    results = [
        {"generatorId": "gen-1", "hypotheses": [{"id": "h1", "statement": "Config drift", "evidenceFor": ["a"]}]},
        {"generatorId": "gen-2", "hypotheses": [{"id": "h2", "statement": "config drift", "evidenceFor": ["b"]}]},
    ]
    out = lib.synthesize_hypotheses(results, min_hypotheses=1)
    assert out["hypothesisCount"] == 1
    assert out["survivors"][0]["sources"] == ["gen-1", "gen-2"]


def test_refuter_survives_requires_causal_chain():
    hyp = {"id": "h1", "statement": "stale cache"}
    incomplete = lib.evaluate_refutation(hyp, {"verdict": "survives", "causalChainComplete": False})
    assert incomplete["survives"] is False
    complete = lib.evaluate_refutation(hyp, {"verdict": "survives", "causalChainComplete": True})
    assert complete["survives"] is True


def test_evaluate_survivors_route_ready():
    results = [
        lib.evaluate_refutation({"id": "h1", "statement": "a"}, {"verdict": "refuted"}),
        lib.evaluate_refutation({"id": "h2", "statement": "b"}, {"verdict": "survives", "causalChainComplete": True}),
    ]
    out = lib.evaluate_survivors(results)
    assert out["routeReady"] is True
    assert out["survivorCount"] == 1
