#!/usr/bin/env python3
"""PRD 047 — Jira ADF/wiki → canonical markdown normalization (R102, D27)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from planning_canonical import (
    CommentRecord,
    IssueSnapshot,
    append_chunk_manifest_marker,
    canonical_form,
    canonical_hash,
    normalize_body,
    MARKER_CHUNK_MANIFEST,
    parse_edges_fence_inner,
)


_FENCE_LANGS = frozenset({
    "json", "yaml", "yml", "text", "markdown", "sw-edges", "bash", "sh", "python",
    "typescript", "javascript", "ts", "js", "sql", "go", "rust",
})


def _parse_fenced_code(block: str) -> tuple[str, str] | None:
    lines = block.split("\n")
    if not lines or not lines[0].startswith("```"):
        return None
    lang = lines[0][3:].strip() or "text"
    body: list[str] = []
    for line in lines[1:]:
        if line.strip() == "```":
            break
        body.append(line)
    return lang, "\n".join(body)


def jira_markdown_canonical(markdown: str) -> str:
    """Lossy-but-deterministic body form after Jira ADF submit + fetch."""
    return adf_to_markdown(markdown_to_adf(markdown))




JIRA_CLOUD_DESCRIPTION_LIMIT = 32767
CHUNK_OVERFLOW_MARKER = "<!-- sw-chunk-overflow -->\n"


def jira_adf_payload_size(markdown: str) -> int:
    return len(json.dumps(markdown_to_adf(markdown), ensure_ascii=False))


def _split_positions(text: str) -> list[int]:
    """Newline split points outside fenced code blocks (never split inside a fence)."""
    positions = [0]
    in_fence = False
    index = 0
    length = len(text)
    while index < length:
        newline = text.find("\n", index)
        if newline == -1:
            break
        line = text[index:newline]
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if not in_fence:
            positions.append(newline + 1)
        index = newline + 1
    if not positions or positions[-1] != length:
        positions.append(length)
    return positions


def _max_jira_fit_chars(text: str, *, limit: int = JIRA_CLOUD_DESCRIPTION_LIMIT) -> int:
    if not text:
        return 0
    if jira_adf_payload_size(text) <= limit:
        return len(text)
    positions = _split_positions(text)
    lo, hi = 0, len(positions) - 1
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        pos = positions[mid]
        if jira_adf_payload_size(text[:pos]) <= limit:
            best = pos
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _split_overflow_comments(overflow: str, comments: list[CommentRecord]) -> list[CommentRecord]:
    new_comments = list(comments)
    while overflow:
        prefix = CHUNK_OVERFLOW_MARKER
        positions = _split_positions(overflow)
        lo, hi = 0, len(positions) - 1
        chunk_len = 0
        while lo <= hi:
            mid = (lo + hi) // 2
            pos = positions[mid]
            candidate = prefix + overflow[:pos]
            if jira_adf_payload_size(candidate) <= JIRA_CLOUD_DESCRIPTION_LIMIT:
                chunk_len = pos
                lo = mid + 1
            else:
                hi = mid - 1
        if chunk_len <= 0:
            raise RuntimeError("Jira body chunking failed: overflow fragment exceeds comment limit")
        chunk_id = f"chunk-{len(new_comments)}"
        piece = overflow[:chunk_len]
        overflow = overflow[chunk_len:]
        new_comments.append(
            CommentRecord(
                id=chunk_id,
                body=f"{prefix}{piece}",
                markers=["sw-chunk-overflow"],
            )
        )
    return new_comments


def _attach_chunk_manifest(head: str, chunk_comments: list[CommentRecord]) -> str:
    if not chunk_comments:
        return head
    manifest = {
        "version": 1,
        "chunks": [{"index": idx, "commentId": c.id} for idx, c in enumerate(chunk_comments)],
    }
    manifest_blob = json.dumps(manifest, sort_keys=True, ensure_ascii=False)
    marker = f"<!-- sw-chunk-manifest: {manifest_blob} -->"
    return append_chunk_manifest_marker(head, marker)


def rewrite_chunk_manifest(body: str, comment_ids: list[str]) -> str:
    if not comment_ids:
        return body
    manifest = {
        "version": 1,
        "chunks": [{"index": idx, "commentId": cid} for idx, cid in enumerate(comment_ids)],
    }
    manifest_blob = json.dumps(manifest, sort_keys=True, ensure_ascii=False)

    marker = f"<!-- sw-chunk-manifest: {manifest_blob} -->"
    return append_chunk_manifest_marker(body, marker)


def chunk_body_for_jira_cloud(
    body: str,
    comments: list[CommentRecord],
) -> tuple[str, list[CommentRecord]]:
    """Split markdown so Jira Cloud ADF description/comments stay within API limits."""
    if jira_adf_payload_size(body) <= JIRA_CLOUD_DESCRIPTION_LIMIT:
        return body, comments

    positions = _split_positions(body)
    lo, hi = 0, len(positions) - 1
    best: tuple[str, list[CommentRecord]] | None = None
    while lo <= hi:
        mid = (lo + hi) // 2
        head_len = positions[mid]
        overflow = body[head_len:]
        extra = _split_overflow_comments(overflow, list(comments)) if overflow else list(comments)
        chunk_only = extra[len(comments) :]
        candidate = _attach_chunk_manifest(body[:head_len], chunk_only)
        if jira_adf_payload_size(candidate) <= JIRA_CLOUD_DESCRIPTION_LIMIT:
            best = (candidate, extra)
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        raise RuntimeError("Jira body chunking failed: no description prefix fits with manifest")
    return best


WIKI_HEADING = re.compile(r"^h([1-6])\.\s+(.+)$")


def _adf_inline(node: dict[str, Any]) -> str:
    t = node.get("type")
    if t == "text":
        return str(node.get("text", ""))
    if t == "mention":
        attrs = node.get("attrs") or {}
        return str(attrs.get("text") or f"@{attrs.get('id', '')}")
    if t == "hardBreak":
        return "\n"
    if t == "emoji":
        attrs = node.get("attrs") or {}
        return str(attrs.get("text") or attrs.get("shortName", ""))
    if t == "inlineCard":
        attrs = node.get("attrs") or {}
        return str(attrs.get("url", ""))
    return ""


def _adf_block(node: dict[str, Any]) -> str:
    t = node.get("type")
    content = node.get("content") or []
    if t == "paragraph":
        if not content:
            return "\n"
        return "".join(_adf_inline(c) for c in content) + "\n"
    if t == "heading":
        level = int((node.get("attrs") or {}).get("level", 1))
        text = "".join(_adf_inline(c) for c in content)
        return ("#" * level) + " " + text + "\n\n"
    if t == "bulletList":
        lines: list[str] = []
        for item in content:
            if item.get("type") != "listItem":
                continue
            for sub in item.get("content") or []:
                if sub.get("type") == "paragraph":
                    text = "".join(_adf_inline(c) for c in sub.get("content") or [])
                    lines.append(f"- {text}")
        return ("\n".join(lines) + "\n") if lines else ""
    if t == "codeBlock":
        text = "".join(_adf_inline(c) for c in content)
        if parse_edges_fence_inner(text):
            return f"```sw-edges\n{text.rstrip()}\n```\n"
        lang = str((node.get("attrs") or {}).get("language") or "").strip()
        if lang and lang not in {"text", ""}:
            return f"```{lang}\n{text}\n```\n"
        return f"```\n{text}\n```\n"
    return ""


def markdown_to_adf(markdown: str) -> dict[str, Any]:
    """Minimal markdown → ADF for Jira Cloud issue descriptions (R102 submit path)."""
    content: list[dict[str, Any]] = []
    blocks = [block for block in normalize_body(markdown).split("\n\n") if block.strip()]
    for block_index, block in enumerate(blocks):
        if block_index > 0:
            content.append({"type": "paragraph", "content": []})
        parsed = _parse_fenced_code(block)
        if parsed is not None:
            lang, code = parsed
            if lang == "sw-edges":
                fence_lang = "sw-edges"
            elif lang in _FENCE_LANGS:
                fence_lang = lang
            else:
                fence_lang = "text"
            content.append(
                {
                    "type": "codeBlock",
                    "attrs": {"language": fence_lang},
                    "content": [{"type": "text", "text": code.rstrip("\n")}],
                }
            )
            continue
        for line in block.split("\n"):
            content.append(
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": line}],
                }
            )
    if not content:
        content.append({"type": "paragraph", "content": [{"type": "text", "text": ""}]})
    return {"type": "doc", "version": 1, "content": content}


def adf_to_markdown(adf: dict[str, Any]) -> str:
    if not isinstance(adf, dict) or adf.get("type") != "doc":
        return ""
    parts = [_adf_block(n) for n in adf.get("content") or []]
    return normalize_body("".join(parts))


def wiki_to_markdown(wiki: str) -> str:
    lines_out: list[str] = []
    for line in normalize_body(wiki).split("\n"):
        m = WIKI_HEADING.match(line)
        if m:
            lines_out.append("#" * int(m.group(1)) + " " + m.group(2))
        else:
            lines_out.append(line)
    return normalize_body("\n".join(lines_out))


def _body_from_fixture(data: dict[str, Any], *, post_refetch: bool = True) -> str:
    if isinstance(data.get("body"), str):
        return data["body"]
    if post_refetch and isinstance(data.get("refetchedAdf"), dict):
        return adf_to_markdown(data["refetchedAdf"])
    if isinstance(data.get("submitAdf"), dict):
        return adf_to_markdown(data["submitAdf"])
    if isinstance(data.get("submitWiki"), str):
        return wiki_to_markdown(data["submitWiki"])
    return ""


def snapshot_from_fixture(data: dict[str, Any], *, post_refetch: bool = True) -> IssueSnapshot:
    comments = [CommentRecord(**c) for c in data.get("comments", [])]
    return IssueSnapshot(
        title=data["title"],
        body=_body_from_fixture(data, post_refetch=post_refetch),
        state=data.get("state", "open"),
        labels=list(data.get("labels", [])),
        comments=comments,
    )


def normalize_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    snap = snapshot_from_fixture(data)
    return {
        "verdict": "ok",
        "canonical": canonical_form(snap),
        "hash": canonical_hash(snap),
        "body": snap.body,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Jira canonical normalization (PRD 047)")
    sub = parser.add_subparsers(dest="command", required=True)
    norm = sub.add_parser("normalize", help="Normalize a Jira canonical fixture")
    norm.add_argument("--fixture", required=True, help="Path to fixture JSON")
    args = parser.parse_args(argv)
    if args.command == "normalize":
        result = normalize_fixture(Path(args.fixture))
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
