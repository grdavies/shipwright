"""Local-synced backend adapter (PRD 082 phase 12 / R27)."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from ..model import StoreResult
from ..repository import PlanningStoreBackend

from ._common import (
    FILE_BACKED_STORE_TXN_ID,
    content_hash,
    finalize_materialize_from_get,
    log_operation,
)


def fail(error: str, exit_code: int = 2, **extra):
    from planning_store import fail as _fail

    _fail(error, exit_code, **extra)


def store_section(cfg: dict[str, Any]) -> dict[str, Any]:
    from planning_store import store_section as _store_section

    return _store_section(cfg)

class LocalSyncedBackend(PlanningStoreBackend):
    backend_id = "local-synced"

    def synced_root(self) -> Path:
        store = store_section(self.cfg)
        local = store.get("localSynced")
        if not isinstance(local, dict):
            fail("planning.store.localSynced.path is required for local-synced backend")
        raw = local.get("path")
        if not isinstance(raw, str) or not raw.strip():
            fail("planning.store.localSynced.path is required for local-synced backend")
        return Path(os.path.expanduser(raw.strip())).resolve()

    def _unit_path(self, unit_id: str) -> Path:
        safe_id = re.sub(r"[^a-zA-Z0-9._-]+", "_", unit_id)
        return self.synced_root() / f"{safe_id}.md"

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        from planning_paths import atomic_write_text

        path = self._unit_path(unit_id)
        store_root = self.synced_root()
        atomic_write_text(path, content, root=store_root, store_id=FILE_BACKED_STORE_TXN_ID)
        log_operation("put", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        path = self._unit_path(unit_id)
        if not path.is_file():
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        content = path.read_text(encoding="utf-8")
        log_operation("get", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        present = self._unit_path(unit_id).is_file()
        log_operation("exists", unit_id, body_path, None, self.backend_id)
        return StoreResult("ok" if present else "missing", unit_id, body_path, self.backend_id, reason=None if present else "not-found")

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        got = self.get(unit_id, body_path)
        return finalize_materialize_from_get(got, unit_id, body_path, self.backend_id, dest_path)
