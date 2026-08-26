"""PRD 331 R28-R30, R34-R35, R48 — workflow contracts, taxonomy, and architecture conformance."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from exploration_architecture import (  # noqa: E402
    EXPLORE_COMMAND_IDS,
    EXPLORE_SKILL_IDS,
    FORBIDDEN_GRAPH_PREFIX,
    INSTRUCTION_ARTIFACTS_REL,
    load_instruction_registry,
    scan_explore_support_command_sprawl,
    validate_architectural_principles,
    validate_bounded_taxonomy,
    validate_closed_anti_goal_set,
    validate_workflow_contract_registry,
)
from explore_command_contract import CLOSED_ANTI_GOALS  # noqa: E402


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_workflow_contract_registry_includes_explore() -> None:
    result = validate_workflow_contract_registry()
    assert result["verdict"] == "pass", result["failures"]
    assert "sw-explore" in result["contractRefs"]
    assert "explore" in result["contractRefs"]
    assert result["exploreCommands"] == sorted(EXPLORE_COMMAND_IDS)
    assert result["exploreSkills"] == sorted(EXPLORE_SKILL_IDS)


def test_workflow_contract_registry_missing_entry_fails(tmp_path: Path) -> None:
    registry = load_instruction_registry(_repo_root())
    broken = deepcopy(registry)
    broken["artifacts"] = [
        entry for entry in broken["artifacts"] if entry.get("id") != "sw-explore"
    ]
    repo = tmp_path
    (repo / "core/sw-reference").mkdir(parents=True)
    (repo / "core/sw-reference/instruction-artifacts.json").write_text(
        json.dumps(broken), encoding="utf-8"
    )
    result = validate_workflow_contract_registry(repo)
    assert result["verdict"] == "fail"
    assert any("missing-explore-commands" in item for item in result["failures"])


def test_workflow_contract_registry_dangling_path_fails(tmp_path: Path) -> None:
    registry = load_instruction_registry(_repo_root())
    broken = deepcopy(registry)
    for entry in broken["artifacts"]:
        if entry.get("id") == "sw-explore":
            entry["sourcePath"] = "core/commands/does-not-exist.md"
    broken_path = tmp_path / "instruction-artifacts.json"
    broken_path.write_text(json.dumps(broken), encoding="utf-8")
    repo = tmp_path
    (repo / "core/sw-reference").mkdir(parents=True)
    (repo / "core/sw-reference/instruction-artifacts.json").write_text(
        broken_path.read_text(encoding="utf-8"), encoding="utf-8"
    )
    result = validate_workflow_contract_registry(repo)
    assert result["verdict"] == "fail"
    assert any("dangling-source-paths" in item for item in result["failures"])


def test_workflow_contract_registry_duplicate_id_fails(tmp_path: Path) -> None:
    registry = load_instruction_registry(_repo_root())
    broken = deepcopy(registry)
    explore_entry = next(entry for entry in broken["artifacts"] if entry.get("id") == "sw-explore")
    broken["artifacts"].append(deepcopy(explore_entry))
    repo = tmp_path
    (repo / "core/sw-reference").mkdir(parents=True)
    (repo / "core/sw-reference/instruction-artifacts.json").write_text(
        json.dumps(broken), encoding="utf-8"
    )
    result = validate_workflow_contract_registry(repo)
    assert result["verdict"] == "fail"
    assert result["duplicateIds"] == ["sw-explore"]


def test_no_explore_support_command_sprawl() -> None:
    result = scan_explore_support_command_sprawl()
    assert result["verdict"] == "pass", result["failures"]
    assert result["exploreCommand"] == "sw-explore"
    assert result["sprawl"] == []
    command_ids = result["commandInventory"]
    assert "sw-explore" in command_ids
    assert not any(cmd.startswith("sw-explore-") for cmd in command_ids)


def test_bounded_taxonomy_and_no_graph_commands() -> None:
    result = validate_bounded_taxonomy()
    assert result["verdict"] == "pass", result["failures"]
    assert result["graphCommands"] == []
    assert "sw-explore" in result["exploreCommands"]
    assert not any(cmd.startswith(FORBIDDEN_GRAPH_PREFIX) for cmd in result["commandInventory"])


def test_bounded_taxonomy_rejects_graph_command(tmp_path: Path) -> None:
    registry = load_instruction_registry(_repo_root())
    broken = deepcopy(registry)
    broken["artifacts"].append(
        {
            "id": "sw-graph-ship",
            "kind": "command",
            "sourcePath": "core/commands/sw-graph-ship.md",
            "description": "forbidden",
            "model": None,
            "capabilities": [],
            "bodyDigest": "0" * 64,
        }
    )
    repo = tmp_path
    (repo / "core/sw-reference").mkdir(parents=True)
    (repo / "core/sw-reference/instruction-artifacts.json").write_text(
        json.dumps(broken), encoding="utf-8"
    )
    result = validate_bounded_taxonomy(repo)
    assert result["verdict"] == "fail"
    assert "sw-graph-ship" in result["graphCommands"]


def test_closed_anti_goal_set_is_enforced() -> None:
    result = validate_closed_anti_goal_set()
    assert result["verdict"] == "pass", result["failures"]
    assert result["closedSetSize"] == len(CLOSED_ANTI_GOALS) == 5
    for goal_id, goal in result["antiGoals"].items():
        assert goal["present"] is True, goal_id


def test_explore_preserves_architectural_principles() -> None:
    result = validate_architectural_principles()
    assert result["verdict"] == "pass", result["failures"]
    principles = result["principles"]
    assert principles["noImplementationDispatch"]
    assert principles["humanOwnsIntent"] is True
    assert principles["noGraphCommands"] is True


@pytest.mark.parametrize("artifact_id", sorted(EXPLORE_COMMAND_IDS | EXPLORE_SKILL_IDS))
def test_explore_registry_entries_resolve(artifact_id: str) -> None:
    registry = load_instruction_registry()
    by_id = {entry["id"]: entry for entry in registry["artifacts"]}
    entry = by_id[artifact_id]
    source = Path(_repo_root() / entry["sourcePath"])
    assert source.is_file(), entry["sourcePath"]
