"""PRD 358 R6 / AS7 — canonical Markdown equality without weakening."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from planning_canonical import (
    EXCLUDED_COMMENT_MARKERS,
    CommentRecord,
    IssueSnapshot,
    canonical_hash,
)
from planning_linear_canonical import (
    LINEAR_PUBLIC_MARKDOWN_R6_REWRITES,
    linear_public_markdown_equivalent,
    linear_public_markdown_r6_form,
    original_bytes_hash_body,
)

_RID_BODY = """# Requirements

- **R1** Facade owns Linear split.
- **R2** UUID head budget.

See `chunk_body_for_linear` and https://example.com/overflow.
"""


class TestPrd358CanonicalMarkdown:
    def test_empty_bodies_are_equivalent(self) -> None:
        """Z — empty body vs empty body is equivalent; empty vs content is not."""
        assert linear_public_markdown_equivalent("", "")
        assert not linear_public_markdown_equivalent("", "# Title\n")

    def test_hyphen_asterisk_list_marker_rewrite_passes(self) -> None:
        """O — Linear `*`/`-` list-marker rewrite is enumerated equivalence."""
        hyphen = "- **R1** Facade owns Linear split.\n- **R2** UUID head budget."
        asterisk = "* **R1** Facade owns Linear split.\n* **R2** UUID head budget."
        assert linear_public_markdown_equivalent(hyphen, asterisk)
        assert linear_public_markdown_r6_form(hyphen) == linear_public_markdown_r6_form(asterisk)

    def test_tables_and_autolinks_rewrite_pass(self) -> None:
        """M — table formatting and plain-domain autolinks are enumerated rewrites."""
        submitted = (
            "Col | Val\n"
            "--- | ---\n"
            "R3 | keep\n"
            "\n"
            "See example.com/overflow and `writeToken`.\n"
        )
        refetched = (
            "| Col | Val |\n"
            "| --- | --- |\n"
            "| R3 | keep |\n"
            "\n"
            "See [example.com/overflow](https://example.com/overflow) and `writeToken`.\n"
        )
        assert linear_public_markdown_equivalent(submitted, refetched)

    def test_bold_and_code_edge_rewrites_pass(self) -> None:
        """B — documented bold delimiter and code-span spacing rewrites pass."""
        submitted = "Keep __R6__ and `code span` plus ``nested``."
        refetched = "Keep **R6** and `code span` plus ``nested``."
        assert linear_public_markdown_equivalent(submitted, refetched)
        # Code content must stay; wrapping spaces inside a span are formatting only.
        spaced = "Keep **R6** and ` code span ` plus ``nested``."
        assert linear_public_markdown_equivalent(submitted, spaced)

    def test_only_enumerated_rewrites_are_equivalent(self) -> None:
        """I — heading or requirement-text drift is not an enumerated rewrite."""
        left = "- **R1** Facade owns Linear split."
        right = "- **R1** Adapter owns Linear split."
        assert not linear_public_markdown_equivalent(left, right)
        assert "list-marker" in LINEAR_PUBLIC_MARKDOWN_R6_REWRITES
        assert "heading-level" not in LINEAR_PUBLIC_MARKDOWN_R6_REWRITES

    def test_dropped_rid_or_link_fails(self) -> None:
        """E — a missing RID or link is not equivalent."""
        full = _RID_BODY
        dropped_rid = full.replace("- **R2** UUID head budget.\n", "")
        dropped_link = full.replace("https://example.com/overflow", "https://example.com/other")
        assert not linear_public_markdown_equivalent(full, dropped_rid)
        assert not linear_public_markdown_equivalent(full, dropped_link)

    def test_dropped_code_span_fails(self) -> None:
        """E — a missing code span is not equivalent."""
        full = _RID_BODY
        dropped_code = full.replace("`chunk_body_for_linear`", "chunk_body_for_linear")
        assert not linear_public_markdown_equivalent(full, dropped_code)

    def test_original_bytes_hashed_not_r6_form(self) -> None:
        """S — freeze/hash witness is original bytes, not the R6 comparison form."""
        hyphen = "- **R1** Facade owns Linear split."
        asterisk = "* **R1** Facade owns Linear split."
        assert linear_public_markdown_equivalent(hyphen, asterisk)
        snap_h = IssueSnapshot(title="t", body=hyphen, state="open", labels=[], comments=[])
        snap_a = IssueSnapshot(title="t", body=asterisk, state="open", labels=[], comments=[])
        assert canonical_hash(snap_h) != canonical_hash(snap_a)
        assert original_bytes_hash_body(hyphen) == hyphen.strip("\n")
        assert original_bytes_hash_body(hyphen) != linear_public_markdown_r6_form(hyphen) or hyphen == asterisk

    def test_canonical_hash_still_excludes_freeze_and_overflow(self) -> None:
        """R6 — do not change canonical-hash exclusion of freeze-record / chunk-overflow."""
        assert "sw-freeze-record" in EXCLUDED_COMMENT_MARKERS
        assert "sw-chunk-overflow" in EXCLUDED_COMMENT_MARKERS
        body = "# Keep original bytes\n"
        excluded = [
            CommentRecord(id="f", body="hash-witness", markers=["sw-freeze-record"]),
            CommentRecord(id="o", body="overflow-chunk", markers=["sw-chunk-overflow"]),
        ]
        included = [CommentRecord(id="c", body="operator note", markers=[])]
        hashed_excluded = canonical_hash(
            IssueSnapshot(title="t", body=body, state="open", labels=[], comments=excluded)
        )
        hashed_none = canonical_hash(
            IssueSnapshot(title="t", body=body, state="open", labels=[], comments=[])
        )
        hashed_included = canonical_hash(
            IssueSnapshot(title="t", body=body, state="open", labels=[], comments=included)
        )
        assert hashed_excluded == hashed_none
        assert hashed_included != hashed_none
