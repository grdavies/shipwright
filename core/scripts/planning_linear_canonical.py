#!/usr/bin/env python3
"""PRD 066 — Linear Public Markdown canonicalization + fidelity suite (R15).

Supported adapter contract is Linear **Public Markdown** fields (issue/document
``description`` / ``content``). Internal ProseMirror ``contentData`` and Yjs
``contentState`` are explicitly **not** adapter-complete and must not be used as
freeze-hash or round-trip authority.
"""

from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path
from typing import Any

from planning_canonical import (
    BODY_SIZE_LIMIT,
    CHUNK_TOKEN_MARKER_PREFIX,
    CommentRecord,
    IssueSnapshot,
    MARKER_CHUNK_MANIFEST,
    canonical_form,
    canonical_hash,
    normalize_body,
    require_linear_size_pin,
)

SUPPORTED_CONTRACT = "public-markdown"
UNSUPPORTED_INTERNAL_FIELDS = frozenset({"contentData", "contentState"})

# Linear GraphQL Public Markdown mention submit form (developers.linear.app):
# bare workspace URLs become @mentions in the editor; we canonicalize to URLs.
_MENTION_MD_LINK = re.compile(
    r"\[@[^\]]+\]\((https://linear\.app/[^)\s]+)\)"
)

# +++ Title ... +++ collapsible sections (Linear Public Markdown).
_COLLAPSIBLE = re.compile(
    r"^\+\+\+\s*(?P<title>[^\n]*)\n(?P<body>.*?)^\+\+\+\s*$",
    re.MULTILINE | re.DOTALL,
)

_HTML_DETAILS = re.compile(r"<details\b", re.IGNORECASE)
_HTML_SUMMARY = re.compile(r"<summary\b", re.IGNORECASE)


class LinearCanonicalContractError(ValueError):
    """Raised when a payload claims an unsupported Linear content contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LinearCanonicalDegradeError(ValueError):
    """Raised when a construct cannot round-trip via Public Markdown."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def assert_public_markdown_contract(payload: dict[str, Any] | None) -> None:
    """Fail closed when ProseMirror/Yjs internal fields are treated as supported."""
    if not isinstance(payload, dict):
        return
    present = sorted(UNSUPPORTED_INTERNAL_FIELDS.intersection(payload.keys()))
    if present:
        raise LinearCanonicalContractError(
            "unsupported-internal-content-contract",
            "Linear adapter contract is Public Markdown only; "
            f"internal fields not adapter-complete: {', '.join(present)}",
        )


def is_adapter_complete_field(field_name: str) -> bool:
    """Return True only for Public Markdown content fields."""
    if field_name in UNSUPPORTED_INTERNAL_FIELDS:
        return False
    return field_name in {"description", "content", "body", "markdown", "publicMarkdown"}


def _normalize_mention_urls(text: str) -> str:
    """Canonical mention form is the bare Linear resource URL (API submit shape)."""

    def _link_to_url(match: re.Match[str]) -> str:
        return match.group(1).rstrip("/")

    return _MENTION_MD_LINK.sub(_link_to_url, text)


def _normalize_collapsibles(text: str) -> str:
    """Normalize +++ collapsible blocks to a stable Public Markdown shape."""

    def _repl(match: re.Match[str]) -> str:
        title = match.group("title").strip()
        body = normalize_body(match.group("body"))
        if body:
            return f"+++ {title}\n\n{body}\n\n+++"
        return f"+++ {title}\n\n+++"

    return _COLLAPSIBLE.sub(_repl, text)


def _normalize_fenced_code_langs(text: str) -> str:
    """Preserve language tags; empty fence opener stays language-less (GFM)."""
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    for line in lines:
        if line.startswith("```"):
            if not in_fence:
                lang = line[3:].strip()
                out.append(f"```{lang}" if lang else "```")
                in_fence = True
            else:
                out.append("```")
                in_fence = False
        else:
            out.append(line)
    return "\n".join(out)


def reject_non_round_trippable(markdown: str) -> None:
    """Reject constructs that Linear cannot round-trip via Public Markdown alone."""
    if _HTML_DETAILS.search(markdown) or _HTML_SUMMARY.search(markdown):
        raise LinearCanonicalDegradeError(
            "html-details-not-public-markdown",
            "HTML <details>/<summary> is not Linear Public Markdown; use +++ collapsibles",
        )
    stripped = markdown.strip()
    if stripped.startswith("{") and (
        '"contentData"' in stripped or '"contentState"' in stripped
    ):
        try:
            blob = json.loads(stripped)
        except json.JSONDecodeError:
            blob = None
        if isinstance(blob, dict):
            assert_public_markdown_contract(blob)


def linear_markdown_canonical(markdown: str) -> str:
    """Normalize Linear Public Markdown into the PRD 043 body subset for freeze hash."""
    reject_non_round_trippable(markdown)
    text = normalize_body(markdown)
    text = _normalize_mention_urls(text)
    text = _normalize_collapsibles(text)
    text = _normalize_fenced_code_langs(text)
    return normalize_body(text)


def simulate_public_markdown_round_trip(submit_markdown: str) -> str:
    """Simulate submit→refetch through Public Markdown fields only (no contentData)."""
    return linear_markdown_canonical(submit_markdown)


def snapshot_from_linear_markdown(
    *,
    title: str,
    markdown: str,
    state: str = "open",
    labels: list[str] | None = None,
    comments: list[dict[str, Any]] | None = None,
) -> IssueSnapshot:
    body = linear_markdown_canonical(markdown)
    comment_records = [
        CommentRecord(
            id=str(c.get("id", "")),
            body=linear_markdown_canonical(str(c.get("body", ""))),
            created_at=str(c.get("created_at", "")),
            markers=list(c.get("markers") or []),
        )
        for c in (comments or [])
    ]
    return IssueSnapshot(
        title=title,
        body=body,
        state=state,
        labels=list(labels or []),
        comments=comment_records,
    )


def _body_from_fixture(data: dict[str, Any]) -> str:
    assert_public_markdown_contract(data)
    if isinstance(data.get("refetchedMarkdown"), str):
        return linear_markdown_canonical(data["refetchedMarkdown"])
    if isinstance(data.get("submitMarkdown"), str):
        return simulate_public_markdown_round_trip(data["submitMarkdown"])
    if isinstance(data.get("body"), str):
        return linear_markdown_canonical(data["body"])
    raise LinearCanonicalContractError(
        "missing-public-markdown",
        "fixture requires submitMarkdown, refetchedMarkdown, or body (Public Markdown)",
    )


def snapshot_from_fixture(data: dict[str, Any]) -> IssueSnapshot:
    assert_public_markdown_contract(data)
    return snapshot_from_linear_markdown(
        title=str(data.get("title") or "linear-canonical-fixture"),
        markdown=_body_from_fixture(data),
        state=str(data.get("state") or "open"),
        labels=list(data.get("labels") or []),
        comments=list(data.get("comments") or []),
    )


CHUNK_OVERFLOW_MARKER = "<!-- sw-chunk-overflow -->\n"
_LINEAR_CHUNK_LIMIT = BODY_SIZE_LIMIT
# PRD 358 D4 — Linear overflow comment ids are 36-char UUID strings after post.
LINEAR_OVERFLOW_COMMENT_ID_UTF8_LEN = 36


class LinearChunkHeadBudgetError(RuntimeError):
    """No description head fits within the limit after UUID manifest rewrite (PRD 358 R2)."""


def _utf8_byte_len(text: str) -> int:
    return len(text.encode("utf-8"))


def _is_gfm_table_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped or "|" not in stripped:
        return False
    if stripped.startswith("|") and stripped.endswith("|"):
        return True
    if re.match(r"^[\s|:-]+$", stripped.replace("|", "")):
        return True
    parts = [p.strip() for p in stripped.split("|") if p.strip()]
    return len(parts) >= 2 and "|" in stripped


def _split_positions(text: str) -> list[int]:
    """Split points outside fenced code blocks and GFM tables (R9).

    Prefer newline boundaries; allow Unicode character boundaries on plain lines.
    """
    positions: set[int] = {0}
    in_fence = False
    in_table = False
    index = 0
    length = len(text)
    while index < length:
        newline = text.find("\n", index)
        line_end = length if newline == -1 else newline
        line = text[index:line_end]
        line_start = index
        if line.strip().startswith("```"):
            in_fence = not in_fence
            in_table = False
            if not in_fence and newline != -1:
                positions.add(newline + 1)
        elif in_fence:
            pass
        else:
            if not line.strip():
                in_table = False
                if newline != -1:
                    positions.add(newline + 1)
            elif _is_gfm_table_line(line):
                if not in_table:
                    positions.add(line_start)
                in_table = True
            else:
                if in_table:
                    in_table = False
                if newline != -1:
                    positions.add(newline + 1)
                if not in_table:
                    for cut in range(line_start + 1, line_end + 1):
                        positions.add(cut)
        if newline == -1:
            break
        index = newline + 1
    positions.add(length)
    return sorted(positions)


def _max_prefix_chars(text: str, max_bytes: int) -> int:
    """Largest prefix length (Unicode code points) whose UTF-8 encoding fits max_bytes."""
    if not text:
        return 0
    lo, hi = 0, len(text)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        if _utf8_byte_len(text[:mid]) <= max_bytes:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _max_prefix_bytes(text: str, *, limit: int, positions: list[int] | None = None) -> int:
    if not text:
        return 0
    if _utf8_byte_len(text) <= limit:
        return len(text)
    cuts = positions if positions is not None else _split_positions(text)
    lo, hi = 0, len(cuts) - 1
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        pos = cuts[mid]
        if _utf8_byte_len(text[:pos]) <= limit:
            best = pos
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _overflow_comment_prefix(write_token: str) -> str:
    return (
        f"{CHUNK_OVERFLOW_MARKER}"
        f"<!-- {CHUNK_TOKEN_MARKER_PREFIX}{write_token} -->\n"
    )


def _overflow_comment_markers(write_token: str) -> list[str]:
    return [
        "sw-chunk-overflow",
        f"{CHUNK_TOKEN_MARKER_PREFIX}{write_token}",
    ]


def _split_overflow_comments(
    overflow: str,
    comments: list[CommentRecord],
    *,
    write_token: str,
) -> list[CommentRecord]:
    new_comments = list(comments)
    prefix = _overflow_comment_prefix(write_token)
    remaining = overflow
    prefix_bytes = _utf8_byte_len(prefix)
    max_piece_bytes = _LINEAR_CHUNK_LIMIT - prefix_bytes
    if max_piece_bytes <= 0:
        raise RuntimeError("Linear body chunking failed: overflow marker exceeds comment limit")
    while remaining:
        positions = _split_positions(remaining)
        chunk_len = _max_prefix_bytes(remaining, limit=max_piece_bytes, positions=positions)
        if chunk_len <= 0:
            chunk_len = _max_prefix_chars(remaining, max_piece_bytes)
        if chunk_len <= 0:
            raise RuntimeError("Linear body chunking failed: overflow fragment exceeds comment limit")
        chunk_id = f"chunk-{len(new_comments)}"
        piece = remaining[:chunk_len]
        remaining = remaining[chunk_len:]
        new_comments.append(
            CommentRecord(
                id=chunk_id,
                body=f"{prefix}{piece}",
                markers=_overflow_comment_markers(write_token),
            )
        )
    return new_comments


def _worst_case_linear_overflow_comment_ids(count: int) -> list[str]:
    """Worst-case UTF-8 length for post-posting Linear overflow comment ids."""
    if count <= 0:
        return []
    pad = "a" * LINEAR_OVERFLOW_COMMENT_ID_UTF8_LEN
    return [pad for _ in range(count)]


def _head_fits_after_uuid_manifest_rewrite(head: str, overflow_chunk_count: int) -> bool:
    """True when rewrite_chunk_manifest_ids cannot push the head over the Linear limit."""
    if overflow_chunk_count <= 0:
        return _utf8_byte_len(head) <= _LINEAR_CHUNK_LIMIT
    from planning_canonical import rewrite_chunk_manifest_ids

    rewritten = rewrite_chunk_manifest_ids(
        head, _worst_case_linear_overflow_comment_ids(overflow_chunk_count)
    )
    return _utf8_byte_len(rewritten) <= _LINEAR_CHUNK_LIMIT


def _attach_chunk_manifest(
    head: str,
    chunk_comments: list[CommentRecord],
    *,
    write_token: str,
) -> str:
    if not chunk_comments:
        return head
    manifest = {
        "version": 1,
        "chunks": [{"index": idx, "commentId": c.id} for idx, c in enumerate(chunk_comments)],
        "writeToken": write_token,
    }
    marker = f"<!-- sw-chunk-manifest: {json.dumps(manifest, sort_keys=True, ensure_ascii=False)} -->"
    if MARKER_CHUNK_MANIFEST.search(head):
        return MARKER_CHUNK_MANIFEST.sub(marker, head)
    return head + marker


def chunk_body_for_linear(
    body: str,
    comments: list[CommentRecord],
) -> tuple[str, list[CommentRecord]]:
    """Split markdown for Linear description/comment UTF-8 byte limits (PRD 357 R8–R11)."""
    require_linear_size_pin()
    if _utf8_byte_len(body) <= _LINEAR_CHUNK_LIMIT:
        return body, comments

    write_token = uuid.uuid4().hex[:12]
    positions = _split_positions(body)
    lo, hi = 0, len(positions) - 1
    best: tuple[str, list[CommentRecord]] | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        head_len = positions[mid]
        overflow = body[head_len:]
        extra = (
            _split_overflow_comments(overflow, list(comments), write_token=write_token)
            if overflow
            else list(comments)
        )
        chunk_only = extra[len(comments) :]
        candidate = _attach_chunk_manifest(body[:head_len], chunk_only, write_token=write_token)
        if _utf8_byte_len(candidate) <= _LINEAR_CHUNK_LIMIT and _head_fits_after_uuid_manifest_rewrite(
            candidate, len(chunk_only)
        ):
            best = (candidate, extra)
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        raise LinearChunkHeadBudgetError(
            "Linear body chunking failed: no description head fits after UUID manifest rewrite"
        )
    return best


def normalize_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    snap = snapshot_from_fixture(data)
    return {
        "verdict": "ok",
        "contract": SUPPORTED_CONTRACT,
        "canonical": canonical_form(snap),
        "hash": canonical_hash(snap),
        "body": snap.body,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Linear Public Markdown canonicalization (PRD 066 R15)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    norm = sub.add_parser("normalize", help="Normalize a Linear canonical fixture")
    norm.add_argument("--fixture", required=True, help="Path to fixture JSON")
    args = parser.parse_args(argv)
    if args.command == "normalize":
        try:
            result = normalize_fixture(Path(args.fixture))
        except (LinearCanonicalContractError, LinearCanonicalDegradeError) as exc:
            print(
                json.dumps(
                    {
                        "verdict": "fail",
                        "code": exc.code,
                        "error": exc.message,
                        "contract": SUPPORTED_CONTRACT,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
            )
            return 2
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
