#!/usr/bin/env python3
"""Durable graph run ownership independent of chat session (PRD 271 R18/R1b)."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


class RunOwnershipError(RuntimeError):
    """Raised when run ownership state is invalid or unauthorized."""


@dataclass
class RunOwnershipRecord:
    """Persisted ownership for one graph execution run."""

    run_id: str
    graph_hash: str = ""
    session_id: str | None = None
    detached: bool = False
    cancel_requested: bool = False
    created_at: float = field(default_factory=time.time)
    detached_at: float | None = None
    last_seen_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "graphHash": self.graph_hash,
            "sessionId": self.session_id,
            "detached": self.detached,
            "cancelRequested": self.cancel_requested,
            "createdAt": self.created_at,
            "detachedAt": self.detached_at,
            "lastSeenAt": self.last_seen_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> RunOwnershipRecord:
        return RunOwnershipRecord(
            run_id=str(payload.get("runId") or ""),
            graph_hash=str(payload.get("graphHash") or ""),
            session_id=(
                str(payload["sessionId"])
                if payload.get("sessionId") is not None
                else None
            ),
            detached=bool(payload.get("detached")),
            cancel_requested=bool(payload.get("cancelRequested")),
            created_at=float(payload.get("createdAt") or time.time()),
            detached_at=(
                float(payload["detachedAt"])
                if payload.get("detachedAt") is not None
                else None
            ),
            last_seen_at=float(payload.get("lastSeenAt") or time.time()),
        )


def ownership_path(journal_root: Path, run_id: str) -> Path:
    """Ownership sidecar path under a run-scoped journal root."""
    return journal_root / run_id / "ownership.json"


class RunOwnershipStore:
    """Attach/detach/re-enter durable graph runs without session-bound cancellation."""

    def __init__(self, journal_root: Path) -> None:
        self._root = journal_root

    def path_for(self, run_id: str) -> Path:
        return ownership_path(self._root, run_id)

    def load(self, run_id: str) -> RunOwnershipRecord | None:
        path = self.path_for(run_id)
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RunOwnershipRecord.from_dict(payload)

    def save(self, record: RunOwnershipRecord) -> None:
        if not record.run_id:
            raise RunOwnershipError("run_id is required")
        path = self.path_for(record.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def begin(
        self,
        run_id: str,
        *,
        graph_hash: str,
        session_id: str | None = None,
    ) -> RunOwnershipRecord:
        record = RunOwnershipRecord(
            run_id=run_id,
            graph_hash=graph_hash,
            session_id=session_id,
            detached=False,
        )
        self.save(record)
        return record

    def detach(self, run_id: str) -> RunOwnershipRecord:
        """Session detach — run continues; session end does not cancel."""
        record = self._require(run_id)
        record.detached = True
        record.detached_at = time.time()
        record.session_id = None
        record.last_seen_at = time.time()
        self.save(record)
        return record

    def reenter(
        self,
        run_id: str,
        *,
        session_id: str | None = None,
    ) -> RunOwnershipRecord:
        """Operator re-entry via /sw-status — does not restart execution."""
        record = self._require(run_id)
        record.detached = False
        record.session_id = session_id
        record.last_seen_at = time.time()
        self.save(record)
        return record

    def request_cancel(self, run_id: str) -> RunOwnershipRecord:
        """Explicit operator cancel — distinct from session detach."""
        record = self._require(run_id)
        record.cancel_requested = True
        record.last_seen_at = time.time()
        self.save(record)
        return record

    def touch(self, run_id: str) -> RunOwnershipRecord:
        record = self._require(run_id)
        record.last_seen_at = time.time()
        self.save(record)
        return record

    def _require(self, run_id: str) -> RunOwnershipRecord:
        record = self.load(run_id)
        if record is None:
            raise RunOwnershipError(f"unknown run ownership: {run_id}")
        return record
