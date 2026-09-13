"""Implementation-capture event journal (PRD 350 R6–R20, R13–R16, R25–R26).

Sole write/read API for run-scoped ``events.jsonl`` (via ``wave_run_paths.events_path``).
When ``capture.enabled`` is false (Phase 1 default), ``record_event`` is a no-op.

Agents outside this module must not open ``events.jsonl`` directly (R25).

Discovery call convention (R8)
------------------------------
Agents emit discoveries only via ``emit_discovery(...)`` — never by calling
``record_event`` directly. After a successful write, ``emit_discovery`` may
surface a gap-capture *prompt* when ``summary`` matches ``capture.gapKeywords``;
operator confirmation is required before any gap write (R19).
"""
from __future__ import annotations

import fcntl
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from _sw.capture_schema_lib import (
    CapturePrivacyError,
    CaptureSchemaError,
    SCHEMA_VERSION,
    compute_event_id,
    validate_event,
)
from shipwright_paths import load_workflow_config
from wave_run_paths import events_path, run_directory

EVENTS_FILENAME = "events.jsonl"
CAPTURE_ERRORS_FILENAME = "capture-errors.jsonl"
SUB_AGENT_EVENTS_DIRNAME = "sub-agent-events"
DEFAULT_MAX_FILE_SIZE_BYTES = 52_428_800  # 50 MiB


class RunIsolationError(ValueError):
    """Raised when an event's runId does not match the open journal run."""


class CaptureStorageError(OSError):
    """Raised when events.jsonl would exceed the configured size limit."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def capture_errors_path(root: Path, run_id: str) -> Path:
    return run_directory(root, run_id) / CAPTURE_ERRORS_FILENAME


def sub_agent_events_path(root: Path, run_id: str, dispatch_id: str) -> Path:
    return run_directory(root, run_id) / SUB_AGENT_EVENTS_DIRNAME / f"{dispatch_id}.jsonl"


def _capture_section(root: Path) -> dict[str, Any]:
    cfg = load_workflow_config(root)
    section = cfg.get("capture")
    return section if isinstance(section, dict) else {}


def capture_enabled(root: Path) -> bool:
    return bool(_capture_section(root).get("enabled", False))


def max_file_size_bytes(root: Path) -> int:
    raw = _capture_section(root).get("maxFileSizeBytes", DEFAULT_MAX_FILE_SIZE_BYTES)
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_FILE_SIZE_BYTES


def ensure_capture_files(root: Path, run_id: str) -> dict[str, Path]:
    """Create empty events.jsonl and capture-errors.jsonl if missing (R13).

    Resume-safe: existing files are left intact.
    """
    run_dir = run_directory(root, run_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    events = events_path(root, run_id)
    errors = capture_errors_path(root, run_id)
    for path in (events, errors):
        if not path.exists():
            path.touch()
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
    return {"events": events, "errors": errors, "runDir": run_dir}


def _append_error(root: Path, run_id: str, record: dict[str, Any]) -> None:
    ensure_capture_files(root, run_id)
    path = capture_errors_path(root, run_id)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(line)
            handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _existing_event_ids(path: Path) -> set[str]:
    ids: set[str] = set()
    if not path.is_file():
        return ids
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ids
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            eid = obj.get("eventId")
            if isinstance(eid, str) and eid:
                ids.add(eid)
    return ids


def record_event(
    event: dict[str, Any],
    run_id: str | None = None,
    *,
    root: Path | None = None,
) -> None:
    """Append one validated capture event to events.jsonl (R14).

    No-op when ``capture.enabled`` is false. Deduplicates by ``eventId``
    (first write wins). Never uses ``os.replace``.
    """
    if root is None:
        raise RunIsolationError("root is required for record_event")
    root = root.resolve()

    if not capture_enabled(root):
        return

    journal_run_id = run_id or str(event.get("runId") or "")
    if not journal_run_id:
        raise RunIsolationError("run_id required")

    ensure_capture_files(root, journal_run_id)

    try:
        validate_event(event)
    except (CaptureSchemaError, CapturePrivacyError) as exc:
        _append_error(
            root,
            journal_run_id,
            {
                "at": _utc_now(),
                "kind": type(exc).__name__,
                "message": str(exc),
                "eventId": event.get("eventId"),
                "eventType": event.get("eventType"),
            },
        )
        raise

    event_run_id = str(event.get("runId") or "")
    if event_run_id != journal_run_id:
        raise RunIsolationError(
            f"event runId {event_run_id!r} does not match journal run {journal_run_id!r}"
        )

    path = events_path(root, journal_run_id)
    event_id = str(event.get("eventId") or "")
    if event_id in _existing_event_ids(path):
        return

    limit = max_file_size_bytes(root)
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    payload_bytes = len(payload.encode("utf-8"))

    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.touch()

    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        # Size check inside flock to avoid TOCTOU under concurrent writers (CR-P2-001).
        try:
            current_size = path.stat().st_size
        except OSError:
            current_size = 0
        if current_size + payload_bytes > limit:
            err = CaptureStorageError(
                f"events.jsonl would exceed maxFileSizeBytes ({limit})"
            )
            _append_error(
                root,
                journal_run_id,
                {
                    "at": _utc_now(),
                    "kind": "CaptureStorageError",
                    "message": str(err),
                    "eventId": event_id,
                    "sizeBytes": current_size,
                    "limitBytes": limit,
                },
            )
            raise err
        try:
            if event_id in _existing_event_ids(path):
                return
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _parse_iso(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def read_events(
    run_id: str,
    event_types: Sequence[str] | None = None,
    phase_id: str | None = None,
    agent_id: str | None = None,
    after: str | None = None,
    before: str | None = None,
    *,
    root: Path | None = None,
) -> list[dict[str, Any]]:
    """Read and filter capture events in append order (R25, R26)."""
    if root is None:
        raise RunIsolationError("root is required for read_events")
    root = root.resolve()
    path = events_path(root, run_id)
    if not path.is_file():
        return []

    type_filter = set(event_types) if event_types else None
    after_dt = _parse_iso(after) if after else None
    before_dt = _parse_iso(before) if before else None

    results: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        # Skip non-capture legacy log lines that may share events.jsonl.
        if "eventId" not in obj or "eventType" not in obj:
            continue
        if type_filter is not None and obj.get("eventType") not in type_filter:
            continue
        if phase_id is not None and obj.get("phaseId") != phase_id:
            continue
        if agent_id is not None and obj.get("agentId") != agent_id:
            continue
        ts = obj.get("timestamp")
        if isinstance(ts, str) and (after_dt or before_dt):
            try:
                event_dt = _parse_iso(ts)
            except ValueError:
                continue
            if after_dt is not None and event_dt <= after_dt:
                continue
            if before_dt is not None and event_dt >= before_dt:
                continue
        results.append(obj)
    return results


def consolidate_sub_agent_events(
    run_id: str, dispatch_id: str, *, root: Path
) -> int:
    """Merge a sub-agent sidecar into events.jsonl (R16). Idempotent.

    Returns the count of newly appended events. Missing sidecar → 0.
    Truncated final line (no trailing newline) is discarded with a warning.
    """
    if not capture_enabled(root):
        return 0

    sidecar = sub_agent_events_path(root, run_id, dispatch_id)
    if not sidecar.is_file():
        return 0

    ensure_capture_files(root, run_id)
    raw = sidecar.read_bytes()
    if raw and not raw.endswith(b"\n"):
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        discarded = lines[-1] if lines else ""
        complete = lines[:-1]
        _append_error(
            root,
            run_id,
            {
                "at": _utc_now(),
                "kind": "sidecar_truncation",
                "message": "discarded incomplete trailing sidecar line",
                "dispatchId": dispatch_id,
                "discardedPrefix": discarded[:80],
            },
        )
    else:
        complete = raw.decode("utf-8").splitlines()

    appended = 0
    for line in complete:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            _append_error(
                root,
                run_id,
                {
                    "at": _utc_now(),
                    "kind": "sidecar_malformed",
                    "message": "skipped malformed sidecar line",
                    "dispatchId": dispatch_id,
                },
            )
            continue
        if not isinstance(obj, dict):
            continue
        before_ids = _existing_event_ids(events_path(root, run_id))
        eid = obj.get("eventId")
        if isinstance(eid, str) and eid in before_ids:
            continue
        try:
            record_event(obj, run_id=run_id, root=root)
        except (
            CaptureSchemaError,
            CapturePrivacyError,
            CaptureStorageError,
            RunIsolationError,
        ):
            continue
        after_ids = _existing_event_ids(events_path(root, run_id))
        if isinstance(eid, str) and eid in after_ids and eid not in before_ids:
            appended += 1
    return appended


# ---------------------------------------------------------------------------
# Phase 2 trigger emitters (R6–R12, R15–R20)
# ---------------------------------------------------------------------------

MILESTONE_SUB_TRIGGERS = frozenset(
    {"phase_boundary", "decision_recorded", "blocker_resolved"}
)
_FILE_FIELD_RE = re.compile(
    r"\*\*File:\*\*\s*`?([^`\n]+)`?", re.IGNORECASE
)
ORPHAN_EVENTS_DIRNAME = "sw-orphan-events"
ORPHAN_EVENTS_FILENAME = "capture-orphan-events.jsonl"
SYNTHETIC_INTERRUPTION_SUMMARY = (
    "Synthetic interruption inferred on resume (missing trailing interruption event)"
)
_RESUME_EVENT_ID: dict[str, str] = {}


def _default_agent_id() -> str:
    return (
        os.environ.get("SW_CAPTURE_AGENT_ID")
        or os.environ.get("SW_AGENT_ID")
        or "orchestrator"
    )


def resolve_capture_run_id(state: dict[str, Any] | None = None) -> str | None:
    """Resolve active capture run id from env or deliver state."""
    for key in ("SW_CAPTURE_RUN_ID", "SW_RUN_ID"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return raw
    run_dir = os.environ.get("SW_RUN_DIR", "").strip()
    if run_dir:
        return Path(run_dir).name
    if isinstance(state, dict):
        for key in ("runId", "scopedRunId"):
            val = state.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def gap_keywords(root: Path) -> list[str]:
    raw = _capture_section(root).get("gapKeywords", [])
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if isinstance(item, str) and item.strip()]


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def _build_event(
    *,
    run_id: str,
    phase_id: str,
    event_type: str,
    summary: str,
    provenance_kind: str,
    provenance_ref: str,
    agent_id: str | None = None,
    pending_state: dict[str, Any] | None = None,
    timestamp: str | None = None,
    id_phase_id: str | None = None,
    **optional: Any,
) -> dict[str, Any]:
    ts = timestamp or _utc_now()
    phase_for_id = id_phase_id or phase_id
    event: dict[str, Any] = {
        "eventId": compute_event_id(run_id, phase_for_id, event_type, ts),
        "schemaVersion": SCHEMA_VERSION,
        "eventType": event_type,
        "runId": run_id,
        "phaseId": phase_id,
        "agentId": agent_id or _default_agent_id(),
        "timestamp": ts,
        "provenanceKind": provenance_kind,
        "provenanceRef": provenance_ref,
        "summary": summary,
        "pendingState": pending_state,
    }
    resume_id = _RESUME_EVENT_ID.get(run_id)
    if resume_id and "resumedFromEventId" not in optional:
        event["resumedFromEventId"] = resume_id
    for key, value in optional.items():
        if value is not None:
            event[key] = value
    return event


def _safe_record(event: dict[str, Any], *, root: Path, run_id: str) -> str | None:
    if not capture_enabled(root):
        return None
    try:
        record_event(event, run_id=run_id, root=root)
    except (
        CaptureSchemaError,
        CapturePrivacyError,
        CaptureStorageError,
        RunIsolationError,
    ) as exc:
        _append_error(
            root,
            run_id,
            {
                "at": _utc_now(),
                "kind": type(exc).__name__,
                "message": str(exc),
                "eventId": event.get("eventId"),
                "eventType": event.get("eventType"),
            },
        )
        return None
    return str(event.get("eventId") or "") or None


def _extract_scope(task_row: dict[str, Any]) -> list[str]:
    scope: list[str] = []
    for key in ("files", "filePaths", "scope", "paths"):
        raw = task_row.get(key)
        if isinstance(raw, list):
            scope.extend(str(item) for item in raw if str(item).strip())
        elif isinstance(raw, str) and raw.strip():
            scope.append(raw.strip())
    body = task_row.get("body") or task_row.get("text") or task_row.get("description")
    if isinstance(body, str):
        scope.extend(m.group(1).strip() for m in _FILE_FIELD_RE.finditer(body))
    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for item in scope:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _acceptance_summary(task_row: dict[str, Any]) -> str:
    for key in ("acceptance", "acceptanceCriteria", "acceptanceConditions"):
        raw = task_row.get(key)
        if isinstance(raw, list):
            return _truncate("; ".join(str(x) for x in raw), 300)
        if isinstance(raw, str) and raw.strip():
            return _truncate(raw.strip(), 300)
    body = task_row.get("body") or task_row.get("text") or ""
    if isinstance(body, str) and body.strip():
        return _truncate(body.strip().replace("\n", " "), 300)
    return ""


def transition_task_to_in_progress(
    task_row: dict[str, Any],
    run_id: str,
    *,
    root: Path,
    phase_id: str | None = None,
    agent_id: str | None = None,
) -> str | None:
    """Task-row pending → in_progress transition helper (R6). Emits task_start."""
    return _emit_task_start(
        task_row,
        run_id,
        root=root,
        phase_id=phase_id,
        agent_id=agent_id,
    )


def _emit_task_start(
    task_row: dict[str, Any],
    run_id: str,
    *,
    root: Path,
    phase_id: str | None = None,
    agent_id: str | None = None,
) -> str | None:
    if not capture_enabled(root):
        return None
    title = str(
        task_row.get("title")
        or task_row.get("name")
        or task_row.get("id")
        or task_row.get("phaseId")
        or "task"
    )
    pid = str(
        phase_id
        or task_row.get("phaseId")
        or task_row.get("id")
        or "phase-unknown"
    )
    acceptance = _acceptance_summary(task_row)
    scope = _extract_scope(task_row)
    summary = _truncate(
        f"task_start: {title}"
        + (f" | acceptance: {acceptance}" if acceptance else "")
        + (f" | scope: {', '.join(scope)}" if scope else ""),
        500,
    )
    event = _build_event(
        run_id=run_id,
        phase_id=pid,
        event_type="task_start",
        summary=summary,
        provenance_kind="tool_output",
        provenance_ref=f"task-row:{task_row.get('id') or pid}",
        agent_id=agent_id,
        pending_state=None,
    )
    return _safe_record(event, root=root, run_id=run_id)


def _emit_milestone(
    sub_trigger: str,
    phase_id: str,
    run_id: str,
    summary: str,
    *,
    root: Path,
    agent_id: str | None = None,
) -> str | None:
    if not capture_enabled(root):
        return None
    if sub_trigger not in MILESTONE_SUB_TRIGGERS:
        raise ValueError(f"invalid milestone sub_trigger: {sub_trigger!r}")
    # Deterministic timestamp per sub-trigger so the same (phaseId, sub_trigger)
    # composite yields a stable eventId and dedups via R3 (R7).
    stable_ts = {
        "phase_boundary": "1970-01-01T00:00:01Z",
        "decision_recorded": "1970-01-01T00:00:02Z",
        "blocker_resolved": "1970-01-01T00:00:03Z",
    }[sub_trigger]
    event = _build_event(
        run_id=run_id,
        phase_id=phase_id,
        event_type="milestone",
        summary=_truncate(summary, 500),
        provenance_kind="tool_output",
        provenance_ref=f"milestone:{sub_trigger}",
        agent_id=agent_id,
        pending_state=None,
        timestamp=stable_ts,
    )
    return _safe_record(event, root=root, run_id=run_id)


def match_gap_keywords(summary: str, keywords: list[str]) -> str | None:
    """Return the first multi-word/phrase keyword found in summary (case-insensitive)."""
    lowered = summary.lower()
    for keyword in keywords:
        needle = keyword.lower().strip()
        if needle and needle in lowered:
            return keyword
    return None


def emit_discovery(
    summary: str,
    phase_id: str,
    run_id: str,
    provenance_kind: str,
    provenance_ref: str,
    *,
    root: Path,
    agent_id: str | None = None,
    pending_state: dict[str, Any] | None = None,
) -> str:
    """Sole public API for discovery events (R8). Returns eventId.

    When ``summary`` matches ``capture.gapKeywords``, returns a draft gapRef on
    the event and includes ``gapPrompt`` metadata in capture-errors.jsonl for
    operator confirmation — never auto-writes the gap store (R19).
    """
    if len(summary) > 500:
        raise CaptureSchemaError("summary exceeds 500 characters")
    if not capture_enabled(root):
        # Still allocate a deterministic id for callers when disabled.
        ts = _utc_now()
        return compute_event_id(run_id, phase_id, "discovery", ts)

    matched = match_gap_keywords(summary, gap_keywords(root))
    draft_gap_ref = None
    if matched:
        draft_gap_ref = f"gap-draft:{compute_event_id(run_id, phase_id, 'discovery', matched)[:12]}"

    event = _build_event(
        run_id=run_id,
        phase_id=phase_id,
        event_type="discovery",
        summary=summary,
        provenance_kind=provenance_kind,
        provenance_ref=provenance_ref,
        agent_id=agent_id,
        pending_state=pending_state,
        gapRef=draft_gap_ref,
    )
    # Memory observation candidates: tag for manual promotion when provider
    # lacks native observation status (R20). Phase 3 wires the real gate.
    if matched:
        event["memoryObservationRef"] = "sw:observation-pending"

    eid = _safe_record(event, root=root, run_id=run_id)
    if matched:
        _append_error(
            root,
            run_id,
            {
                "at": _utc_now(),
                "kind": "gap_keyword_prompt",
                "message": (
                    "Discovery summary matched gap keyword; confirm gap capture "
                    "with planning_gap_capture.py --event-id "
                    f"{event.get('eventId')} (auto-write prohibited)"
                ),
                "eventId": event.get("eventId"),
                "matchedKeyword": matched,
                "draftGapRef": draft_gap_ref,
                "requiresOperatorConfirmation": True,
            },
        )
    return str(eid or event.get("eventId") or "")


def emit_verification(
    *,
    root: Path,
    run_id: str,
    phase_id: str,
    outcome: str,
    evidence: str,
    provenance_ref: str,
    summary: str | None = None,
    agent_id: str | None = None,
) -> str | None:
    """Emit a verification event (R9)."""
    if outcome not in {"pass", "fail", "partial"}:
        raise ValueError(f"invalid verification outcome: {outcome!r}")
    event = _build_event(
        run_id=run_id,
        phase_id=phase_id,
        event_type="verification",
        summary=_truncate(summary or f"verification:{outcome}", 500),
        provenance_kind="tool_output",
        provenance_ref=provenance_ref,
        agent_id=agent_id,
        pending_state=None,
        verificationOutcome=outcome,
        verificationEvidence=_truncate(evidence, 500),
    )
    return _safe_record(event, root=root, run_id=run_id)


def _pending_state_from_phases(state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(state, dict):
        return None
    phases = state.get("phases") or {}
    if not isinstance(phases, dict):
        return None
    tasks = []
    for pid, meta in phases.items():
        if not isinstance(meta, dict):
            continue
        status = str(meta.get("status") or "")
        if status in {"in-flight", "blocked", "in_progress", "in-progress"}:
            tasks.append({"id": str(pid), "status": status})
    return {"tasks": tasks} if tasks else {"tasks": []}


def _emit_blocker(
    condition: str,
    pending_state: dict[str, Any] | None,
    phase_id: str,
    run_id: str,
    *,
    root: Path,
    agent_id: str | None = None,
) -> str | None:
    event = _build_event(
        run_id=run_id,
        phase_id=phase_id,
        event_type="blocker",
        summary=_truncate(f"blocker: {condition}", 500),
        provenance_kind="tool_output",
        provenance_ref=f"blocker:{phase_id}",
        agent_id=agent_id,
        pending_state=pending_state,
        blockerCondition=condition,
    )
    return _safe_record(event, root=root, run_id=run_id)


def _emit_delegation(
    target: str,
    phase_id: str,
    context_file_list: list[str] | Sequence[str],
    run_id: str,
    *,
    root: Path,
    agent_id: str | None = None,
) -> str | None:
    files = [str(p) for p in context_file_list if str(p).strip()]
    event = _build_event(
        run_id=run_id,
        phase_id=phase_id,
        event_type="delegation",
        summary=_truncate(
            f"delegation: {target}" + (f" | files: {', '.join(files)}" if files else ""),
            500,
        ),
        provenance_kind="tool_output",
        provenance_ref=f"delegation:{phase_id}",
        agent_id=agent_id,
        pending_state=None,
        delegationTarget=target,
    )
    return _safe_record(event, root=root, run_id=run_id)


def _emit_interruption(
    pending_state: dict[str, Any] | None,
    run_id: str,
    *,
    root: Path,
    phase_id: str = "session",
    agent_id: str | None = None,
    provenance_kind: str = "tool_output",
    summary: str | None = None,
) -> str | None:
    event = _build_event(
        run_id=run_id,
        phase_id=phase_id,
        event_type="interruption",
        summary=_truncate(summary or "Session interruption / pause", 500),
        provenance_kind=provenance_kind,
        provenance_ref=f"interruption:{phase_id}",
        agent_id=agent_id,
        pending_state=pending_state,
    )
    return _safe_record(event, root=root, run_id=run_id)


def ensure_interruption_on_resume(
    run_id: str,
    *,
    root: Path,
    state: dict[str, Any] | None = None,
    phase_id: str = "session",
) -> str | None:
    """On resume, emit synthetic interruption when last event is not interruption (R12/R17)."""
    if not capture_enabled(root):
        return None
    events = read_events(run_id, root=root)
    last = events[-1] if events else None
    if last and last.get("eventType") == "interruption":
        eid = str(last.get("eventId") or "")
        if eid:
            _RESUME_EVENT_ID[run_id] = eid
        return eid
    eid = _emit_interruption(
        _pending_state_from_phases(state),
        run_id,
        root=root,
        phase_id=phase_id,
        provenance_kind="inferred",
        summary=SYNTHETIC_INTERRUPTION_SUMMARY,
    )
    if eid:
        _RESUME_EVENT_ID[run_id] = eid
    return eid


def orphan_events_path(root: Path, agent_id: str | None = None) -> Path:
    aid = agent_id or _default_agent_id()
    return root / ".cursor" / ORPHAN_EVENTS_DIRNAME / f"{aid}.jsonl"


def repo_orphan_events_path(root: Path) -> Path:
    return root / ".cursor" / ORPHAN_EVENTS_FILENAME


def write_sub_agent_event(
    event: dict[str, Any],
    *,
    root: Path,
    run_id: str | None = None,
    dispatch_id: str | None = None,
    agent_id: str | None = None,
) -> Path:
    """Append one event to a sub-agent sidecar (R15). Falls back to orphan paths."""
    root = root.resolve()
    env_run = os.environ.get("SW_CAPTURE_RUN_ID", "").strip()
    env_dispatch = os.environ.get("SW_CAPTURE_DISPATCH_ID", "").strip()
    rid = run_id or env_run
    did = dispatch_id or env_dispatch
    line = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"

    def _append(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.write(line)
                handle.flush()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return path

    if rid and did:
        target = sub_agent_events_path(root, rid, did)
        try:
            return _append(target)
        except OSError as exc:
            fallback = orphan_events_path(root, agent_id)
            _append_error(
                root,
                rid,
                {
                    "at": _utc_now(),
                    "kind": "sidecar_permission_fallback",
                    "message": f"sidecar write failed ({exc}); falling back to orphan path",
                    "dispatchId": did,
                    "orphanPath": str(fallback),
                },
            )
            return _append(fallback)

    # Missing env vars — must not fail silently (R15).
    orphan = repo_orphan_events_path(root)
    orphan.parent.mkdir(parents=True, exist_ok=True)
    warning = {
        "at": _utc_now(),
        "kind": "orphan_capture_missing_env",
        "message": (
            "SW_CAPTURE_RUN_ID / SW_CAPTURE_DISPATCH_ID missing; "
            f"wrote to {orphan}"
        ),
        "agentId": agent_id or _default_agent_id(),
    }
    # Best-effort warning alongside the orphan event file.
    warn_path = orphan.parent / "capture-orphan-warnings.jsonl"
    with warn_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(warning, ensure_ascii=False, sort_keys=True) + "\n")
    return _append(orphan)


def capture_dispatch_env(run_id: str, dispatch_id: str) -> dict[str, str]:
    """Env vars the orchestrator must pass into each Task (R15)."""
    return {
        "SW_CAPTURE_RUN_ID": run_id,
        "SW_CAPTURE_DISPATCH_ID": dispatch_id,
    }




__all__ = [
    "CAPTURE_ERRORS_FILENAME",
    "CaptureStorageError",
    "EVENTS_FILENAME",
    "MILESTONE_SUB_TRIGGERS",
    "RunIsolationError",
    "SYNTHETIC_INTERRUPTION_SUMMARY",
    "capture_dispatch_env",
    "capture_enabled",
    "capture_errors_path",
    "consolidate_sub_agent_events",
    "emit_discovery",
    "emit_verification",
    "ensure_capture_files",
    "ensure_interruption_on_resume",
    "gap_keywords",
    "match_gap_keywords",
    "max_file_size_bytes",
    "orphan_events_path",
    "read_events",
    "record_event",
    "repo_orphan_events_path",
    "resolve_capture_run_id",
    "sub_agent_events_path",
    "transition_task_to_in_progress",
    "write_sub_agent_event",
    "_emit_blocker",
    "_emit_delegation",
    "_emit_interruption",
    "_emit_milestone",
    "_emit_task_start",
]
