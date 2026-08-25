"""PRD 331 R10, R19, R43, R44 — exploration evidence reuse and security boundaries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from decision_graph.evidence import (  # noqa: E402
    KIND_PROTOTYPE,
    KIND_RESEARCH,
    build_evidence_record,
    build_research_evidence_record,
    write_evidence_record,
)
from exploration_evidence import (  # noqa: E402
    ExplorationEvidenceError,
    attach_evidence_to_map,
    bind_prototype_evidence,
    bind_research_evidence,
    build_evidence_ref,
    digest_record,
    is_production_eligible,
    resolve_evidence_record,
    summarize_evidence_bindings,
    validate_evidence_ref,
)
from exploration_security import (  # noqa: E402
    ExplorationSecurityError,
    assert_secret_free,
    lookup_historical_context,
    redact_exploration_payload,
    sanitize_projection,
)
from memory_preflight import PreflightError  # noqa: E402

_SECRET_SAMPLE = "ghp_fixture_allowlisted_secret_scan_012345678901234567890"


def _sample_map() -> dict:
    return {
        "id": "explore-evidence",
        "version": "ExplorationMap@v1",
        "revision": 1,
        "destination": {"statement": "Bind evidence without parallel silos.", "nonCommittal": True},
        "structuredFields": {},
        "nodes": [
            {
                "id": "ev-1",
                "type": "evidence",
                "status": "open",
                "title": "Research claim",
            }
        ],
        "persistenceTriggers": {
            "blockingUnknowns": False,
            "resumeRequired": False,
            "promoteReceipt": None,
        },
        "provenance": {"createdAt": "2026-08-25T00:00:00Z", "source": "conversation"},
    }


def _research_record(parent: str = "dec-1") -> dict:
    return build_research_evidence_record(
        parent_decision_id=parent,
        claim="Users prefer conversation-first exploration.",
        sources=[
            {
                "uri": "https://example.com/research",
                "accessedAt": "2026-08-25T00:00:00Z",
                "digest": "a" * 64,
            }
        ],
        source_kind="interview",
    )


def _prototype_record(parent: str = "dec-1") -> dict:
    return build_evidence_record(
        parent_decision_id=parent,
        prototype_node_id="proto-1",
        head_sha="b" * 40,
        content_hash="c" * 64,
        branch="prototype/spike",
    )


def test_existing_evidence_contracts_are_reused(tmp_path: Path) -> None:
    bound = bind_research_evidence(
        tmp_path,
        parent_decision_id="dec-1",
        claim="Canonical research evidence is reused.",
        sources=[
            {
                "uri": "https://example.com/note",
                "accessedAt": "2026-08-25T00:00:00Z",
                "digest": "d" * 64,
            }
        ],
        source_kind="note",
        trust="trusted",
    )
    record = bound["record"]
    assert record["kind"] == KIND_RESEARCH
    evidence_ref = bound["evidenceRef"]
    assert evidence_ref["kind"] == KIND_RESEARCH
    resolved = resolve_evidence_record(tmp_path, evidence_ref, parent_decision_id="dec-1")
    assert resolved is not None
    assert resolved["spec"]["claim"] == record["spec"]["claim"]
    updated = attach_evidence_to_map(_sample_map(), node_id="ev-1", record=record, trust="trusted")
    summary = summarize_evidence_bindings(updated)
    assert summary["trusted"] == 1
    assert summary["untrusted"] == 0


def test_trusted_and_untrusted_evidence_classification(tmp_path: Path) -> None:
    research = bind_research_evidence(
        tmp_path,
        parent_decision_id="dec-1",
        claim="Trusted research",
        sources=[
            {
                "uri": "https://example.com/a",
                "accessedAt": "2026-08-25T00:00:00Z",
                "digest": "e" * 64,
            }
        ],
        source_kind="doc",
        trust="trusted",
    )
    prototype = bind_prototype_evidence(
        tmp_path,
        parent_decision_id="dec-1",
        prototype_node_id="proto-1",
        head_sha="f" * 40,
        content_hash="0" * 64,
        branch="prototype/spike",
        trust="untrusted",
    )
    assert research["evidenceRef"]["trust"] == "trusted"
    assert prototype["evidenceRef"]["trust"] == "untrusted"


def test_prototype_ineligibility(tmp_path: Path) -> None:
    bound = bind_prototype_evidence(
        tmp_path,
        parent_decision_id="dec-1",
        prototype_node_id="proto-1",
        head_sha="1" * 40,
        content_hash="2" * 64,
        branch="prototype/spike",
    )
    evidence_ref = bound["evidenceRef"]
    assert evidence_ref["productionEligible"] is False
    assert is_production_eligible(evidence_ref) is False


def test_no_duplicate_evidence_schema() -> None:
    research = _research_record()
    prototype = _prototype_record()
    assert digest_record(research) != digest_record(prototype)
    with pytest.raises(ExplorationEvidenceError):
        validate_evidence_ref({"kind": "CustomEvidence", "refId": "x", "trust": "trusted"})


def test_memory_lookup_is_brokered_and_redacted(tmp_path: Path) -> None:
    def _preflight(_root: Path) -> dict:
        return {"verdict": "ok", "provider": "in-repo", "rulesLoad": {"rules": []}}

    def _query(_root: Path, _query: str, _ctx: dict) -> dict:
        return {
            "results": [
                {
                    "snippet": (
                        "Historical note with "
                        f"{_SECRET_SAMPLE} secret"
                    )
                },
            ]
        }

    result = lookup_historical_context(
        tmp_path,
        "prior exploration",
        preflight=_preflight,
        query_fn=_query,
    )
    assert result["verdict"] == "ok"
    assert result["redacted"] is True
    assert _SECRET_SAMPLE not in result["results"][0]["snippet"]


def test_broker_refusal_is_non_blocking(tmp_path: Path) -> None:
    def _preflight_fail(_root: Path) -> dict:
        raise PreflightError("auth refused", cause="auth-refused")

    result = lookup_historical_context(tmp_path, "query", preflight=_preflight_fail)
    assert result["verdict"] == "degraded"
    assert result["cause"] == "auth-refused"
    assert result["results"] == []


def test_explore_trust_and_redaction_boundaries() -> None:
    payload = {
        "destination": {"statement": "Safe"},
        "notes": f"token={_SECRET_SAMPLE}",
    }
    redacted = redact_exploration_payload(payload, artifact_kind="map")
    assert _SECRET_SAMPLE not in json.dumps(redacted)
    assert_secret_free(redacted)
    with pytest.raises(ExplorationSecurityError):
        assert_secret_free({"apiKey": _SECRET_SAMPLE})


def test_projection_and_prototype_boundaries() -> None:
    canonical = _sample_map()
    projection = {
        "sourceRevision": 1,
        "frontier": [{"id": "ev-1", "label": "prototype spike"}],
        "prototypeEligible": False,
    }
    sanitized = sanitize_projection(projection, canonical_map=canonical)
    assert sanitized["prototypeEligible"] is False
    with pytest.raises(ExplorationSecurityError):
        sanitize_projection({"sourceRevision": 99, "frontier": []}, canonical_map=canonical)


def test_research_evidence_ref_round_trip(tmp_path: Path) -> None:
    record = _research_record()
    path = write_evidence_record(tmp_path, record)
    evidence_ref = build_evidence_ref(record, trust="trusted")
    resolved = resolve_evidence_record(tmp_path, evidence_ref, parent_decision_id="dec-1")
    assert resolved is not None
    assert path.is_file()
