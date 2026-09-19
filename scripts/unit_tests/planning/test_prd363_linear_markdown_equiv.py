"""PRD 363 — Linear Public Markdown 2.21.0 equivalence (phase-scoped growth)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from planning_linear_canonical import linear_public_markdown_equivalent
from prd363_fixture_lib import (
    PRD363_LEFTOVER_REGION_COUNT,
    PRD363_PRIVATE_PILOT_DIR,
    family_map_covers_redacted_pairs,
    load_json,
    private_pilot_tree_gitignored,
    validate_family_map,
    validate_redacted_families,
)

FIXTURE_LINEAR = scripts / "test" / "fixtures" / "linear"
FAMILY_MAP = FIXTURE_LINEAR / "markdown-repro-2.21.0-family-map.json"
REDACTED_FAMILIES = FIXTURE_LINEAR / "prd363-redacted-comparison-families.json"
REPO_ROOT = Path(__file__).resolve().parents[3]


class TestPrd363Phase1FamilyMap:
    def test_seven_leftover_rows_map_to_r2_through_r5(self) -> None:
        data = load_json(FAMILY_MAP)
        errors = validate_family_map(data)
        assert errors == []
        assert len(data["leftovers"]) == PRD363_LEFTOVER_REGION_COUNT
        reqs = {row["requirementId"] for row in data["leftovers"]}
        assert reqs == {"R2", "R3", "R4", "R5"}

    def test_unclassified_leftover_fails_validation(self) -> None:
        data = load_json(FAMILY_MAP)
        broken = dict(data)
        leftovers = [dict(row) for row in data["leftovers"]]
        leftovers[0] = dict(leftovers[0])
        leftovers[0]["requirementId"] = "R99"
        broken["leftovers"] = leftovers
        errors = validate_family_map(broken)
        assert any("requirementId" in err for err in errors)

    def test_family_map_links_redacted_fixture_ids(self) -> None:
        family_map = load_json(FAMILY_MAP)
        redacted = load_json(REDACTED_FAMILIES)
        errors = family_map_covers_redacted_pairs(family_map, redacted)
        assert errors == []


class TestPrd363Phase1RedactedFixtures:
    def test_redacted_fixture_contract_and_no_private_markers(self) -> None:
        data = load_json(REDACTED_FAMILIES)
        errors = validate_redacted_families(data)
        assert errors == []

    def test_mutants_fail_equivalent_today(self) -> None:
        data = load_json(REDACTED_FAMILIES)
        for row in data["mutants"]:
            if row.get("expectEquivalent") is False:
                assert linear_public_markdown_equivalent(
                    row["submitted"], row["refetched"]
                ) is False

    def test_private_pilot_tree_stays_gitignored(self) -> None:
        assert not PRD363_PRIVATE_PILOT_DIR.exists() or private_pilot_tree_gitignored(
            REPO_ROOT
        )


class TestPrd363Phase2MultiSpanBold:
    @staticmethod
    def _r2_pairs() -> list[dict[str, str]]:
        data = load_json(REDACTED_FAMILIES)
        return [
            row
            for row in data["pairs"]
            if row.get("family") == "multi-span-bold-around-inline-code"
        ]

    def test_redacted_r2_pairs_pass_equivalent(self) -> None:
        for row in self._r2_pairs():
            assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]), row[
                "id"
            ]

    def test_single_bold_run_multi_code_phrase_passes(self) -> None:
        left = "**Call `fn-a` and `fn-b` in one phrase.**\n"
        right = "Call **`fn-a`** and `fn-b` in one phrase.\n"
        assert linear_public_markdown_equivalent(left, right)

    def test_prd359_neighbor_rid_redistribution_mutant_fails(self) -> None:
        left = "See **`token`** and **R1**.\n"
        moved = "See `token` and **`R1`**.\n"
        assert linear_public_markdown_equivalent(left, moved) is False

    def test_redacted_r2_redistribution_mutant_fails(self) -> None:
        data = load_json(REDACTED_FAMILIES)
        row = next(
            row
            for row in data["mutants"]
            if row["id"] == "r2-neighbor-rid-redistributed"
        )
        assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]) is False
