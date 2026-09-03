#!/usr/bin/env python3
"""Workflow extension feature flags and explore↔doc handoff routing (PRD 280 R20–R22, PRD 331 R26–R31, R50)."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from explore_command_contract import refuse_implementation_dispatch
from exploration_brief import ExplorationBriefError, assert_fresh as assert_brief_fresh, emit_brief
from planning_readiness import (
    PlanningReadinessError,
    assert_fresh as assert_readiness_fresh,
    compute_readiness,
    refuse_invalidated,
)
from sw_router import check_loop_guard, persistence_effects_for, record_transition

EXTENSION_FLAGS = (
    "externalIntake",
    "handoffBundle",
    "packageSdk",
)

FLAG_ALIASES = {
    "external-intake": "externalIntake",
    "external_intake": "externalIntake",
    "handoff-bundle": "handoffBundle",
    "handoff_bundle": "handoffBundle",
    "package-sdk": "packageSdk",
    "package_sdk": "packageSdk",
    "workflow-pack-sdk": "packageSdk",
}


def load_workflow_config(root: Path) -> dict[str, Any]:
    from shipwright_paths import load_workflow_config as _load_workflow_config

    return _load_workflow_config(root)
def normalize_flag_name(name: str) -> str:
    key = str(name or "").strip()
    if key in EXTENSION_FLAGS:
        return key
    return FLAG_ALIASES.get(key, key)


def extension_flags(cfg: Mapping[str, Any] | None = None, *, root: Path | None = None) -> dict[str, bool]:
    """Return workflow.extensions.* flags (default false when omitted)."""
    if cfg is None:
        cfg = load_workflow_config(root or Path.cwd())
    block = cfg.get("workflow") if isinstance(cfg, Mapping) else None
    extensions = block.get("extensions") if isinstance(block, Mapping) else None
    raw = extensions if isinstance(extensions, Mapping) else {}
    return {flag: bool(raw.get(flag, False)) for flag in EXTENSION_FLAGS}


def extension_enabled(
    flag: str,
    *,
    root: Path | None = None,
    cfg: Mapping[str, Any] | None = None,
) -> bool:
    """True when the named extension flag is enabled.

    `SW_WORKFLOW_EXTENSIONS=1` enables all flags (fixture/CI harness override).
    Per-flag env `SW_WORKFLOW_EXTENSION_<FLAG>=1` enables a single flag.
    """
    normalized = normalize_flag_name(flag)
    if normalized not in EXTENSION_FLAGS:
        raise ValueError(f"unknown workflow extension flag: {flag}")
    if os.environ.get("SW_WORKFLOW_EXTENSIONS", "").strip() in {"1", "true", "TRUE", "yes"}:
        return True
    env_key = f"SW_WORKFLOW_EXTENSION_{normalized.upper()}"
    if os.environ.get(env_key, "").strip() in {"1", "true", "TRUE", "yes"}:
        return True
    return bool(extension_flags(cfg, root=root).get(normalized, False))


def require_extension(
    flag: str,
    *,
    root: Path | None = None,
    cfg: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a typed halt payload when the extension flag is disabled; else None."""
    normalized = normalize_flag_name(flag)
    if extension_enabled(normalized, root=root, cfg=cfg):
        return None
    return {
        "verdict": "halt",
        "error": "workflow-extensions:disabled",
        "flag": f"workflow.extensions.{normalized}",
        "message": (
            f"Extension '{normalized}' is disabled. Set workflow.extensions.{normalized}=true "
            "in .cursor/workflow.config.json after cutover evidence (PRD 280)."  # shipwright-paths-exclusion: operator error cites legacy path during redirect window
        ),
    }


DOC_COMMAND_REL = Path("core/commands/sw-doc.md")

NESTED_ORCHESTRATOR_COMMANDS: frozenset[str] = frozenset(
    {
        "/sw-doc",
        "/sw-deliver",
        "/sw-ship",
        "/sw-debug",
        "/sw-feedback",
        "/sw-retrospective",
    }
)

DOC_BACKWARD_PERSISTENCE: tuple[dict[str, str], ...] = (
    {
        "target": ".cursor/sw-explore/maps/<map-id>.json",
        "effect": "resume-exploration-session",
        "when": "on-confirm-only",
    },
)

EXPLORE_FORWARD_PERSISTENCE: tuple[dict[str, str], ...] = (
    {
        "target": "docs/planning/<unit-id>/",
        "effect": "substantive-doc-write",
        "when": "on-confirm-via-docs-worktree",
    },
    {
        "target": ".cursor/sw-doc-runs/<run-id>/",
        "effect": "provision-doc-run-state",
        "when": "on-confirm-only",
    },
)


class DocExploreRoutingError(ValueError):
    """Invalid explore↔doc handoff input."""


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def _route_reason(*, code: str, message: str, evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if evidence:
        payload["evidence"] = dict(evidence)
    return payload


def _map_id(map_document: Mapping[str, Any]) -> str:
    map_id = str(map_document.get("id") or "").strip()
    if not map_id:
        raise DocExploreRoutingError("missing-map-id")
    return map_id


def _live_readiness(
    map_document: Mapping[str, Any],
    readiness: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if readiness is None:
        return compute_readiness(map_document)
    refuse_invalidated(readiness)
    assert_readiness_fresh(readiness, map_document)
    return dict(readiness)


def refuse_handoff_dispatch(
    command: str,
    *,
    allowed_commands: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Refuse nested orchestration and implementation dispatch during handoff (R26, R31, R50)."""
    base = command.strip().split()[0] if command.strip() else ""
    if allowed_commands and base in allowed_commands:
        return {"verdict": "allow", "command": command}
    if base in NESTED_ORCHESTRATOR_COMMANDS:
        return {
            "verdict": "refused",
            "reason": "nested-orchestrator-dispatch-forbidden",
            "command": command,
        }
    return refuse_implementation_dispatch(command)


def doc_readiness_sufficient(readiness: Mapping[str, Any] | None) -> bool:
    if not isinstance(readiness, Mapping):
        return False
    invalidation = readiness.get("invalidation")
    if isinstance(invalidation, dict) and invalidation.get("state") != "valid":
        return False
    return bool(readiness.get("readyForDocHandoff"))


def propose_doc_backward_route(
    map_document: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any] | None = None,
    route_history: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Insufficient /sw-doc readiness → reasoned, cancelable backward route to explore (R26, R39)."""
    map_id = _map_id(map_document)
    live = _live_readiness(map_document, readiness)
    if doc_readiness_sufficient(live):
        return {
            "verdict": "refused",
            "reason": "doc-readiness-sufficient",
            "message": "Exploration readiness is already sufficient — forward doc entry applies.",
            "mapId": map_id,
        }

    history = list(route_history or [])
    guard = check_loop_guard(history, "explore")
    if guard["verdict"] == "refused":
        return {
            "verdict": "refused",
            "reason": "explore-doc-loop-guard",
            "destination": "explore",
            "command": f"/sw-explore resume {map_id}",
            "loopGuard": guard["loopGuard"],
            "readOnlyUntilConfirm": True,
        }

    blockers = [
        item
        for item in live.get("unknowns") or []
        if isinstance(item, dict) and item.get("classification") == "blocking"
    ]
    command = f"/sw-explore resume {map_id}"
    return {
        "verdict": "propose",
        "direction": "backward",
        "destination": "explore",
        "command": command,
        "mapId": map_id,
        "reason": _route_reason(
            code="doc-readiness-insufficient",
            message="Doc entry requires resolved blocking unknowns — continue exploration first.",
            evidence={
                "mapId": map_id,
                "blockingCount": live.get("summary", {}).get("blockingCount"),
                "blockers": blockers[:5],
            },
        ),
        "persistenceEffects": [dict(item) for item in DOC_BACKWARD_PERSISTENCE],
        "loopGuard": guard.get("loopGuard", {"blocked": False}),
        "loopGuardToken": record_transition(history, "explore"),
        "readOnlyUntilConfirm": True,
        "nestedDispatchForbidden": True,
    }


def apply_doc_backward_cancel(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Operator declined backward route — no persistence (R26)."""
    return {
        "verdict": "cancelled",
        "direction": "backward",
        "destination": proposal.get("destination"),
        "command": proposal.get("command"),
        "persistenceEffects": [],
        "reason": _route_reason(
            code="operator-cancel",
            message="Operator cancelled the backward route to exploration.",
        ),
    }


def apply_doc_backward_confirm(
    proposal: Mapping[str, Any],
    *,
    operator: str,
    dispatch_command: str | None = None,
) -> dict[str, Any]:
    """Confirm backward route — still no silent persistence; operator runs explore next (R26)."""
    command = dispatch_command or str(proposal.get("command") or "")
    blocked = refuse_handoff_dispatch(command, allowed_commands=frozenset({"/sw-explore"}))
    if blocked["verdict"] == "refused":
        return blocked
    return {
        "verdict": "confirmed",
        "direction": "backward",
        "destination": "explore",
        "command": command,
        "operator": operator,
        "persistenceEffects": [dict(item) for item in DOC_BACKWARD_PERSISTENCE],
        "loopGuardToken": proposal.get("loopGuardToken"),
        "reason": _route_reason(
            code="backward-handoff-confirmed",
            message="Operator confirmed backward route to structured exploration.",
            evidence={"operator": operator, "mapId": proposal.get("mapId")},
        ),
        "implements": False,
    }


def propose_explore_forward_handoff(
    map_document: Mapping[str, Any],
    *,
    brief: Mapping[str, Any] | None = None,
    readiness: Mapping[str, Any] | None = None,
    route_history: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Ready exploration → explicit forward /sw-doc handoff proposal (R27, R31, R50)."""
    map_id = _map_id(map_document)
    live_readiness = _live_readiness(map_document, readiness)
    if not doc_readiness_sufficient(live_readiness):
        return {
            "verdict": "refused",
            "reason": "exploration-not-ready",
            "mapId": map_id,
            "readiness": {
                "readyForDocHandoff": False,
                "blockingCount": live_readiness.get("summary", {}).get("blockingCount"),
            },
        }

    live_brief = brief or emit_brief(map_document, readiness=live_readiness)
    try:
        refuse_invalidated(live_readiness)
        assert_brief_fresh(live_brief, map_document)
    except (PlanningReadinessError, ExplorationBriefError) as exc:
        return {
            "verdict": "refused",
            "reason": "stale-brief-or-readiness",
            "detail": str(exc),
            "mapId": map_id,
        }

    if not bool(live_brief.get("readiness", {}).get("readyForDocHandoff")):
        return {
            "verdict": "refused",
            "reason": "brief-not-ready",
            "mapId": map_id,
        }

    history = list(route_history or [])
    guard = check_loop_guard(history, "doc")
    if guard["verdict"] == "refused":
        return {
            "verdict": "refused",
            "reason": "explore-doc-loop-guard",
            "destination": "doc",
            "command": f"/sw-doc --from-explore {map_id}",
            "loopGuard": guard["loopGuard"],
            "readOnlyUntilConfirm": True,
        }

    command = f"/sw-doc --from-explore {map_id}"
    candidates = list(live_brief.get("planningUnitCandidates") or [])
    return {
        "verdict": "propose",
        "direction": "forward",
        "destination": "doc",
        "command": command,
        "mapId": map_id,
        "briefId": live_brief.get("id"),
        "reason": _route_reason(
            code="exploration-ready-for-doc",
            message="Exploration brief and readiness are sufficient for explicit doc handoff.",
            evidence={
                "mapId": map_id,
                "briefId": live_brief.get("id"),
                "candidateCount": len(candidates),
            },
        ),
        "persistenceEffects": [dict(item) for item in EXPLORE_FORWARD_PERSISTENCE],
        "planningUnitCandidates": candidates,
        "loopGuard": guard.get("loopGuard", {"blocked": False}),
        "loopGuardToken": record_transition(history, "doc"),
        "readOnlyUntilConfirm": True,
        "implements": False,
        "authorityBoundary": dict(live_brief.get("authorityBoundary") or {}),
    }


def apply_explore_forward_decline(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Operator declined forward doc handoff (R27)."""
    return {
        "verdict": "declined",
        "direction": "forward",
        "destination": proposal.get("destination"),
        "command": proposal.get("command"),
        "persistenceEffects": [],
        "reason": _route_reason(
            code="operator-decline",
            message="Operator declined the forward doc handoff.",
        ),
    }


def apply_explore_forward_confirm(
    proposal: Mapping[str, Any],
    *,
    operator: str,
    dispatch_command: str | None = None,
) -> dict[str, Any]:
    """Confirm forward handoff — declares effects only; never implements (R27, R31)."""
    command = dispatch_command or str(proposal.get("command") or "")
    blocked = refuse_handoff_dispatch(command, allowed_commands=frozenset({"/sw-doc"}))
    if blocked["verdict"] == "refused":
        return blocked
    return {
        "verdict": "confirmed",
        "direction": "forward",
        "destination": "doc",
        "command": command,
        "operator": operator,
        "persistenceEffects": [dict(item) for item in EXPLORE_FORWARD_PERSISTENCE],
        "loopGuardToken": proposal.get("loopGuardToken"),
        "reason": _route_reason(
            code="forward-handoff-confirmed",
            message="Operator confirmed explicit forward handoff to the doc chain.",
            evidence={"operator": operator, "mapId": proposal.get("mapId")},
        ),
        "implements": False,
    }


def recover_from_loop_guard(
    *,
    route_history: Sequence[str],
    break_destination: str,
    operator: str,
) -> dict[str, Any]:
    """Bounded loop recovery — operator must pick a non-alternating destination (R50)."""
    if break_destination not in {"capture", "deliver", "resume"}:
        return {
            "verdict": "refused",
            "reason": "loop-recovery-destination-invalid",
            "allowed": ["capture", "deliver", "resume"],
        }
    guard = check_loop_guard(list(route_history), break_destination)
    if guard["verdict"] == "refused":
        return {
            "verdict": "refused",
            "reason": "explore-doc-loop-guard",
            "loopGuard": guard["loopGuard"],
        }
    return {
        "verdict": "recovered",
        "destination": break_destination,
        "operator": operator,
        "persistenceEffects": persistence_effects_for(break_destination),
        "loopGuard": guard.get("loopGuard", {"blocked": False}),
        "reason": _route_reason(
            code="loop-recovery",
            message=f"Operator broke explore↔doc cycle via {break_destination}.",
            evidence={"operator": operator},
        ),
    }


def validate_doc_explore_handoff_contract(root: Path | None = None) -> dict[str, Any]:
    """Ensure sw-doc.md documents backward routing and handoff controls (R26, R39)."""
    repo = root or Path(__file__).resolve().parent.parent
    path = repo / DOC_COMMAND_REL
    if not path.is_file():
        return {"verdict": "fail", "error": f"missing-artifact:{DOC_COMMAND_REL}"}
    text = _normalized(path.read_text(encoding="utf-8"))
    controls = {
        "fromExploreEntry": "--from-explore" in text or "from explore" in text,
        "backwardRoute": "backward" in text and "explore" in text,
        "readinessCheck": "readiness" in text,
        "cancelable": "cancel" in text,
        "noNestedOrchestration": "nested" in text and "orchestr" in text,
        "noSilentPersistence": "silent" in text and "persist" in text,
        "workflowExtensionsBackend": "workflow_extensions.py" in text,
        "loopGuard": "loop guard" in text or "loop-guard" in text or "explore↔doc" in text,
    }
    failures = [key for key, ok in controls.items() if not ok]
    return {
        "verdict": "pass" if not failures else "fail",
        "failures": failures,
        "controls": controls,
    }
