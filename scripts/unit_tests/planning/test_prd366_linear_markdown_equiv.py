"""PRD 366 Linear markdown equivalence — phase 1 classification/witness + phase 11 stance."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import authoring_guard
from planning.backends import issues_helpers as ih
from planning.backends.issues_helpers import reconstruct_bodies_equivalent
from planning_canonical import IssueSnapshot, canonical_hash
from planning_linear_canonical import (
    LINEAR_PUBLIC_MARKDOWN_EQUIVALENCE_STRATEGY,
    LINEAR_PUBLIC_MARKDOWN_PARSER_GRADE_AST_COMPARE,
    LINEAR_PUBLIC_MARKDOWN_R6_REWRITES,
    PRD366_ADDED_R6_REWRITE_FAMILIES,
    PRD366_REDACTED_FAMILY_REGISTRY_BINDINGS,
    _autolink_comparison_url,
    _autolink_identity,
    _implicit_autolink_policy,
    _looks_like_domain,
    linear_public_markdown_equivalence_strategy,
    original_bytes_hash_body,
    prd366_leftover_rewrite_families_registered,
    _r6_identity_tokens,
    linear_public_markdown_equivalent,
    linear_public_markdown_r6_form,
    prove_r7_acceptance_criteria_underscore_full_line,
)
from prd366_fixture_lib import (
    PRD366_ALLOWED_REQUIREMENT_IDS,
    PRD366_LEFTOVER_REGION_COUNT,
    PRD366_PRIVATE_PILOT_DIR,
    WitnessUnavailableError,
    family_map_covers_redacted_pairs,
    load_committed_family_map,
    load_json,
    private_pilot_tree_gitignored,
    require_witness_source,
    resolve_witness_source,
    validate_family_map,
    validate_family_map_against_diagnosis,
    validate_redacted_families,
)

FIXTURE_LINEAR = scripts / "test" / "fixtures" / "linear"
FAMILY_MAP = FIXTURE_LINEAR / "markdown-repro-2.22.0-family-map.json"
REDACTED_FAMILIES = FIXTURE_LINEAR / "prd366-redacted-comparison-families.json"
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

class TestPrd366Phase2VersionSectionTokenDomainRewrite:
    @staticmethod
    def _r4_pairs() -> list[dict[str, str]]:
        data = load_json(REDACTED_FAMILIES)
        return [
            row
            for row in data["pairs"]
            if row.get("family") == "version-section-token-domain-rewrite"
        ]

    def test_redacted_fixture_contract(self) -> None:
        data = load_json(REDACTED_FAMILIES)
        assert validate_redacted_families(data) == []
        family_map = load_json(FAMILY_MAP)
        assert family_map_covers_redacted_pairs(family_map, data) == []

    def test_version_and_section_tokens_are_not_domains(self) -> None:
        assert not _looks_like_domain("v0.3")
        assert not _looks_like_domain("v1.2.3")
        assert not _looks_like_domain("§5.3")
        assert not _looks_like_domain("5.3")
        assert _looks_like_domain("docs.example.test")
        assert _looks_like_domain("example.com")

    def test_r6_form_preserves_version_and_section_tokens(self) -> None:
        text = "Ship v0.3 per §5.3; see docs.example.test/path.\n"
        normalized = linear_public_markdown_r6_form(text)
        assert "v0.3" in normalized
        assert "§5.3" in normalized
        assert "https://docs.example.test/path" in normalized
        assert "https://v0.3" not in normalized

    def test_redacted_r4_pairs_pass_equivalent(self) -> None:
        for row in self._r4_pairs():
            assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]), row[
                "id"
            ]

    def test_r4_mutants_fail_equivalence(self) -> None:
        data = load_json(REDACTED_FAMILIES)
        for row in data["mutants"]:
            if row.get("family") != "version-section-token-domain-rewrite":
                continue
            if row.get("expectEquivalent") is False:
                assert (
                    linear_public_markdown_equivalent(row["submitted"], row["refetched"]) is False
                )


class TestPrd366Phase3ImplicitAutolinkUnification:
    @staticmethod
    def _r5_pairs() -> list[dict[str, str]]:
        data = load_json(REDACTED_FAMILIES)
        return [
            row
            for row in data["pairs"]
            if row.get("family") == "implicit-domain-http-autolink"
        ]

    def test_implicit_autolink_policy_unifies_identity_and_comparison(self) -> None:
        bare = "docs.example.test/path"
        angle_http = "http://docs.example.test/path"
        identity, comparison = _implicit_autolink_policy(bare)
        assert identity == _autolink_identity(bare)
        assert comparison == _autolink_comparison_url(angle_http)
        assert identity == _autolink_identity(angle_http)
        assert comparison == _autolink_comparison_url(bare)
        assert identity.startswith("schemeless:")
        assert comparison == "https://docs.example.test/path"

    def test_redacted_r5_pairs_pass_equivalent(self) -> None:
        for row in self._r5_pairs():
            assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]), row[
                "id"
            ]

    def test_schemeless_host_matches_http_angle_autolink(self) -> None:
        left = "See docs.example.test/path today.\n"
        right = "See <http://docs.example.test/path> today.\n"
        assert linear_public_markdown_equivalent(left, right)

    def test_explicit_url_mutants_fail_identity_and_form(self) -> None:
        data = load_json(REDACTED_FAMILIES)
        for row in data["mutants"]:
            if row.get("family") != "implicit-domain-http-autolink":
                continue
            if row.get("expectEquivalent") is False:
                submitted, refetched = row["submitted"], row["refetched"]
                assert linear_public_markdown_equivalent(submitted, refetched) is False
                assert _r6_identity_tokens(submitted) != _r6_identity_tokens(refetched)
                if row["id"] == "r5-destination-changed-explicit":
                    assert (
                        linear_public_markdown_r6_form(submitted)
                        != linear_public_markdown_r6_form(refetched)
                    )


class TestPrd366Phase4MixedBoldInlineCodeBothSidesUnwrap:
    @staticmethod
    def _r6_pairs() -> list[dict[str, str]]:
        data = load_json(REDACTED_FAMILIES)
        return [
            row
            for row in data["pairs"]
            if row.get("family") == "mixed-bold-inline-code-both-sides-unwrap"
        ]

    def test_named_family_registered(self) -> None:
        assert "mixed-bold-inline-code-both-sides-unwrap" in LINEAR_PUBLIC_MARKDOWN_R6_REWRITES
        assert "bold-around-inline-code" in LINEAR_PUBLIC_MARKDOWN_R6_REWRITES

    def test_redacted_r6_pairs_pass_equivalent(self) -> None:
        for row in self._r6_pairs():
            assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]), row[
                "id"
            ]

    def test_half_unwrap_fails_without_mixed_phrase_family(self) -> None:
        import planning_linear_canonical as plc

        left = "Call **`fn-a`** and **`fn-b`** in one phrase.\n"
        right = "Call **`fn-a`** and `fn-b` in one phrase.\n"
        assert left != right
        orig = plc._normalize_mixed_bold_inline_code_both_sides_unwrap
        plc._normalize_mixed_bold_inline_code_both_sides_unwrap = lambda text: text
        try:
            assert linear_public_markdown_r6_form(left) != linear_public_markdown_r6_form(right)
        finally:
            plc._normalize_mixed_bold_inline_code_both_sides_unwrap = orig
        assert linear_public_markdown_equivalent(left, right)

    def test_code_content_mutant_fails(self) -> None:
        left = "Call **`fn-a`** and **`fn-b`** in one phrase.\n"
        right = "Call **`fn-a`** and **`fn-other`** in one phrase.\n"
        assert linear_public_markdown_equivalent(left, right) is False

    def test_single_span_still_uses_bold_around_inline_code(self) -> None:
        left = "Keep **`token`** here.\n"
        right = "Keep `token` here.\n"
        assert linear_public_markdown_equivalent(left, right)


class TestPrd366Phase5FullAcceptanceCriteriaUnderscoreLine:
    @staticmethod
    def _r7_pairs() -> list[dict[str, str]]:
        data = load_json(REDACTED_FAMILIES)
        return [
            row
            for row in data["pairs"]
            if row.get("family") == "acceptance-criteria-underscore-full-line"
        ]

    def test_named_family_registered(self) -> None:
        assert "acceptance-criteria-underscore-full-line" in LINEAR_PUBLIC_MARKDOWN_R6_REWRITES
        assert "post-code-underscore-unescape" in LINEAR_PUBLIC_MARKDOWN_R6_REWRITES

    def test_r7_prove_full_line_not_excerpt(self) -> None:
        out = prove_r7_acceptance_criteria_underscore_full_line()
        assert out["ok"] is True
        assert out["fullLineEquivalent"] is True
        assert out["excerptNotProof"] is True

    def test_redacted_r7_pairs_pass_equivalent(self) -> None:
        for row in self._r7_pairs():
            assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]), row[
                "id"
            ]


class _Ps:
    PUT_INCOMPLETE_LABEL = "sw-put-incomplete"

    @staticmethod
    def strip_markers_and_edges(text: str) -> str:
        return text

    @staticmethod
    def reassemble_body(body: str, comments: list[object], *, linear_bind: bool = False) -> str:
        return body

    @staticmethod
    def has_raw_yaml_frontmatter(body: str) -> bool:
        return False

    @staticmethod
    def operator_body_from_canonical(body: str) -> str:
        return body

    @staticmethod
    def fail(message: str, **_kwargs: object) -> None:
        raise AssertionError(message)


class TestPrd366Phase6DualGateNamedFamilyRegistryAndOriginalBytesHash:
    def test_reconstruct_requires_both_identity_and_comparison_form(self) -> None:
        left = "## R1 Title\n\nBody.\n"
        right = "R1 Title\n\nBody.\n"
        assert _r6_identity_tokens(left) == _r6_identity_tokens(right)
        assert linear_public_markdown_equivalent(left, right) is False
        assert (
            reconstruct_bodies_equivalent(left, right, issues_provider="linear", ps_mod=_Ps)
            is False
        )

    def test_freeze_refuse_uses_shared_reconstruct_predicate(self) -> None:
        from check_frozen_lib import refuse_truncated_linear_reconstruct

        record = type(
            "Rec",
            (),
            {
                "id": "issue-1",
                "labels": [],
                "body": "R1 Title\n\nBody.\n",
                "comments": [],
                "comments_complete": True,
            },
        )()
        pre_chunk = "## R1 Title\n\nBody.\n"
        with pytest.raises(AssertionError, match="reconstruct"):
            refuse_truncated_linear_reconstruct(
                issues_provider="linear",
                record=record,
                ps_mod=_Ps,
                pre_chunk_body=pre_chunk,
            )

    def test_leftover_redacted_families_bind_to_named_registry(self) -> None:
        data = load_json(REDACTED_FAMILIES)
        fixture_families = frozenset(
            row["family"] for row in data["pairs"] if isinstance(row.get("family"), str)
        )
        assert fixture_families == frozenset(PRD366_REDACTED_FAMILY_REGISTRY_BINDINGS)
        assert prd366_leftover_rewrite_families_registered(fixture_families) == []
        assert PRD366_ADDED_R6_REWRITE_FAMILIES <= LINEAR_PUBLIC_MARKDOWN_R6_REWRITES

    def test_freeze_hash_stays_on_original_bytes_not_r6_form(self) -> None:
        hyphen = "- **R1** Facade owns Linear split."
        asterisk = "* **R1** Facade owns Linear split."
        assert linear_public_markdown_equivalent(hyphen, asterisk)
        snap_h = IssueSnapshot(title="t", body=hyphen, state="open", labels=[], comments=[])
        snap_a = IssueSnapshot(title="t", body=asterisk, state="open", labels=[], comments=[])
        assert canonical_hash(snap_h) != canonical_hash(snap_a)
        assert original_bytes_hash_body(hyphen) == hyphen.strip("\n")
        assert (
            original_bytes_hash_body(hyphen) != linear_public_markdown_r6_form(hyphen)
            or hyphen == asterisk
        )


class TestPrd366Phase7Preserve363GreensAndIdentityDroppingNegatives:
    """R3 ordered-list regression plus R9 identity-dropping negatives."""

    def test_prd363_ordered_list_one_space_padding_still_green(self) -> None:
        left = "1. Alpha step\n2. Beta step\n"
        right = " 1. Alpha step\n 2. Beta step\n"
        assert linear_public_markdown_equivalent(left, right)

    def test_changed_prose_fails_equivalent(self) -> None:
        left = "Ship the leftover families today.\n"
        right = "Ship the leftover families tomorrow.\n"
        assert linear_public_markdown_equivalent(left, right) is False

    def test_changed_code_fails_equivalent(self) -> None:
        left = "Call **`fn-a`** and **`fn-b`** in one phrase.\n"
        right = "Call **`fn-a`** and **`fn-other`** in one phrase.\n"
        assert linear_public_markdown_equivalent(left, right) is False

    def test_changed_explicit_url_fails_equivalent(self) -> None:
        data = load_json(REDACTED_FAMILIES)
        row = next(m for m in data["mutants"] if m["id"] == "r5-destination-changed-explicit")
        assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]) is False
        assert _r6_identity_tokens(row["submitted"]) != _r6_identity_tokens(row["refetched"])

    def test_changed_nesting_fails_equivalent(self) -> None:
        left = "1. Parent\n   2. Child\n"
        right = "1. Parent\n  2. Child\n"
        assert linear_public_markdown_equivalent(left, right) is False

    def test_missing_content_fails_equivalent(self) -> None:
        left = "## Title\n\nFull acceptance criteria line with context.\n"
        right = "## Title\n\n"
        assert linear_public_markdown_equivalent(left, right) is False


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
        base = os.environ.get("SW_INTEGRATION_BRANCH", "feat/linear-markdown-equiv-222")
        proc = subprocess.run(
            ["git", "diff", f"{base}...HEAD", "--name-only"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            pytest.skip(f"{base}...HEAD diff unavailable in this worktree")
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
