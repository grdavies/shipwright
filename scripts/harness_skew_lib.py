"""Shared harness-mode predicate for orch↔primary skew skip (PRD 072 R3)."""
from __future__ import annotations

import os

_TRUTHY = frozenset({"1", "true", "yes"})


def skip_live_canonical_sync(env: dict[str, str] | None = None) -> bool:
    """True when live orch↔primary skew sync must not fail closed."""
    source = os.environ if env is None else env
    if str(source.get("SW_SKIP_CANONICAL_SYNC", "")).strip().lower() in _TRUTHY:
        return True
    if source.get("SW_HARNESS") == "1":
        return True
    if str(source.get("SW_DELIVER_VERIFY", "")).strip().lower() in _TRUTHY:
        return True
    return False
