"""Host-switch transition state machine with durable persistence (PRD 352 R18–R20, R23, TR5)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .bundle import atomic_write_json

TRANSITION_SCHEMA_VERSION = "HandoffTransition@v1"
TRANSITIONS_DIR_NAME = "sw-handoff-transitions"
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")

TERMINAL_STATES = frozenset({"resumed", "failed", "cancelled"})
VALID_STATES = frozenset(
    {
        "requested",
        "checkpointed",
        "destination_validated",
        "ownership_transferred",
        "resumed",
        "waiting",
        "failed",
        "cancelled",
    }
)
ORDERED_PROGRESSION = (
    "requested",
    "checkpointed",
    "destination_validated",
    "ownership_transferred",
    "resumed",
)
FABRICATED_FAILURE_KEYS = frozenset(
    {
        "remainingAllowance",
        "remaining_allowance",
        "resetAt",
        "resetTime",
        "quotaRemaining",
        "quotaResetAt",
    }
)


class TransitionError(RuntimeError):
    """Invalid or blocked transition operation."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, **self.details}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def transitions_dir(root: Path) -> Path:
    return root / (".cursor") / TRANSITIONS_DIR_NAME


def transition_path(root: Path, transition_id: str) -> Path:
    tid = str(transition_id or "").strip()
    if not tid or not _SAFE_ID_RE.match(tid):
        raise TransitionError("transition_id_invalid", "transition_id is not a safe identifier")
    return transitions_dir(root) / f"{tid}.json"


def _validate_record(record: Mapping[str, Any]) -> None:
    missing = [key for key in ("schemaVersion", "transitionId", "runId", "state", "updatedAt") if not record.get(key)]
    if missing:
        raise TransitionError("transition_record_incomplete", "transition record missing required fields", missing=missing)
    if record.get("schemaVersion") != TRANSITION_SCHEMA_VERSION:
        raise TransitionError("transition_schema_mismatch", "unexpected transition schema version")
    state = str(record.get("state") or "")
    if state not in VALID_STATES:
        raise TransitionError("transition_state_invalid", f"invalid transition state: {state!r}")


def load_transition(root: Path, transition_id: str) -> dict[str, Any]:
    path = transition_path(root, transition_id)
    if not path.is_file():
        raise TransitionError("transition_absent", "no transition record on disk", path=str(path))
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransitionError("transition_invalid", "transition record is not valid JSON", path=str(path)) from exc
    if not isinstance(record, dict):
        raise TransitionError("transition_invalid", "transition record must be a JSON object", path=str(path))
    _validate_record(record)
    return record


def persist_transition(root: Path, record: Mapping[str, Any]) -> Path:
    """Write transition record before announcing state change (R20)."""
    payload = dict(record)
    payload.setdefault("schemaVersion", TRANSITION_SCHEMA_VERSION)
    payload["updatedAt"] = _utc_now()
    _validate_record(payload)
    path = transition_path(root, str(payload["transitionId"]))
    atomic_write_json(path, payload)
    return path


def create_transition(
    root: Path,
    *,
    transition_id: str,
    run_id: str,
    session_id: str | None = None,
    source_host: str | None = None,
    destination_host: str | None = None,
    ownership_generation: int = 0,
) -> dict[str, Any]:
    now = _utc_now()
    record: dict[str, Any] = {
        "schemaVersion": TRANSITION_SCHEMA_VERSION,
        "transitionId": transition_id,
        "runId": run_id,
        "state": "requested",
        "ownershipGeneration": int(ownership_generation),
        "createdAt": now,
        "updatedAt": now,
    }
    if session_id:
        record["sessionId"] = session_id
    if source_host:
        record["sourceHost"] = source_host
    if destination_host:
        record["destinationHost"] = destination_host
    persist_transition(root, record)
    return record


def _allowed_next_states(current: str) -> set[str]:
    if current in TERMINAL_STATES:
        return set()
    if current == "waiting":
        return set(ORDERED_PROGRESSION)
    idx = ORDERED_PROGRESSION.index(current) if current in ORDERED_PROGRESSION else -1
    allowed: set[str] = {"waiting", "failed", "cancelled"}
    if idx >= 0 and idx + 1 < len(ORDERED_PROGRESSION):
        allowed.add(ORDERED_PROGRESSION[idx + 1])
    return allowed


def advance_transition(
    root: Path,
    transition_id: str,
    new_state: str,
    *,
    resume_evidence: Mapping[str, Any] | None = None,
    failure: Mapping[str, Any] | None = None,
    ownership_generation: int | None = None,
) -> dict[str, Any]:
    if new_state not in VALID_STATES:
        raise TransitionError("transition_state_invalid", f"invalid target state: {new_state!r}")
    record = load_transition(root, transition_id)
    current = str(record.get("state") or "")
    if new_state not in _allowed_next_states(current):
        raise TransitionError(
            "transition_not_allowed",
            f"cannot transition from {current!r} to {new_state!r}",
            fromState=current,
            toState=new_state,
        )
    record["previousState"] = current
    record["state"] = new_state
    if ownership_generation is not None:
        record["ownershipGeneration"] = int(ownership_generation)
    if resume_evidence is not None:
        record["resumeEvidence"] = dict(resume_evidence)
    if failure is not None:
        record["failure"] = dict(failure)
    persist_transition(root, record)
    return record


def _sanitize_observation(observation: Mapping[str, Any]) -> dict[str, Any]:
    fabricated = [key for key in observation if key in FABRICATED_FAILURE_KEYS]
    if fabricated:
        raise TransitionError(
            "transition_failure_fabrication",
            "cannot record fabricated allowance or reset time",
            fabricated=fabricated,
        )
    payload = {key: value for key, value in dict(observation).items() if key not in FABRICATED_FAILURE_KEYS}
    payload.setdefault("recordedAt", _utc_now())
    return payload


def record_observed_failure(
    root: Path,
    transition_id: str,
    observation: Mapping[str, Any] | None = None,
    *,
    user_instruction: str | None = None,
) -> dict[str, Any]:
    """Record observed quota failure or user instruction without fabrication (PRD 352 R23)."""
    if user_instruction and str(user_instruction).strip():
        payload = {
            "source": "user_instruction",
            "code": "user:instruction",
            "message": str(user_instruction).strip(),
            "recordedAt": _utc_now(),
        }
    elif observation is not None:
        payload = _sanitize_observation(observation)
        payload.setdefault("source", str(observation.get("source") or "observed"))
        if "code" not in payload and observation.get("code") is not None:
            payload["code"] = str(observation.get("code"))
        if "message" not in payload and observation.get("message") is not None:
            payload["message"] = str(observation.get("message"))
    else:
        raise TransitionError(
            "transition_failure_missing",
            "observed failure or user instruction required",
        )
    record = load_transition(root, transition_id)
    record["spendingObservation"] = payload
    record["failure"] = {
        "code": str(payload.get("code") or "observed"),
        "message": str(payload.get("message") or ""),
        "source": str(payload.get("source") or "observed"),
    }
    persist_transition(root, record)
    return record


def attach_resume_evidence(
    root: Path,
    transition_id: str,
    *,
    next_eligible_action: str,
    host_adapter_id: str,
) -> dict[str, Any]:
    """Record execution-resumed evidence distinct from import-ack (PRD 352 R21)."""
    record = load_transition(root, transition_id)
    evidence = {
        "recordedAt": _utc_now(),
        "nextEligibleAction": next_eligible_action,
        "hostAdapterId": host_adapter_id,
    }
    record["resumeEvidence"] = evidence
    if record.get("state") != "resumed":
        record["previousState"] = record.get("state")
        record["state"] = "resumed"
    persist_transition(root, record)
    return record
