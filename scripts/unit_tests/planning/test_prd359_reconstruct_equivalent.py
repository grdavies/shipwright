"""PRD 359 R2/R11/D5 — put and freeze reconstruct-before-ok share equivalent()."""

from __future__ import annotations

import sys
from pathlib import Path

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from planning.backends.issues_helpers import reconstruct_bodies_equivalent
from planning_linear_canonical import linear_public_markdown_equivalent


class _Ps:
    @staticmethod
    def strip_markers_and_edges(text: str) -> str:
        return text

    @staticmethod
    def fail(message: str, **_kwargs: object) -> None:
        raise AssertionError(message)


def test_comparison_form_mismatch_is_not_equivalent() -> None:
    left = "See [docs](https://example.com/a) please\n"
    right = "See [docs](https://example.com/b) please\n"
    assert linear_public_markdown_equivalent(left, right) is False
    assert (
        reconstruct_bodies_equivalent(left, right, issues_provider="linear", ps_mod=_Ps)
        is False
    )


def test_identity_token_equality_alone_is_not_ok() -> None:
    # Same RID / no code-token set, but comparison form differs (heading vs paragraph).
    left = "## R1 Title\n\nBody.\n"
    right = "R1 Title\n\nBody.\n"
    assert linear_public_markdown_equivalent(left, right) is False
    assert (
        reconstruct_bodies_equivalent(left, right, issues_provider="linear", ps_mod=_Ps)
        is False
    )


def test_escaped_unmatched_ticks_are_not_equal_code_tokens() -> None:
    left = "use `code` here\n"
    right = "use \\`code\\` here\n"
    assert linear_public_markdown_equivalent(left, right) is False
    assert (
        reconstruct_bodies_equivalent(left, right, issues_provider="linear", ps_mod=_Ps)
        is False
    )


def test_enumerated_rewrite_still_equivalent() -> None:
    left = "hello  world\n"
    right = "hello world\n"
    assert reconstruct_bodies_equivalent(
        left, right, issues_provider="linear", ps_mod=_Ps
    ) is linear_public_markdown_equivalent(left, right)


def test_github_provider_does_not_call_linear_equivalent() -> None:
    left = "same-bytes"
    right = "same-bytes"
    assert (
        reconstruct_bodies_equivalent(left, right, issues_provider="github", ps_mod=_Ps)
        is True
    )
