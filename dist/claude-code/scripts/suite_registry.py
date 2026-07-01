#!/usr/bin/env python3
"""Suite registry discovery and lane projection helpers (PRD 052 TR2)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

REGISTRY_REL = Path("core/sw-reference/suite-registry.json")
VALID_LANES = frozenset({"pr-ci", "verify", "ci-yml", "doc", "internal"})


def repo_root(start: Path | None = None) -> Path:
    start = start or SCRIPT_DIR
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists():
            return candidate
    return cur


def discover_suites(root: Path | None = None) -> list[Path]:
    """Return on-disk run_*_fixtures.py paths via shared test harness discovery."""
    root = root or repo_root()
    test_dir = root / "scripts" / "test"
    sys.path.insert(0, str(test_dir))
    from _runner import discover_suites as _discover

    return [p for p in _discover(test_dir) if p.suffix == ".py"]


def load_registry(root: Path | None = None) -> dict[str, Any]:
    root = root or repo_root()
    path = root / REGISTRY_REL
    if not path.is_file():
        raise FileNotFoundError(f"suite registry missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "suites" not in data:
        raise ValueError("invalid suite registry shape")
    return data


def _entries_for_lane(registry: dict[str, Any], lane: str) -> list[dict[str, Any]]:
    suites = registry.get("suites") or []
    matched = [entry for entry in suites if lane in (entry.get("lanes") or [])]
    if lane == "verify":
        return sorted(
            matched,
            key=lambda row: (
                row.get("verifyOrder", 10_000),
                row.get("script", ""),
            ),
        )
    return sorted(matched, key=lambda row: row.get("script", ""))


def verify_bundle_entries(root: Path | None = None, *, active_only: bool = False) -> list[str]:
    """Basenames of scripts in verify lane, stable sort order."""
    registry = load_registry(root)
    rows = _entries_for_lane(registry, "verify")
    if active_only:
        rows = [row for row in rows if row.get("verifyActive", True)]
    return [Path(row["script"]).name for row in rows]


def manifest_entries(root: Path | None = None) -> list[dict[str, Any]]:
    """Registry rows projected to pr-test-plan manifest fixture shape."""
    registry = load_registry(root)
    out: list[dict[str, Any]] = []
    for row in _entries_for_lane(registry, "pr-ci"):
        item: dict[str, Any] = {
            "id": row["id"],
            "script": row["script"],
            "args": [],
            "classification": row.get("classification", "required"),
            "ciJobName": row["ciJobName"],
        }
        out.append(item)
    return out


def pr_ci_entries(root: Path | None = None) -> list[dict[str, Any]]:
    """Alias for manifest_entries — pr-ci lane projection."""
    return manifest_entries(root)


def doc_lane_entries(root: Path | None = None) -> list[str]:
    """Script paths listed in doc lane."""
    registry = load_registry(root)
    return [row["script"] for row in _entries_for_lane(registry, "doc")]


def registry_script_set(registry: dict[str, Any]) -> set[str]:
    return {row["script"] for row in registry.get("suites") or []}


def disk_script_set(root: Path) -> set[str]:
    return {f"scripts/test/{p.name}" for p in discover_suites(root)}


def validate_lanes(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for row in registry.get("suites") or []:
        lanes = row.get("lanes") or []
        if not lanes:
            errors.append(f"{row.get('id')}: empty lanes")
            continue
        invalid = set(lanes) - VALID_LANES
        if invalid:
            errors.append(f"{row.get('id')}: invalid lanes {sorted(invalid)}")
        if "pr-ci" in lanes:
            if not row.get("classification"):
                errors.append(f"{row.get('id')}: pr-ci missing classification")
            if not row.get("ciJobName"):
                errors.append(f"{row.get('id')}: pr-ci missing ciJobName")
    return errors
