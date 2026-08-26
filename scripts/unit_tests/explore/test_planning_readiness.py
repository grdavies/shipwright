"""PRD 331 R11, R12, R20, R31, R41 — planning readiness and candidate decomposition."""

from __future__ import annotations

from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from exploration_decompose import (  # noqa: E402
    AUTHORITY_BOUNDARY,
    PlanningWriteForbiddenError,
    assert_no_planning_writes,
    decompose,
    derive_candidates,
)
from planning_readiness import (  # noqa: E402
    PlanningReadinessError,
    assert_fresh,
    collect_unknowns,
    compute_readiness,
    invalidate_readiness,
    recompute_if_stale,
    refuse_invalidated,
    summarize_unknowns,
)


def _sample_map(**overrides: object) -> dict:
    doc: dict = {
        "id": "explore-readiness",
        "version": "ExplorationMap@v1",
        "revision": 1,
        "destination": {
            "statement": "Derive readiness and bounded planning-unit candidates.",
            "nonCommittal": True,
        },
        "structuredFields": {
            "problem": "Operators need deterministic readiness before doc handoff.",
            "outcomes": ["Classify unknowns without creating planning artifacts"],
            "successCriteria": ["Readiness cites source revision"],
            "unknowns": [
                {
                    "id": "unk-blocking",
                    "statement": "Which intelligence hooks are mandatory?",
                    "classification": "blocking",
                },
                {
                    "id": "unk-deferred",
                    "statement": "Optional visualization provider",
                    "classification": "deferred",
                },
            ],
            "planningUnitCandidates": [
                {
                    "id": "unit-schemas",
                    "title": "Exploration artifact schemas",
                    "rationale": "Contracts precede consumer surfaces.",
                },
                {
                    "id": "unit-storage",
                    "title": "Exploration storage lifecycle",
                    "rationale": "Lifecycle before consumers.",
                    "dependencies": ["unit-schemas"],
                },
            ],
            "candidateApproaches": ["Schema-first rollout", "Storage-first rollout"],
        },
        "nodes": [
            {
                "id": "q-open",
                "type": "question",
                "status": "open",
                "statement": "What is the atomic release boundary?",
            },
            {
                "id": "disc-1",
                "type": "discovery",
                "status": "open",
                "statement": "Conversation-first promotion reduces premature doc routing.",
                "linkedNodeIds": ["q-open"],
            },
        ],
        "persistenceTriggers": {
            "blockingUnknowns": True,
            "resumeRequired": False,
            "promoteReceipt": None,
        },
        "provenance": {"createdAt": "2026-08-25T00:00:00Z", "source": "conversation"},
    }
    doc.update(overrides)
    return doc


def test_planning_readiness_v1_is_deterministic() -> None:
    map_doc = _sample_map()
    first = compute_readiness(map_doc, computed_at="2026-08-25T01:00:00Z")
    second = compute_readiness(map_doc, computed_at="2026-08-25T01:00:00Z")
    assert first == second
    assert first["version"] == "PlanningReadiness@v1"
    assert first["sourceRevision"] == 1
    assert first["explorationMapId"] == "explore-readiness"
    assert first["readyForDocHandoff"] is False


def test_unknown_classification_is_complete() -> None:
    map_doc = _sample_map(
        structuredFields={
            "unknowns": [
                {"id": "b", "statement": "Blocking item", "classification": "blocking"},
                {"id": "n", "statement": "Non-blocking item", "classification": "non-blocking"},
                {"id": "d", "statement": "Deferred item", "classification": "deferred"},
            ]
        },
        nodes=[],
    )
    unknowns = collect_unknowns(map_doc)
    classes = {item["classification"] for item in unknowns}
    assert classes == {"blocking", "non-blocking", "deferred"}
    summary = summarize_unknowns(unknowns)
    assert summary["blockingCount"] == 1
    assert summary["nonBlockingCount"] == 1
    assert summary["deferredCount"] == 1


def test_planning_readiness_empty_unknowns() -> None:
    map_doc = _sample_map(structuredFields={}, nodes=[])
    readiness = compute_readiness(map_doc, computed_at="2026-08-25T01:00:00Z")
    assert readiness["unknowns"] == []
    assert readiness["summary"]["blockingCount"] == 0
    assert readiness["readyForDocHandoff"] is True


def test_planning_readiness_many_unknowns_merges_questions() -> None:
    map_doc = _sample_map()
    unknowns = collect_unknowns(map_doc)
    assert len(unknowns) == 3
    assert any(item["id"] == "q-open" and item["classification"] == "blocking" for item in unknowns)


def test_planning_readiness_stale_source_revision() -> None:
    map_doc = _sample_map(revision=3)
    readiness = compute_readiness(map_doc, computed_at="2026-08-25T01:00:00Z")
    stale = invalidate_readiness(readiness, current_revision=4)
    assert stale["invalidation"]["state"] == "stale"
    assert stale["readyForDocHandoff"] is False
    with pytest.raises(PlanningReadinessError, match="readiness-invalidated"):
        refuse_invalidated(stale)
    with pytest.raises(PlanningReadinessError, match="stale-readiness"):
        assert_fresh(readiness, _sample_map(revision=4))


def test_recompute_if_stale_refreshes_readiness() -> None:
    map_doc = _sample_map(revision=2)
    stale = compute_readiness(_sample_map(revision=1), computed_at="2026-08-25T01:00:00Z")
    refreshed = recompute_if_stale(stale, map_doc, computed_at="2026-08-25T02:00:00Z")
    assert refreshed["sourceRevision"] == 2
    assert refreshed["invalidation"]["state"] == "valid"


def test_decomposition_returns_candidates_only() -> None:
    result = decompose(_sample_map())
    candidates = result["planningUnitCandidates"]
    assert candidates
    assert all("id" in item and "title" in item and "rationale" in item for item in candidates)
    assert [item["id"] for item in candidates] == sorted(item["id"] for item in candidates)
    assert result["authorityBoundary"] == AUTHORITY_BOUNDARY


def test_decomposition_emits_candidates_without_writes(tmp_path: Path) -> None:
    result = decompose(_sample_map())
    boundary = result["authorityBoundary"]
    assert boundary["createsPrds"] is False
    assert boundary["createsTasks"] is False
    assert boundary["dispatchesImplementation"] is False
    with pytest.raises(PlanningWriteForbiddenError):
        assert_no_planning_writes("docs/prds/331-sw-explore-first-release/331-prd.md")
    with pytest.raises(PlanningWriteForbiddenError):
        assert_no_planning_writes("docs/planning/unit-1/tasks.md")
    with pytest.raises(PlanningWriteForbiddenError):
        assert_no_planning_writes(str(tmp_path / "docs" / "prds" / "331-prd.md"))


def test_derive_candidates_minimal_map() -> None:
    map_doc = _sample_map(structuredFields={}, nodes=[])
    assert derive_candidates(map_doc) == []


def test_derive_candidates_many_sources() -> None:
    candidates = derive_candidates(_sample_map())
    ids = {item["id"] for item in candidates}
    assert "unit-schemas" in ids
    assert "unit-storage" in ids
    assert any(item["id"].startswith("approach-") for item in candidates)
    assert any(item["id"] == "discovery-disc-1" for item in candidates)
    storage = next(item for item in candidates if item["id"] == "unit-storage")
    assert storage["dependencies"] == ["unit-schemas"]

def test_decompose_refuses_invalidated_readiness() -> None:
    readiness = compute_readiness(_sample_map(), computed_at="2026-08-25T01:00:00Z")
    invalidated = invalidate_readiness(readiness, current_revision=2)
    with pytest.raises(PlanningReadinessError, match="readiness-invalidated"):
        decompose(_sample_map(), readiness=invalidated)
