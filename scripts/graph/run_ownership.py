#!/usr/bin/env python3
"""Durable graph run ownership independent of chat session (PRD 271 R18/R1b).

Deliver runId CAS leases (PRD 279 R9–R12) reuse ``.cursor/sw-deliver-run-locks/`` via
``DeliverRunOwnershipProvider`` — distinct from graph session ``RunOwnershipStore``.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


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


@dataclass(frozen=True)
class RunOwnershipLeaseRecord:
    """CAS lease record for exclusive deliver runId ownership (PRD 279 R9/R12)."""

    run_id: str
    owner: str
    generation: int
    expiry: str
    fencing_token: str
    lock_path: str = ""
    live: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "owner": self.owner,
            "generation": self.generation,
            "expiry": self.expiry,
            "fencingToken": self.fencing_token,
            "lockPath": self.lock_path,
            "live": self.live,
        }

    @classmethod
    def from_lock_meta(
        cls,
        meta: Mapping[str, Any],
        *,
        lock_path: Path | None = None,
        live: bool = False,
    ) -> RunOwnershipLeaseRecord:
        from wave_lock import RUN_LEASE_STALE_SECONDS

        run_id = str(meta.get("runId") or "")
        generation = int(meta.get("generation") or 0)
        owner = str(meta.get("owner") or "")
        hb = meta.get("heartbeatAt") or meta.get("acquiredAt")
        expiry = str(hb or "")
        if isinstance(hb, str):
            try:
                dt = datetime.strptime(hb, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                expiry = (dt + timedelta(seconds=RUN_LEASE_STALE_SECONDS)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
            except ValueError:
                pass
        return cls(
            run_id=run_id,
            owner=owner,
            generation=generation,
            expiry=expiry,
            fencing_token=f"{run_id}:{generation}",
            lock_path=str(lock_path or ""),
            live=live,
        )


class RunOwnershipProvider(Protocol):
    """CAS/fencing lease provider for exclusive deliver runId ownership (PRD 279 R9)."""

    def acquire(
        self,
        run_id: str,
        *,
        cross_host_ack: bool = False,
        source_task_list: str | None = None,
    ) -> dict[str, Any]: ...

    def heartbeat(self, run_id: str, generation: int) -> dict[str, Any]: ...

    def assert_write(self, run_id: str, generation: int) -> dict[str, Any]: ...

    def release(self, run_id: str, generation: int | None = None) -> dict[str, Any]: ...

    def status(self, run_id: str) -> dict[str, Any]: ...


class DeliverRunOwnershipProvider:
    """RunOwnershipProvider backed by ``wave_lock`` deliver-run-locks taxonomy (R12)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def acquire(
        self,
        run_id: str,
        *,
        cross_host_ack: bool = False,
        source_task_list: str | None = None,
    ) -> dict[str, Any]:
        from wave_lock import acquire_run_lease

        out = acquire_run_lease(
            self._root,
            run_id,
            cross_host_ack=cross_host_ack,
            source_task_list=source_task_list,
        )
        if out.get("verdict") == "pass":
            lease = RunOwnershipLeaseRecord(
                run_id=run_id,
                owner=f"{os.environ.get('HOSTNAME', 'local')}:{os.getpid()}",
                generation=int(out.get("generation") or 1),
                expiry="",
                fencing_token=f"{run_id}:{int(out.get('generation') or 1)}",
                lock_path=str(out.get("lockPath") or ""),
            )
            out["lease"] = lease.to_dict()
        return out

    def heartbeat(self, run_id: str, generation: int) -> dict[str, Any]:
        from wave_lock import heartbeat_run_lease

        return heartbeat_run_lease(self._root, run_id, generation)

    def assert_write(self, run_id: str, generation: int) -> dict[str, Any]:
        from wave_lock import assert_run_lease_write

        return assert_run_lease_write(self._root, run_id, generation)

    def release(self, run_id: str, generation: int | None = None) -> dict[str, Any]:
        from wave_lock import release_run_lease

        return release_run_lease(self._root, run_id, generation)

    def status(self, run_id: str) -> dict[str, Any]:
        from wave_lock import run_lease_owner_live, status_run_lease

        out = status_run_lease(self._root, run_id)
        meta = out.get("meta") if isinstance(out.get("meta"), dict) else None
        if meta:
            out["lease"] = RunOwnershipLeaseRecord.from_lock_meta(
                meta,
                lock_path=Path(str(out.get("lockPath") or "")),
                live=bool(run_lease_owner_live(meta)),
            ).to_dict()
        return out


def default_deliver_run_ownership_provider(root: Path) -> DeliverRunOwnershipProvider:
    return DeliverRunOwnershipProvider(root)
