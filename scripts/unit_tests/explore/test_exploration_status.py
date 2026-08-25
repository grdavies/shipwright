"""PRD 331 R22, R23, R43, R44, R45 — visualization and status projections."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from exploration_model import apply_supersession_invalidation  # noqa: E402
from exploration_projection import (  # noqa: E402
    build_local_projection,
    build_provider_projection,
    project_frontier,
    render_accessible_text,
    semantic_parity,
)
from exploration_security import (  # noqa: E402
    ExplorationSecurityError,
    assert_secret_free,
    sanitize_projection,
)
from exploration_store import ExplorationStore  # noqa: E402
from explore_command_contract import INTERACTION_STATES  # noqa: E402
from status_collect import collect_explain_decision, collect_exploration_summary  # noqa: E402

_SECRET_SAMPLE = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _init_git(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("# sample\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)


def _sample_map(**overrides: object) -> dict:
    doc: dict = {
        "id": "explore-status",
        "version": "ExplorationMap@v1",
        "revision": 1,
        "destination": {
            "statement": "Expose exploration status without mutating canonical maps.",
            "nonCommittal": True,
        },
        "structuredFields": {
            "problem": "Operators need status projections.",
            "outcomes": ["Read-only status surfaces"],
            "successCriteria": ["No canonical mutation from status"],
            "unknowns": [],
        },
        "nodes": [
            {
                "id": "q-open",
                "type": "question",
                "status": "open",
                "statement": "Which projection mode is active?",
            }
        ],
        "interaction": {"state": "ask"},
        "persistenceTriggers": {
            "blockingUnknowns": False,
            "resumeRequired": False,
            "promoteReceipt": None,
        },
        "provenance": {"createdAt": "2026-08-25T00:00:00Z", "source": "conversation"},
        "supersededNodeIds": [],
    }
    doc.update(overrides)
    return doc


def test_provider_and_local_projection_semantic_parity() -> None:
    map_doc = _sample_map()
    local = build_local_projection(map_doc)

    def provider_ok(document: dict) -> dict:
        return {
            "verdict": "ok",
            "visualization": {
                "nodes": [
                    {"id": node["id"], "label": node.get("statement") or node.get("title")}
                    for node in document.get("nodes") or []
                    if isinstance(node, dict)
                ]
            },
        }

    provider = build_provider_projection(map_doc, provider_ok)
    parity = semantic_parity(local, provider)
    assert parity["verdict"] == "pass"
    assert local["frontier"]["readyCount"] == 1
    assert provider["mode"] == "provider"
    assert provider["visualizationAvailable"] is True


def test_provider_error_degrades_to_local_parity() -> None:
    map_doc = _sample_map()

    def provider_error(_document: dict) -> dict:
        return {"verdict": "degraded", "cause": "viz-unavailable"}

    provider = build_provider_projection(map_doc, provider_error)
    local = build_local_projection(map_doc)
    assert provider["mode"] == "local"
    assert provider["degradedToLocal"] is True
    assert semantic_parity(local, provider)["verdict"] == "pass"


def test_status_explains_active_and_superseded_decisions(tmp_path: Path) -> None:
    _init_git(tmp_path)
    store = ExplorationStore(tmp_path)
    map_doc = _sample_map(
        revision=2,
        nodes=[
            {
                "id": "dec-1",
                "type": "decision",
                "status": "superseded",
                "title": "Use local fallback first",
                "rationale": "Provider visualization may be unavailable.",
            },
            {
                "id": "dec-2",
                "type": "decision",
                "status": "open",
                "title": "Prefer text fallback",
                "supersedes": "dec-1",
            },
        ],
        supersededNodeIds=["dec-1"],
    )
    store.create(map_doc)

    active = collect_explain_decision(tmp_path, "explore-status", "dec-2", store=store)
    assert active["verdict"] == "pass"
    assert active["active"] is True
    assert active["superseded"] is False
    assert active["supersedes"] == "dec-1"

    superseded = collect_explain_decision(tmp_path, "explore-status", "dec-1", store=store)
    assert superseded["verdict"] == "pass"
    assert superseded["superseded"] is True
    assert superseded["successorDecisionIds"] == ["dec-2"]

    missing = collect_explain_decision(tmp_path, "explore-status", "dec-missing", store=store)
    assert missing["verdict"] == "fail"
    assert missing["error"] == "decision-not-found"


def test_explore_trust_and_redaction_boundaries() -> None:
    map_doc = _sample_map(
        structuredFields={
            "problem": f"Token leak {_SECRET_SAMPLE}",
            "outcomes": ["Redact secrets in projections"],
            "successCriteria": ["No secret keys in output"],
            "unknowns": [],
        }
    )
    projection = build_local_projection(map_doc)
    assert _SECRET_SAMPLE not in json.dumps(projection)
    assert_secret_free(projection)

    summary_map = _sample_map(
        structuredFields={
            "problem": "Safe summary",
            "outcomes": ["ok"],
            "successCriteria": ["ok"],
            "unknowns": [],
        }
    )
    store = ExplorationStore(Path("/tmp"))
    store._maps["explore-status"] = summary_map  # noqa: SLF001 — test fixture
    payload = collect_exploration_summary(Path("/tmp"), "explore-status", store=store)
    assert payload["verdict"] == "pass"
    assert payload["readOnly"] is True
    assert "apiKey" not in json.dumps(payload)


def test_projection_and_prototype_boundaries() -> None:
    map_doc = _sample_map(
        nodes=[
            {"id": "proto-1", "type": "question", "status": "open", "prototype": True, "statement": "Spike"},
            {"id": "q-open", "type": "question", "status": "open", "statement": "Real question"},
        ]
    )
    projection = build_local_projection(map_doc)
    summaries = projection["frontier"]["nodeSummaries"]
    proto = next(item for item in summaries if item["nodeId"] == "proto-1")
    real = next(item for item in summaries if item["nodeId"] == "q-open")
    assert proto["productionEligible"] is False
    assert real["productionEligible"] is True

    mutated = dict(projection)
    mutated["sourceRevision"] = 999
    with pytest.raises(ExplorationSecurityError, match="projection-above-canonical"):
        sanitize_projection(mutated, canonical_map=map_doc)


def test_interaction_matrix_and_accessible_recovery() -> None:
    for state in INTERACTION_STATES:
        map_doc = _sample_map(interaction={"state": state})
        projection = build_local_projection(map_doc)
        assert projection["interactionState"] == state
        text = render_accessible_text(projection)
        assert state in text
        assert "/sw-explore" in text
        assert projection["visualizationAvailable"] is False
        assert projection["textFallback"]


def test_supersession_status_round_trip_without_canonical_mutation() -> None:
    map_doc = _sample_map(
        nodes=[{"id": "dec-1", "type": "decision", "status": "open", "title": "Initial"}],
    )
    readiness = {
        "id": "readiness-explore-status",
        "version": "PlanningReadiness@v1",
        "sourceRevision": 1,
        "explorationMapId": "explore-status",
        "unknowns": [],
        "invalidation": {"state": "valid"},
        "computedAt": "2026-08-25T01:00:00Z",
        "readyForDocHandoff": True,
    }
    before = json.dumps(map_doc, sort_keys=True)
    apply_supersession_invalidation(
        map_doc,
        readiness=readiness,
        decision_id="dec-1",
        successor={"id": "dec-2", "type": "decision", "title": "Updated"},
    )
    bundle = project_frontier(map_doc)
    assert bundle["verdict"] == "pass"
    assert json.dumps(map_doc, sort_keys=True) == before
