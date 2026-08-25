#!/usr/bin/env python3
"""Canonical ExplorationMap lifecycle store (PRD 331 R6, R8, R13, R37, R41, R47)."""
from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class ExplorationStoreError(RuntimeError):
    """Base error for exploration store operations."""


class StaleRevisionError(ExplorationStoreError):
    """Optimistic write refused — expected revision does not match live map (R41)."""

    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"stale-revision:expected={expected}:actual={actual}")
        self.expected = expected
        self.actual = actual


class PersistenceRefusedError(ExplorationStoreError):
    """Persistence requested without an allowed trigger (R37)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def persistence_required(triggers: Mapping[str, Any] | None) -> bool:
    """True when map persistence is allowed — never always-on (R37)."""
    if not isinstance(triggers, dict):
        return False
    if triggers.get("blockingUnknowns") is True:
        return True
    if triggers.get("resumeRequired") is True:
        return True
    if triggers.get("promoteReceipt") is not None:
        return True
    return False


def _atomic_write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _apply_patch(document: dict[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    updated = deepcopy(document)
    for key, value in patch.items():
        if key == "revision":
            continue
        updated[key] = deepcopy(value)
    return updated


class ExplorationStore:
    """Provider-neutral in-memory store with conditional disk persistence."""

    def __init__(self, root: Path | str, *, persist_root: Path | str | None = None) -> None:
        self._root = Path(root)
        self._persist_root = (
            Path(persist_root) if persist_root is not None else self._root / ".cursor" / "sw-explore-maps"
        )
        self._maps: dict[str, dict[str, Any]] = {}
        self._persisted_receipts: dict[str, set[str]] = {}

    def _map_path(self, map_id: str) -> Path:
        safe = map_id.replace("/", "_")
        return self._persist_root / safe / "map.json"

    def _require_map(self, map_id: str) -> dict[str, Any]:
        if map_id not in self._maps:
            hydrated = self._hydrate_from_disk(map_id)
            if hydrated is None:
                raise ExplorationStoreError("map-not-found")
            return hydrated
        return self._maps[map_id]

    def _hydrate_from_disk(self, map_id: str) -> dict[str, Any] | None:
        path = self._map_path(map_id)
        if not path.is_file():
            return None
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ExplorationStoreError("persisted-map-invalid")
        self._maps[map_id] = document
        return document

    def create(self, document: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(document, Mapping):
            raise ExplorationStoreError("invalid-document")
        map_id = str(document.get("id") or "").strip()
        if not map_id:
            raise ExplorationStoreError("missing-map-id")
        if map_id in self._maps or self._map_path(map_id).is_file():
            raise ExplorationStoreError("map-already-exists")
        stored = deepcopy(dict(document))
        revision = stored.get("revision")
        if not isinstance(revision, int) or revision < 1:
            stored["revision"] = 1
        self._maps[map_id] = stored
        return {
            "verdict": "ok",
            "mapId": map_id,
            "map": deepcopy(stored),
            "persisted": False,
            "source": "memory",
        }

    def read(self, map_id: str) -> dict[str, Any] | None:
        if map_id in self._maps:
            return {
                "verdict": "ok",
                "mapId": map_id,
                "map": deepcopy(self._maps[map_id]),
                "source": "memory",
            }
        hydrated = self._hydrate_from_disk(map_id)
        if hydrated is None:
            return None
        return {
            "verdict": "ok",
            "mapId": map_id,
            "map": deepcopy(hydrated),
            "source": "disk",
        }

    def update(
        self,
        map_id: str,
        patch: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        current = self._require_map(map_id)
        actual = int(current.get("revision", 0))
        if actual != expected_revision:
            raise StaleRevisionError(expected_revision, actual)
        updated = _apply_patch(current, patch)
        updated["revision"] = actual + 1
        provenance = updated.get("provenance")
        if isinstance(provenance, dict):
            provenance["updatedAt"] = utc_now()
        self._maps[map_id] = updated
        return {
            "verdict": "ok",
            "mapId": map_id,
            "map": deepcopy(updated),
            "revision": updated["revision"],
            "persisted": self._map_path(map_id).is_file(),
        }

    def persist(self, map_id: str, *, expected_revision: int) -> dict[str, Any]:
        current = self._require_map(map_id)
        actual = int(current.get("revision", 0))
        if actual != expected_revision:
            raise StaleRevisionError(expected_revision, actual)
        triggers = current.get("persistenceTriggers")
        if not persistence_required(triggers if isinstance(triggers, dict) else None):
            raise PersistenceRefusedError("no-persistence-trigger")
        path = self._map_path(map_id)
        receipt = triggers.get("promoteReceipt") if isinstance(triggers, dict) else None
        receipt_id = None
        if isinstance(receipt, dict):
            receipt_id = str(receipt.get("receiptId") or "").strip() or None
        if receipt_id and receipt_id in self._persisted_receipts.get(map_id, set()):
            return {
                "verdict": "ok",
                "mapId": map_id,
                "persisted": True,
                "idempotent": True,
                "path": str(path),
                "revision": actual,
            }
        _atomic_write(path, current)
        if receipt_id:
            self._persisted_receipts.setdefault(map_id, set()).add(receipt_id)
        return {
            "verdict": "ok",
            "mapId": map_id,
            "persisted": True,
            "idempotent": False,
            "path": str(path),
            "revision": actual,
        }
