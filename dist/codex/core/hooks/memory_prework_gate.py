"""Shared pre-work memory search record validation (PRD 019 R6–R8, PRD 072 R8 surface window)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

RECORD_PATH = Path(".cursor/hooks/state/memory-prework-search.json")
_VALID_OUTCOMES = frozenset({"memory:offline", "memory:none", "memory:hits"})
DEFAULT_SURFACE_MUTATION_BUDGET = 50


def mutation_budget(record: dict[str, Any]) -> int:
    raw = record.get("mutationBudget")
    if raw is None:
        return 1
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1


def mutations_used(record: dict[str, Any]) -> int:
    try:
        return max(0, int(record.get("mutationsUsed") or 0))
    except (TypeError, ValueError):
        return 0


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
    if mutations_used(record) >= mutation_budget(record):
        return "exhausted-prework-surface-window"
    if record.get("consumedAt"):
        return "stale-prework-search-record"
    expires_at = int(record.get("expiresAt") or 0)
    if expires_at <= int(time.time()):
        return "expired-prework-search-record"
    return None


def _persist_record(root: Path, record: dict[str, Any]) -> None:
    path = root / RECORD_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")


def consume_mutation(root: Path) -> None:
    """Consume one mutation use within the surface window; exhaust when budget spent."""
    record = load_record(root)
    if not record:
        return
    used = mutations_used(record) + 1
    record["mutationsUsed"] = used
    if used >= mutation_budget(record):
        record["consumedAt"] = int(time.time())
    _persist_record(root, record)


def consume_record(root: Path) -> None:
    """Backward-compatible alias — decrements surface-window budget."""
    consume_mutation(root)
