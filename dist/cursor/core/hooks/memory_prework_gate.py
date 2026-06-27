"""Shared pre-work memory search record validation (PRD 019 R6–R8)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

RECORD_PATH = Path(".cursor/hooks/state/memory-prework-search.json")
_VALID_OUTCOMES = frozenset({"memory:offline", "memory:none", "memory:hits"})


def load_record(root: Path) -> dict[str, Any] | None:
    path = root / RECORD_PATH
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def validate_fresh_record(record: dict[str, Any] | None) -> str | None:
    """Return None when valid; otherwise a machine cause string."""
    if not record:
        return "missing-prework-search-record"
    outcome = str(record.get("outcome") or "")
    if outcome not in _VALID_OUTCOMES:
        return "invalid-prework-search-outcome"
    if record.get("consumedAt"):
        return "stale-prework-search-record"
    expires_at = int(record.get("expiresAt") or 0)
    if expires_at <= int(time.time()):
        return "expired-prework-search-record"
    return None


def consume_record(root: Path) -> None:
    record = load_record(root)
    if not record:
        return
    record["consumedAt"] = int(time.time())
    path = root / RECORD_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
