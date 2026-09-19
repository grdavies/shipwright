"""PRD 363 Linear markdown equivalence regression suite."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from planning.backends.issues_helpers import reconstruct_bodies_equivalent
from planning_canonical import BODY_SIZE_LIMIT, CommentRecord, IssueSnapshot, canonical_hash, chunk_body_if_needed
from planning_linear_canonical import (
    LINEAR_PUBLIC_MARKDOWN_R6_REWRITES,
    _split_positions,
    chunk_body_for_linear,
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
SPLIT_ORACLE = FIXTURE_LINEAR / "prd19-sized-split-oracle.json"
REPO_ROOT = Path(__file__).resolve().parents[3]
UNIQUE = "SPAN-TOKEN-NEVER-IN-ERROR-prd363-split"


def _positions_digest(positions: list[int]) -> str:
    return hashlib.sha256("\n".join(str(p) for p in positions).encode("utf-8")).hexdigest()


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


class TestPrd363Phase6LegalCutEnumeration:
    def test_empty_body_split_positions(self) -> None:
        assert _split_positions("") == [0]

    def test_one_line_body_split_positions(self) -> None:
        text = "hello world\n"
        assert 0 in _split_positions(text)
        assert len(text) in _split_positions(text)

    def test_no_interior_cut_inside_inline_code(self) -> None:
        text = f"before `{UNIQUE} interior` after\n"
        start = text.index("`")
        end = text.rindex("`") + 1
        for pos in _split_positions(text):
            assert not (start < pos < end)

    def test_prd19_sized_oracle_position_digest(self) -> None:
        oracle = load_json(SPLIT_ORACLE)
        body = oracle["syntheticMarkdown"]
        positions = _split_positions(body)
        assert len(positions) == oracle["positionCount"]
        assert _positions_digest(positions) == oracle["positionsSha256"]
        assert oracle["utf8ByteLength"] >= 190_000

    def test_prd19_sized_enumeration_subsecond(self) -> None:
        oracle = load_json(SPLIT_ORACLE)
        body = oracle["syntheticMarkdown"]
        start = time.perf_counter()
        _split_positions(body)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0, f"_split_positions took {elapsed:.2f}s"

    def test_60kb_long_line_enumeration_subsecond(self) -> None:
        long_line = "x" * 60_000 + "\n"
        start = time.perf_counter()
        positions = _split_positions(long_line)
        elapsed = time.perf_counter() - start
        assert elapsed < 1.0
        assert len(positions) > 2

    def test_chunker_uses_same_legal_cut_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import planning_linear_canonical as llc

        oracle = load_json(SPLIT_ORACLE)
        body = oracle["syntheticMarkdown"]
        monkeypatch.setattr(llc, "_LINEAR_CHUNK_LIMIT", 8_000)

        original = llc._split_positions
        seen: list[list[int]] = []

        def _recorder(text: str) -> list[int]:
            cuts = original(text)
            seen.append(cuts)
            return cuts

        monkeypatch.setattr(llc, "_split_positions", _recorder)
        chunk_body_for_linear(body[:50_000], [])
        assert seen, "chunker should call _split_positions"
        assert seen[0] == original(body[:50_000])


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


class TestPrd363Phase8DocsEmit:
    @staticmethod
    def _families_from_canonical_serialization_doc() -> set[str]:
        text = (REPO_ROOT / "core/sw-reference/canonical-serialization.md").read_text(
            encoding="utf-8"
        )
        anchor = "rewrite families as equal:"
        start = text.index(anchor) + len(anchor)
        end = text.index("\n\nA new Standard unit", start)
        block = text[start:end]
        families: set[str] = set()
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("- `") and "`" in stripped[3:]:
                families.add(stripped[3 : stripped.index("`", 3)])
        return families

    def test_canonical_serialization_emits_full_r6_rewrite_list(self) -> None:
        doc_families = self._families_from_canonical_serialization_doc()
        assert doc_families == set(LINEAR_PUBLIC_MARKDOWN_R6_REWRITES)

    def test_linear_md_map13_contract_matches_code(self) -> None:
        text = (REPO_ROOT / "core/providers/issues/linear.md").read_text(encoding="utf-8")
        assert "Map-13 contract" in text
        for family in sorted(LINEAR_PUBLIC_MARKDOWN_R6_REWRITES):
            assert f"`{family}`" in text

    def test_dist_linear_md_matches_core_emit(self) -> None:
        core = (REPO_ROOT / "core/providers/issues/linear.md").read_text(encoding="utf-8")
        for platform in ("cursor", "claude-code"):
            dist_path = REPO_ROOT / "dist" / platform / "providers/issues/linear.md"
            assert dist_path.is_file(), f"missing dist emit: {dist_path}"
            assert dist_path.read_text(encoding="utf-8") == core


class TestPrd363Phase8Prd359ItalicsNonRegression:
    """PRD 359 R9 — italics and single-span bold-around-inline-code stay equivalent."""

    def test_underscore_versus_asterisk_italics_equivalent(self) -> None:
        left = "Note _same emphasis_ text.\n"
        right = "Note *same emphasis* text.\n"
        assert linear_public_markdown_equivalent(left, right)

    def test_single_span_bold_around_inline_code_equivalent(self) -> None:
        left = "Keep **`token`** here.\n"
        right = "Keep `token` here.\n"
        assert linear_public_markdown_equivalent(left, right)
