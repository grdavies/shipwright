"""Implementation-capture event journal (PRD 350 R13–R16, R25–R26).

Sole write/read API for ``.cursor/sw-deliver-runs/{runId}/events.jsonl``.
When ``capture.enabled`` is false (Phase 1 default), ``record_event`` is a no-op.

Agents outside this module must not open ``events.jsonl`` directly (R25).
"""
from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from _sw.capture_schema_lib import (
    CapturePrivacyError,
    CaptureSchemaError,
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
    try:
        current_size = path.stat().st_size if path.is_file() else 0
    except OSError:
        current_size = 0
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
    if current_size + len(payload.encode("utf-8")) > limit:
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

    with path.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
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


__all__ = [
    "CAPTURE_ERRORS_FILENAME",
    "CaptureStorageError",
    "EVENTS_FILENAME",
    "RunIsolationError",
    "capture_enabled",
    "capture_errors_path",
    "consolidate_sub_agent_events",
    "ensure_capture_files",
    "max_file_size_bytes",
    "read_events",
    "record_event",
    "sub_agent_events_path",
]
