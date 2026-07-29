"""Shared helpers for planning store backends (PRD 082 phase 12 / R27)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from ..model import StoreResult, materialize_missing_result

FILE_BACKED_STORE_TXN_ID = "file-backed"


def content_hash(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def log_operation(
    op: str,
    unit_id: str,
    body_path: str,
    content: str | None,
    backend: str,
    *,
    stream: Any = None,
    notice: str | None = None,
) -> None:
    digest = content_hash(content) if content is not None else "none"
    payload: dict[str, Any] = {
        "planningStore": True,
        "op": op,
        "unitId": unit_id,
        "path": body_path,
        "hash": digest,
        "backend": backend,
    }
    if notice:
        payload["notice"] = notice
    line = json.dumps(payload, ensure_ascii=False)
    target = stream if stream is not None else sys.stderr
    print(line, file=target)


def finalize_materialize_from_get(
    got: StoreResult,
    unit_id: str,
    body_path: str,
    backend_id: str,
    dest_path: Path,
) -> StoreResult:
    """Write materialized body to dest or return typed missing-frozen-body (PRD 069 R5)."""
    content = got.content
    if got.verdict != "ok" or content is None or (isinstance(content, str) and not content.strip()):
        return materialize_missing_result(unit_id, body_path, backend_id)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(content, encoding="utf-8")
    log_operation("materialize", unit_id, body_path, content, backend_id)
    return StoreResult("ok", unit_id, body_path, backend_id, content=content, hash=got.hash or content_hash(content))
