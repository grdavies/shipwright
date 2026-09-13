"""Reviewer independence + lineage hashes — PRD 351 phase 2 (TS3, R10–R14)."""
from __future__ import annotations

import hashlib
import json
import re

import pytest

from graph.reviewer_metrics.selection import (
    UnresolvableIdentity,
    assertion_meets_requirement,
    build_independence_record,
    compute_lineage_hash,
    evaluate_independence,
)

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")


def test_inherit_model_id_raises_unresolvable_identity() -> None:
    """TS3 / R10 — model_id='inherit' raises UnresolvableIdentity."""
    with pytest.raises(UnresolvableIdentity):
        evaluate_independence({"model_id": "inherit"})


@pytest.mark.parametrize("model_id", ["parent", "auto", "", "${MODEL}", "{placeholder}"])
def test_unresolved_placeholders_raise(model_id: str) -> None:
    with pytest.raises(UnresolvableIdentity):
        evaluate_independence({"model_id": model_id})


def test_same_concrete_model_different_tier_labels_not_independent() -> None:
    """TS3 / R11 — identical (provider, model, version) is not independent."""
    result = evaluate_independence(
        {
            "model_id": "claude-opus-4",
            "author_model_identity": ("anthropic", "claude-opus-4", "20250901"),
            "reviewer_model_identity": ("anthropic", "claude-opus-4", "20250901"),
            "author_tier_label": "build",
            "reviewer_tier_label": "deep",
        }
    )
    assert result["independent"] is False
    assert result["assertion_status"] == "verified"


def test_distinct_version_tuples_are_independent() -> None:
    result = evaluate_independence(
        {
            "model_id": "claude-opus-4",
            "author_identity": ("anthropic", "claude-opus-4", "20250901"),
            "reviewer_identity": ("anthropic", "claude-opus-4", "20250902"),
        }
    )
    assert result["independent"] is True
    assert result["assertion_status"] == "verified"


def test_unverified_does_not_satisfy_verified_requirement() -> None:
    """R14 — unverified must not satisfy a verified requirement."""
    result = evaluate_independence(
        {
            "model_id": "gpt-5",
            "author_model_identity": ("openai", "gpt-5", "1"),
        }
    )
    assert result["assertion_status"] == "unverified"
    assert assertion_meets_requirement("unverified", "verified") is False
    assert assertion_meets_requirement("verified", "verified") is True


def test_lineage_hash_is_sha256_hex_and_redacts_prompt() -> None:
    """R13 — SHA-256 hex; raw prompt excluded from hash input."""
    context = {
        "task_type": "implement",
        "raw_prompt": "SYSTEM PROMPT: secret instructions",
        "api_key": "sk-test",
        "model": "claude-opus-4",
    }
    digest = compute_lineage_hash(context, ["model"])
    assert SHA256_HEX.match(digest)
    expected = hashlib.sha256(
        json.dumps({"task_type": "implement"}, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    assert digest == expected


def test_build_independence_record_unverified_without_reviewer() -> None:
    record = build_independence_record(
        author_model_identity=("anthropic", "claude-opus-4", "1"),
        reviewer_model_identity=None,
        author_context={"task_type": "review"},
        external_finding_count=2,
    )
    assert record["assertion_status"] == "unverified"
    assert record["reviewer_lineage_hash"] is None
    assert record["external_finding_count"] == 2
    assert record["author_lineage_hash"] is not None
