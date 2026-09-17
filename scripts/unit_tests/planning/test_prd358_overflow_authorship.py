"""PRD 358 R4 / D11 — overflow reconstruction binds writeToken and Linear authorship."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from planning_canonical import (
    BODY_SIZE_LIMIT,
    CHUNK_TOKEN_MARKER_PREFIX,
    CommentRecord,
    LinearChunkAuthorshipError,
    chunk_token_from_comment,
    load_chunk_manifest,
    normalize_body,
    reassemble_body,
    rewrite_chunk_manifest_ids,
)
from planning_linear_canonical import chunk_body_for_linear

_OWN_AUTHOR = "linear-actor-own"
_FOREIGN_AUTHOR = "linear-actor-foreign"


def _chunked_linear_body() -> tuple[str, str, list[CommentRecord]]:
    body = "# Authorship bind\n\n" + ("z" * (BODY_SIZE_LIMIT + 800))
    head, comments = chunk_body_for_linear(body, [])
    overflow = [c for c in comments if "sw-chunk-overflow" in c.markers]
    assert overflow, "expected Linear overflow comments"
    return body, head, overflow


def _with_author(comment: CommentRecord, author_id: str, *, comment_id: str | None = None) -> CommentRecord:
    return CommentRecord(
        id=comment_id if comment_id is not None else comment.id,
        body=comment.body,
        created_at=comment.created_at,
        markers=list(comment.markers),
        author_id=author_id,
    )


def _retoken(comment: CommentRecord, token: str, *, comment_id: str | None = None) -> CommentRecord:
    markers = [m for m in comment.markers if not m.startswith(CHUNK_TOKEN_MARKER_PREFIX)]
    markers.append(f"{CHUNK_TOKEN_MARKER_PREFIX}{token}")
    body = comment.body
    old = chunk_token_from_comment(comment)
    if old:
        body = body.replace(f"{CHUNK_TOKEN_MARKER_PREFIX}{old}", f"{CHUNK_TOKEN_MARKER_PREFIX}{token}")
    return CommentRecord(
        id=comment_id if comment_id is not None else comment.id,
        body=body,
        created_at=comment.created_at,
        markers=markers,
        author_id=comment.author_id,
    )


def test_zero_comments_with_write_token_fails_closed() -> None:
    """Z — a manifested Linear head with no overflow comments is a failed reconstruct."""
    _body, head, overflow = _chunked_linear_body()
    assert load_chunk_manifest(head)
    with pytest.raises(LinearChunkAuthorshipError, match="linear-chunk-overflow-missing"):
        reassemble_body(head, [])
    assert overflow


def test_matching_write_token_round_trip() -> None:
    """O — overflow that matches this write's writeToken reassembles the caller body."""
    body, head, overflow = _chunked_linear_body()
    session = chunk_token_from_comment(overflow[0])
    assert session
    manifest = load_chunk_manifest(head)
    assert manifest is not None
    assert manifest.get("writeToken") == session
    stamped = [_with_author(c, _OWN_AUTHOR) for c in overflow]
    rebuilt = reassemble_body(head, stamped, linear_author_id=_OWN_AUTHOR)
    assert normalize_body(rebuilt) == normalize_body(body)


def test_mixed_authors_foreign_referenced_fails_closed() -> None:
    """M — identifier survival of a foreign author's overflow is not enough."""
    body, head, overflow = _chunked_linear_body()
    own = [_with_author(c, _OWN_AUTHOR, comment_id=f"own-{i}") for i, c in enumerate(overflow)]
    foreign = [
        _with_author(c, _FOREIGN_AUTHOR, comment_id=f"foreign-{i}")
        for i, c in enumerate(overflow)
    ]
    rewritten = rewrite_chunk_manifest_ids(head, [c.id for c in foreign])
    with pytest.raises(LinearChunkAuthorshipError, match="linear-chunk-author-mismatch"):
        reassemble_body(rewritten, own + foreign, linear_author_id=_OWN_AUTHOR)
    # Mixed presence is allowed when the referenced ids are this write's actor.
    own_head = rewrite_chunk_manifest_ids(head, [c.id for c in own])
    rebuilt = reassemble_body(own_head, own + foreign, linear_author_id=_OWN_AUTHOR)
    assert normalize_body(rebuilt) == normalize_body(body)
    assert "STALE" not in rebuilt


def test_superseded_session_token_fails_closed() -> None:
    """B — a referenced overflow from a superseded writeToken is a failed write."""
    _body, head, overflow = _chunked_linear_body()
    stale_token = "stale" + "0" * 7
    superseded = [_retoken(c, stale_token, comment_id=f"stale-{i}") for i, c in enumerate(overflow)]
    rewritten = rewrite_chunk_manifest_ids(head, [c.id for c in superseded])
    with pytest.raises(LinearChunkAuthorshipError, match="linear-chunk-token-superseded"):
        reassemble_body(rewritten, superseded)


def test_authorship_bind_missing_author_fails_closed() -> None:
    """I — Linear authorship bind refuses overflow with a blank provider author_id."""
    _body, head, overflow = _chunked_linear_body()
    missing = [_with_author(c, "") for c in overflow]
    with pytest.raises(LinearChunkAuthorshipError, match="linear-chunk-author-missing"):
        reassemble_body(head, missing, linear_author_id=_OWN_AUTHOR)


def test_positional_foreign_mix_fails_closed() -> None:
    """E — unscoped positional fallback of foreign overflow is a failed write."""
    _body, head, overflow = _chunked_linear_body()
    foreign_token = "other" + "1" * 7
    foreign = [
        _retoken(_with_author(c, _FOREIGN_AUTHOR), foreign_token, comment_id=f"mix-{i}")
        for i, c in enumerate(overflow)
    ]
    # Placeholder ids force positional fallback; only foreign-token comments exist.
    with pytest.raises(LinearChunkAuthorshipError, match="linear-chunk-overflow-missing"):
        reassemble_body(head, foreign, linear_author_id=_OWN_AUTHOR)


def test_restart_recovery_placeholder_ids_matching_token() -> None:
    """S — restart recovery may positional-match this write's token, not a foreign session."""
    body, head, overflow = _chunked_linear_body()
    session = chunk_token_from_comment(overflow[0])
    assert session
    recovered = [
        _with_author(c, _OWN_AUTHOR, comment_id=f"uuid-{i}-restart")
        for i, c in enumerate(overflow)
    ]
    stale = [
        _retoken(_with_author(c, _FOREIGN_AUTHOR), "old" + "2" * 9, comment_id=f"old-{i}")
        for i, c in enumerate(overflow)
    ]
    rebuilt = reassemble_body(head, stale + recovered, linear_author_id=_OWN_AUTHOR)
    assert normalize_body(rebuilt) == normalize_body(body)


def test_nested_overflow_manifest_fails_closed() -> None:
    """Nested sw-chunk-manifest inside overflow is a failure (R4)."""
    _body, head, overflow = _chunked_linear_body()
    nested_marker = (
        '<!-- sw-chunk-manifest: {"version": 1, "chunks": [], "writeToken": "nested"} -->\n'
    )
    nested = []
    for comment in overflow:
        nested.append(
            CommentRecord(
                id=comment.id,
                body=comment.body + nested_marker,
                created_at=comment.created_at,
                markers=list(comment.markers),
                author_id=_OWN_AUTHOR,
            )
        )
    with pytest.raises(LinearChunkAuthorshipError, match="linear-chunk-nested-manifest"):
        reassemble_body(head, nested, linear_author_id=_OWN_AUTHOR)
