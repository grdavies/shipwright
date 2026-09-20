"""PRD 366 Linear markdown equivalence — phase 1 classification and witness policy."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from prd366_fixture_lib import (
    PRD366_ALLOWED_REQUIREMENT_IDS,
    PRD366_LEFTOVER_REGION_COUNT,
    PRD366_PRIVATE_PILOT_DIR,
    WitnessUnavailableError,
    load_committed_family_map,
    load_json,
    private_pilot_tree_gitignored,
    require_witness_source,
    resolve_witness_source,
    validate_family_map,
    validate_family_map_against_diagnosis,
)

FIXTURE_LINEAR = scripts / "test" / "fixtures" / "linear"
FAMILY_MAP = FIXTURE_LINEAR / "markdown-repro-2.22.0-family-map.json"
REPO_ROOT = Path(__file__).resolve().parents[3]


class TestPrd366Phase1FamilyMap:
    def test_seven_leftover_rows_map_to_r4_through_r7(self) -> None:
        data = load_json(FAMILY_MAP)
        errors = validate_family_map(data)
        assert errors == []
        assert len(data["leftovers"]) == PRD366_LEFTOVER_REGION_COUNT
        reqs = {row["requirementId"] for row in data["leftovers"]}
        assert reqs == PRD366_ALLOWED_REQUIREMENT_IDS

    def test_unclassified_leftover_fails_validation(self) -> None:
        data = load_json(FAMILY_MAP)
        broken = dict(data)
        leftovers = [dict(row) for row in data["leftovers"]]
        leftovers[0] = dict(leftovers[0])
        leftovers[0]["requirementId"] = "R99"
        broken["leftovers"] = leftovers
        errors = validate_family_map(broken)
        assert any("requirementId" in err for err in errors)

    def test_diagnosis_alignment_requires_every_region_classified(self) -> None:
        family_map = load_json(FAMILY_MAP)
        diagnosis = {
            "leftovers": [
                {"regionId": row["regionId"]} for row in family_map["leftovers"]
            ]
        }
        assert validate_family_map_against_diagnosis(family_map, diagnosis) == []
        missing = dict(family_map)
        missing["leftovers"] = family_map["leftovers"][:-1]
        errors = validate_family_map_against_diagnosis(missing, diagnosis)
        assert any("unclassified" in err for err in errors)


class TestPrd366Phase1WitnessPolicy:
    def test_private_pilot_tree_stays_gitignored(self) -> None:
        assert not PRD366_PRIVATE_PILOT_DIR.exists() or private_pilot_tree_gitignored(
            REPO_ROOT
        )

    def test_witness_halts_when_private_and_live_unavailable(self) -> None:
        if PRD366_PRIVATE_PILOT_DIR.exists():
            pytest.skip("private pilot tree present on this machine")
        with pytest.raises(WitnessUnavailableError):
            resolve_witness_source(REPO_ROOT)

    def test_committed_family_map_loads(self) -> None:
        data = load_committed_family_map(REPO_ROOT)
        assert validate_family_map(data) == []

    def test_require_witness_matches_resolve(self) -> None:
        try:
            assert require_witness_source(REPO_ROOT).kind == resolve_witness_source(
                REPO_ROOT
            ).kind
        except WitnessUnavailableError:
            pytest.skip("no witness source in this environment")
