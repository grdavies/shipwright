#!/usr/bin/env python3
"""Redaction-safe namespaced query cache (PRD 046 R84, R85)."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig  # noqa: E402
import planning_paths as pp  # noqa: E402
from planning_request_budget import RequestBudgetLedger  # noqa: E402

CACHE_STATE_REL = ".cursor/hooks/state/planning-query-cache.json"
DEFAULT_QUERY_FINGERPRINT = "discover-units-all"


def cache_path(root: Path) -> Path:
    return pp.git_root(root) / CACHE_STATE_REL


def query_fingerprint(project_key: str, *, artifact_type: str | None = None) -> str:
    raw = f"{project_key}|{artifact_type or '*'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def cache_key(project_key: str, fingerprint: str, generation_epoch: int) -> str:
    return f"{project_key}:{fingerprint}:{generation_epoch}"


def load_cache(root: Path) -> dict[str, Any]:
    path = cache_path(root)
    if not path.is_file():
        return {"version": 1, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "entries": {}}
    return data if isinstance(data, dict) else {"version": 1, "entries": {}}


def save_cache(root: Path, data: dict[str, Any]) -> None:
    path = cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def get_entry(root: Path, *, project_key: str, fingerprint: str = DEFAULT_QUERY_FINGERPRINT, ttl_seconds: int | None = None) -> dict[str, Any] | None:
    epoch = pig.read_generation(root)
    key = cache_key(project_key, fingerprint, epoch)
    cache = load_cache(root)
    entries = cache.get("entries")
    if not isinstance(entries, dict):
        return None
    entry = entries.get(key)
    if not isinstance(entry, dict):
        return None
    if ttl_seconds is not None:
        written = float(entry.get("writtenAt", 0))
        if written and time.time() - written > ttl_seconds:
            return None
    return entry


def put_entry(root: Path, *, project_key: str, fingerprint: str, projections: list[dict[str, Any]], metadata: dict[str, Any] | None = None) -> str:
    epoch = pig.read_generation(root)
    key = cache_key(project_key, fingerprint, epoch)
    cache = load_cache(root)
    entries = cache.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    entries[key] = {
        "projectKey": project_key,
        "fingerprint": fingerprint,
        "generationEpoch": epoch,
        "projections": projections,
        "metadata": metadata or {},
        "writtenAt": time.time(),
        "postRedactionOnly": True,
    }
    cache["entries"] = entries
    save_cache(root, cache)
    return key


def invalidate_all(root: Path) -> None:
    save_cache(root, {"version": 1, "entries": {}})


def revalidate_live_metadata(root: Path, client: Any, entry: dict[str, Any]) -> bool:
    metadata = entry.get("metadata")
    if not isinstance(metadata, dict):
        return False
    cached_by_unit = metadata.get("units")
    if not isinstance(cached_by_unit, dict):
        return False
    project_key = str(entry.get("projectKey", ""))
    live = client.issue_search(project_key=project_key)
    live_map = {str(r.unit_id or r.id): {"state": r.state, "labels": sorted(r.labels), "updated_at": r.updated_at} for r in live if str(r.unit_id or r.id)}
    for unit_id, snap in cached_by_unit.items():
        live_row = live_map.get(unit_id)
        if live_row is None:
            if snap.get("state") == "open":
                return False
            continue
        if live_row["state"] != snap.get("state"):
            return False
        if live_row["labels"] != snap.get("labels"):
            return False
    return True


def resolve_ttl(root: Path, provider: str) -> int:
    return RequestBudgetLedger.from_config(root, provider).cache_ttl_seconds
