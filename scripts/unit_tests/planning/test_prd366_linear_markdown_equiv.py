"""PRD 366 Linear markdown equivalence — phase 1 classification/witness + phase 11 stance."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import authoring_guard
from planning.backends import issues_helpers as ih
from planning_linear_canonical import (
    LINEAR_PUBLIC_MARKDOWN_EQUIVALENCE_STRATEGY,
    LINEAR_PUBLIC_MARKDOWN_PARSER_GRADE_AST_COMPARE,
    LINEAR_PUBLIC_MARKDOWN_R6_REWRITES,
    linear_public_markdown_equivalence_strategy,
)
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

class TestPrd366Phase11ExtendingUnitStance:
    def test_binding_stance_a_and_rejected_b_c_d(self) -> None:
        policy = authoring_guard.prd366_extending_unit_policy()
        assert policy["bindingStance"] == "A"
        assert set(policy["rejectedStances"]) == {"B", "C", "D"}
        assert policy["parentCompleteUnitId"] == "363-prd-linear-markdown-equiv-221"
        assert policy["extendingUnitId"] == "366-prd-linear-markdown-equiv-222"
        assert policy["method"] == "dual-gate-named-family-allowlist-continuation"

    def test_authoring_guard_surface_reexports_policy(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "authoring_guard_cli", scripts / "authoring-guard.py"
        )
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert mod.PRD366_BINDING_STANCE == "A"
        assert mod.reject_prd366_stance_substitute("B")["verdict"] == "fail"
        assert mod.reject_prd366_stance_substitute("A")["verdict"] == "pass"

    def test_stance_b_not_whole_unit_substitute(self) -> None:
        verdict = authoring_guard.reject_prd366_stance_substitute("B")
        assert verdict["verdict"] == "fail"
        assert "witness" in verdict["summary"].lower()

    def test_immutable_363_paths_classified(self) -> None:
        assert (
            authoring_guard.classify_prd366_mutation_path(
                "docs/prds/363-linear-markdown-equiv-221/363-prd-linear-markdown-equiv-221.md"
            )
            == "immutable-363"
        )
        assert (
            authoring_guard.classify_prd366_mutation_path(
                "scripts/unit_tests/planning/test_prd363_linear_markdown_equiv.py"
            )
            == "immutable-363"
        )

    def test_allowed_366_paths_classified(self) -> None:
        assert (
            authoring_guard.classify_prd366_mutation_path(
                "scripts/unit_tests/planning/test_prd366_linear_markdown_equiv.py"
            )
            == "allowed-366"
        )
        for family in LINEAR_PUBLIC_MARKDOWN_R6_REWRITES:
            assert family  # named-family members remain the rewrite registry

    def test_branch_diff_does_not_touch_frozen_363_artifacts(self) -> None:
        proc = subprocess.run(
            ["git", "diff", "main...HEAD", "--name-only"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            pytest.skip("main...HEAD diff unavailable in this worktree")
        changed = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
        for rel in changed:
            assert authoring_guard.classify_prd366_mutation_path(rel) != "immutable-363", rel

    def test_identity_only_reconstruct_ok_rejected_on_oversized_body(self) -> None:
        pad = "A" * ih.LINEAR_OVERSIZED_BODY_UTF8_BYTES
        left = f"# Title\n\n{pad}\n\n**R1** tail.\n"
        right = f"Title\n\n{pad}\n\nR1 tail.\n"
        assert ih.identity_only_linear_reconstruct_ok_rejected(left, right)
        assert not ih.reconstruct_bodies_equivalent(left, right, issues_provider="linear", ps_mod=object())

    def test_parser_grade_ast_compare_rejected(self) -> None:
        strategy = linear_public_markdown_equivalence_strategy()
        assert strategy["strategy"] == LINEAR_PUBLIC_MARKDOWN_EQUIVALENCE_STRATEGY
        assert strategy["parserGradeAstCompare"] == LINEAR_PUBLIC_MARKDOWN_PARSER_GRADE_AST_COMPARE
        assert strategy["parserGradeAstCompare"] == "rejected"
