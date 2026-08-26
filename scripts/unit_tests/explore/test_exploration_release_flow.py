"""PRD 331 R1, R2, R22, R24, R32, R38, R39, R45 — integrated release scenarios."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from explore_command_contract import graduate_notebook_to_explore, validate_command_contract  # noqa: E402
from exploration_brief import emit_brief  # noqa: E402
from exploration_engine import ExplorationEngine  # noqa: E402
from exploration_intelligence import enrich_exploration_context  # noqa: E402
from exploration_metrics import (  # noqa: E402
    EVENT_AUTHORITY_VIOLATION,
    EVENT_PREMATURE_DOC,
    EVENT_RESUME_SUCCESS,
    EVENT_SESSION_START,
    aggregate_metrics,
    build_event,
    evaluate_against_thresholds,
    load_acceptance_thresholds,
)
from exploration_projection import project_frontier, render_accessible_text  # noqa: E402
from exploration_store import ExplorationStore  # noqa: E402
from handoff_bundle import export_exploration_bundle, import_exploration_resume  # noqa: E402
from planning_readiness import compute_readiness  # noqa: E402
from status_collect import collect_exploration_summary  # noqa: E402
from workflow_extensions import (  # noqa: E402
    propose_doc_backward_route,
    propose_explore_forward_handoff,
    validate_doc_explore_handoff_contract,
)


def _repo_with_schema(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    ref = SCRIPT_DIR.parent / "core" / "sw-reference"
    (repo / "core" / "sw-reference").mkdir(parents=True)
    for name in (
        "handoff-bundle.schema.json",
        "exploration-brief.schema.json",
        "exploration-map.schema.json",
        "planning-readiness.schema.json",
        "exploration-acceptance.json",
    ):
        src = ref / name
        if src.is_file():
            (repo / "core" / "sw-reference" / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    for rel in (
        "core/commands/sw-explore.md",
        "core/commands/sw-doc.md",
        "core/commands/sw-note.md",
        "core/skills/explore/SKILL.md",
    ):
        src = SCRIPT_DIR.parent / rel
        if src.is_file():
            dest = repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return repo


def _drive_core_journey(
    store: ExplorationStore,
    engine: ExplorationEngine,
    *,
    map_id: str,
    source: str = "idea",
    notebook_id: str | None = None,
) -> dict:
    existing = store.read(map_id)
    if existing is None:
        engine.start_session(
            map_id=map_id,
            destination_statement="Ship first-release /sw-explore journey.",
            source=source,
            notebook_id=notebook_id,
        )
    loaded = store.read(map_id)
    assert loaded is not None
    revision = int(loaded["map"]["revision"])
    for field, value in (
        ("problem", "Unclear route into planning."),
        ("outcomes", ["Resumable explore", "Explicit doc handoff"]),
        ("successCriteria", ["Readiness before doc"]),
    ):
        updated = engine.set_structured_field(map_id, field, value, expected_revision=revision)
        revision = int(updated["revision"])
    loaded = store.read(map_id)
    assert loaded is not None
    document = loaded["map"]
    readiness = compute_readiness(document)
    brief = emit_brief(document, readiness=readiness)
    return {"map": document, "readiness": readiness, "brief": brief}


def test_release_flow_idea_to_doc_handoff(tmp_path: Path) -> None:
    """R1/R39 — idea entry reaches resumable readiness and explicit doc handoff."""
    repo = _repo_with_schema(tmp_path)
    store = ExplorationStore(tmp_path / "maps")
    engine = ExplorationEngine(store)
    journey = _drive_core_journey(store, engine, map_id="release-idea")
    document = journey["map"]
    readiness = journey["readiness"]

    contract = validate_command_contract(repo)
    assert contract["verdict"] == "pass"
    assert contract["entryPaths"]["idea"] is True

    blocking_map = dict(document)
    blocking_map["structuredFields"] = dict(document["structuredFields"])
    blocking_map["structuredFields"]["unknowns"] = [
        {"id": "unk-block", "statement": "Tier?", "classification": "blocking"}
    ]
    blocking_readiness = compute_readiness(blocking_map)
    backward = propose_doc_backward_route(blocking_map, readiness=blocking_readiness)
    assert backward["verdict"] == "propose"

    forward = propose_explore_forward_handoff(document, readiness=readiness, brief=journey["brief"])
    assert forward["verdict"] == "propose"
    assert forward["destination"] == "doc"


def test_release_flow_notebook_graduation_and_resume(tmp_path: Path) -> None:
    """R2 — notebook graduation preserves provenance and resume round trip."""
    repo = _repo_with_schema(tmp_path)
    store = ExplorationStore(tmp_path / "maps")
    engine = ExplorationEngine(store)
    link = graduate_notebook_to_explore(
        {"id": "nb-release", "text": "Graduate to explore"},
        map_id="release-notebook",
        destination_statement="Notebook-originated exploration.",
    )
    assert link["verdict"] == "ok"
    engine.start_session(
        map_id="release-notebook",
        destination_statement="Notebook-originated exploration.",
        source="notebook",
        notebook_id="nb-release",
    )
    journey = _drive_core_journey(
        store,
        engine,
        map_id="release-notebook",
        source="notebook",
        notebook_id="nb-release",
    )
    bundle = export_exploration_bundle(
        repo,
        journey["map"],
        brief=journey["brief"],
        interaction_state={"state": "confirm"},
    )
    assert bundle["verdict"] == "pass"
    resumed = import_exploration_resume(repo, bundle["bundle"])
    assert resumed["verdict"] == "pass"
    assert resumed["exploration"]["explorationMapId"] == "release-notebook"


def test_release_flow_projection_status_and_accessible_recovery(tmp_path: Path) -> None:
    """R22/R45 — projection/status surfaces expose accessible fallback without mutation."""
    repo = _repo_with_schema(tmp_path)
    store = ExplorationStore(tmp_path / "maps")
    engine = ExplorationEngine(store)
    journey = _drive_core_journey(store, engine, map_id="release-status")
    document = journey["map"]
    projection = project_frontier(document)
    assert projection["verdict"] == "pass"
    local = projection["local"]
    assert local["readOnly"] is True
    assert render_accessible_text(local)
    summary = collect_exploration_summary(repo, "release-status", store=store)
    assert summary["verdict"] == "pass"
    assert summary["readOnly"] is True


def test_release_flow_degraded_intel_does_not_block_core(tmp_path: Path) -> None:
    """R38/R42 — degraded intelligence is visible but non-blocking for atomic core."""
    repo = _repo_with_schema(tmp_path)
    store = ExplorationStore(tmp_path / "maps")
    engine = ExplorationEngine(store)
    journey = _drive_core_journey(store, engine, map_id="release-intel")
    snapshot = enrich_exploration_context(repo, journey["map"], query="release")
    assert snapshot["blocking"] is False
    assert snapshot["destinationProgressInvariant"] is True
    intel = snapshot["intelligence"]
    assert intel.get("blocking") is False


def test_release_flow_quality_metrics_and_acceptance_thresholds(tmp_path: Path) -> None:
    """R32/R40 — metrics include required rates and respect acceptance thresholds."""
    repo = _repo_with_schema(tmp_path)
    events = [build_event(EVENT_SESSION_START, f"map-{i}", sequence=0) for i in range(5)]
    events.extend(build_event(EVENT_RESUME_SUCCESS, f"map-{i}", sequence=1) for i in range(5))
    metrics = aggregate_metrics(events)
    thresholds = load_acceptance_thresholds(repo)
    evaluation = evaluate_against_thresholds(metrics, thresholds)
    assert evaluation["verdict"] == "pass"
    assert metrics["authorityBoundaryViolations"] == 0

    violation = build_event(EVENT_AUTHORITY_VIOLATION, "map-0", sequence=2)
    blocked = evaluate_against_thresholds(aggregate_metrics(events + [violation]), load_acceptance_thresholds(repo))
    assert blocked["verdict"] == "fail"


def test_release_flow_premature_doc_metric_is_redacted() -> None:
    """R33/R43 — premature-doc events redact secrets before aggregation."""
    event = build_event(
        EVENT_PREMATURE_DOC,
        "map-premature",
        sequence=0,
        metadata={"route": "doc", "token": "ghp_SUPERSECRETTOKEN1234567890"},
    )
    assert "ghp_" not in json.dumps(event)
    metrics = aggregate_metrics([event, build_event(EVENT_SESSION_START, "map-premature", sequence=1)])
    assert metrics["rates"]["prematureDocRate"] == 1.0


def test_release_flow_human_confirmation_contract(tmp_path: Path) -> None:
    """R24 — human interaction and doc handoff contracts are documented."""
    repo = _repo_with_schema(tmp_path)
    contract = validate_command_contract(repo)
    assert contract["interaction"]["askDecideConfirm"] is True
    handoff = validate_doc_explore_handoff_contract(repo)
    assert handoff["verdict"] == "pass", handoff


def test_acceptance_config_covers_entry_through_ux(tmp_path: Path) -> None:
    """R32 — acceptance checklist gates entry through UX surfaces."""
    repo = _repo_with_schema(tmp_path)
    config = json.loads((repo / "core/sw-reference/exploration-acceptance.json").read_text(encoding="utf-8"))
    checklist_ids = {item["id"] for item in config["checklist"]}
    assert {
        "entry_paths",
        "exploration_map",
        "planning_readiness",
        "exploration_brief",
        "authority_anti_goals",
        "doc_explore_routing",
        "projection_status",
        "intelligence_hooks",
        "quality_metrics",
    }.issubset(checklist_ids)
    assert config["metrics"]["authorityBoundaryViolations"]["max"] == 0
