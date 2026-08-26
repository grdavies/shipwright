#!/usr/bin/env python3
"""Workflow contract registry and taxonomy conformance (PRD 331 R28-R30, R34-R35, R48)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from explore_command_contract import CLOSED_ANTI_GOALS, validate_command_contract

INSTRUCTION_ARTIFACTS_REL = Path("core/sw-reference/instruction-artifacts.json")

EXPLORE_COMMAND_IDS: frozenset[str] = frozenset({"sw-explore"})
EXPLORE_SKILL_IDS: frozenset[str] = frozenset({"explore"})
PRD331_NEW_COMMAND_IDS: frozenset[str] = frozenset({"sw-explore"})
PRD331_NEW_SKILL_IDS: frozenset[str] = frozenset({"explore"})
FORBIDDEN_GRAPH_PREFIX = "sw-graph-"
EXPLORE_SUPPORT_SPRAWL_RE = re.compile(r"^sw-explore[-_]")


class ExplorationArchitectureError(ValueError):
    """Architecture conformance validation failure."""


def _repo_root(root: Path | None = None) -> Path:
    if root is not None:
        return root
    return Path(__file__).resolve().parent.parent


def load_instruction_registry(root: Path | None = None) -> dict[str, Any]:
    repo = _repo_root(root)
    path = repo / INSTRUCTION_ARTIFACTS_REL
    if not path.is_file():
        raise ExplorationArchitectureError(f"missing-registry:{INSTRUCTION_ARTIFACTS_REL}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ExplorationArchitectureError("registry-not-object")
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        raise ExplorationArchitectureError("registry-artifacts-not-array")
    return payload


def _artifacts_by_id(registry: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for entry in registry.get("artifacts", []):
        if not isinstance(entry, dict):
            continue
        artifact_id = str(entry.get("id") or "").strip()
        if not artifact_id:
            continue
        by_id[artifact_id] = entry
    return by_id


def validate_workflow_contract_registry(root: Path | None = None) -> dict[str, Any]:
    """R28 — explore command + skill registered with resolvable source paths."""
    repo = _repo_root(root)
    registry = load_instruction_registry(repo)
    by_id = _artifacts_by_id(registry)
    failures: list[str] = []

    if registry.get("version") != 1:
        failures.append("registry-version-mismatch")

    duplicate_ids = [
        artifact_id
        for artifact_id, count in _duplicate_ids(registry).items()
        if count > 1
    ]
    if duplicate_ids:
        failures.append(f"duplicate-ids:{duplicate_ids}")

    missing_commands = sorted(EXPLORE_COMMAND_IDS - set(by_id))
    missing_skills = sorted(EXPLORE_SKILL_IDS - set(by_id))
    if missing_commands:
        failures.append(f"missing-explore-commands:{missing_commands}")
    if missing_skills:
        failures.append(f"missing-explore-skills:{missing_skills}")

    dangling: list[str] = []
    contract_refs: dict[str, str] = {}
    for artifact_id in sorted(EXPLORE_COMMAND_IDS | EXPLORE_SKILL_IDS):
        entry = by_id.get(artifact_id)
        if entry is None:
            continue
        kind = str(entry.get("kind") or "")
        source_path = str(entry.get("sourcePath") or "").strip()
        contract_refs[artifact_id] = source_path
        if not source_path:
            failures.append(f"missing-source-path:{artifact_id}")
            continue
        if not (repo / source_path).is_file():
            dangling.append(source_path)
        if artifact_id in EXPLORE_COMMAND_IDS and kind != "command":
            failures.append(f"wrong-kind-command:{artifact_id}")
        if artifact_id in EXPLORE_SKILL_IDS and kind != "skill":
            failures.append(f"wrong-kind-skill:{artifact_id}")

    if dangling:
        failures.append(f"dangling-source-paths:{dangling}")

    return {
        "verdict": "pass" if not failures else "fail",
        "failures": failures,
        "exploreCommands": sorted(EXPLORE_COMMAND_IDS),
        "exploreSkills": sorted(EXPLORE_SKILL_IDS),
        "contractRefs": contract_refs,
        "duplicateIds": duplicate_ids,
    }


def scan_explore_support_command_sprawl(root: Path | None = None) -> dict[str, Any]:
    """R29 — no explore-support top-level command sprawl beyond sw-explore."""
    registry = load_instruction_registry(root)
    by_id = _artifacts_by_id(registry)
    command_ids = sorted(
        artifact_id
        for artifact_id, entry in by_id.items()
        if str(entry.get("kind") or "") == "command"
    )
    extras = sorted(
        artifact_id
        for artifact_id in command_ids
        if EXPLORE_SUPPORT_SPRAWL_RE.match(artifact_id)
    )
    new_explore_surface = sorted(
        artifact_id
        for artifact_id in command_ids
        if artifact_id.startswith("sw-explore") and artifact_id not in PRD331_NEW_COMMAND_IDS
    )
    failures: list[str] = []
    if extras:
        failures.append(f"explore-support-sprawl:{extras}")
    if new_explore_surface:
        failures.append(f"unbounded-explore-commands:{new_explore_surface}")

    sw_explore_present = "sw-explore" in by_id
    if not sw_explore_present:
        failures.append("missing-sw-explore")

    return {
        "verdict": "pass" if not failures else "fail",
        "failures": failures,
        "commandInventory": command_ids,
        "exploreCommand": "sw-explore" if sw_explore_present else None,
        "sprawl": extras + new_explore_surface,
    }


def validate_bounded_taxonomy(root: Path | None = None) -> dict[str, Any]:
    """R30 — sw- naming, bounded explore surface, no /sw-graph-* commands."""
    registry = load_instruction_registry(root)
    by_id = _artifacts_by_id(registry)
    failures: list[str] = []

    graph_commands = sorted(
        artifact_id
        for artifact_id, entry in by_id.items()
        if str(entry.get("kind") or "") == "command" and artifact_id.startswith(FORBIDDEN_GRAPH_PREFIX)
    )
    if graph_commands:
        failures.append(f"graph-commands-forbidden:{graph_commands}")

    non_sw_commands = sorted(
        artifact_id
        for artifact_id, entry in by_id.items()
        if str(entry.get("kind") or "") == "command" and not artifact_id.startswith("sw-")
    )
    if non_sw_commands:
        failures.append(f"non-sw-command-ids:{non_sw_commands}")

    explore_commands = sorted(
        artifact_id
        for artifact_id, entry in by_id.items()
        if str(entry.get("kind") or "") == "command" and "explore" in artifact_id.lower()
    )
    unexpected_explore = sorted(set(explore_commands) - PRD331_NEW_COMMAND_IDS)
    if unexpected_explore:
        failures.append(f"unexpected-explore-commands:{unexpected_explore}")

    explore_skills = sorted(
        artifact_id
        for artifact_id, entry in by_id.items()
        if str(entry.get("kind") or "") == "skill" and artifact_id in PRD331_NEW_SKILL_IDS
    )
    if sorted(explore_skills) != sorted(PRD331_NEW_SKILL_IDS):
        failures.append(f"explore-skill-taxonomy-mismatch:{explore_skills}")

    return {
        "verdict": "pass" if not failures else "fail",
        "failures": failures,
        "graphCommands": graph_commands,
        "exploreCommands": explore_commands,
        "commandInventory": sorted(
            artifact_id
            for artifact_id, entry in by_id.items()
            if str(entry.get("kind") or "") == "command"
        ),
        "namingContract": "sw-prefix-required",
    }


def validate_closed_anti_goal_set(root: Path | None = None) -> dict[str, Any]:
    """R34 — closed anti-goal set enforced in explore command contract."""
    contract = validate_command_contract(root)
    anti_goals = contract.get("antiGoals") or {}
    missing = [
        goal_id
        for goal_id in (goal["id"] for goal in CLOSED_ANTI_GOALS)
        if not anti_goals.get(goal_id, {}).get("present")
    ]
    failures = list(contract.get("failures") or [])
    if missing:
        failures.append(f"missing-anti-goals:{missing}")
    return {
        "verdict": "pass" if not failures else "fail",
        "failures": failures,
        "antiGoals": anti_goals,
        "closedSetSize": len(CLOSED_ANTI_GOALS),
    }


def _normalized_explore_contract(contract: Mapping[str, Any]) -> str:
    from explore_command_contract import load_command_contract

    bundle = load_command_contract()
    return (bundle.get("commandText", "") + bundle.get("skillText", "")).lower()


def validate_architectural_principles(root: Path | None = None) -> dict[str, Any]:
    """R35 — explore preserves kernel boundaries and degradable integrations."""
    repo = _repo_root(root)
    registry_result = validate_workflow_contract_registry(repo)
    taxonomy_result = validate_bounded_taxonomy(repo)
    contract = validate_command_contract(repo)
    failures = (
        list(registry_result.get("failures") or [])
        + list(taxonomy_result.get("failures") or [])
        + list(contract.get("failures") or [])
    )

    skill_path = repo / "core/skills/explore/SKILL.md"
    skill_text = skill_path.read_text(encoding="utf-8").lower() if skill_path.is_file() else ""
    principle_checks = {
        "noImplementationDispatch": bool(contract.get("forbiddenDispatchDeclared")),
        "optionalExplore": "optional" in _normalized_explore_contract(contract),
        "degradableIntelligence": "degrad" in skill_text,
        "humanOwnsIntent": (contract.get("interaction") or {}).get("humanOwnsIntent"),
        "noGraphCommands": not taxonomy_result.get("graphCommands"),
    }
    for key, ok in principle_checks.items():
        if not ok:
            failures.append(f"architecture-principle:{key}")

    return {
        "verdict": "pass" if not failures else "fail",
        "failures": failures,
        "principles": principle_checks,
        "registry": registry_result,
        "taxonomy": taxonomy_result,
    }


def _duplicate_ids(registry: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in registry.get("artifacts", []):
        if not isinstance(entry, dict):
            continue
        artifact_id = str(entry.get("id") or "").strip()
        if artifact_id:
            counts[artifact_id] = counts.get(artifact_id, 0) + 1
    return counts


def validate_exploration_architecture(root: Path | None = None) -> dict[str, Any]:
    """Aggregate architecture conformance for ship/gap-check consumers."""
    repo = _repo_root(root)
    sections = {
        "registry": validate_workflow_contract_registry(repo),
        "sprawl": scan_explore_support_command_sprawl(repo),
        "taxonomy": validate_bounded_taxonomy(repo),
        "antiGoals": validate_closed_anti_goal_set(repo),
        "principles": validate_architectural_principles(repo),
    }
    failures: list[str] = []
    for name, result in sections.items():
        if result.get("verdict") != "pass":
            failures.extend(f"{name}:{item}" for item in result.get("failures") or [])
    return {"verdict": "pass" if not failures else "fail", "failures": failures, "sections": sections}
