"""PRD 363 — Linear Public Markdown 2.21.0 equivalence (phase-scoped growth)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from planning.backends.issues_helpers import reconstruct_bodies_equivalent
from planning_canonical import BODY_SIZE_LIMIT, CommentRecord, IssueSnapshot, canonical_hash, chunk_body_if_needed
from planning_linear_canonical import (
    linear_public_markdown_equivalent,
    linear_public_markdown_r6_form,
    original_bytes_hash_body,
)
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


class TestPrd363Phase3TopLevelOrderedOneSpacePad:
    @staticmethod
    def _r3_pairs() -> list[dict[str, str]]:
        data = load_json(REDACTED_FAMILIES)
        return [
            row
            for row in data["pairs"]
            if row.get("family") == "top-level-ordered-one-space-pad"
        ]

    def test_redacted_r3_pairs_pass_equivalent(self) -> None:
        for row in self._r3_pairs():
            assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]), row[
                "id"
            ]

    def test_one_leading_space_on_top_level_ordered_passes(self) -> None:
        left = "1. Alpha step\n2. Beta step\n"
        right = " 1. Alpha step\n 2. Beta step\n"
        assert linear_public_markdown_equivalent(left, right)

    def test_nested_indent_change_fails(self) -> None:
        left = "1. Parent\n   2. Child\n"
        right = "1. Parent\n  2. Child\n"
        assert linear_public_markdown_equivalent(left, right) is False

    def test_two_space_pad_mutant_fails(self) -> None:
        data = load_json(REDACTED_FAMILIES)
        row = next(row for row in data["mutants"] if row["id"] == "r3-two-space-pad")
        assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]) is False

    def test_changed_marker_mutant_fails(self) -> None:
        data = load_json(REDACTED_FAMILIES)
        row = next(row for row in data["mutants"] if row["id"] == "r3-changed-marker")
        assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]) is False


class TestPrd363Phase4PostCodeUnderscoreUnescape:
    @staticmethod
    def _r4_pairs() -> list[dict[str, str]]:
        data = load_json(REDACTED_FAMILIES)
        return [
            row
            for row in data["pairs"]
            if row.get("family") == "post-code-underscore-unescape"
        ]

    def test_redacted_r4_pairs_pass_equivalent(self) -> None:
        for row in self._r4_pairs():
            assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]), row[
                "id"
            ]

    def test_identity_preserving_post_code_escape_passes(self) -> None:
        left = "After `token`_suffix here.\n"
        right = "After `token`\\_suffix here.\n"
        assert linear_public_markdown_equivalent(left, right)

    def test_underscore_inside_code_span_unchanged(self) -> None:
        left = "Use `token_suffix` today.\n"
        right = "Use `token\\_suffix` today.\n"
        assert linear_public_markdown_equivalent(left, right) is False

    def test_underscore_inside_emphasis_not_post_code(self) -> None:
        left = "_wrap `code` tail_\n"
        right = "_wrap `code` tail\\_\n"
        assert linear_public_markdown_equivalent(left, right) is False

    def test_emphasis_inventing_mutant_fails(self) -> None:
        data = load_json(REDACTED_FAMILIES)
        row = next(
            row for row in data["mutants"] if row["id"] == "r4-underscore-starts-emphasis"
        )
        assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]) is False


class TestPrd363Phase5ImplicitDomainAutolinkIdentityPolicy:
    @staticmethod
    def _r5_pairs() -> list[dict[str, str]]:
        data = load_json(REDACTED_FAMILIES)
        return [
            row
            for row in data["pairs"]
            if row.get("family") == "implicit-domain-http-autolink"
        ]

    def test_redacted_r5_pairs_pass_equivalent(self) -> None:
        for row in self._r5_pairs():
            assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]), row[
                "id"
            ]

    def test_schemeless_domain_matches_http_angle_autolink(self) -> None:
        left = "See docs.example.test/path today.\n"
        right = "See <http://docs.example.test/path> today.\n"
        assert linear_public_markdown_equivalent(left, right)

    def test_http_vs_https_autolink_mutant_fails(self) -> None:
        data = load_json(REDACTED_FAMILIES)
        row = next(row for row in data["mutants"] if row["id"] == "r5-http-vs-https")
        assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]) is False

    def test_javascript_scheme_mutant_fails(self) -> None:
        data = load_json(REDACTED_FAMILIES)
        row = next(row for row in data["mutants"] if row["id"] == "r5-javascript-scheme")
        assert linear_public_markdown_equivalent(row["submitted"], row["refetched"]) is False


class _Ps:
    @staticmethod
    def strip_markers_and_edges(text: str) -> str:
        return text

    @staticmethod
    def fail(message: str, **_kwargs: object) -> None:
        raise AssertionError(message)


class TestPrd363Phase7NegativesFreezeHashAndProviderNoOps:
    def test_identity_token_match_without_comparison_form_fails(self) -> None:
        left = "## R1 Title\n\nBody.\n"
        right = "R1 Title\n\nBody.\n"
        assert linear_public_markdown_equivalent(left, right) is False
        assert (
            reconstruct_bodies_equivalent(left, right, issues_provider="linear", ps_mod=_Ps)
            is False
        )

    def test_rewrite_only_equivalent_bodies_keep_distinct_freeze_hash(self) -> None:
        hyphen = "- **R1** Facade owns Linear split."
        asterisk = "* **R1** Facade owns Linear split."
        assert linear_public_markdown_equivalent(hyphen, asterisk)
        snap_h = IssueSnapshot(title="t", body=hyphen, state="open", labels=[], comments=[])
        snap_a = IssueSnapshot(title="t", body=asterisk, state="open", labels=[], comments=[])
        assert canonical_hash(snap_h) != canonical_hash(snap_a)
        assert original_bytes_hash_body(hyphen) != linear_public_markdown_r6_form(hyphen) or hyphen == asterisk

    def test_github_chunk_output_unchanged_vs_default(self) -> None:
        body = "Z" * (BODY_SIZE_LIMIT + 64)
        head_default, comments_default = chunk_body_if_needed(body, [], provider=None)
        head_github, comments_github = chunk_body_if_needed(body, [], provider="github-issues")
        assert len(comments_github) == len(comments_default) == 1
        assert [c.body for c in comments_github] == [c.body for c in comments_default]

    def test_non_linear_providers_do_not_invoke_linear_chunker(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        body = "Z" * (BODY_SIZE_LIMIT + 64)

        def _boom(*_args: object, **_kwargs: object) -> tuple[str, list[CommentRecord]]:
            raise AssertionError("linear chunker must not run for non-linear providers")

        monkeypatch.setattr(
            "planning_linear_canonical.chunk_body_for_linear",
            _boom,
        )
        chunk_body_if_needed(body, [], provider="github-issues")
        chunk_body_if_needed(body, [], provider="notion")

    def test_jira_routes_to_jira_chunker_not_linear(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        jira_calls: list[str] = []

        def _boom(*_args: object, **_kwargs: object) -> tuple[str, list[CommentRecord]]:
            raise AssertionError("linear chunker must not run for Jira")

        def _jira_chunk(body: str, comments: list[CommentRecord]) -> tuple[str, list[CommentRecord]]:
            jira_calls.append("jira")
            return body, comments

        monkeypatch.setattr(
            "planning_linear_canonical.chunk_body_for_linear",
            _boom,
        )
        monkeypatch.setattr(
            "planning_jira_canonical.chunk_body_for_jira_cloud",
            _jira_chunk,
        )
        chunk_body_if_needed("Jira-sized body.\n", [], provider="jira")
        assert jira_calls == ["jira"]
