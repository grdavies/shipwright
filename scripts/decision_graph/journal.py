"""Decision run receipt journal under .cursor/sw-decision-runs/<runId>/ (PRD 280 R19)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

EVENT_TYPES = frozenset({"resolution", "human-action", "prototype-teardown"})
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_EVENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")


class DecisionJournalError(ValueError):
    """Raised when journal operations fail validation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def decision_runs_root(repo_root: Path) -> Path:
    return repo_root / ".cursor" / "sw-decision-runs"


def sanitize_run_id(run_id: str) -> str:
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise DecisionJournalError(f"invalid decision run id: {run_id!r}")
    return run_id


def sanitize_event_id(event_id: str) -> str:
    if not _SAFE_EVENT_ID.fullmatch(event_id):
        raise DecisionJournalError(f"invalid event id: {event_id!r}")
    return event_id


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_json(record) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


class DecisionRunJournal:
    """Append-only, idempotent journal for resolution and human-action events."""

    def __init__(self, repo_root: Path, run_id: str) -> None:
        self.run_id = sanitize_run_id(run_id)
        self.repo_root = repo_root
        self.run_dir = decision_runs_root(repo_root) / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._events_dir = self.run_dir / "events"
        self._events_dir.mkdir(parents=True, exist_ok=True)
        self._jsonl_path = self.run_dir / "events.jsonl"

    def _event_path(self, event_id: str) -> Path:
        digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:16]
        return self._events_dir / f"{digest}.json"

    def append_event(self, event_id: str, event: Mapping[str, Any]) -> dict[str, Any]:
        """Append a journal event idempotently; conflicting replays fail closed."""
        safe_id = sanitize_event_id(event_id)
        event_type = str(event.get("eventType") or "")
        if event_type not in EVENT_TYPES:
            raise DecisionJournalError(f"invalid event type: {event_type!r}")

        node_id = str(event.get("nodeId") or "")
        if not node_id:
            raise DecisionJournalError("event requires nodeId")

        payload = {
            "apiVersion": "decision-run-journal/v1",
            "runId": self.run_id,
            "eventId": safe_id,
            "eventType": event_type,
            "nodeId": node_id,
            "recordedAt": str(event.get("recordedAt") or utc_now()),
        }
        for key in ("outcome", "rationale", "actor", "receipt", "resolution"):
            if key in event and event[key] is not None:
                payload[key] = event[key]

        path = self._event_path(safe_id)
        if path.is_file():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != payload:
                raise DecisionJournalError(f"event id {safe_id!r} already records a different payload")
            return existing

        _atomic_write(path, payload)
        _append_jsonl(self._jsonl_path, payload)
        return payload

    def append_resolution(
        self,
        event_id: str,
        *,
        node_id: str,
        outcome: str,
        rationale: str = "",
    ) -> dict[str, Any]:
        return self.append_event(
            event_id,
            {
                "eventType": "resolution",
                "nodeId": node_id,
                "outcome": outcome,
                "rationale": rationale,
                "resolution": {"outcome": outcome, "rationale": rationale},
            },
        )

    def append_human_action(
        self,
        event_id: str,
        *,
        node_id: str,
        receipt: Mapping[str, Any],
        actor: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "eventType": "human-action",
            "nodeId": node_id,
            "receipt": dict(receipt),
        }
        if actor:
            body["actor"] = actor
        return self.append_event(event_id, body)

    def append_prototype_teardown(
        self,
        event_id: str,
        *,
        node_id: str,
        receipt: Mapping[str, Any],
        actor: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "eventType": "prototype-teardown",
            "nodeId": node_id,
            "receipt": dict(receipt),
        }
        if actor:
            body["actor"] = actor
        return self.append_event(event_id, body)

    def read_event(self, event_id: str) -> dict[str, Any] | None:
        path = self._event_path(sanitize_event_id(event_id))
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def list_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for path in sorted(self._events_dir.glob("*.json")):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise DecisionJournalError(f"corrupt journal event: {path.name}") from exc
            if isinstance(document, dict):
                events.append(document)
        events.sort(key=lambda item: (str(item.get("recordedAt") or ""), str(item.get("eventId") or "")))
        return events

    def replay_events(self) -> list[dict[str, Any]]:
        """Return events in append order from the jsonl ledger."""
        if not self._jsonl_path.is_file():
            return self.list_events()
        events: list[dict[str, Any]] = []
        for line in self._jsonl_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                document = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DecisionJournalError("corrupt events.jsonl ledger") from exc
            if isinstance(document, dict):
                events.append(document)
        return events


def receipts_by_node_from_journal(journal: DecisionRunJournal) -> dict[str, dict[str, Any]]:
    """Build a node-id → receipt map from human-action journal events."""
    receipts: dict[str, dict[str, Any]] = {}
    for event in journal.list_events():
        if str(event.get("eventType") or "") != "human-action":
            continue
        node_id = str(event.get("nodeId") or "")
        receipt = event.get("receipt")
        if node_id and isinstance(receipt, Mapping):
            receipts[node_id] = dict(receipt)
    return receipts


def load_receipts_for_unit(repo_root: Path, unit_id: str) -> dict[str, dict[str, Any]]:
    """Scan decision run journals for human-action receipts (best-effort)."""
    root = decision_runs_root(repo_root)
    if not root.is_dir():
        return {}
    merged: dict[str, dict[str, Any]] = {}
    for run_dir in sorted(root.iterdir()):
        if not run_dir.is_dir():
            continue
        journal = DecisionRunJournal(repo_root, run_dir.name)
        for node_id, receipt in receipts_by_node_from_journal(journal).items():
            merged[node_id] = receipt
    return merged


__all__ = [
    "DecisionJournalError",
    "DecisionRunJournal",
    "decision_runs_root",
    "load_receipts_for_unit",
    "receipts_by_node_from_journal",
    "sanitize_event_id",
    "sanitize_run_id",
]
