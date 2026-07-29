#!/usr/bin/env python3
"""PRD 082 phase 5 — authority hysteresis and per-operation pinning (R26)."""

from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from host_lib import load_workflow_config

import planning_authority as pa
import planning_authority_reasons as par
from planning_authority import AuthorityDecision

STATE_DIR = Path(".cursor") / "sw-authority-probe"
STATE_FILENAME = "state.json"
RECORD_FILE_MODE = 0o600
RECORD_DIR_MODE = 0o700

DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_MIN_DWELL_SECONDS = 30.0
DEFAULT_RECOVERY_SUCCESSES = 1

_OPERATION_PIN = threading.local()


def _utc_now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _monotonic() -> float:
    return time.monotonic()


def state_path(root: Path) -> Path:
    return root / STATE_DIR / STATE_FILENAME


def empty_state() -> dict[str, Any]:
    mono = _monotonic()
    return {
        "version": 1,
        "authorityState": "online",
        "consecutiveFailures": 0,
        "consecutiveSuccesses": 0,
        "stateEnteredAt": _utc_now_iso(),
        "stateEnteredMonotonic": mono,
        "pendingRecovery": False,
        "flapTransitions": [],
        "updatedAt": _utc_now_iso(),
    }


def load_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        return empty_state()
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_state()
    if not isinstance(doc, dict):
        return empty_state()
    doc.setdefault("version", 1)
    doc.setdefault("authorityState", "online")
    doc.setdefault("consecutiveFailures", 0)
    doc.setdefault("consecutiveSuccesses", 0)
    doc.setdefault("pendingRecovery", False)
    doc.setdefault("flapTransitions", [])
    return doc


def save_state(root: Path, state: dict[str, Any]) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(state)
    payload["updatedAt"] = _utc_now_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    os.chmod(path, RECORD_FILE_MODE)
    os.chmod(path.parent, RECORD_DIR_MODE)


def _config_int(probe: dict[str, Any], key: str, default: int) -> int:
    if key in probe and probe[key] is not None:
        return int(probe[key])
    return default


def _config_float(probe: dict[str, Any], key: str, default: float) -> float:
    if key in probe and probe[key] is not None:
        return float(probe[key])
    return default


def hysteresis_config(cfg: dict[str, Any] | None) -> dict[str, float | int]:
    planning = (cfg or {}).get("planning") or {}
    store = planning.get("store") or {}
    probe = store.get("authorityProbe") or {}
    return {
        "failureThreshold": _config_int(probe, "failureThreshold", DEFAULT_FAILURE_THRESHOLD),
        "minDwellSeconds": _config_float(probe, "minDwellSeconds", DEFAULT_MIN_DWELL_SECONDS),
        "recoverySuccesses": _config_int(probe, "recoverySuccesses", DEFAULT_RECOVERY_SUCCESSES),
    }


def read_flap_transitions(root: Path) -> list[dict[str, Any]]:
    """Return persisted flap transitions for doctor / operator reporting."""
    state = load_state(root)
    transitions = state.get("flapTransitions")
    if not isinstance(transitions, list):
        return []
    return [dict(item) for item in transitions if isinstance(item, dict)]


def doctor_authority_flap_report(root: Path) -> dict[str, Any]:
    """Doctor-readable summary of authority flap transitions."""
    transitions = read_flap_transitions(root)
    state = load_state(root)
    return {
        "verdict": "pass",
        "action": "doctor-authority-flap",
        "authorityState": state.get("authorityState"),
        "transitionCount": len(transitions),
        "flapTransitions": transitions,
    }


def _state_entered_monotonic(state: dict[str, Any]) -> float:
    raw = state.get("stateEnteredMonotonic")
    if isinstance(raw, (int, float)):
        return float(raw)
    return _monotonic()


def _record_transition(
    state: dict[str, Any],
    *,
    from_state: str,
    to_state: str,
    reason: str | None,
    trigger: str,
) -> None:
    flap = {
        "from": from_state,
        "to": to_state,
        "at": _utc_now_iso(),
        "reason": reason,
        "trigger": trigger,
    }
    transitions = list(state.get("flapTransitions") or [])
    transitions.append(flap)
    state["flapTransitions"] = transitions[-100:]
    state["authorityState"] = to_state
    state["stateEnteredAt"] = flap["at"]
    state["stateEnteredMonotonic"] = _monotonic()
    state["consecutiveFailures"] = 0
    state["consecutiveSuccesses"] = 0
    state["pendingRecovery"] = to_state != "online"


def _decision_for_published_state(
    raw: AuthorityDecision,
    published_state: str,
) -> AuthorityDecision:
    if published_state == "online":
        return AuthorityDecision(
            configured=raw.configured,
            authorityState="online",
            reason=None,
            writeDisposition="accept",
            cacheValidity="fresh",
            guidance=None,
        )
    reason = raw.reason or par.REASON_STORE_UNAVAILABLE
    policy = par.policy_for_reason(reason)
    return AuthorityDecision(
        configured=raw.configured,
        authorityState=published_state,
        reason=reason,
        writeDisposition=str(policy["writeDisposition"]),
        cacheValidity=str(policy["cacheValidity"]),
        guidance=policy.get("guidance"),
    )


def apply_probe_result(
    root: Path,
    raw: AuthorityDecision,
    *,
    cfg: dict[str, Any] | None = None,
    probe_ok: bool | None = None,
    now_mono: float | None = None,
) -> AuthorityDecision:
    """Apply damped hysteresis to a raw authority probe result."""
    state = load_state(root)
    hs = hysteresis_config(cfg)
    mono = _monotonic() if now_mono is None else float(now_mono)
    published = str(state.get("authorityState") or "online")
    degraded = probe_ok is False if probe_ok is not None else raw.authorityState != "online"
    target_degraded_state = raw.authorityState if raw.authorityState != "online" else "read-only"
    dwell = mono - _state_entered_monotonic(state)

    if not degraded:
        state["consecutiveFailures"] = 0
        if published != "online":
            successes = int(state.get("consecutiveSuccesses") or 0) + 1
            state["consecutiveSuccesses"] = successes
            if state.get("pendingRecovery") and successes >= hs["recoverySuccesses"]:
                if dwell >= hs["minDwellSeconds"]:
                    _record_transition(
                        state,
                        from_state=published,
                        to_state="online",
                        reason=None,
                        trigger="recovery",
                    )
                    published = "online"
                    state["pendingRecovery"] = False
        else:
            state["consecutiveSuccesses"] = 0
            state["pendingRecovery"] = False
    else:
        state["consecutiveSuccesses"] = 0
        failures = int(state.get("consecutiveFailures") or 0) + 1
        state["consecutiveFailures"] = failures
        if (
            failures >= hs["failureThreshold"]
            and dwell >= hs["minDwellSeconds"]
            and published == "online"
        ):
            _record_transition(
                state,
                from_state=published,
                to_state=target_degraded_state,
                reason=raw.reason,
                trigger="degrade",
            )
            published = target_degraded_state

    save_state(root, state)
    return _decision_for_published_state(raw, published)


def resolve_with_hysteresis(
    root: Path,
    cfg: dict[str, Any] | None = None,
    *,
    raw_resolver: Callable[[], AuthorityDecision] | None = None,
    probe_ok: bool | None = None,
    **resolve_kwargs: Any,
) -> AuthorityDecision:
    """Resolve authority once through hysteresis (unpinned path)."""
    cfg = cfg if cfg is not None else load_workflow_config(root)
    if raw_resolver is not None:
        raw = raw_resolver()
    else:
        raw = pa.resolve_authority(root, cfg, **resolve_kwargs)
    return apply_probe_result(root, raw, cfg=cfg, probe_ok=probe_ok)


def current_operation_pin() -> AuthorityDecision | None:
    return getattr(_OPERATION_PIN, "decision", None)


def set_operation_pin(decision: AuthorityDecision | None) -> None:
    _OPERATION_PIN.decision = decision


@contextmanager
def operation_authority_pin(
    root: Path,
    cfg: dict[str, Any] | None = None,
    *,
    raw_resolver: Callable[[], AuthorityDecision] | None = None,
    probe_ok: bool | None = None,
    **resolve_kwargs: Any,
) -> Iterator[AuthorityDecision]:
    """Pin authority for one logical operation — resolved once at entry."""
    prior = current_operation_pin()
    decision = resolve_with_hysteresis(
        root,
        cfg,
        raw_resolver=raw_resolver,
        probe_ok=probe_ok,
        **resolve_kwargs,
    )
    set_operation_pin(decision)
    try:
        yield decision
    finally:
        set_operation_pin(prior)


def resolve_pinned_authority(
    root: Path,
    cfg: dict[str, Any] | None = None,
    **resolve_kwargs: Any,
) -> AuthorityDecision:
    """Return the pinned decision when inside an operation; otherwise resolve fresh."""
    pinned = current_operation_pin()
    if pinned is not None:
        return pinned
    return resolve_with_hysteresis(root, cfg, **resolve_kwargs)


def run_chunked_operation(
    root: Path,
    cfg: dict[str, Any] | None,
    chunks: list[Any],
    writer: Callable[[Any, AuthorityDecision], Any],
    *,
    raw_resolver: Callable[[], AuthorityDecision] | None = None,
    probe_ok: bool | None = None,
) -> dict[str, Any]:
    """Head-plus-overflow-chunk write: authority resolved once for the whole operation."""
    with operation_authority_pin(
        root,
        cfg,
        raw_resolver=raw_resolver,
        probe_ok=probe_ok,
    ) as decision:
        if decision.writeDisposition != "accept":
            return {
                "verdict": "refused",
                "disposition": decision.writeDisposition,
                "reason": decision.reason,
                "chunksCompleted": 0,
                "decision": decision.to_dict(),
            }
        results = [writer(chunk, decision) for chunk in chunks]
        return {
            "verdict": "ok",
            "disposition": decision.writeDisposition,
            "chunksCompleted": len(results),
            "decision": decision.to_dict(),
            "results": results,
        }
