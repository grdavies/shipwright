#!/usr/bin/env python3
"""Crash-safe, idempotent per-node execution receipt journal (PRD 269 R6/R7/R13/R16)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from graph.artifact_registry import receipt_is_reusable

_SAFE_NODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_CACHE_KEY = re.compile(r"^[a-f0-9]{64}$")
_REQUIRED_FIELDS = {
    "model",
    "attempts",
    "tokens",
    "durationMs",
    "inputHashes",
    "outputHashes",
    "verdict",
    "coverage",
}

# Default retention / size ceiling for the gitignored run-scoped store (R13).
DEFAULT_RETENTION_SECONDS = 14 * 24 * 60 * 60
DEFAULT_SIZE_CEILING_BYTES = 64 * 1024 * 1024
DEFAULT_MAC_KEY = b"shipwright-graph-receipt-mac-v1"


class ReceiptJournalError(RuntimeError):
    """Base class for receipt journal failures."""


class ReceiptConflictError(ReceiptJournalError):
    """Raised on conflicting idempotent writes or corrupt persisted data."""


class ReceiptStoreFull(ReceiptJournalError):
    """Raised when a write would exceed the configured size ceiling."""


def _canonical(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _receipt_mac(source: dict[str, Any], *, mac_key: bytes) -> str:
    digest_source = {
        key: value
        for key, value in source.items()
        if key not in {"receiptHash", "receiptMac"}
    }
    return hmac.new(mac_key, _canonical(digest_source), hashlib.sha256).hexdigest()


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_canonical(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(_REQUIRED_FIELDS - set(payload))
    if missing:
        raise ValueError("receipt is missing fields: " + ", ".join(missing))
    if payload["attempts"] < 1:
        raise ValueError("receipt attempts must be positive")
    if payload["durationMs"] < 0:
        raise ValueError("receipt durationMs cannot be negative")
    return json.loads(json.dumps(payload))


def default_store_root(repo_root: str | Path) -> Path:
    """Gitignored, user-writable graph journal root (R13)."""
    return Path(repo_root) / ".cursor" / "sw-graph-runs"


def sanitize_run_id(run_id: str) -> str:
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError(f"invalid run id: {run_id!r}")
    return run_id


class ExecutionReceiptJournal:
    """One-file-per-idempotency-key journal with durable partial states.

    Prefer :meth:`for_run` so receipts, intents, and pool snapshots are indexed
    under a single ``runId`` directory rather than scanning all history (R13).
    Content-addressed cache hits and HMAC integrity are phase-4 (R6/R7/R15).
    """

    def __init__(
        self,
        root: str | Path,
        *,
        run_id: str | None = None,
        size_ceiling_bytes: int = DEFAULT_SIZE_CEILING_BYTES,
        mac_key: bytes | None = None,
    ) -> None:
        self.root = Path(root)
        self.run_id = run_id
        self.size_ceiling_bytes = int(size_ceiling_bytes)
        self.partial_root = self.root / "partial"
        self.complete_root = self.root / "complete"
        self.quarantine_root = self.root / "quarantine"
        self.cache_index_root = self.root / "cache-index"
        self._mac_key = mac_key if mac_key is not None else DEFAULT_MAC_KEY
        for directory in (
            self.partial_root,
            self.complete_root,
            self.quarantine_root,
            self.cache_index_root,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        # Restrict to owning user when possible (R13 writable-only-by-owner).
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass

    @classmethod
    def for_run(
        cls,
        store_root: str | Path,
        run_id: str,
        *,
        size_ceiling_bytes: int = DEFAULT_SIZE_CEILING_BYTES,
        mac_key: bytes | None = None,
    ) -> ExecutionReceiptJournal:
        """Open the per-run journal at ``<store>/<runId>/receipts``."""
        safe = sanitize_run_id(run_id)
        run_dir = Path(store_root) / safe
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(run_dir, 0o700)
        except OSError:
            pass
        return cls(
            run_dir / "receipts",
            run_id=safe,
            size_ceiling_bytes=size_ceiling_bytes,
            mac_key=mac_key,
        )

    @property
    def run_dir(self) -> Path:
        """Run-scoped directory holding receipts sibling artifacts."""
        if self.root.name == "receipts":
            return self.root.parent
        return self.root

    def pool_snapshot_path(self) -> Path:
        return self.run_dir / "pool-snapshot.json"

    def telemetry_path(self) -> Path:
        return self.run_dir / "telemetry.json"

    @staticmethod
    def _key(node_id: str, idempotency_key: str) -> str:
        if not _SAFE_NODE_ID.fullmatch(node_id):
            raise ValueError(f"invalid node id: {node_id!r}")
        digest = hashlib.sha256(
            f"{node_id}\0{idempotency_key}".encode("utf-8")
        ).hexdigest()
        return f"{node_id}-{digest}"

    def partial_path(self, node_id: str, idempotency_key: str) -> Path:
        return self.partial_root / f"{self._key(node_id, idempotency_key)}.json"

    def complete_path(self, node_id: str, idempotency_key: str) -> Path:
        return self.complete_root / f"{self._key(node_id, idempotency_key)}.json"

    def cache_index_path(self, cache_key: str) -> Path:
        if not _SAFE_CACHE_KEY.fullmatch(cache_key):
            raise ValueError(f"invalid cache key: {cache_key!r}")
        return self.cache_index_root / f"{cache_key}.json"

    def _size_bytes(self) -> int:
        total = 0
        for directory in (
            self.partial_root,
            self.complete_root,
            self.quarantine_root,
            self.cache_index_root,
            self.run_dir,
        ):
            if not directory.is_dir():
                continue
            for path in directory.rglob("*"):
                if path.is_file():
                    try:
                        total += path.stat().st_size
                    except OSError:
                        continue
        return total

    def _enforce_ceiling(self, upcoming_bytes: int = 0) -> None:
        if self.size_ceiling_bytes <= 0:
            return
        if self._size_bytes() + upcoming_bytes > self.size_ceiling_bytes:
            raise ReceiptStoreFull(
                f"receipt store exceeds size ceiling "
                f"({self.size_ceiling_bytes} bytes)"
            )

    def _quarantine(self, path: Path, exc: BaseException) -> None:
        quarantine = self.quarantine_root / (
            f"{path.stem}-{os.getpid()}.corrupt.json"
        )
        try:
            os.replace(path, quarantine)
        except OSError:
            pass
        raise ReceiptConflictError(
            f"corrupt receipt quarantined from {path}: {exc}"
        ) from exc

    def _load(self, path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._quarantine(path, exc)
            raise  # pragma: no cover — _quarantine always raises
        if not isinstance(value, dict):
            self._quarantine(path, ReceiptConflictError("receipt is not an object"))
            raise  # pragma: no cover
        return value

    def _safe_load(self, path: Path) -> dict[str, Any] | None:
        """Load or quarantine; never fail unrelated list/query callers (R13)."""
        try:
            return self._load(path)
        except ReceiptConflictError:
            return None

    @staticmethod
    def _same_request(
        stored: dict[str, Any],
        *,
        node_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> bool:
        comparable = {
            key: value
            for key, value in stored.items()
            if key not in {"state", "receiptHash", "receiptMac"}
        }
        expected = {
            "nodeId": node_id,
            "idempotencyKey": idempotency_key,
            **payload,
        }
        return comparable == expected

    def begin(
        self,
        node_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist a complete resumable intent before node execution starts."""
        validated = _validate_payload(payload)
        final_path = self.complete_path(node_id, idempotency_key)
        if final_path.is_file():
            final = self._load(final_path)
            if self._same_request(
                final,
                node_id=node_id,
                idempotency_key=idempotency_key,
                payload=validated,
            ):
                return final
            raise ReceiptConflictError("idempotency key already has another receipt")

        partial_path = self.partial_path(node_id, idempotency_key)
        if partial_path.is_file():
            partial = self._load(partial_path)
            if self._same_request(
                partial,
                node_id=node_id,
                idempotency_key=idempotency_key,
                payload=validated,
            ):
                return partial
            # Allow upgrade from a pre-dispatch intent to a richer payload.
            if partial.get("coverage", {}).get("intent") is True:
                pass
            else:
                raise ReceiptConflictError(
                    "idempotency key already has another partial"
                )

        partial = {
            "state": "partial",
            "nodeId": node_id,
            "idempotencyKey": idempotency_key,
            **validated,
        }
        encoded = _canonical(partial)
        self._enforce_ceiling(len(encoded))
        _atomic_write(partial_path, partial)
        return partial

    def resume_partial(
        self, node_id: str, idempotency_key: str
    ) -> dict[str, Any]:
        path = self.partial_path(node_id, idempotency_key)
        if not path.is_file():
            raise KeyError((node_id, idempotency_key))
        partial = self._load(path)
        if (
            partial.get("state") != "partial"
            or partial.get("nodeId") != node_id
            or partial.get("idempotencyKey") != idempotency_key
        ):
            raise ReceiptConflictError("partial receipt identity is invalid")
        return partial

    def _stamp_integrity(self, completed: dict[str, Any]) -> dict[str, Any]:
        digest_source = {
            key: value
            for key, value in completed.items()
            if key not in {"receiptHash", "receiptMac"}
        }
        completed["receiptHash"] = hashlib.sha256(
            _canonical(digest_source)
        ).hexdigest()
        completed["receiptMac"] = _receipt_mac(completed, mac_key=self._mac_key)
        return completed

    def complete(
        self,
        node_id: str,
        idempotency_key: str,
        *,
        verdict: str | None = None,
        cache_key: str | None = None,
        cache_hit: bool | None = None,
    ) -> dict[str, Any]:
        """Atomically publish a final receipt and retire its partial intent."""
        final_path = self.complete_path(node_id, idempotency_key)
        if final_path.is_file():
            return self._verify_complete(self._load(final_path))
        partial_path = self.partial_path(node_id, idempotency_key)
        partial = self.resume_partial(node_id, idempotency_key)
        completed = {**partial, "state": "complete"}
        if verdict is not None:
            completed["verdict"] = verdict
        if cache_hit is not None:
            completed["cacheHit"] = bool(cache_hit)
        if cache_key is not None:
            completed["cacheKey"] = cache_key
        self._stamp_integrity(completed)
        encoded = _canonical(completed)
        self._enforce_ceiling(len(encoded))
        _atomic_write(final_path, completed)
        partial_path.unlink(missing_ok=True)
        if (
            cache_key
            and completed.get("verdict") == "pass"
            and completed.get("cacheHit") is not True
            and receipt_is_reusable(completed)
        ):
            self._index_cache_hit(cache_key, node_id, idempotency_key)
        return completed

    def finish(
        self,
        node_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
        *,
        cache_key: str | None = None,
        cache_hit: bool | None = None,
    ) -> dict[str, Any]:
        """Publish a final receipt, replacing any pre-dispatch intent."""
        validated = _validate_payload(payload)
        final_path = self.complete_path(node_id, idempotency_key)
        if final_path.is_file():
            existing = self._verify_complete(self._load(final_path))
            if self._same_request(
                existing,
                node_id=node_id,
                idempotency_key=idempotency_key,
                payload=validated,
            ):
                return existing
            raise ReceiptConflictError("idempotency key already has another receipt")
        completed = {
            "state": "complete",
            "nodeId": node_id,
            "idempotencyKey": idempotency_key,
            **validated,
        }
        if cache_hit is not None:
            completed["cacheHit"] = bool(cache_hit)
        if cache_key is not None:
            completed["cacheKey"] = cache_key
        self._stamp_integrity(completed)
        encoded = _canonical(completed)
        self._enforce_ceiling(len(encoded))
        _atomic_write(final_path, completed)
        self.partial_path(node_id, idempotency_key).unlink(missing_ok=True)
        if (
            cache_key
            and completed.get("verdict") == "pass"
            and completed.get("cacheHit") is not True
            and receipt_is_reusable(completed)
        ):
            self._index_cache_hit(cache_key, node_id, idempotency_key)
        return completed

    def _index_cache_hit(
        self, cache_key: str, node_id: str, idempotency_key: str
    ) -> None:
        path = self.cache_index_path(cache_key)
        payload = {
            "cacheKey": cache_key,
            "nodeId": node_id,
            "idempotencyKey": idempotency_key,
        }
        encoded = _canonical(payload)
        self._enforce_ceiling(len(encoded))
        _atomic_write(path, payload)

    def lookup_reusable_by_cache_key(self, cache_key: str) -> dict[str, Any] | None:
        """Return a verified reusable receipt for a stable cache key, or None."""
        path = self.cache_index_path(cache_key)
        if not path.is_file():
            return None
        try:
            index = self._load(path)
        except ReceiptConflictError:
            return None
        node_id = str(index.get("nodeId") or "")
        idempotency_key = str(index.get("idempotencyKey") or "")
        if not node_id or not idempotency_key:
            return None
        try:
            receipt = self.get(node_id, idempotency_key)
        except (KeyError, ReceiptConflictError):
            return None
        if not receipt_is_reusable(receipt):
            return None
        return receipt

    def record_cache_hit(
        self,
        node_id: str,
        idempotency_key: str,
        *,
        source: dict[str, Any],
        cache_key: str,
    ) -> dict[str, Any]:
        """Write a run-scoped receipt that restores artifacts from a cache hit (R6)."""
        payload = {
            key: value
            for key, value in source.items()
            if key
            not in {
                "state",
                "nodeId",
                "idempotencyKey",
                "receiptHash",
                "receiptMac",
                "cacheHit",
                "cacheKey",
            }
        }
        payload["cacheHit"] = True
        payload["cacheKey"] = cache_key
        begun = self.begin(node_id, idempotency_key, payload)
        if begun.get("state") == "complete":
            return begun
        return self.complete(
            node_id,
            idempotency_key,
            cache_key=cache_key,
            cache_hit=True,
        )

    def record(
        self,
        node_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
        *,
        cache_key: str | None = None,
    ) -> dict[str, Any]:
        """Idempotently persist a complete receipt."""
        begun = self.begin(node_id, idempotency_key, payload)
        if begun.get("state") == "complete":
            return begun
        # If begin upgraded an intent, finish with the caller payload.
        if begun.get("coverage", {}).get("intent") is True:
            return self.finish(
                node_id, idempotency_key, payload, cache_key=cache_key
            )
        return self.complete(node_id, idempotency_key, cache_key=cache_key)

    def _verify_complete(self, receipt: dict[str, Any]) -> dict[str, Any]:
        digest = receipt.get("receiptHash")
        source = {
            key: value
            for key, value in receipt.items()
            if key not in {"receiptHash", "receiptMac"}
        }
        if digest != hashlib.sha256(_canonical(source)).hexdigest():
            raise ReceiptConflictError("complete receipt hash mismatch")
        expected_mac = receipt.get("receiptMac")
        actual_mac = _receipt_mac(receipt, mac_key=self._mac_key)
        if expected_mac is not None and expected_mac != actual_mac:
            raise ReceiptConflictError("complete receipt MAC mismatch")
        # Legacy receipts without receiptMac still verify via hash; new writes always
        # stamp MAC. Mutating either hash or MAC fails closed for cache reuse.
        return receipt

    def get(self, node_id: str, idempotency_key: str) -> dict[str, Any]:
        path = self.complete_path(node_id, idempotency_key)
        if not path.is_file():
            raise KeyError((node_id, idempotency_key))
        return self._verify_complete(self._load(path))

    def list_receipts(self) -> list[dict[str, Any]]:
        receipts: list[dict[str, Any]] = []
        for path in sorted(self.complete_root.glob("*.json")):
            receipt = self._safe_load(path)
            if receipt is not None:
                receipts.append(receipt)
        return receipts

    def list_inflight_intents(self) -> list[dict[str, Any]]:
        intents: list[dict[str, Any]] = []
        for path in sorted(self.partial_root.glob("*.json")):
            intent = self._safe_load(path)
            if intent is not None:
                intents.append(intent)
        return intents

    def list_run_receipts(self, run_id: str) -> list[dict[str, Any]]:
        """Return immutable receipts belonging to one scheduler run."""
        prefix = f"{run_id}:"
        return [
            receipt
            for receipt in self.list_receipts()
            if str(receipt.get("idempotencyKey", "")).startswith(prefix)
        ]

    def write_pool_snapshot(
        self,
        snapshot: dict[str, Any],
        *,
        parked: list[str] | tuple[str, ...] | None = None,
        queue: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """Persist a pool/park snapshot keyed by this journal's run (R13)."""
        payload = {
            "runId": self.run_id,
            "pools": snapshot,
            "parked": list(parked or ()),
            "queue": list(queue or ()),
            "updatedAt": time.time(),
        }
        encoded = _canonical(payload)
        self._enforce_ceiling(len(encoded))
        _atomic_write(self.pool_snapshot_path(), payload)
        return payload

    def read_pool_snapshot(self) -> dict[str, Any] | None:
        path = self.pool_snapshot_path()
        if not path.is_file():
            return None
        return self._safe_load(path)

    def write_telemetry(self, telemetry: dict[str, Any]) -> dict[str, Any]:
        payload = {"runId": self.run_id, **telemetry}
        encoded = _canonical(payload)
        self._enforce_ceiling(len(encoded))
        _atomic_write(self.telemetry_path(), payload)
        return payload

    def read_telemetry(self) -> dict[str, Any] | None:
        path = self.telemetry_path()
        if not path.is_file():
            return None
        return self._safe_load(path)

    def gc(
        self,
        *,
        max_age_seconds: int = DEFAULT_RETENTION_SECONDS,
        max_bytes: int | None = None,
        now: float | None = None,
    ) -> dict[str, int]:
        """Retain recent receipts; delete oldest complete entries past policy (R13)."""
        ceiling = self.size_ceiling_bytes if max_bytes is None else int(max_bytes)
        clock = time.time() if now is None else float(now)
        deleted = 0
        bytes_freed = 0

        complete_files = sorted(
            self.complete_root.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
        )
        for path in list(complete_files):
            try:
                mtime = path.stat().st_mtime
                size = path.stat().st_size
            except OSError:
                continue
            over_age = max_age_seconds >= 0 and (clock - mtime) > max_age_seconds
            over_size = ceiling > 0 and self._size_bytes() > ceiling
            if not over_age and not over_size:
                continue
            try:
                path.unlink()
            except OSError:
                continue
            deleted += 1
            bytes_freed += size
            if path in complete_files:
                complete_files.remove(path)
            if ceiling <= 0 or self._size_bytes() <= ceiling:
                if not over_age:
                    # Only continuing for size pressure.
                    if self._size_bytes() <= ceiling:
                        break
        return {"deleted": deleted, "bytesFreed": bytes_freed}
