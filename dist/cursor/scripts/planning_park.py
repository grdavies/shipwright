#!/usr/bin/env python3
"""Scheduler park governance + exhaustion semantics (PRD 057 R16, R28).

Shared, backend-neutral helpers used by the file-path scheduler
(``planning_deliver_gate``), the issue-store scheduler (``planning_scheduler``),
the graph dispatcher (``planning-graph.py``), and the doctor
(``planning-doctor.py``):

- **Park allowlist (R28):** a unit may only be parked by an actor listed in the
  local ``planning.scheduler.parkAllowlist`` config; parking requires a reason.
  An unauthorized or reasonless park is refused (fail-closed).
- **Park registry:** a backend-neutral local record (``.cursor/planning-parked.json``)
  of parked units keyed by unit-id, each carrying ``reason``/``actor``/``at``.
  The issue-store frontier ALSO honors the provider-native ``sw:parked`` label
  (D4); this registry is the offline-testable, file-store-compatible mechanism.
- **Exhaustion (R28):** when the eligible frontier is empty after skip/park
  filtering the scheduler emits an explicit ``scheduler-exhausted`` halt (distinct
  from failure and from silent empty output) naming the parked/unrunnable units
  and the unpark remediation.

Writing the registry only occurs on an explicit park/unpark; when no unit is
parked ``load_parked`` returns ``{}`` and scheduler behavior is unchanged, so the
file-store code path is preserved (R23).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_paths as pp  # noqa: E402

PARK_LABEL = "sw:parked"
PARK_REGISTRY_REL = ".cursor/planning-parked.json"
SCHEDULER_EXHAUSTED_EXIT = 40
PARK_REFUSED_EXIT = 22

UNPARK_REMEDIATION = (
    "unpark a unit as an allowlisted actor "
    "(planning-graph.py unpark <unit-id> --actor <actor> --reason <why>) "
    "or freeze a runnable task list for a skipped unit"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def actor_id() -> str:
    """Resolve the acting operator id for park/unpark authorization."""
    return (
        os.environ.get("SW_PARK_ACTOR")
        or os.environ.get("SW_RECOVERY_ACTOR")
        or os.environ.get("USER")
        or "operator"
    )


def park_allowlist(root: Path, cfg: dict[str, Any] | None = None) -> list[str]:
    """Local-config allowlist of actors permitted to park units (R28, fail-closed).

    An empty/missing allowlist authorizes no actor, so parking is refused by
    default until an operator opts in via ``planning.scheduler.parkAllowlist``.
    """
    if cfg is None:
        cfg = pp.load_workflow_config(root)
    scheduler = ((cfg.get("planning") or {}).get("scheduler") or {})
    raw = scheduler.get("parkAllowlist") or []
    if not isinstance(raw, list):
        return []
    return [str(a).strip() for a in raw if str(a).strip()]


def is_authorized(actor: str | None, allowlist: list[str]) -> bool:
    return bool(actor) and str(actor) in set(allowlist)


def registry_path(root: Path) -> Path:
    try:
        base = pp.git_root(root)
    except Exception:
        # Fall back to the given root when not inside a git worktree (offline
        # fixtures / detached invocations); real callers pass a git root.
        base = root
    return base / PARK_REGISTRY_REL


def _load_registry(root: Path) -> dict[str, Any]:
    path = registry_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def load_parked(root: Path) -> dict[str, dict[str, Any]]:
    """Return the parked-unit map (unit-id → {reason, actor, at})."""
    registry = _load_registry(root)
    parked = registry.get("parked")
    if not isinstance(parked, dict):
        return {}
    return {uid: dict(rec) for uid, rec in parked.items() if isinstance(rec, dict)}


def _write_registry(root: Path, registry: dict[str, Any]) -> None:
    path = registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def park_unit(
    root: Path,
    unit_id: str,
    *,
    reason: str | None,
    actor: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Park a unit after allowlist + reason governance (R28).

    Returns a ``refused`` verdict (never mutates) when the actor is not
    allowlisted or no reason is supplied.
    """
    actor = actor or actor_id()
    allow = park_allowlist(root, cfg)
    if not is_authorized(actor, allow):
        return {
            "verdict": "refused",
            "halt": "park-unauthorized",
            "action": "park",
            "unitId": unit_id,
            "actor": actor,
            "allowlist": allow,
            "remediation": "add the actor to planning.scheduler.parkAllowlist in workflow.config.json",
        }
    if not reason or not str(reason).strip():
        return {
            "verdict": "refused",
            "halt": "park-reason-required",
            "action": "park",
            "unitId": unit_id,
            "actor": actor,
            "remediation": "supply a park reason with --reason <why>",
        }
    registry = _load_registry(root)
    parked = registry.get("parked")
    if not isinstance(parked, dict):
        parked = {}
    parked[unit_id] = {"reason": str(reason).strip(), "actor": actor, "at": utc_now()}
    registry["parked"] = parked
    _write_registry(root, registry)
    return {
        "verdict": "pass",
        "action": "park",
        "unitId": unit_id,
        "reason": str(reason).strip(),
        "actor": actor,
    }


def unpark_unit(
    root: Path,
    unit_id: str,
    *,
    actor: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Unpark a unit (allowlist-governed, idempotent)."""
    actor = actor or actor_id()
    allow = park_allowlist(root, cfg)
    if not is_authorized(actor, allow):
        return {
            "verdict": "refused",
            "halt": "park-unauthorized",
            "action": "unpark",
            "unitId": unit_id,
            "actor": actor,
            "allowlist": allow,
            "remediation": "add the actor to planning.scheduler.parkAllowlist in workflow.config.json",
        }
    registry = _load_registry(root)
    parked = registry.get("parked")
    removed = False
    if isinstance(parked, dict) and unit_id in parked:
        del parked[unit_id]
        registry["parked"] = parked
        _write_registry(root, registry)
        removed = True
    return {
        "verdict": "pass",
        "action": "unpark",
        "unitId": unit_id,
        "actor": actor,
        "removed": removed,
    }


def is_parked_label(labels: list[str] | set[str]) -> bool:
    return PARK_LABEL in set(labels)


def parked_skip_record(unit_id: str, entry: dict[str, Any]) -> dict[str, Any]:
    """Standard 'parked' skip record for a registry-backed park entry (R16/R28)."""
    return {
        "unitId": unit_id,
        "reason": "parked",
        "parkReason": entry.get("reason"),
        "parkedBy": entry.get("actor"),
    }


def partition_skipped(skipped: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Split skip records into parked-unit ids and unrunnable-unit ids."""
    parked = [str(s.get("unitId")) for s in skipped if s.get("reason") == "parked"]
    unrunnable = [str(s.get("unitId")) for s in skipped if s.get("reason") != "parked"]
    return parked, unrunnable


def scheduler_exhausted_payload(
    *,
    source: str,
    eligible: list[str],
    skipped: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the explicit ``scheduler-exhausted`` halt payload (R28).

    Distinct from a failure verdict and from silent empty output; names the
    parked and unrunnable units and the unpark remediation.
    """
    parked, unrunnable = partition_skipped(skipped)
    return {
        "verdict": "halt",
        "halt": "scheduler-exhausted",
        "action": "next",
        "source": source,
        "error": "scheduler-exhausted: no runnable, unparked planning unit in the frontier",
        "parkedUnits": parked,
        "unrunnableUnits": unrunnable,
        "skipped": skipped,
        "eligible": eligible,
        "remediation": UNPARK_REMEDIATION,
    }
