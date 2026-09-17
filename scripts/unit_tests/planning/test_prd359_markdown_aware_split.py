"""PRD 359 R8–R10 / R14 — Markdown-aware Linear splits and fail-closed oversized constructs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from planning_canonical import CommentRecord
from planning_linear_canonical import (
    LinearOversizedConstructError,
    _split_overflow_comments,
    _split_positions,
    _utf8_byte_len,
    chunk_body_for_linear,
    linear_public_markdown_equivalent,
)
from planning.backends.issues import scan_put_payloads
from planning.backends.issues_helpers import reconstruct_bodies_equivalent

UNIQUE = "SPAN-TOKEN-NEVER-IN-ERROR-prd359"


def _assert_no_interior_cuts(text: str, start: int, end: int) -> None:
    for pos in _split_positions(text):
        assert not (start < pos < end), f"illegal cut {pos} inside [{start},{end})"


class TestPrd359SplitPositions:
    def test_no_cut_inside_inline_code(self) -> None:
        text = f"before `{UNIQUE} interior` after\n"
        start = text.index("`")
        end = text.rindex("`") + 1
        _assert_no_interior_cuts(text, start, end)

    def test_no_cut_inside_markdown_link(self) -> None:
        text = f"see [{UNIQUE}](https://example.com/{UNIQUE}) please\n"
        start = text.index("[")
        end = text.index(")") + 1
        _assert_no_interior_cuts(text, start, end)

    def test_no_cut_inside_emphasis_run(self) -> None:
        text = f"keep **{UNIQUE} bold** here\n"
        start = text.index("**")
        end = text.rindex("**") + 2
        _assert_no_interior_cuts(text, start, end)

    def test_no_cut_inside_fenced_code(self) -> None:
        text = f"intro\n```\n{UNIQUE}\nstill-inside\n```\nout\n"
        start = text.index("```")
        end = text.rindex("```") + 3
        _assert_no_interior_cuts(text, start, end)

    def test_no_cut_inside_gfm_table(self) -> None:
        text = f"| Col | {UNIQUE} |\n| --- | --- |\n| a | b |\n\n"
        start = 0
        end = text.rindex("|") + 1
        _assert_no_interior_cuts(text, start, end)

    def test_cuts_allowed_immediately_before_and_after_span(self) -> None:
        text = f"aa `{UNIQUE}` bb\n"
        start = text.index("`")
        end = text.rindex("`") + 1
        positions = set(_split_positions(text))
        assert start in positions
        assert end in positions


class TestPrd359OversizedClosedSet:
    def test_oversized_inline_code_raises_opaque_typed_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import planning_linear_canonical as llc

        monkeypatch.setattr(llc, "_LINEAR_CHUNK_LIMIT", 64)
        inner = UNIQUE + ("x" * 80)
        body = f"`{inner}`"
        with pytest.raises(LinearOversizedConstructError) as exc:
            chunk_body_for_linear(body, [])
        err = exc.value
        assert err.kind == "inline-code"
        assert err.code == "oversized-closed-set"
        assert err.length == _utf8_byte_len(body)
        payload = str(err)
        assert UNIQUE not in payload
        parsed = json.loads(payload)
        assert parsed == {"code": "oversized-closed-set", "kind": "inline-code", "length": err.length}

    def test_overflow_does_not_fallback_max_prefix_inside_fence(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import planning_linear_canonical as llc

        monkeypatch.setattr(llc, "_LINEAR_CHUNK_LIMIT", 80)

        def _boom(text: str, max_bytes: int) -> int:
            raise AssertionError("_max_prefix_chars must not run inside closed-set")

        monkeypatch.setattr(llc, "_max_prefix_chars", _boom)
        fence = f"```\n{UNIQUE}\n" + ("y" * 120) + "\n```"
        with pytest.raises(LinearOversizedConstructError) as exc:
            _split_overflow_comments(fence, [], write_token="0" * 12)
        assert exc.value.kind == "fenced-code"
        assert UNIQUE not in str(exc.value)

    def test_plain_text_still_chunks_without_closed_set_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import planning_linear_canonical as llc

        monkeypatch.setattr(llc, "_LINEAR_CHUNK_LIMIT", 200)
        remaining = "z" * 800
        comments = llc._split_overflow_comments(remaining, [], write_token="0" * 12)
        assert comments
        assert all(UNIQUE not in (c.body or "") for c in comments)
        for comment in comments:
            assert "sw-chunk-overflow" in (comment.markers or [])


class TestPrd359SecretScanContract:
    def test_scan_put_payloads_covers_pre_chunk_head_and_overflow(self) -> None:
        seen: list[str] = []

        def guard(*texts: str, path_hint: str | None = None) -> None:
            seen.extend([t for t in texts if t])

        overflows = [
            CommentRecord(id="c1", body="overflow-one", markers=["sw-chunk-overflow"]),
            CommentRecord(id="c2", body="overflow-two", markers=["sw-chunk-overflow"]),
        ]
        scan_put_payloads(
            guard,
            pre_chunk_body="PRE-CHUNK",
            head="HEAD-BODY",
            overflow_bodies=[c.body for c in overflows],
            path_hint="docs/prds/359.md",
        )
        assert seen == ["PRE-CHUNK", "HEAD-BODY", "overflow-one", "overflow-two"]

    def test_scan_put_payloads_is_the_absorb_surface(self) -> None:
        src = Path(__file__).resolve().parents[2] / "planning" / "backends" / "issues.py"
        text = src.read_text(encoding="utf-8")
        assert "GAP-474" in text and "GAP-475" in text
        assert "scan_put_payloads(" in text


class _Ps:
    @staticmethod
    def strip_markers_and_edges(text: str) -> str:
        return text

    @staticmethod
    def fail(message: str, **_kwargs: object) -> None:
        raise AssertionError(message)


class TestPrd359ReconstructEquivalent:
    def test_comparison_form_mismatch_is_not_equivalent(self) -> None:
        left = "See [docs](https://example.com/a) please\n"
        right = "See [docs](https://example.com/b) please\n"
        assert linear_public_markdown_equivalent(left, right) is False
        assert (
            reconstruct_bodies_equivalent(left, right, issues_provider="linear", ps_mod=_Ps)
            is False
        )

    def test_identity_token_equality_alone_is_not_ok(self) -> None:
        left = "## R1 Title\n\nBody.\n"
        right = "R1 Title\n\nBody.\n"
        assert linear_public_markdown_equivalent(left, right) is False
        assert (
            reconstruct_bodies_equivalent(left, right, issues_provider="linear", ps_mod=_Ps)
            is False
        )

    def test_escaped_unmatched_ticks_are_not_equal_code_tokens(self) -> None:
        left = "use `code` here\n"
        right = "use \\`code\\` here\n"
        assert linear_public_markdown_equivalent(left, right) is False
        assert (
            reconstruct_bodies_equivalent(left, right, issues_provider="linear", ps_mod=_Ps)
            is False
        )

    def test_enumerated_rewrite_still_equivalent(self) -> None:
        left = "hello  world\n"
        right = "hello world\n"
        assert reconstruct_bodies_equivalent(
            left, right, issues_provider="linear", ps_mod=_Ps
        ) is linear_public_markdown_equivalent(left, right)

    def test_github_provider_does_not_call_linear_equivalent(self) -> None:
        left = "same-bytes"
        right = "same-bytes"
        assert (
            reconstruct_bodies_equivalent(left, right, issues_provider="github", ps_mod=_Ps)
            is True
        )
