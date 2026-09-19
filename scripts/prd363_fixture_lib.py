#!/usr/bin/env python3
"""PRD 363 phase-1 fixture contracts — leftover classification and redacted families."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PRD363_ALLOWED_REQUIREMENT_IDS = frozenset({"R2", "R3", "R4", "R5"})
PRD363_LEFTOVER_REGION_COUNT = 7
PRD363_PRIVATE_PILOT_DIR = Path(
    ".shipwright/migrations/linear-20260914/pilot-2.21.0"
)
PRD363_PRIVATE_DIAGNOSIS = PRD363_PRIVATE_PILOT_DIR / "pilot-diagnosis-2.21.0.json"

FORBIDDEN_REDACTED_SUBSTRINGS = (
    "Authorization:",
    "Bearer ",
    "upsertDiscount",
    "listDiscounts",
    "Tierforge.dev",
    "linear.app/acme",
    "RED-1",
    "sw:token",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_family_map(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("version") != "2.21.0":
        errors.append("family-map version must be 2.21.0")
    leftovers = data.get("leftovers")
    if not isinstance(leftovers, list):
        errors.append("family-map leftovers must be a list")
        return errors
    if len(leftovers) != PRD363_LEFTOVER_REGION_COUNT:
        errors.append(
            f"family-map expects {PRD363_LEFTOVER_REGION_COUNT} leftover rows, got {len(leftovers)}"
        )
    seen_ids: set[str] = set()
    for idx, row in enumerate(leftovers):
        if not isinstance(row, dict):
            errors.append(f"leftovers[{idx}] must be an object")
            continue
        region_id = row.get("regionId")
        if not isinstance(region_id, str) or not region_id:
            errors.append(f"leftovers[{idx}] missing regionId")
        elif region_id in seen_ids:
            errors.append(f"duplicate regionId {region_id}")
        else:
            seen_ids.add(region_id)
        req = row.get("requirementId")
        if req not in PRD363_ALLOWED_REQUIREMENT_IDS:
            errors.append(
                f"leftovers[{idx}] requirementId {req!r} not in {sorted(PRD363_ALLOWED_REQUIREMENT_IDS)}"
            )
        fixture_ref = row.get("redactedFixtureId")
        if not isinstance(fixture_ref, str) or not fixture_ref:
            errors.append(f"leftovers[{idx}] missing redactedFixtureId")
        gap = row.get("gapUnitId")
        if not isinstance(gap, str) or not gap.startswith("gap-48"):
            errors.append(f"leftovers[{idx}] gapUnitId must reference gap-482..486 absorb set")
    return errors


def validate_redacted_families(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("version") != "2.21.0-redacted":
        errors.append("redacted families version must be 2.21.0-redacted")
    pairs = data.get("pairs")
    mutants = data.get("mutants")
    if not isinstance(pairs, list) or not pairs:
        errors.append("redacted families pairs must be a non-empty list")
    if not isinstance(mutants, list) or not mutants:
        errors.append("redacted families mutants must be a non-empty list")
    blob = json.dumps(data, ensure_ascii=False)
    for needle in FORBIDDEN_REDACTED_SUBSTRINGS:
        if needle in blob:
            errors.append(f"redacted fixture must not contain private corpus marker: {needle}")
    for label, rows in (("pairs", pairs), ("mutants", mutants)):
        if not isinstance(rows, list):
            continue
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                errors.append(f"{label}[{idx}] must be an object")
                continue
            for key in ("id", "family", "requirementId", "submitted", "refetched"):
                if not isinstance(row.get(key), str) or not row.get(key):
                    errors.append(f"{label}[{idx}] missing {key}")
            if row.get("requirementId") not in PRD363_ALLOWED_REQUIREMENT_IDS:
                errors.append(f"{label}[{idx}] invalid requirementId")
    return errors


def family_map_covers_redacted_pairs(
    family_map: dict[str, Any], redacted: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    leftovers = family_map.get("leftovers") or []
    ref_ids = {row.get("redactedFixtureId") for row in leftovers if isinstance(row, dict)}
    pair_ids = {
        row.get("id")
        for row in (redacted.get("pairs") or [])
        if isinstance(row, dict)
    }
    missing = sorted(pair_ids - ref_ids)
    extra = sorted(ref_ids - pair_ids)
    if missing:
        errors.append(f"family-map missing redactedFixtureId for pair ids: {missing}")
    if extra:
        errors.append(f"family-map references unknown redactedFixtureId: {extra}")
    return errors


def private_pilot_tree_gitignored(repo_root: Path) -> bool:
    """True when the private pilot directory is not tracked (expected for CI)."""
    from subprocess import run

    rel = PRD363_PRIVATE_PILOT_DIR.as_posix()
    proc = run(
        ["git", "check-ignore", "-q", rel],
        cwd=repo_root,
        capture_output=True,
    )
    return proc.returncode == 0
