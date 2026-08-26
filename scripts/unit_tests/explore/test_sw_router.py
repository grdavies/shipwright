"""PRD 331 R25, R29, R30, R50 — bare /sw bounded routing and operator controls."""

from __future__ import annotations

from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from sw_router import (  # noqa: E402
    DESTINATIONS,
    RouterContext,
    apply_cancel,
    apply_override,
    check_loop_guard,
    detect_explore_doc_loop,
    persistence_effects_for,
    propose_route,
    record_transition,
    validate_command_surface,
    validate_sw_command_contract,
)


def _map(*, map_id: str = "map-1", revision: int = 1) -> dict:
    return {
        "id": map_id,
        "revision": revision,
        "destination": {"statement": "Ship explore-first release"},
        "structuredFields": {
            "problem": "Need bounded /sw routing",
            "outcomes": ["operators get one next action"],
            "successCriteria": ["all destinations covered"],
            "unknowns": [],
        },
        "nodes": [],
    }


def _readiness(*, ready: bool = True) -> dict:
    return {
        "readyForDocHandoff": ready,
        "sourceRevision": 1,
        "invalidation": {"state": "valid"},
    }


@pytest.mark.parametrize(
    "destination,expected_command_prefix",
    [
        ("capture", "/sw-note"),
        ("explore", "/sw-explore"),
        ("doc", "/sw-doc"),
        ("deliver", "/sw-deliver"),
        ("resume", "/sw-deliver"),
    ],
)
def test_all_destinations_are_bounded(destination: str, expected_command_prefix: str) -> None:
    assert destination in DESTINATIONS
    if destination == "capture":
        result = propose_route(RouterContext(open_notebook_ideas=1))
    elif destination == "explore":
        result = propose_route(RouterContext(exploration_map=_map()))
    elif destination == "doc":
        result = propose_route(RouterContext(unfrozen_prd=True))
    elif destination == "deliver":
        result = propose_route(RouterContext(frozen_task_list="docs/prds/x/tasks.md"))
    else:
        result = propose_route(
            RouterContext(deliver_run={"status": "running", "runId": "run-1"})
        )
    assert result["verdict"] == "propose"
    assert result["destination"] == destination
    assert str(result["command"]).startswith(expected_command_prefix)


def test_ambiguous_deliver_runs_refuse_silent_pick() -> None:
    result = propose_route(
        RouterContext(
            ambiguous_deliver_runs=[
                {"runId": "a", "worktree": "/wt/a"},
                {"runId": "b", "worktree": "/wt/b"},
            ]
        )
    )
    assert result["verdict"] == "ambiguous"
    assert result["reason"]["code"] == "ambiguous-deliver-runs"
    assert len(result["candidates"]) == 2


def test_route_reason_and_persistence_effects_are_declared() -> None:
    result = propose_route(RouterContext(frozen_task_list="tasks.md"))
    assert result["verdict"] == "propose"
    assert result["reason"]["code"] == "frozen-task-list"
    assert result["reason"]["message"]
    assert result["persistenceEffects"]
    assert any(effect["when"] for effect in result["persistenceEffects"])


def test_cancel_clears_persistence_effects() -> None:
    proposal = propose_route(RouterContext(open_notebook_ideas=2))
    cancelled = apply_cancel(proposal)
    assert cancelled["verdict"] == "cancelled"
    assert cancelled["persistenceEffects"] == []
    assert cancelled["reason"]["code"] == "operator-cancel"


def test_override_requires_bounded_destination() -> None:
    proposal = propose_route(RouterContext(open_notebook_ideas=1))
    ok = apply_override(proposal, "explore", operator="operator-1")
    assert ok["verdict"] == "override"
    assert ok["destination"] == "explore"
    assert ok["command"] == "/sw-explore"
    assert ok["persistenceEffects"]

    refused = apply_override(proposal, "implement-now", operator="operator-1")  # type: ignore[arg-type]
    assert refused["verdict"] == "refused"
    assert refused["reason"] == "override-destination-invalid"


def test_loop_guard_blocks_explore_doc_cycling() -> None:
    history = ["explore", "doc", "explore", "doc"]
    guard = detect_explore_doc_loop(history)
    assert guard["blocked"] is True

    refused = check_loop_guard(history, "explore")
    assert refused["verdict"] == "refused"
    assert refused["reason"] == "explore-doc-loop-guard"

    in_progress = propose_route(
        RouterContext(
            exploration_map=_map(),
            exploration_readiness=_readiness(ready=True),
            route_history=history,
        )
    )
    assert in_progress["verdict"] == "refused"
    assert in_progress["reason"]["code"] == "explore-doc-loop-guard"


def test_record_transition_appends_destination() -> None:
    updated = record_transition(["capture"], "explore")
    assert updated == ["capture", "explore"]


def test_invented_command_surface_refused() -> None:
    refused = validate_command_surface("/sw-mega-front-door")
    assert refused["verdict"] == "refused"
    assert refused["reason"] == "invented-command-surface"

    allowed = validate_command_surface("/sw-explore idea test")
    assert allowed["verdict"] == "allow"


def test_sw_command_contract_documents_router_controls() -> None:
    result = validate_sw_command_contract()
    assert result["verdict"] == "pass", result["failures"]
    assert all(result["destinations"].values())
    assert all(result["controls"].values())


def test_resume_deliver_includes_task_list_when_present() -> None:
    result = propose_route(
        RouterContext(
            deliver_run={
                "status": "blocked",
                "runId": "run-9",
                "sourceTaskList": "docs/prds/331/tasks.md",
            }
        )
    )
    assert result["destination"] == "resume"
    assert "docs/prds/331/tasks.md" in result["command"]


def test_exploration_in_progress_routes_to_explore_not_doc() -> None:
    result = propose_route(
        RouterContext(
            exploration_map=_map(),
            exploration_readiness=_readiness(ready=False),
        )
    )
    assert result["destination"] == "explore"
    assert "resume map-1" in result["command"]


def test_persistence_effects_per_destination() -> None:
    for destination in DESTINATIONS:
        effects = persistence_effects_for(destination)
        assert isinstance(effects, list)
        if destination == "capture":
            assert effects[0]["target"].endswith("notebook.jsonl")
