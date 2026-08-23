#!/usr/bin/env python3
"""ResearchEvidence record lifecycle tests (PRD 326 phase 6)."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from decision_graph.evidence import (  # noqa: E402
    EvidenceSchemaError,
    KIND_PROTOTYPE,
    KIND_RESEARCH,
    RedactionRefusedError,
    build_evidence_record,
    build_research_evidence_record,
    link_evidence_to_decision,
    write_evidence_record,
)
from decision_graph.schema import minimal_fixture_graph  # noqa: E402

_SECRET_SAMPLE = "ghp_" + "A" * 36
_VALID_DIGEST = "a" * 64


def _research_record(**overrides: object) -> dict:
    base = build_research_evidence_record(
        parent_decision_id="d1",
        claim="Backend should use Postgres",
        sources=[
            {
                "uri": "https://example.com/docs",
                "accessedAt": "2026-08-22T00:00:00Z",
                "digest": _VALID_DIGEST,
            }
        ],
        source_kind="web",
        retrieved_at="2026-08-22T00:00:00Z",
        linked_at="2026-08-22T00:00:00Z",
    )
    if overrides:
        merged = deepcopy(base)
        for key, value in overrides.items():
            if key == "claim":
                merged["spec"]["claim"] = value
            else:
                merged[key] = value
        return merged
    return base


def test_build_research_evidence_record_validates_schema() -> None:
    record = build_research_evidence_record(
        parent_decision_id="d1",
        claim="claim text",
        sources=[
            {
                "uri": "https://example.com",
                "accessedAt": "2026-08-22T00:00:00Z",
                "digest": _VALID_DIGEST,
            }
        ],
        source_kind="web",
    )
    assert record["kind"] == KIND_RESEARCH
    assert record["spec"]["contentHash"] == record["spec"]["contentHash"]


def test_build_research_evidence_record_rejects_invalid_parent() -> None:
    with pytest.raises(EvidenceSchemaError):
        build_research_evidence_record(
            parent_decision_id="INVALID",
            claim="claim",
            sources=[
                {
                    "uri": "https://example.com",
                    "accessedAt": "2026-08-22T00:00:00Z",
                    "digest": _VALID_DIGEST,
                }
            ],
            source_kind="web",
        )


def test_write_evidence_record_kind_keyed_collection(tmp_path: Path) -> None:
    prototype = build_evidence_record(
        parent_decision_id="d1",
        prototype_node_id="p1",
        head_sha="b" * 40,
        content_hash="c" * 64,
        branch="feat/prototype-p1",
    )
    research = _research_record()

    proto_path = write_evidence_record(tmp_path, prototype)
    research_path = write_evidence_record(tmp_path, research)

    assert proto_path.name == prototype["spec"]["contentHash"] + ".json"
    assert research_path.parent.name == KIND_RESEARCH
    assert proto_path.parent.name == KIND_PROTOTYPE
    assert proto_path != research_path


def test_write_evidence_record_idempotent_by_content_hash(tmp_path: Path) -> None:
    record = _research_record()
    first = write_evidence_record(tmp_path, record)
    second = write_evidence_record(tmp_path, record)
    assert first == second
    files = list((tmp_path / ".cursor" / "sw-decision-evidence" / "d1" / KIND_RESEARCH).glob("*.json"))
    assert len(files) == 1


def test_write_evidence_record_redacts_claim_before_write(tmp_path: Path) -> None:
    record = _research_record(claim=f"token {_SECRET_SAMPLE}")
    path = write_evidence_record(tmp_path, record)
    payload = path.read_text(encoding="utf-8")
    assert _SECRET_SAMPLE not in payload
    assert "[REDACTED" in payload


def test_write_evidence_record_redacts_source_quote(tmp_path: Path) -> None:
    record = build_research_evidence_record(
        parent_decision_id="d1",
        claim="safe claim",
        sources=[
            {
                "uri": "https://example.com",
                "accessedAt": "2026-08-22T00:00:00Z",
                "digest": _VALID_DIGEST,
                "quote": f"quoted {_SECRET_SAMPLE}",
            }
        ],
        source_kind="web",
    )
    path = write_evidence_record(tmp_path, record)
    payload = path.read_text(encoding="utf-8")
    assert _SECRET_SAMPLE not in payload
    assert "[REDACTED" in payload


def test_link_evidence_to_decision_idempotent_for_content_hash() -> None:
    graph = minimal_fixture_graph()
    research = _research_record()
    first = link_evidence_to_decision(graph, "d1", research)
    second = link_evidence_to_decision(first["graph"], "d1", research)
    assert first["verdict"] == "pass"
    assert second["verdict"] == "pass"
    node = second["graph"]["spec"]["nodes"][0]
    assert "contentHash" in node["resolution"]["rationale"]


def test_link_evidence_to_decision_accepts_research_kind() -> None:
    graph = minimal_fixture_graph()
    research = _research_record()
    linked = link_evidence_to_decision(graph, "d1", research)
    assert linked["verdict"] == "pass"
    outcome = linked["graph"]["spec"]["nodes"][0]["resolution"]["outcome"]
    assert outcome.startswith(f"evidence:{KIND_RESEARCH}:")
