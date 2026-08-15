#!/usr/bin/env python3
"""Authenticated canonical cache store — separate from run journals (PRD 271 R4–R6, R21–R26)."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from graph.artifact_registry import receipt_is_reusable
from graph.cache_mac import MacKeyResolver, resolve_cache_mac_key
from graph.lineage import CacheKeyMaterial, compute_stable_cache_key, keyed_mac

_SAFE_CACHE_KEY = re.compile(r"^[a-f0-9]{64}$")
CACHE_STORE_VERSION = 1
DEFAULT_CACHE_SIZE_CEILING_BYTES = 256 * 1024 * 1024
DEFAULT_CACHE_RETENTION_SECONDS = 30 * 24 * 60 * 60

IDENTITY_FIELDS = (
    "repo_state_identity",
    "trust_domain",
    "resolved_scope_identity",
    "repository_identity",
)
IDENTITY_ALIASES: dict[str, tuple[str, ...]] = {
    "resolved_scope_identity": ("scope_identity", "resolvedScopeIdentity"),
    "repository_identity": ("repositoryIdentity",),
    "trust_domain": ("trustDomain",),
    "repo_state_identity": ("repoStateIdentity",),
}

GATE_NODE_KINDS = frozenset(
    {
        "verify",
        "review",
        "ready-gate",
        "mechanical-verify",
        "gap-check",
        "check-gate",
        "verification-gate",
        "stabilize",
    }
)

class CacheStoreError(RuntimeError):
    """Base class for canonical cache failures."""


class CacheStoreFull(CacheStoreError):
    """Raised when a write would exceed the configured size ceiling."""


class CacheIntegrityError(CacheStoreError):
    """Raised when a cache entry fails MAC or structural validation."""


class CacheScope(str, Enum):
    """Scope ladder: dogfood defaults to run; repository after trust gates (R5c)."""

    RUN = "run"
    REPOSITORY = "repository"


def _canonical(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


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


def default_cache_root(repo_root: str | Path) -> Path:
    """Gitignored canonical cache root — distinct from run journals (R4/R21)."""
    return Path(repo_root) / ".cursor" / "sw-graph-cache"


def _identity_value(identity: Mapping[str, Any], field: str) -> str:
    if field in identity and identity[field]:
        return str(identity[field])
    for alias in IDENTITY_ALIASES.get(field, ()):
        if alias in identity and identity[alias]:
            return str(identity[alias])
    return ""


def cache_identity_eligible(identity: Mapping[str, Any]) -> bool:
    """R25: missing or defaulted identity components make the node cache-ineligible."""
    for field in IDENTITY_FIELDS:
        value = _identity_value(identity, field)
        if not value or value == "default":
            return False
    return True


def node_cache_eligible(node: Mapping[str, Any], identity: Mapping[str, Any]) -> bool:
    """Gate-bearing nodes are non-cacheable; content-addressed + full identity required."""
    kind = str(node.get("kind") or "").lower()
    if kind in GATE_NODE_KINDS:
        return False
    execution = node.get("execution") or {}
    if not isinstance(execution, Mapping):
        return False
    if execution.get("cache") != "content-addressed":
        return False
    if execution.get("gate") or execution.get("reAttest"):
        return False
    return cache_identity_eligible(identity)


@dataclass(frozen=True)
class CacheEntry:
    """Verified canonical cache payload."""

    cache_key: str
    stable_cache_key: str
    scope: CacheScope
    source_run_id: str
    source_receipt: dict[str, Any]
    artifacts: tuple[dict[str, Any], ...]
    entry_mac: str
    stored_at: float

    def as_record(self) -> dict[str, Any]:
        return {
            "version": CACHE_STORE_VERSION,
            "cacheKey": self.cache_key,
            "stableCacheKey": self.stable_cache_key,
            "scope": self.scope.value,
            "sourceRunId": self.source_run_id,
            "sourceReceipt": self.source_receipt,
            "artifacts": list(self.artifacts),
            "entryMac": self.entry_mac,
            "storedAt": self.stored_at,
        }


@dataclass(frozen=True)
class CacheHit:
    """Receipt-visible cache hit metadata (R6)."""

    cache_key: str
    source: str
    original_run_id: str
    source_receipt: dict[str, Any]
    artifacts: tuple[dict[str, Any], ...]


class CanonicalCacheStore:
    """Versioned transactional store with immutable objects and atomic manifests (R4a)."""

    def __init__(
        self,
        root: str | Path,
        *,
        scope: CacheScope = CacheScope.RUN,
        repo_root: str | Path | None = None,
        size_ceiling_bytes: int = DEFAULT_CACHE_SIZE_CEILING_BYTES,
        mac_key: bytes | None = None,
        mac_key_resolver: MacKeyResolver | None = None,
    ) -> None:
        self.root = Path(root)
        self.scope = scope
        self._repo_root = Path(repo_root) if repo_root is not None else self.root.parent.parent
        self.size_ceiling_bytes = int(size_ceiling_bytes)
        self._mac_key = resolve_cache_mac_key(
            self._repo_root,
            mac_key=mac_key,
            resolver=mac_key_resolver,
        )
        self.objects_root = self.root / "objects"
        self.manifests_root = self.root / "manifests"
        self.bookkeeping_root = self.root / "bookkeeping"
        self.quarantine_root = self.root / "quarantine"
        for directory in (
            self.objects_root,
            self.manifests_root,
            self.bookkeeping_root,
            self.quarantine_root,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.root, 0o700)
        except OSError:
            pass
        self._ensure_bookkeeping()

    @classmethod
    def for_repo(
        cls,
        repo_root: str | Path,
        *,
        scope: CacheScope = CacheScope.RUN,
        size_ceiling_bytes: int = DEFAULT_CACHE_SIZE_CEILING_BYTES,
        mac_key: bytes | None = None,
        mac_key_resolver: MacKeyResolver | None = None,
    ) -> CanonicalCacheStore:
        return cls(
            default_cache_root(repo_root),
            scope=scope,
            repo_root=repo_root,
            size_ceiling_bytes=size_ceiling_bytes,
            mac_key=mac_key,
            mac_key_resolver=mac_key_resolver,
        )

    def _bookkeeping_path(self) -> Path:
        return self.bookkeeping_root / "stats.json"

    def _ensure_bookkeeping(self) -> dict[str, Any]:
        path = self._bookkeeping_path()
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        payload = {
            "version": CACHE_STORE_VERSION,
            "totalBytes": 0,
            "entryCount": 0,
            "refCounts": {},
            "updatedAt": time.time(),
        }
        _atomic_write(path, payload)
        return payload

    def _read_bookkeeping(self) -> dict[str, Any]:
        path = self._bookkeeping_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CacheIntegrityError(f"bookkeeping unreadable: {exc}") from exc
        if not isinstance(data, dict):
            raise CacheIntegrityError("bookkeeping is not an object")
        return data

    def _write_bookkeeping(self, stats: dict[str, Any]) -> None:
        stats["updatedAt"] = time.time()
        _atomic_write(self._bookkeeping_path(), stats)

    def _object_path(self, cache_key: str) -> Path:
        if not _SAFE_CACHE_KEY.fullmatch(cache_key):
            raise ValueError(f"invalid cache key: {cache_key!r}")
        return self.objects_root / f"{cache_key}.json"

    def _entry_mac(self, body: dict[str, Any]) -> str:
        digest_source = {
            key: value for key, value in body.items() if key not in {"entryMac"}
        }
        return keyed_mac(_canonical(digest_source), mac_key=self._mac_key)

    def _enforce_ceiling(self, upcoming_bytes: int) -> None:
        if self.size_ceiling_bytes <= 0:
            return
        stats = self._read_bookkeeping()
        total = int(stats.get("totalBytes") or 0)
        if total + upcoming_bytes > self.size_ceiling_bytes:
            raise CacheStoreFull(
                f"cache store exceeds size ceiling ({self.size_ceiling_bytes} bytes)"
            )

    def _adjust_bookkeeping(
        self,
        *,
        delta_bytes: int,
        delta_count: int,
        cache_key: str | None = None,
        ref_delta: int = 0,
    ) -> None:
        stats = self._read_bookkeeping()
        stats["totalBytes"] = max(0, int(stats.get("totalBytes") or 0) + delta_bytes)
        stats["entryCount"] = max(0, int(stats.get("entryCount") or 0) + delta_count)
        if cache_key is not None and ref_delta:
            ref_counts = dict(stats.get("refCounts") or {})
            current = int(ref_counts.get(cache_key) or 0) + ref_delta
            if current <= 0:
                ref_counts.pop(cache_key, None)
            else:
                ref_counts[cache_key] = current
            stats["refCounts"] = ref_counts
        self._write_bookkeeping(stats)

    def _quarantine(self, path: Path, exc: BaseException) -> None:
        target = self.quarantine_root / f"{path.stem}-{os.getpid()}.corrupt.json"
        try:
            os.replace(path, target)
        except OSError:
            pass
        raise CacheIntegrityError(
            f"cache entry quarantined from {path}: {exc}"
        ) from exc

    def _verify_entry(self, payload: dict[str, Any], *, path: Path) -> CacheEntry:
        entry_mac = payload.get("entryMac")
        if not isinstance(entry_mac, str) or not entry_mac:
            self._quarantine(path, CacheIntegrityError("missing entryMac"))
        expected = self._entry_mac(payload)
        if entry_mac != expected:
            self._quarantine(path, CacheIntegrityError("entryMac mismatch"))
        cache_key = str(payload.get("cacheKey") or "")
        if not _SAFE_CACHE_KEY.fullmatch(cache_key):
            self._quarantine(path, CacheIntegrityError("invalid cacheKey"))
        source_receipt = payload.get("sourceReceipt")
        if not isinstance(source_receipt, dict) or not receipt_is_reusable(
            source_receipt, mac_key=self._mac_key
        ):
            self._quarantine(path, CacheIntegrityError("source receipt not reusable"))
        artifacts_raw = payload.get("artifacts")
        if not isinstance(artifacts_raw, list):
            self._quarantine(path, CacheIntegrityError("artifacts must be a list"))
        scope_raw = str(payload.get("scope") or CacheScope.RUN.value)
        try:
            scope = CacheScope(scope_raw)
        except ValueError as exc:
            self._quarantine(path, exc)
        return CacheEntry(
            cache_key=cache_key,
            stable_cache_key=str(payload.get("stableCacheKey") or cache_key),
            scope=scope,
            source_run_id=str(payload.get("sourceRunId") or ""),
            source_receipt=source_receipt,
            artifacts=tuple(dict(item) for item in artifacts_raw),
            entry_mac=entry_mac,
            stored_at=float(payload.get("storedAt") or 0.0),
        )

    def _load_entry(self, cache_key: str) -> CacheEntry | None:
        path = self._object_path(cache_key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            try:
                self._quarantine(path, exc)
            except CacheIntegrityError:
                return None
            return None
        if not isinstance(payload, dict):
            try:
                self._quarantine(path, CacheIntegrityError("entry is not an object"))
            except CacheIntegrityError:
                return None
            return None
        try:
            return self._verify_entry(payload, path=path)
        except CacheIntegrityError:
            return None

    def _extract_run_id(self, receipt: Mapping[str, Any]) -> str:
        idempotency = str(receipt.get("idempotencyKey") or "")
        if ":" in idempotency:
            return idempotency.split(":", 1)[0]
        policy = receipt.get("policyEvent")
        if isinstance(policy, Mapping) and policy.get("runId"):
            return str(policy["runId"])
        return ""

    def put(
        self,
        *,
        material: CacheKeyMaterial,
        source_receipt: Mapping[str, Any],
        artifacts: Sequence[Mapping[str, Any]],
        run_id: str,
    ) -> str:
        """Persist a reusable cache entry; idempotent on identical payload."""
        receipt = dict(source_receipt)
        if not receipt_is_reusable(receipt, mac_key=self._mac_key):
            raise CacheStoreError("source receipt is not cache-reusable")
        stable_key = compute_stable_cache_key(material)
        cache_key = stable_key
        body = {
            "version": CACHE_STORE_VERSION,
            "cacheKey": cache_key,
            "stableCacheKey": stable_key,
            "scope": self.scope.value,
            "sourceRunId": run_id,
            "sourceReceipt": receipt,
            "artifacts": [dict(item) for item in artifacts],
            "storedAt": time.time(),
        }
        body["entryMac"] = self._entry_mac(body)
        encoded = _canonical(body)
        path = self._object_path(cache_key)
        if path.is_file():
            existing = self._load_entry(cache_key)
            if existing is not None and existing.source_receipt == receipt:
                return cache_key
            raise CacheStoreError("cache key already exists with different payload")
        self._enforce_ceiling(len(encoded))
        _atomic_write(path, body)
        self._adjust_bookkeeping(
            delta_bytes=len(encoded),
            delta_count=1,
        )
        self._publish_manifest(cache_key)
        return cache_key

    def _manifest_path(self) -> Path:
        return self.manifests_root / self.scope.value / "current.json"

    def _publish_manifest(self, cache_key: str) -> None:
        manifest_dir = self.manifests_root / self.scope.value
        manifest_dir.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {"version": CACHE_STORE_VERSION, "keys": []}
        path = self._manifest_path()
        if path.is_file():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing = loaded
            except (OSError, json.JSONDecodeError):
                pass
        keys = list(existing.get("keys") or [])
        if cache_key not in keys:
            keys.append(cache_key)
        payload = {
            "version": CACHE_STORE_VERSION,
            "scope": self.scope.value,
            "keys": sorted(keys),
            "publishedAt": time.time(),
        }
        _atomic_write(path, payload)

    def lookup(
        self,
        cache_key: str,
        *,
        run_id: str,
    ) -> CacheHit | None:
        """Return a verified hit or None; untrusted-on-read (R5a)."""
        entry = self._load_entry(cache_key)
        if entry is None:
            return None
        if self.scope is CacheScope.RUN and entry.source_run_id != run_id:
            return None
        return CacheHit(
            cache_key=entry.cache_key,
            source="cache",
            original_run_id=entry.source_run_id or self._extract_run_id(entry.source_receipt),
            source_receipt=entry.source_receipt,
            artifacts=entry.artifacts,
        )

    def lookup_material(
        self,
        material: CacheKeyMaterial,
        *,
        run_id: str,
    ) -> CacheHit | None:
        return self.lookup(compute_stable_cache_key(material), run_id=run_id)

    def gc(
        self,
        *,
        max_age_seconds: int = DEFAULT_CACHE_RETENTION_SECONDS,
        max_bytes: int | None = None,
        now: float | None = None,
    ) -> dict[str, int]:
        """Reference-aware GC with incremental bookkeeping (R4b/R4c/R22/R23)."""
        ceiling = self.size_ceiling_bytes if max_bytes is None else int(max_bytes)
        clock = time.time() if now is None else float(now)
        deleted = 0
        bytes_freed = 0
        stats = self._read_bookkeeping()
        ref_counts = dict(stats.get("refCounts") or {})
        candidates = sorted(
            self.objects_root.glob("*.json"),
            key=lambda path: path.stat().st_mtime,
        )
        for path in list(candidates):
            cache_key = path.stem
            if int(ref_counts.get(cache_key) or 0) > 0:
                continue
            try:
                mtime = path.stat().st_mtime
                size = path.stat().st_size
            except OSError:
                continue
            over_age = max_age_seconds >= 0 and (clock - mtime) > max_age_seconds
            over_size = ceiling > 0 and int(stats.get("totalBytes") or 0) > ceiling
            if not over_age and not over_size:
                continue
            try:
                path.unlink()
            except OSError:
                continue
            deleted += 1
            bytes_freed += size
            stats["totalBytes"] = max(0, int(stats.get("totalBytes") or 0) - size)
            stats["entryCount"] = max(0, int(stats.get("entryCount") or 0) - 1)
            if not over_age and int(stats.get("totalBytes") or 0) <= ceiling:
                break
        self._write_bookkeeping(stats)
        return {"deleted": deleted, "bytesFreed": bytes_freed}
