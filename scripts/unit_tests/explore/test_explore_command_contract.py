"""PRD 331 D3, R1, R2, R3, R31, R48 — explore command and entry path contract.

Phase 12 (PRD 337 R9/R10): complete explore command surface — idea, notebook, resume, and
`/sw-note graduate --to explore` handoff with notebook provenance round trips.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from explore_command_contract import (  # noqa: E402
    CLOSED_ANTI_GOALS,
    ENTRY_PATHS,
    FIRST_RELEASE_CAPABILITIES,
    FORBIDDEN_IMPLEMENTATION_DISPATCH,
    graduate_notebook_to_explore,
    load_command_contract,
    refuse_implementation_dispatch,
    tier_routing_absent,
    validate_command_contract,
)


def test_explore_idea_entry_is_first_class() -> None:
    bundle = load_command_contract()
    command = bundle["commandText"].lower()
    assert "idea" in command
    assert "/sw-explore idea" in command or "/sw-explore <text>" in command
    entries = validate_command_contract()["entryPaths"]
    assert entries["idea"] is True


def test_all_entry_paths_preserve_notebook_provenance() -> None:
    result = validate_command_contract()
    assert result["entryPaths"]["notebook"] is True
    assert result["entryPaths"]["resume"] is True
    notebook = result["notebookGraduate"]
    assert notebook["graduateTarget"] is True
    assert notebook["bidirectionalProvenance"] is True
    assert notebook["reversible"] is True

    link = graduate_notebook_to_explore(
        {"id": "nb-1", "text": "Explore notebook graduation"},
        map_id="map-abc",
        destination_statement="",
    )
    assert link["verdict"] == "ok"
    assert link["entry"] == "notebook"
    assert link["provenance"]["notebookId"] == "nb-1"
    assert link["provenance"]["reversible"] is True


def test_explore_entry_has_no_qsf_tier() -> None:
    bundle = load_command_contract()
    assert tier_routing_absent(bundle["commandText"]) is True
    command = bundle["commandText"].lower()
    assert "no tier at entry" in command or "no-tier" in command or "no tier" in command


def test_first_release_is_not_shell_only() -> None:
    result = validate_command_contract()
    assert all(result["capabilities"].values()), result["capabilities"]
    bundle = load_command_contract()
    for module in (
        "exploration_store.py",
        "exploration_engine.py",
        "exploration_policy.py",
        "exploration_evidence.py",
        "exploration_security.py",
    ):
        assert (Path(bundle["commandPath"]).parent.parent.parent / "scripts" / module).is_file()


def test_explore_cannot_dispatch_implementation() -> None:
    for blocked in FORBIDDEN_IMPLEMENTATION_DISPATCH:
        refused = refuse_implementation_dispatch(blocked)
        assert refused["verdict"] == "refused", blocked
        assert refused["reason"] == "implementation-dispatch-forbidden"
    allowed = refuse_implementation_dispatch("/sw-explore resume map-1")
    assert allowed["verdict"] == "allow"


def test_command_inlines_all_five_anti_goals() -> None:
    result = validate_command_contract()
    assert result["verdict"] == "pass", result["failures"]
    assert len(CLOSED_ANTI_GOALS) == 5
    for goal_id, goal in result["antiGoals"].items():
        assert goal["present"] is True, goal_id
    bundle = load_command_contract()
    for path_name in ENTRY_PATHS:
        assert path_name in bundle["commandText"].lower()


@pytest.mark.parametrize("entry", ENTRY_PATHS)
def test_entry_paths_declared_in_command(entry: str) -> None:
    bundle = load_command_contract()
    assert entry in bundle["commandText"].lower()


def test_validate_command_contract_passes() -> None:
    result = validate_command_contract()
    assert result["verdict"] == "pass"
    assert result["failures"] == []
    assert result["forbiddenDispatchDeclared"] == sorted(FORBIDDEN_IMPLEMENTATION_DISPATCH)
    interaction = result["interaction"]
    assert interaction["askDecideConfirm"] is True
    assert interaction["humanOwnsIntent"] is True
    assert interaction["blockingPolicy"] is True
    assert interaction["cancel"] is True
    assert interaction["resumeRecovery"] is True


def test_first_release_capabilities_documented() -> None:
    bundle = load_command_contract()
    lowered = bundle["commandText"].lower()
    for cap in FIRST_RELEASE_CAPABILITIES:
        assert cap.lower() in lowered, cap
