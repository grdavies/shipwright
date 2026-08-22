#!/usr/bin/env python3
"""Greenfield init posture seeds shared by /sw-init and schema tests (PRD 069 R10)."""
from __future__ import annotations

from typing import Any

from init_profile_report import (
    curated_posture_leaf_keys,
    greenfield_posture_patch as _profile_posture_patch,
    leaf_get,
)

# Seven leaf keys — sole source is init_profile_report (PRD 324 R9).
GREENFIELD_POSTURE_LEAF_KEYS: tuple[tuple[tuple[str, ...], Any], ...] = curated_posture_leaf_keys()


def greenfield_posture_patch() -> dict[str, Any]:
    """Nested dict patch merged into sw-configure write-draft."""
    return _profile_posture_patch()
