"""PRD 363 — Linear Public Markdown 2.21.0 equivalence (phase-scoped growth)."""

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

from planning_linear_canonical import (
    _split_positions,
    chunk_body_for_linear,
    linear_public_markdown_equivalent,
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
