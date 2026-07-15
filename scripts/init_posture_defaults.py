#!/usr/bin/env python3
"""Greenfield init posture seeds shared by /sw-init and schema tests (PRD 069 R10)."""
from __future__ import annotations

from typing import Any

# Seven leaf keys seeded on greenfield /sw-init (schema defaults + write-draft).
GREENFIELD_POSTURE_LEAF_KEYS: tuple[tuple[tuple[str, ...], Any], ...] = (
    (("orchestration", "planPolicy"), "proposed"),
    (("delegation", "mode"), "heuristic"),
    (("planning", "autonomy"), "full-conductor"),
    (("deliver", "autonomy", "mode"), "autonomous"),
    (("deliver", "loop", "drainMechanical"), True),
    (("inefficiency", "enabled"), True),
    (("execute", "enabled"), True),
)


def greenfield_posture_patch() -> dict[str, Any]:
    """Nested dict patch merged into sw-configure write-draft."""
    return {
        "orchestration": {"planPolicy": "proposed"},
        "delegation": {"mode": "heuristic"},
        "planning": {"autonomy": "full-conductor", "store": {"backend": "in-repo-public"}},
        "deliver": {
            "autonomy": {"mode": "autonomous", "maxRunMinutes": 1440, "maxIterations": 500},
            "loop": {"drainMechanical": True},
        },
        "inefficiency": {"enabled": True},
        "execute": {"enabled": True},
    }


def leaf_get(doc: dict[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = doc
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            raise KeyError(".".join(path))
        cur = cur[key]
    return cur
