"""PRD 331 R14, R15, R27, R41, R45 — exploration brief, handoff bundle, and resume."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from exploration_brief import (  # noqa: E402
    ExplorationBriefError,
    assert_fresh,
    brief_id_for_map,
    emit_brief,
    invalidate_brief,
    recompute_if_stale,
)
from exploration_model import invalidate_dependent_outputs  # noqa: E402
from handoff_bundle import (  # noqa: E402
    build_exploration_resume_context,
    build_workflow_digest,
    digest_payload,
    export_exploration_bundle,
    import_exploration_resume,
    validate_bundle,
)


def _repo_with_schema(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "core" / "sw-reference").mkdir(parents=True)
    for name in ("handoff-bundle.schema.json", "exploration-brief.schema.json"):
        src = SCRIPT_DIR.parent / "core" / "sw-reference" / name
        if src.is_file():
            (repo / "core" / "sw-reference" / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return repo


def _sample_map(**overrides: object) -> dict:
    doc: dict = {
        "id": "explore-handoff",
        "version": "ExplorationMap@v1",
        "revision": 1,
        "destination": {
            "statement": "Ship exploration brief and handoff resume for PRD 331.",
            "nonCommittal": True,
        },
        "structuredFields": {
            "problem": "Operators need resumable explore sessions.",
            "outcomes": ["Revision-bound brief", "Cross-session handoff"],
            "successCriteria": ["Stale derivations fail closed"],
            "unknowns": [
                {
                    "id": "unk-deferred",
                    "statement": "Optional visualization provider",
                    "classification": "deferred",
                }
            ],
            "planningUnitCandidates": [
                {
                    "id": "unit-handoff",
                    "title": "Exploration handoff bundle",
                    "rationale": "Resume without deliver dispatch.",
                }
            ],
        },
        "nodes": [
            {
                "id": "dec-auth",
                "type": "decision",
                "status": "resolved",
                "title": "Use HandoffBundle extensions",
                "resolution": "extensions.exploration carries resume context",
            },
            {
                "id": "ev-1",
                "type": "evidence",
                "status": "resolved",
                "title": "Prior notebook graduation",
                "evidenceRef": {
                    "kind": "ResearchEvidence",
                    "refId": "sha256:abc123",
                    "trust": "trusted",
                },
            },
        ],
        "persistenceTriggers": {
            "blockingUnknowns": False,
            "resumeRequired": True,
            "promoteReceipt": None,
        },
        "provenance": {
            "createdAt": "2026-08-25T00:00:00Z",
            "source": "notebook",
            "notebookId": "nb-explore-001",
            "notebook": {"notebookId": "nb-explore-001", "graduatedAt": "2026-08-25T00:00:00Z"},
        },
    }
    doc.update(overrides)
    return doc


def test_emit_brief_is_revision_bound_and_deterministic() -> None:
    map_doc = _sample_map()
    first = emit_brief(map_doc, emitted_at="2026-08-25T12:00:00Z")
    second = emit_brief(map_doc, emitted_at="2026-08-25T12:00:00Z")
    assert first == second
    assert first["version"] == "ExplorationBrief@v1"
    assert first["id"] == brief_id_for_map("explore-handoff")
    assert first["sourceRevision"] == 1
    assert first["destination"]["statement"] == map_doc["destination"]["statement"]
    assert first["readiness"]["readyForDocHandoff"] is True
    assert first["authorityBoundary"]["createsPrds"] is False
    assert len(first["planningUnitCandidates"]) >= 1
    assert first["decisions"][0]["nodeId"] == "dec-auth"
    assert first["evidence"][0]["refId"] == "sha256:abc123"


def test_stale_brief_derivation_fails_closed() -> None:
    map_doc = _sample_map()
    brief = emit_brief(map_doc, emitted_at="2026-08-25T12:00:00Z")
    advanced = deepcopy(map_doc)
    advanced["revision"] = 2
    with pytest.raises(ExplorationBriefError, match="stale-brief"):
        assert_fresh(brief, advanced)
    stale = invalidate_brief(brief, current_revision=2)
    with pytest.raises(ExplorationBriefError, match="brief-invalidated"):
        assert_fresh(stale, advanced)
    refreshed = recompute_if_stale(brief, advanced, emitted_at="2026-08-25T13:00:00Z")
    assert refreshed["sourceRevision"] == 2


def test_supersession_invalidates_brief_output() -> None:
    map_doc = _sample_map()
    brief = emit_brief(map_doc)
    outputs = invalidate_dependent_outputs(map_doc, brief=brief)
    invalidated = outputs["brief"]
    assert invalidated["invalidation"]["state"] == "valid"
    advanced_map = deepcopy(map_doc)
    advanced_map["revision"] = 2
    stale = invalidate_brief(brief, current_revision=2)
    assert stale["invalidation"]["state"] == "stale"


def test_exploration_handoff_round_trip_same_session(tmp_path: Path) -> None:
    repo = _repo_with_schema(tmp_path)
    map_doc = _sample_map()
    brief = emit_brief(map_doc)
    context = build_exploration_resume_context(
        map_doc,
        brief=brief,
        interaction_state={"mode": "conversation", "activeNodeId": "dec-auth"},
    )
    assert context["explorationMapId"] == "explore-handoff"
    assert context["revision"] == 1
    assert context["notebookProvenance"]["notebookId"] == "nb-explore-001"
    assert context["interactionState"]["mode"] == "conversation"

    exported = export_exploration_bundle(repo, map_doc, brief=brief)
    assert exported["verdict"] == "pass"
    bundle = exported["bundle"]
    assert validate_bundle(bundle, root=repo)["verdict"] == "pass"

    imported = import_exploration_resume(repo, bundle, expected_revision=1)
    assert imported["verdict"] == "pass"
    assert imported["exploration"]["explorationMapId"] == "explore-handoff"
    assert imported["foreignHarnessResumeForbidden"] is True


def test_cross_session_resume_refuses_stale_revision(tmp_path: Path) -> None:
    repo = _repo_with_schema(tmp_path)
    map_doc = _sample_map()
    exported = export_exploration_bundle(repo, map_doc)
    bundle = exported["bundle"]
    result = import_exploration_resume(repo, bundle, expected_revision=2)
    assert result["verdict"] == "halt"
    assert result["error"] == "handoff:stale-revision"


def test_export_preserves_supported_exploration_interaction_state(tmp_path: Path) -> None:
    repo = _repo_with_schema(tmp_path)
    interaction = {
        "mode": "conversation", "activeNodeId": "dec-auth", "lastPrompt": "Resume",
        "phase": "confirm", "mapId": "explore-handoff", "expectedRevision": 1,
    }
    result = export_exploration_bundle(repo, _sample_map(), interaction_state=interaction)
    assert result["verdict"] == "pass", result
    exploration = result["bundle"]["extensions"]["exploration"]
    assert exploration["interactionState"] == interaction
    assert exploration["mapRevision"] == exploration["revision"] == 1
    assert exploration["brief"]["sourceRevision"] == 1


def test_export_keeps_redacted_context_in_every_returned_copy(tmp_path: Path) -> None:
    repo = _repo_with_schema(tmp_path)
    synthetic_token = "ghp_" + "A" * 36
    document = _sample_map()
    document["provenance"]["notebook"]["detail"] = synthetic_token
    brief = emit_brief(document)
    brief["invalidation"]["reason"] = synthetic_token
    result = export_exploration_bundle(
        repo, document, brief=brief,
        interaction_state={"lastPrompt": synthetic_token},
    )
    assert result["verdict"] == "pass", result
    assert synthetic_token not in json.dumps(result)
    bundle = result["bundle"]
    copies = [bundle["currentState"]["exploration"],
              bundle["extensions"]["exploration"],
              bundle["extensions"]["cursor"]["exploration"]]
    assert copies[0] == copies[1] == copies[2]
    assert "REDACTED" in copies[0]["interactionState"]["lastPrompt"]
    assert "REDACTED" in copies[0]["notebookProvenance"]["detail"]
    assert "REDACTED" in copies[0]["brief"]["invalidation"]["reason"]
    assert "REDACTED" in result["brief"]["invalidation"]["reason"]
    assert validate_bundle(bundle, root=repo)["verdict"] == "pass"
    assert import_exploration_resume(repo, bundle, expected_revision=1)["verdict"] == "pass"


@pytest.mark.parametrize("path,value", [
    (("unexpected",), True),
    (("mapRevision",), "1"),
    (("brief", "unexpected"), True),
    (("brief", "sourceRevision"), "1"),
    (("brief", "readyForDocHandoff"), "yes"),
    (("brief", "invalidation", "state"), "unknown"),
    (("brief", "invalidation", "unexpected"), True),
    (("interactionState", "unexpected"), True),
    (("interactionState", "expectedRevision"), "1"),
])
def test_exploration_extension_retains_strict_schema(
    tmp_path: Path, path: tuple[str, ...], value: object,
) -> None:
    repo = _repo_with_schema(tmp_path)
    exported = export_exploration_bundle(repo, _sample_map())
    assert exported["verdict"] == "pass", exported
    bundle = exported["bundle"]
    target = bundle["extensions"]["exploration"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    bundle["workflowDigest"] = build_workflow_digest(bundle)
    bundle["bundleDigest"] = digest_payload(bundle)
    result = validate_bundle(bundle, root=repo)
    assert result["verdict"] == "schema_failure", result
    assert "extensions.exploration." + ".".join(path) in result["fields"]


def test_invalidated_brief_in_bundle_is_rejected(tmp_path: Path) -> None:
    repo = _repo_with_schema(tmp_path)
    map_doc = _sample_map()
    brief = emit_brief(map_doc)
    stale_brief = invalidate_brief(brief, current_revision=2)
    exported = export_exploration_bundle(repo, map_doc, brief=brief)
    bundle = exported["bundle"]
    bundle["extensions"]["exploration"]["brief"] = {
        "id": stale_brief["id"],
        "sourceRevision": stale_brief["sourceRevision"],
        "readyForDocHandoff": False,
        "invalidation": stale_brief["invalidation"],
    }
    bundle["workflowDigest"] = build_workflow_digest(bundle)
    bundle["bundleDigest"] = digest_payload(bundle)
    result = import_exploration_resume(repo, bundle, expected_revision=1)
    assert result["verdict"] == "halt"
    assert result["error"] == "handoff:brief-invalidated"


def test_forward_handoff_ready_flag_on_ready_brief(tmp_path: Path) -> None:
    repo = _repo_with_schema(tmp_path)
    map_doc = _sample_map(
        structuredFields={
            "problem": "Ready exploration",
            "outcomes": ["Doc handoff"],
            "successCriteria": ["No blocking unknowns"],
            "unknowns": [],
        },
        nodes=[],
    )
    brief = emit_brief(map_doc)
    assert brief["readiness"]["readyForDocHandoff"] is True
    exported = export_exploration_bundle(repo, map_doc, brief=brief)
    exploration = exported["bundle"]["extensions"]["exploration"]
    assert exploration.get("forwardHandoffReady") is True


def test_provenance_round_trip_preserves_notebook_link(tmp_path: Path) -> None:
    repo = _repo_with_schema(tmp_path)
    map_doc = _sample_map()
    exported = export_exploration_bundle(repo, map_doc)
    exploration = exported["bundle"]["extensions"]["exploration"]
    assert exploration["notebookProvenance"]["notebookId"] == "nb-explore-001"
    assert exploration["notebookProvenance"]["graduatedAt"] == "2026-08-25T00:00:00Z"
