"""In-repo public backend adapter (PRD 082 phase 12 / R27)."""
from __future__ import annotations

from pathlib import Path

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

class InRepoPublicBackend(PlanningStoreBackend):
    backend_id = "in-repo-public"

    def _resolve_path(self, body_path: str) -> Path:
        path = (self.root / body_path).resolve()
        root_resolved = self.root.resolve()
        if root_resolved not in path.parents and path != root_resolved:
            fail("body path escapes repository root", bodyPath=body_path)
        return path

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        from planning_paths import atomic_write_text

        path = self._resolve_path(body_path)
        atomic_write_text(path, content, root=self.root, store_id=FILE_BACKED_STORE_TXN_ID)
        log_operation("put", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        path = self._resolve_path(body_path)
        if not path.is_file():
            return StoreResult("missing", unit_id, body_path, self.backend_id, reason="not-found")
        content = path.read_text(encoding="utf-8")
        log_operation("get", unit_id, body_path, content, self.backend_id)
        return StoreResult("ok", unit_id, body_path, self.backend_id, content=content, hash=content_hash(content))

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        path = self._resolve_path(body_path)
        present = path.is_file()
        log_operation("exists", unit_id, body_path, None, self.backend_id)
        return StoreResult("ok" if present else "missing", unit_id, body_path, self.backend_id, reason=None if present else "not-found")

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        got = self.get(unit_id, body_path)
        return finalize_materialize_from_get(got, unit_id, body_path, self.backend_id, dest_path)

