"""PRD 331 D6, R37, R41, R47 — exploration store lifecycle and optimistic revision."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from exploration_model import (  # noqa: E402
    apply_supersession_invalidation,
    invalidate_dependent_output,
)
from exploration_store import (  # noqa: E402
    ExplorationStore,
    PersistenceRefusedError,
    StaleRevisionError,
    persistence_required,
)


def _conversation_map(**overrides: object) -> dict:
    doc = {
        "id": "explore-conversation",
        "version": "ExplorationMap@v1",
        "revision": 1,
        "destination": {
            "statement": "Explore whether storage should persist conversation-only sessions.",
            "nonCommittal": True,
        },
        "structuredFields": {},
        "nodes": [],
        "persistenceTriggers": {
            "blockingUnknowns": False,
            "resumeRequired": False,
            "promoteReceipt": None,
        },
        "provenance": {"createdAt": "2026-08-25T00:00:00Z", "source": "conversation"},
    }
    doc.update(overrides)
    return doc


def _blocking_unknowns_map(**overrides: object) -> dict:
    doc = _conversation_map(
        id="explore-blocking",
        persistenceTriggers={
            "blockingUnknowns": True,
            "resumeRequired": False,
            "promoteReceipt": None,
        },
        structuredFields={
            "unknowns": [
                {
                    "id": "unk-1",
                    "statement": "Which persistence backend is canonical?",
                    "classification": "blocking",
                }
            ]
        },
    )
    doc.update(overrides)
    return doc


def test_persistence_required_only_on_allowed_triggers() -> None:
    assert persistence_required({"blockingUnknowns": False, "resumeRequired": False, "promoteReceipt": None}) is False
    assert persistence_required({"blockingUnknowns": True, "resumeRequired": False, "promoteReceipt": None}) is True
    assert persistence_required({"blockingUnknowns": False, "resumeRequired": True, "promoteReceipt": None}) is True
    assert persistence_required(
        {
            "blockingUnknowns": False,
            "resumeRequired": False,
            "promoteReceipt": {"receiptId": "rcpt-1", "issuedAt": "2026-08-25T00:00:00Z"},
        }
    ) is True


def test_conversation_only_session_no_persist(tmp_path: Path) -> None:
    store = ExplorationStore(tmp_path)
    created = store.create(_conversation_map())
    assert created["persisted"] is False
    with pytest.raises(PersistenceRefusedError):
        store.persist("explore-conversation", expected_revision=1)
    assert not (tmp_path / ".cursor" / "sw-explore-maps" / "explore-conversation" / "map.json").exists()


def test_persistence_trigger_blocking_unknowns(tmp_path: Path) -> None:
    store = ExplorationStore(tmp_path)
    store.create(_blocking_unknowns_map())
    result = store.persist("explore-blocking", expected_revision=1)
    assert result["persisted"] is True
    path = Path(result["path"])
    assert path.is_file()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["id"] == "explore-blocking"


def test_persistence_trigger_resume_required(tmp_path: Path) -> None:
    store = ExplorationStore(tmp_path)
    store.create(
        _conversation_map(
            id="explore-resume",
            persistenceTriggers={
                "blockingUnknowns": False,
                "resumeRequired": True,
                "promoteReceipt": None,
            },
        )
    )
    result = store.persist("explore-resume", expected_revision=1)
    assert result["persisted"] is True


def test_persistence_trigger_promote_receipt(tmp_path: Path) -> None:
    store = ExplorationStore(tmp_path)
    store.create(
        _conversation_map(
            id="explore-promote",
            persistenceTriggers={
                "blockingUnknowns": False,
                "resumeRequired": False,
                "promoteReceipt": {
                    "receiptId": "promote-rcpt-1",
                    "issuedAt": "2026-08-25T01:00:00Z",
                    "actor": "operator",
                },
            },
        )
    )
    result = store.persist("explore-promote", expected_revision=1)
    assert result["persisted"] is True


def test_stale_concurrent_resume_rejection(tmp_path: Path) -> None:
    store = ExplorationStore(tmp_path)
    store.create(_blocking_unknowns_map())
    with pytest.raises(StaleRevisionError) as exc:
        store.update(
            "explore-blocking",
            {"destination": {"statement": "Updated", "nonCommittal": True}},
            expected_revision=2,
        )
    assert exc.value.expected == 2
    assert exc.value.actual == 1
    store.update(
        "explore-blocking",
        {"destination": {"statement": "Updated", "nonCommittal": True}},
        expected_revision=1,
    )
    with pytest.raises(StaleRevisionError):
        store.persist("explore-blocking", expected_revision=1)


def test_idempotent_promote_receipt(tmp_path: Path) -> None:
    store = ExplorationStore(tmp_path)
    store.create(
        _conversation_map(
            id="explore-idempotent",
            persistenceTriggers={
                "blockingUnknowns": False,
                "resumeRequired": False,
                "promoteReceipt": {
                    "receiptId": "promote-rcpt-dup",
                    "issuedAt": "2026-08-25T02:00:00Z",
                },
            },
        )
    )
    first = store.persist("explore-idempotent", expected_revision=1)
    second = store.persist("explore-idempotent", expected_revision=1)
    assert first["persisted"] is True
    assert second["idempotent"] is True


def test_read_hydrates_from_disk(tmp_path: Path) -> None:
    store = ExplorationStore(tmp_path)
    store.create(_blocking_unknowns_map())
    store.persist("explore-blocking", expected_revision=1)
    reloaded = ExplorationStore(tmp_path)
    out = reloaded.read("explore-blocking")
    assert out is not None
    assert out["source"] == "disk"
    assert out["map"]["revision"] == 1


def test_supersession_invalidation() -> None:
    map_doc = {
        "id": "explore-supersede",
        "version": "ExplorationMap@v1",
        "revision": 2,
        "destination": {"statement": "Destination", "nonCommittal": True},
        "structuredFields": {},
        "nodes": [
            {"id": "dec-1", "type": "decision", "status": "resolved", "title": "Use in-memory first"},
        ],
        "persistenceTriggers": {
            "blockingUnknowns": False,
            "resumeRequired": False,
            "promoteReceipt": None,
        },
        "provenance": {"createdAt": "2026-08-25T00:00:00Z", "source": "conversation"},
        "supersededNodeIds": [],
    }
    readiness = {
        "id": "readiness-1",
        "version": "PlanningReadiness@v1",
        "sourceRevision": 2,
        "explorationMapId": "explore-supersede",
        "unknowns": [],
        "invalidation": {"state": "valid"},
        "computedAt": "2026-08-25T01:00:00Z",
        "readyForDocHandoff": True,
    }
    brief = {
        "id": "brief-1",
        "version": "ExplorationBrief@v1",
        "sourceRevision": 2,
        "explorationMapId": "explore-supersede",
        "destination": {"statement": "Destination"},
        "readiness": {"readinessId": "readiness-1", "readyForDocHandoff": True},
        "planningUnitCandidates": [],
        "invalidation": {"state": "valid"},
        "emittedAt": "2026-08-25T01:00:00Z",
    }
    result = apply_supersession_invalidation(
        map_doc,
        readiness=readiness,
        brief=brief,
        decision_id="dec-1",
        successor={"id": "dec-2", "title": "Use conditional persistence", "status": "open"},
    )
    updated_map = result["map"]
    assert updated_map["revision"] == 3
    assert "dec-1" in updated_map["supersededNodeIds"]
    assert any(node.get("id") == "dec-2" for node in updated_map["nodes"])
    assert result["readiness"]["invalidation"]["state"] == "stale"
    assert result["readiness"]["readyForDocHandoff"] is False
    assert result["brief"]["invalidation"]["state"] == "stale"
    assert result["brief"]["readiness"]["readyForDocHandoff"] is False


def test_invalidate_dependent_output_keeps_valid_revision() -> None:
    readiness = {
        "sourceRevision": 4,
        "invalidation": {"state": "valid"},
        "readyForDocHandoff": True,
    }
    unchanged = invalidate_dependent_output(readiness, current_revision=4)
    assert unchanged["invalidation"]["state"] == "valid"
    assert unchanged["readyForDocHandoff"] is True
