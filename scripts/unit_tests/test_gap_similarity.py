"""Unit tests for gap_similarity_lib (PRD 064 R24/R25)."""
from __future__ import annotations

import gap_similarity_lib as lib


def test_feature_vector_deterministic():
    a = lib.feature_vector("gap unit title summary", dim=64)
    b = lib.feature_vector("gap unit title summary", dim=64)
    assert a == b


def test_cosine_identical_text_is_one():
    text = "semantic near duplicate detection"
    vec = lib.feature_vector(text, dim=128)
    assert lib.cosine_similarity(vec, vec) == 1.0


def test_empty_candidate_is_clear():
    result = lib.scan_candidate("", [{"unitId": "gap-1", "title": "x", "status": "open", "text": "x"}])
    assert result["verdict"] == "clear"
    assert result["autoSuppress"] is False


def test_high_tier_for_terminal_match():
    corpus = [
        {
            "unitId": "gap-resolved",
            "title": "Fix flaky CI gate on merge",
            "status": "resolved",
            "text": "Fix flaky CI gate on merge",
        }
    ]
    result = lib.scan_candidate(
        "Fix flaky CI gate on merge path",
        corpus,
        {"highThreshold": 0.5, "softThreshold": 0.4, "featureDim": 256},
    )
    assert result["autoSuppress"] is False
    assert result["verdict"] == "flag-for-review"
    assert result["matches"][0]["tier"] == "high-terminal"


def test_soft_tier_for_open_match():
    corpus = [
        {
            "unitId": "gap-open",
            "title": "Improve brainstorm candidate intake",
            "status": "open",
            "text": "Improve brainstorm candidate intake",
        }
    ]
    result = lib.scan_candidate(
        "Improve brainstorm candidate intake flow",
        corpus,
        {"highThreshold": 0.95, "softThreshold": 0.4, "featureDim": 256},
    )
    assert result["autoSuppress"] is False
    assert any(m["tier"] == "soft-open" for m in result["matches"])


def test_handoff_summary_lists_matches():
    scan = {
        "candidateText": "candidate",
        "matches": [
            {"unitId": "gap-1", "status": "open", "similarity": 0.9, "tier": "soft-open"}
        ],
    }
    summary = lib.format_handoff_summary(scan)
    assert "never auto-suppress" in summary.lower() or "flag-for-review" in summary
    assert "gap-1" in summary
