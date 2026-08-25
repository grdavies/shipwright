#!/usr/bin/env python3
"""Explore command/skill contract helpers (PRD 331 R1, R2, R3, R31, R34, R35, R48)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping, Sequence

COMMAND_REL = Path("core/commands/sw-explore.md")
SKILL_REL = Path("core/skills/explore/SKILL.md")
NOTE_REL = Path("core/commands/sw-note.md")

ENTRY_PATHS: tuple[str, ...] = ("idea", "notebook", "resume", "promote", "handoff")

CLOSED_ANTI_GOALS: tuple[dict[str, str], ...] = (
    {
        "id": "mega-planning",
        "label": "Mega-planning",
        "requiredPhrases": (
            "mega-planning",
            "does not create prds",
            "does not create tasks",
        ),
    },
    {
        "id": "implementation-dispatch",
        "label": "Implementation dispatch",
        "requiredPhrases": (
            "implementation dispatch",
            "/sw-deliver",
            "/sw-ship",
            "/sw-execute",
        ),
    },
    {
        "id": "autonomous-product-authority",
        "label": "Autonomous product authority",
        "requiredPhrases": (
            "autonomous product",
            "human owns intent",
        ),
    },
    {
        "id": "mandatory-explore",
        "label": "Mandatory explore",
        "requiredPhrases": (
            "optional",
            "not mandatory",
        ),
    },
    {
        "id": "unrestricted-prototypes",
        "label": "Unrestricted prototypes",
        "requiredPhrases": (
            "prototype",
            "non-production",
            "non-production-eligible",
        ),
    },
)

FORBIDDEN_IMPLEMENTATION_DISPATCH: frozenset[str] = frozenset(
    {
        "/sw-deliver",
        "/sw-ship",
        "/sw-execute",
        "/sw-start",
        "/sw-worktree",
    }
)

FIRST_RELEASE_CAPABILITIES: tuple[str, ...] = (
    "exploration_store.py",
    "exploration_engine.py",
    "exploration_policy.py",
    "exploration_evidence.py",
    "exploration_security.py",
    "ExplorationMap@v1",
    "memory-preflight",
)

INTERACTION_STATES: tuple[str, ...] = ("ask", "decide", "confirm")


class ExploreContractError(ValueError):
    """Explore command contract validation failure."""


def _repo_root(root: Path | None = None) -> Path:
    if root is not None:
        return root
    return Path(__file__).resolve().parent.parent


def _read_text(root: Path, rel: Path) -> str:
    path = root / rel
    if not path.is_file():
        raise ExploreContractError(f"missing-artifact:{rel}")
    return path.read_text(encoding="utf-8")


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def load_command_contract(root: Path | None = None) -> dict[str, Any]:
    repo = _repo_root(root)
    command_text = _read_text(repo, COMMAND_REL)
    skill_text = _read_text(repo, SKILL_REL)
    note_text = _read_text(repo, NOTE_REL)
    return {
        "commandPath": str(COMMAND_REL),
        "skillPath": str(SKILL_REL),
        "notePath": str(NOTE_REL),
        "commandText": command_text,
        "skillText": skill_text,
        "noteText": note_text,
    }


def entry_paths_present(text: str) -> dict[str, bool]:
    lowered = _normalized(text)
    return {name: name in lowered for name in ENTRY_PATHS}


def anti_goals_present(text: str) -> dict[str, dict[str, Any]]:
    lowered = _normalized(text)
    results: dict[str, dict[str, Any]] = {}
    for goal in CLOSED_ANTI_GOALS:
        missing = [phrase for phrase in goal["requiredPhrases"] if phrase not in lowered]
        results[goal["id"]] = {
            "label": goal["label"],
            "present": not missing,
            "missingPhrases": missing,
        }
    return results


def forbidden_dispatch_present(text: str) -> list[str]:
    lowered = _normalized(text)
    return sorted(cmd for cmd in FORBIDDEN_IMPLEMENTATION_DISPATCH if cmd.lower() in lowered)


def first_release_capabilities_present(text: str) -> dict[str, bool]:
    lowered = _normalized(text)
    return {cap: cap.lower() in lowered for cap in FIRST_RELEASE_CAPABILITIES}


def interaction_state_machine_present(skill_text: str) -> dict[str, bool]:
    lowered = _normalized(skill_text)
    has_flow = "ask" in lowered and "decide" in lowered and "confirm" in lowered
    return {
        "askDecideConfirm": has_flow,
        "humanOwnsIntent": "human owns intent" in lowered or "humans own intent" in lowered,
        "blockingPolicy": "blocking" in lowered and "human" in lowered,
        "cancel": "cancel" in lowered,
        "resumeRecovery": "resume" in lowered and "recover" in lowered,
    }


def notebook_graduate_to_explore(note_text: str) -> dict[str, Any]:
    lowered = _normalized(note_text)
    return {
        "graduateTarget": "--to explore" in lowered or "--to gap|brainstorm|explore" in lowered,
        "bidirectionalProvenance": "bidirectional provenance" in lowered,
        "notebookRef": "notebookref" in lowered or "notebook id" in lowered,
        "reversible": "reversible" in lowered or "round trip" in lowered,
    }


def tier_routing_absent(text: str) -> bool:
    lowered = _normalized(text)
    forbidden = ("quick tier", "standard tier", "full tier", "qsf", "resolve_entry_tier")
    return not any(token in lowered for token in forbidden) or "no-tier" in lowered or "no tier" in lowered


def validate_command_contract(root: Path | None = None) -> dict[str, Any]:
    bundle = load_command_contract(root)
    command = bundle["commandText"]
    skill = bundle["skillText"]
    note = bundle["noteText"]

    entries = entry_paths_present(command)
    anti_goals = anti_goals_present(command)
    capabilities = first_release_capabilities_present(command)
    interaction = interaction_state_machine_present(skill)
    notebook = notebook_graduate_to_explore(note)
    dispatch_refs = forbidden_dispatch_present(command)

    failures: list[str] = []
    if not all(entries.values()):
        failures.append(f"missing-entry-paths:{[k for k, v in entries.items() if not v]}")
    if not all(goal["present"] for goal in anti_goals.values()):
        failures.append(
            "missing-anti-goals:"
            + ",".join(goal_id for goal_id, goal in anti_goals.items() if not goal["present"])
        )
    if not all(capabilities.values()):
        failures.append(
            f"missing-capabilities:{[k for k, v in capabilities.items() if not v]}"
        )
    if not interaction["askDecideConfirm"]:
        failures.append("missing-interaction-state-machine")
    if not interaction["humanOwnsIntent"]:
        failures.append("missing-human-intent-ownership")
    if not notebook["graduateTarget"]:
        failures.append("missing-notebook-graduate-explore")
    if not notebook["bidirectionalProvenance"]:
        failures.append("missing-notebook-provenance")
    if not tier_routing_absent(command):
        failures.append("tier-routing-present-at-entry")
    if not dispatch_refs:
        failures.append("missing-forbidden-dispatch-declarations")

    return {
        "verdict": "pass" if not failures else "fail",
        "failures": failures,
        "entryPaths": entries,
        "antiGoals": anti_goals,
        "capabilities": capabilities,
        "interaction": interaction,
        "notebookGraduate": notebook,
        "forbiddenDispatchDeclared": dispatch_refs,
        "tierRoutingAbsent": tier_routing_absent(command),
    }


def graduate_notebook_to_explore(
    notebook_item: Mapping[str, Any],
    *,
    map_id: str,
    destination_statement: str,
) -> dict[str, Any]:
    """Reversible notebook → explore provenance link (R2)."""
    item_id = str(notebook_item.get("id") or "").strip()
    text = str(notebook_item.get("text") or "").strip()
    if not item_id or not text:
        raise ExploreContractError("notebook-item-incomplete")
    return {
        "verdict": "ok",
        "entry": "notebook",
        "mapId": map_id,
        "notebookId": item_id,
        "destinationStatement": destination_statement or text,
        "provenance": {
            "notebookId": item_id,
            "graduatedTo": f"explore:{map_id}",
            "reversible": True,
        },
    }


def refuse_implementation_dispatch(command: str) -> dict[str, Any]:
    """Authority boundary — explore never dispatches implementation (R31)."""
    normalized = command.strip().lower()
    for blocked in FORBIDDEN_IMPLEMENTATION_DISPATCH:
        if normalized.startswith(blocked.lower()):
            return {
                "verdict": "refused",
                "reason": "implementation-dispatch-forbidden",
                "command": command,
            }
    return {"verdict": "allow", "command": command}
