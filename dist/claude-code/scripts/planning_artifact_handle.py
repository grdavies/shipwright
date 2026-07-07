#!/usr/bin/env python3
"""Resolve planning artifact content from git files or issue-store handles (PRD 056 R13)."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from host_lib import load_workflow_config
from planning_store import get_backend, resolve_effective_backend


def issue_store_is_effective(root: Path, cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg if cfg is not None else load_workflow_config(root)
    return resolve_effective_backend(root, cfg).get("effective") == "issue-store"


def default_unit_id_from_body_path(body_path: str) -> str:
    return Path(body_path.replace("\\", "/")).stem


def normalize_body_path(body_path: str) -> str:
    return body_path.replace("\\", "/").lstrip("/")


def resolve_repo_file(root: Path, rel: str) -> Path | None:
    rel = normalize_body_path(rel)
    if not rel or rel.startswith("http"):
        return None
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def resolve_artifact_text(
    root: Path,
    body_path: str,
    *,
    unit_id: str | None = None,
) -> tuple[str | None, str]:
    direct = Path(body_path)
    if direct.is_file():
        return direct.read_text(encoding="utf-8"), "file"
    rel = normalize_body_path(body_path)
    path = resolve_repo_file(root, rel)
    if path is not None:
        return path.read_text(encoding="utf-8"), "file"
    if not issue_store_is_effective(root):
        return None, "missing"
    uid = unit_id or default_unit_id_from_body_path(rel)
    backend = get_backend(root)
    result = backend.get(uid, rel)
    if result.verdict == "ok" and result.content is not None:
        return result.content, "issue-store"
    return None, "missing"


def artifact_handle_resolves(
    root: Path,
    rel: str,
    *,
    unit_id: str | None = None,
) -> bool:
    direct = Path(rel)
    if direct.is_file():
        return True
    if resolve_repo_file(root, rel) is not None:
        return True
    if not issue_store_is_effective(root):
        return False
    norm = normalize_body_path(rel)
    backend = get_backend(root)
    if unit_id:
        if backend.exists(unit_id, norm).verdict == "ok":
            return True
    uid = default_unit_id_from_body_path(norm)
    if backend.exists(uid, norm).verdict == "ok":
        return True
    from planning_store import load_issue_unit_index

    idx = load_issue_unit_index(root)
    for key, issue_id in idx.items():
        if not issue_id:
            continue
        parts = key.split(":", 2)
        if len(parts) == 3 and backend.exists(parts[2], norm).verdict == "ok":
            return True
    return False


def materialize_artifact_file(
    root: Path,
    body_path: str,
    *,
    unit_id: str | None = None,
    dest_dir: Path | None = None,
) -> Path | None:
    direct = Path(body_path)
    if direct.is_file():
        return direct
    rel = normalize_body_path(body_path)
    existing = resolve_repo_file(root, rel)
    if existing is not None:
        return existing
    text, source = resolve_artifact_text(root, rel, unit_id=unit_id)
    if text is None or source != "issue-store":
        return None
    base = dest_dir or Path(tempfile.mkdtemp(prefix="sw-artifact-"))
    dest = base / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return dest


def put_artifact_text(
    root: Path,
    unit_id: str,
    body_path: str,
    content: str,
) -> dict[str, Any]:
    if not issue_store_is_effective(root):
        rel = normalize_body_path(body_path)
        path = (root / rel).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"verdict": "ok", "backend": "file", "unitId": unit_id, "bodyPath": rel}
    backend = get_backend(root)
    rel = normalize_body_path(body_path)
    result = backend.put(unit_id, rel, content)
    return {
        "verdict": result.verdict,
        "backend": result.backend,
        "unitId": unit_id,
        "bodyPath": rel,
        "hash": result.hash,
    }
