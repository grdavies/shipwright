#!/usr/bin/env python3
"""Bare /sw bounded route selection and operator controls (PRD 331 R25, R29, R30, R39, R50)."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

COMMAND_REL = Path("core/commands/sw.md")

DESTINATIONS: frozenset[str] = frozenset({"capture", "explore", "doc", "deliver", "resume"})

# Closed command surface — no invented top-level sw-* commands (R29, R30).
ALLOWED_COMMANDS: frozenset[str] = frozenset(
    {
        "/sw-note",
        "/sw-explore",
        "/sw-doc",
        "/sw-doc-review",
        "/sw-freeze",
        "/sw-prd",
        "/sw-deliver",
        "/sw-ship",
        "/sw-triage",
        "/sw-status",
        "/sw-init",
    }
)

DEFAULT_DESTINATION_COMMAND: dict[str, str] = {
    "capture": "/sw-note",
    "explore": "/sw-explore",
    "doc": "/sw-doc",
    "deliver": "/sw-deliver",
    "resume": "/sw-deliver run",
}

PERSISTENCE_EFFECTS: dict[str, tuple[dict[str, str], ...]] = {
    "capture": (
        {
            "target": ".cursor/sw-notebook/notebook.jsonl",
            "effect": "append-notebook-item",
            "when": "on-confirm",
        },
    ),
    "explore": (
        {
            "target": ".cursor/sw-explore/maps/<map-id>.json",
            "effect": "conditional-map-persist",
            "when": "persistence-trigger-only",
        },
    ),
    "doc": (
        {
            "target": "docs/planning/<unit-id>/",
            "effect": "substantive-doc-write",
            "when": "on-confirm-via-docs-worktree",
        },
    ),
    "deliver": (
        {
            "target": ".cursor/sw-deliver-runs/<run-id>/",
            "effect": "provision-deliver-state",
            "when": "on-confirm",
        },
        {
            "target": ".sw-worktrees/<slug>-*",
            "effect": "provision-phase-worktrees",
            "when": "on-confirm",
        },
    ),
    "resume": (
        {
            "target": ".cursor/sw-deliver-runs/<run-id>/",
            "effect": "advance-existing-run",
            "when": "on-confirm",
        },
    ),
}

LOOP_GUARD_PAIR: tuple[str, str] = ("explore", "doc")
LOOP_GUARD_MAX_ALTERNATIONS = 2


class SwRouterError(ValueError):
    """Invalid router input or state."""


@dataclass
class RouterContext:
    """Read-only durable signals for route resolution (testable without live git)."""

    configured: bool = True
    deliver_run: Mapping[str, Any] | None = None
    phase_ship: Mapping[str, Any] | None = None
    frozen_task_list: str | None = None
    exploration_map: Mapping[str, Any] | None = None
    exploration_readiness: Mapping[str, Any] | None = None
    open_notebook_ideas: int = 0
    unfrozen_prd: bool = False
    brainstorm_only: bool = False
    planning_next_unit: str | None = None
    ambiguous_deliver_runs: Sequence[Mapping[str, Any]] | None = None
    route_history: list[str] = field(default_factory=list)
    hint: str | None = None


def _repo_root(root: Path | None = None) -> Path:
    if root is not None:
        return root
    return Path(__file__).resolve().parent.parent


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower())


def persistence_effects_for(destination: str) -> list[dict[str, str]]:
    if destination not in DESTINATIONS:
        raise SwRouterError(f"unknown-destination:{destination}")
    return [dict(item) for item in PERSISTENCE_EFFECTS.get(destination, ())]


def validate_command_surface(command: str) -> dict[str, Any]:
    """Refuse invented or unbounded command surfaces (R29, R30)."""
    base = command.strip().split()[0] if command.strip() else ""
    if not base.startswith("/sw"):
        return {
            "verdict": "refused",
            "reason": "not-sw-command",
            "command": command,
        }
    if base not in ALLOWED_COMMANDS:
        return {
            "verdict": "refused",
            "reason": "invented-command-surface",
            "command": command,
            "allowed": sorted(ALLOWED_COMMANDS),
        }
    return {"verdict": "allow", "command": command}


def detect_explore_doc_loop(history: Sequence[str]) -> dict[str, Any]:
    """Prevent repeated explore↔doc cycling (R50)."""
    left, right = LOOP_GUARD_PAIR
    alternations = 0
    previous: str | None = None
    for entry in history:
        if entry not in {left, right}:
            previous = entry
            continue
        if previous in {left, right} and entry != previous:
            alternations += 1
        previous = entry
    blocked = alternations >= LOOP_GUARD_MAX_ALTERNATIONS
    return {
        "blocked": blocked,
        "alternations": alternations,
        "maxAlternations": LOOP_GUARD_MAX_ALTERNATIONS,
        "pair": list(LOOP_GUARD_PAIR),
    }


def check_loop_guard(history: Sequence[str], destination: str) -> dict[str, Any]:
    if destination not in LOOP_GUARD_PAIR:
        return {"verdict": "allow", "loopGuard": detect_explore_doc_loop(history)}
    projected = list(history) + [destination]
    guard = detect_explore_doc_loop(projected)
    if guard["blocked"]:
        return {
            "verdict": "refused",
            "reason": "explore-doc-loop-guard",
            "loopGuard": guard,
        }
    return {"verdict": "allow", "loopGuard": guard}


def _route_reason(
    *,
    code: str,
    message: str,
    evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if evidence:
        payload["evidence"] = dict(evidence)
    return payload


def _proposal(
    *,
    destination: str,
    command: str,
    reason: Mapping[str, Any],
    loop_guard: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if destination not in DESTINATIONS:
        raise SwRouterError(f"unknown-destination:{destination}")
    surface = validate_command_surface(command)
    if surface["verdict"] == "refused":
        return {
            "verdict": "refused",
            "reason": surface["reason"],
            "command": command,
            "surface": surface,
        }
    return {
        "verdict": "propose",
        "destination": destination,
        "command": command,
        "reason": dict(reason),
        "persistenceEffects": persistence_effects_for(destination),
        "loopGuard": dict(loop_guard or {"blocked": False}),
        "readOnlyUntilConfirm": True,
    }


def propose_route(context: RouterContext) -> dict[str, Any]:
    """Resolve a single bounded next action from durable signals (R25, R39)."""
    if context.ambiguous_deliver_runs:
        runs = list(context.ambiguous_deliver_runs)
        return {
            "verdict": "ambiguous",
            "reason": _route_reason(
                code="ambiguous-deliver-runs",
                message="Multiple live deliver runs — operator must pick a worktree.",
                evidence={"runs": runs},
            ),
            "candidates": [
                {
                    "destination": "resume",
                    "command": f"/sw-deliver run --run-id {run.get('runId', '')}".strip(),
                    "worktree": run.get("worktree"),
                }
                for run in runs
            ],
            "readOnlyUntilConfirm": True,
        }

    hint = _normalized(context.hint or "")

    if not context.configured:
        return _proposal(
            destination="resume",
            command="/sw-init",
            reason=_route_reason(
                code="unconfigured-repo",
                message="Repository has no workflow config — first-run setup required.",
            ),
        )

    deliver = context.deliver_run if isinstance(context.deliver_run, Mapping) else None
    if deliver and str(deliver.get("status") or "") in {"running", "blocked"}:
        run_id = str(deliver.get("runId") or "").strip()
        task_list = str(deliver.get("sourceTaskList") or deliver.get("source_task_list") or "").strip()
        unit_id = str(deliver.get("unitId") or deliver.get("unit_id") or "").strip()
        if unit_id:
            command = f"/sw-deliver run --unit-id {unit_id}"
        elif task_list:
            command = f"/sw-deliver run {task_list}"
        elif run_id:
            command = f"/sw-deliver run --run-id {run_id}"
        else:
            command = "/sw-deliver run"
        return _proposal(
            destination="resume",
            command=command,
            reason=_route_reason(
                code="live-deliver-run",
                message="A deliver run is in flight — resume is the bounded next action.",
                evidence={"runId": run_id, "status": deliver.get("status")},
            ),
        )

    phase_ship = context.phase_ship if isinstance(context.phase_ship, Mapping) else None
    if phase_ship and str(phase_ship.get("phaseStatus") or "") in {"running", "blocked"}:
        return _proposal(
            destination="resume",
            command="/sw-ship",
            reason=_route_reason(
                code="live-phase-ship",
                message="Phase ship chain is active on this worktree.",
                evidence={"phaseStatus": phase_ship.get("phaseStatus")},
            ),
        )

    if context.frozen_task_list and not deliver:
        return _proposal(
            destination="deliver",
            command=f"/sw-deliver run {context.frozen_task_list}",
            reason=_route_reason(
                code="frozen-task-list",
                message="Frozen task list exists with no deliver run — start delivery.",
                evidence={"taskList": context.frozen_task_list},
            ),
        )

    readiness = context.exploration_readiness if isinstance(context.exploration_readiness, Mapping) else None
    exploration_map = context.exploration_map if isinstance(context.exploration_map, Mapping) else None
    if exploration_map:
        ready = bool(readiness and readiness.get("readyForDocHandoff"))
        if ready:
            map_id = str(exploration_map.get("id") or "").strip()
            guard = check_loop_guard(context.route_history, "doc")
            if guard["verdict"] == "refused":
                return {
                    "verdict": "refused",
                    "destination": "doc",
                    "command": f"/sw-doc --from-explore {map_id}".strip(),
                    "reason": _route_reason(
                        code="explore-doc-loop-guard",
                        message="Explore↔doc loop guard blocked another doc handoff.",
                    ),
                    "loopGuard": guard["loopGuard"],
                    "readOnlyUntilConfirm": True,
                }
            return _proposal(
                destination="doc",
                command=f"/sw-doc --from-explore {map_id}".strip(),
                reason=_route_reason(
                    code="exploration-ready",
                    message="Exploration readiness is sufficient for explicit doc handoff.",
                    evidence={"mapId": map_id, "readyForDocHandoff": True},
                ),
                loop_guard=guard.get("loopGuard"),
            )
        map_id = str(exploration_map.get("id") or "").strip()
        return _proposal(
            destination="explore",
            command=f"/sw-explore resume {map_id}".strip() if map_id else "/sw-explore",
            reason=_route_reason(
                code="exploration-in-progress",
                message="Exploration map is open — continue structured exploration.",
                evidence={"mapId": map_id or None},
            ),
        )

    if context.unfrozen_prd:
        command = "/sw-doc-review" if "reviewed" not in hint else "/sw-freeze"
        return _proposal(
            destination="doc",
            command=command,
            reason=_route_reason(
                code="unfrozen-prd",
                message="Draft PRD exists — continue the doc chain.",
            ),
        )

    if context.brainstorm_only:
        return _proposal(
            destination="doc",
            command="/sw-prd",
            reason=_route_reason(
                code="brainstorm-only",
                message="Brainstorm exists without a PRD — continue documentation.",
            ),
        )

    if context.open_notebook_ideas > 0 or any(token in hint for token in ("capture", "note", "jot", "idea")):
        return _proposal(
            destination="capture",
            command="/sw-note",
            reason=_route_reason(
                code="capture-surface",
                message="Low-ceremony capture is the bounded next action.",
                evidence={"openNotebookIdeas": context.open_notebook_ideas},
            ),
        )

    if any(token in hint for token in ("explore", "discover", "unknown")):
        guard = check_loop_guard(context.route_history, "explore")
        if guard["verdict"] == "refused":
            return {
                "verdict": "refused",
                "destination": "explore",
                "command": "/sw-explore",
                "reason": _route_reason(
                    code="explore-doc-loop-guard",
                    message="Explore↔doc loop guard blocked another explore entry.",
                ),
                "loopGuard": guard["loopGuard"],
                "readOnlyUntilConfirm": True,
            }
        return _proposal(
            destination="explore",
            command="/sw-explore",
            reason=_route_reason(
                code="operator-explore-hint",
                message="Operator hint requests exploration before planning.",
            ),
            loop_guard=guard.get("loopGuard"),
        )

    if context.planning_next_unit:
        return _proposal(
            destination="doc",
            command=f"/sw-triage --unit-id {context.planning_next_unit}",
            reason=_route_reason(
                code="planning-next-unit",
                message="Planning store has an eligible unit — classify before ceremony.",
                evidence={"unitId": context.planning_next_unit},
            ),
        )

    return _proposal(
        destination="capture",
        command="/sw-status",
        reason=_route_reason(
            code="idle-state",
            message="No in-flight workflow — report status or capture a new idea.",
        ),
    )


def apply_cancel(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Operator declined the proposal — no persistence effects (R25)."""
    return {
        "verdict": "cancelled",
        "destination": proposal.get("destination"),
        "command": proposal.get("command"),
        "persistenceEffects": [],
        "reason": _route_reason(
            code="operator-cancel",
            message="Operator cancelled the proposed route.",
        ),
    }


def apply_override(
    proposal: Mapping[str, Any],
    destination: str,
    *,
    operator: str,
    command: str | None = None,
) -> dict[str, Any]:
    """Operator explicitly chose a different bounded destination (R25)."""
    if destination not in DESTINATIONS:
        return {
            "verdict": "refused",
            "reason": "override-destination-invalid",
            "destination": destination,
            "allowed": sorted(DESTINATIONS),
        }
    resolved_command = command or DEFAULT_DESTINATION_COMMAND.get(destination, "")
    if not resolved_command:
        return {"verdict": "refused", "reason": "override-command-required", "destination": destination}
    surface = validate_command_surface(resolved_command)
    if surface["verdict"] == "refused":
        return {
            "verdict": "refused",
            "reason": surface["reason"],
            "command": resolved_command,
            "surface": surface,
        }
    guard = check_loop_guard(proposal.get("routeHistory") or [], destination)
    if guard["verdict"] == "refused":
        return {
            "verdict": "refused",
            "reason": "explore-doc-loop-guard",
            "destination": destination,
            "loopGuard": guard["loopGuard"],
        }
    return {
        "verdict": "override",
        "destination": destination,
        "command": resolved_command,
        "operator": operator,
        "persistenceEffects": persistence_effects_for(destination),
        "reason": _route_reason(
            code="operator-override",
            message=f"Operator overrode proposal to {destination}.",
            evidence={"operator": operator, "originalDestination": proposal.get("destination")},
        ),
        "loopGuard": guard.get("loopGuard", {"blocked": False}),
        "readOnlyUntilConfirm": False,
    }


def record_transition(history: list[str], destination: str) -> list[str]:
    """Append a destination to router history for loop-guard evaluation."""
    if destination not in DESTINATIONS:
        raise SwRouterError(f"unknown-destination:{destination}")
    updated = list(history)
    updated.append(destination)
    return updated


def load_command_contract(root: Path | None = None) -> dict[str, Any]:
    repo = _repo_root(root)
    path = repo / COMMAND_REL
    if not path.is_file():
        raise SwRouterError(f"missing-artifact:{COMMAND_REL}")
    return {"commandPath": str(COMMAND_REL), "commandText": path.read_text(encoding="utf-8")}


def validate_sw_command_contract(root: Path | None = None) -> dict[str, Any]:
    """Ensure sw.md documents all bounded destinations and router controls."""
    bundle = load_command_contract(root)
    text = _normalized(bundle["commandText"])
    destinations = {name: name in text for name in sorted(DESTINATIONS)}
    controls = {
        "routeReasons": "route reason" in text or "reason code" in text,
        "persistenceEffects": "persistence effect" in text,
        "cancel": "cancel" in text,
        "override": "override" in text,
        "loopGuard": "loop guard" in text or "explore↔doc" in text or "explore-doc" in text,
        "routerBackend": "sw_router.py" in text,
    }
    failures: list[str] = []
    if not all(destinations.values()):
        failures.append(f"missing-destinations:{[k for k, v in destinations.items() if not v]}")
    if not all(controls.values()):
        failures.append(f"missing-controls:{[k for k, v in controls.items() if not v]}")
    return {
        "verdict": "pass" if not failures else "fail",
        "failures": failures,
        "destinations": destinations,
        "controls": controls,
    }


def build_context_from_signals(signals: Mapping[str, Any]) -> RouterContext:
    """Materialize RouterContext from a JSON signal bundle (CLI adapter)."""
    history = signals.get("routeHistory")
    return RouterContext(
        configured=bool(signals.get("configured", True)),
        deliver_run=signals.get("deliverRun"),
        phase_ship=signals.get("phaseShip"),
        frozen_task_list=signals.get("frozenTaskList"),
        exploration_map=signals.get("explorationMap"),
        exploration_readiness=signals.get("explorationReadiness"),
        open_notebook_ideas=int(signals.get("openNotebookIdeas") or 0),
        unfrozen_prd=bool(signals.get("unfrozenPrd")),
        brainstorm_only=bool(signals.get("brainstormOnly")),
        planning_next_unit=signals.get("planningNextUnit"),
        ambiguous_deliver_runs=signals.get("ambiguousDeliverRuns"),
        route_history=list(history) if isinstance(history, list) else [],
        hint=signals.get("hint"),
    )


def cmd_propose(signals_json: str) -> int:
    signals = json.loads(signals_json)
    context = build_context_from_signals(signals)
    print(json.dumps(propose_route(context), indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Bare /sw bounded router (PRD 331).")
    sub = parser.add_subparsers(dest="cmd", required=True)

    propose = sub.add_parser("propose", help="Propose a single bounded route from signals JSON.")
    propose.add_argument("signals", help="JSON signal bundle or '-' for stdin.")

    sub.add_parser("validate-contract", help="Validate core/commands/sw.md router contract.")

    args = parser.parse_args(argv)
    if args.cmd == "propose":
        payload = sys.stdin.read() if args.signals == "-" else args.signals
        return cmd_propose(payload)
    if args.cmd == "validate-contract":
        result = validate_sw_command_contract()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["verdict"] == "pass" else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
