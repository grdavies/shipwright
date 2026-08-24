#!/usr/bin/env python3
"""PRD 327 — Notion block-children ↔ markdown canonicalization (R3)."""

from __future__ import annotations

import argparse
import json
import re
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
)

NOTION_RICH_TEXT_CHAR_LIMIT = 2000
NOTION_BLOCK_APPEND_LIMIT = 100
CHUNK_OVERFLOW_MARKER = "<!-- sw-chunk-overflow -->\n"

SUPPORTED_CONTRACT = "block-children"
UNSUPPORTED_BLOCK_TYPES = frozenset(
    {
        "image",
        "video",
        "file",
        "pdf",
        "embed",
        "equation",
        "synced_block",
        "column",
        "column_list",
        "breadcrumb",
        "link_preview",
    }
)

_COLLAPSIBLE = re.compile(
    r"^\+\+\+\s*(?P<title>[^\n]*)\n(?P<body>.*?)^\+\+\+\s*$",
    re.MULTILINE | re.DOTALL,
)
_URL_INLINE = re.compile(r"https?://[^\s<>\[\])\"']+")
_MD_LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")
_FENCE = re.compile(r"^```([^\n]*)$")
_HEADING = re.compile(r"^(#{1,3})\s+(.*)$")
_BULLET = re.compile(r"^[-*]\s+(.*)$")
_NUMBERED = re.compile(r"^\d+\.\s+(.*)$")
_CHECKBOX = re.compile(r"^[-*]\s+\[( |x|X)\]\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_DIVIDER = re.compile(r"^(-{3,}|\*{3,}|_{3,})\s*$")
_TABLE_ROW = re.compile(r"^\|(.+)\|$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")


class NotionCanonicalContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NotionCanonicalDegradeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def assert_block_children_contract(payload: dict[str, Any] | None) -> None:
    if not isinstance(payload, dict):
        return
    contract = payload.get("contract")
    if isinstance(contract, str) and contract.strip() and contract != SUPPORTED_CONTRACT:
        raise NotionCanonicalContractError(
            "unsupported-content-contract",
            f"Notion adapter contract is {SUPPORTED_CONTRACT!r}, not {contract!r}",
        )


def _reject_unsupported_block(block: dict[str, Any]) -> None:
    block_type = str(block.get("type") or "")
    if block_type in UNSUPPORTED_BLOCK_TYPES:
        raise NotionCanonicalDegradeError(
            "unsupported-block-type",
            f"Notion block type {block_type!r} cannot round-trip via block-children markdown",
        )


def _text_rich(content: str, *, url: str | None = None) -> dict[str, Any]:
    text: dict[str, Any] = {"content": content}
    text["link"] = {"url": url} if url else None
    return {"type": "text", "text": text, "annotations": {}}


def _mention_link(url: str) -> dict[str, Any]:
    return {
        "type": "mention",
        "mention": {"type": "link", "link": {"url": url}},
        "annotations": {},
    }


def _inline_to_rich(text: str) -> list[dict[str, Any]]:
    if not text:
        return []
    parts: list[dict[str, Any]] = []
    index = 0
    while index < len(text):
        link_match = _MD_LINK.search(text, index)
        url_match = _URL_INLINE.search(text, index)
        next_match = None
        if link_match and url_match:
            next_match = link_match if link_match.start() <= url_match.start() else url_match
        elif link_match:
            next_match = link_match
        elif url_match:
            next_match = url_match
        if next_match is None:
            parts.append(_text_rich(text[index:]))
            break
        if next_match.start() > index:
            parts.append(_text_rich(text[index:next_match.start()]))
        if next_match.re is _MD_LINK:
            url = next_match.group(2).rstrip("/")
            parts.append(_mention_link(url))
            index = next_match.end()
        else:
            url = next_match.group(0).rstrip("/")
            parts.append(_mention_link(url))
            index = next_match.end()
    return parts


def _rich_to_inline(rich: list[dict[str, Any]]) -> str:
    out: list[str] = []
    for item in rich:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "")
        if item_type == "text":
            text = item.get("text") if isinstance(item.get("text"), dict) else {}
            content = str(text.get("content") or "")
            link = text.get("link")
            if isinstance(link, dict) and link.get("url"):
                url = str(link["url"]).rstrip("/")
                out.append(url)
            else:
                out.append(content)
        elif item_type == "mention":
            mention = item.get("mention") if isinstance(item.get("mention"), dict) else {}
            if mention.get("type") == "link":
                link = mention.get("link") if isinstance(mention.get("link"), dict) else {}
                if link.get("url"):
                    out.append(str(link["url"]).rstrip("/"))
    return "".join(out)


def _block_rich_text(block: dict[str, Any]) -> list[dict[str, Any]]:
    payload = block.get(block.get("type", ""))
    if isinstance(payload, dict) and isinstance(payload.get("rich_text"), list):
        return list(payload["rich_text"])
    return []


def _block_children(block: dict[str, Any]) -> list[dict[str, Any]]:
    payload = block.get(block.get("type", ""))
    if isinstance(payload, dict) and isinstance(payload.get("children"), list):
        return [c for c in payload["children"] if isinstance(c, dict)]
    return []


def _make_block(block_type: str, **fields: Any) -> dict[str, Any]:
    payload = dict(fields)
    return {"object": "block", "type": block_type, block_type: payload}


def blocks_to_markdown(blocks: list[dict[str, Any]]) -> str:
    """Convert Notion block children to canonical markdown."""
    lines = _blocks_to_lines(blocks, indent=0)
    return normalize_body("\n".join(lines))


def _blocks_to_lines(blocks: list[dict[str, Any]], *, indent: int) -> list[str]:
    out: list[str] = []
    prefix = "  " * indent
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if not isinstance(block, dict):
            index += 1
            continue
        _reject_unsupported_block(block)
        block_type = str(block.get("type") or "")
        if block_type == "table":
            table_block = block.get("table") if isinstance(block.get("table"), dict) else {}
            width = int(table_block.get("table_width") or 0)
            rows: list[list[str]] = []
            child_index = index + 1
            while child_index < len(blocks) and blocks[child_index].get("type") == "table_row":
                row_block = blocks[child_index]
                cells = (
                    (row_block.get("table_row") or {}).get("cells")
                    if isinstance(row_block.get("table_row"), dict)
                    else []
                )
                row_cells = []
                for cell in cells if isinstance(cells, list) else []:
                    if isinstance(cell, list):
                        row_cells.append(_rich_to_inline(cell))
                    else:
                        row_cells.append("")
                rows.append(row_cells)
                child_index += 1
            if rows:
                col_count = max(len(r) for r in rows) if rows else width
                if width and col_count < width:
                    col_count = width
                for row in rows:
                    while len(row) < col_count:
                        row.append("")
                    out.append(prefix + "| " + " | ".join(row) + " |")
                if len(rows) > 1:
                    sep = "| " + " | ".join(["---"] * col_count) + " |"
                    out.insert(len(out) - len(rows) + 1, prefix + sep)
            index = child_index
            continue
        if block_type == "table_row":
            index += 1
            continue
        if block_type == "paragraph":
            text = _rich_to_inline(_block_rich_text(block))
            out.append(f"{prefix}{text}" if text else "")
        elif block_type in {"heading_1", "heading_2", "heading_3"}:
            level = {"heading_1": 1, "heading_2": 2, "heading_3": 3}[block_type]
            text = _rich_to_inline(_block_rich_text(block))
            out.append(f"{prefix}{'#' * level} {text}")
        elif block_type == "bulleted_list_item":
            text = _rich_to_inline(_block_rich_text(block))
            out.append(f"{prefix}- {text}")
            children = _block_children(block)
            if children:
                out.extend(_blocks_to_lines(children, indent=indent + 1))
        elif block_type == "numbered_list_item":
            text = _rich_to_inline(_block_rich_text(block))
            out.append(f"{prefix}1. {text}")
            children = _block_children(block)
            if children:
                out.extend(_blocks_to_lines(children, indent=indent + 1))
        elif block_type == "to_do":
            payload = block.get("to_do") if isinstance(block.get("to_do"), dict) else {}
            checked = bool(payload.get("checked"))
            text = _rich_to_inline(_block_rich_text(block))
            mark = "x" if checked else " "
            out.append(f"{prefix}- [{mark}] {text}")
            children = _block_children(block)
            if children:
                out.extend(_blocks_to_lines(children, indent=indent + 1))
        elif block_type == "code":
            payload = block.get("code") if isinstance(block.get("code"), dict) else {}
            lang = str(payload.get("language") or "").strip()
            text = _rich_to_inline(_block_rich_text(block))
            out.append(f"{prefix}```{lang}")
            out.extend(f"{prefix}{line}" for line in text.split("\n"))
            out.append(f"{prefix}```")
        elif block_type == "quote":
            text = _rich_to_inline(_block_rich_text(block))
            for line in text.split("\n"):
                out.append(f"{prefix}> {line}")
        elif block_type == "divider":
            out.append(f"{prefix}---")
        elif block_type == "toggle":
            title = _rich_to_inline(_block_rich_text(block))
            children = _block_children(block)
            child_md = "\n".join(_blocks_to_lines(children, indent=0))
            toggle_lines = [f"{prefix}+++ {title}".rstrip()]
            if child_md:
                toggle_lines.append("")
                toggle_lines.append(child_md)
            toggle_lines.append("")
            toggle_lines.append(f"{prefix}+++")
            out.extend(toggle_lines)
        else:
            raise NotionCanonicalDegradeError(
                "unsupported-block-type",
                f"cannot convert Notion block type {block_type!r} to markdown",
            )
        index += 1
    return out


def markdown_to_blocks(markdown: str) -> list[dict[str, Any]]:
    """Convert markdown into Notion block-children JSON."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    if "<!-- notion-unsupported:" in text:
        raise NotionCanonicalDegradeError(
            "unsupported-block-marker",
            "markdown contains unsupported Notion block marker",
        )
    blocks: list[dict[str, Any]] = []
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        list_indent = indent // 2
        if not stripped:
            index += 1
            continue
        if _DIVIDER.match(stripped):
            blocks.append(_make_block("divider", rich_text=[]))
            index += 1
            continue
        fence_match = _FENCE.match(stripped)
        if fence_match:
            lang = fence_match.group(1).strip()
            body_lines: list[str] = []
            index += 1
            while index < len(lines) and not _FENCE.match(lines[index].strip()):
                body_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            blocks.append(
                _make_block(
                    "code",
                    rich_text=_inline_to_rich("\n".join(body_lines)),
                    language=lang,
                )
            )
            continue
        if stripped.startswith("+++"):
            title = stripped[3:].strip()
            body_lines: list[str] = []
            index += 1
            while index < len(lines):
                if lines[index].strip() == "+++":
                    index += 1
                    break
                body_lines.append(lines[index])
                index += 1
            child_md = "\n".join(body_lines).strip("\n")
            children = markdown_to_blocks(child_md) if child_md else []
            blocks.append(
                _make_block(
                    "toggle",
                    rich_text=_inline_to_rich(title),
                    children=children,
                )
            )
            continue
        heading_match = _HEADING.match(stripped)
        if heading_match and indent == 0:
            level = len(heading_match.group(1))
            heading_type = {1: "heading_1", 2: "heading_2", 3: "heading_3"}[level]
            blocks.append(
                _make_block(
                    heading_type,
                    rich_text=_inline_to_rich(heading_match.group(2).strip()),
                )
            )
            index += 1
            continue
        if _TABLE_ROW.match(stripped):
            table_lines: list[str] = []
            while index < len(lines) and _TABLE_ROW.match(lines[index].strip()):
                table_lines.append(lines[index].strip())
                index += 1
            rows: list[list[str]] = []
            for table_line in table_lines:
                if _TABLE_SEP.match(table_line):
                    continue
                cells = [c.strip() for c in table_line.strip("|").split("|")]
                rows.append(cells)
            if rows:
                width = max(len(r) for r in rows)
                blocks.append(
                    _make_block(
                        "table",
                        table_width=width,
                        has_column_header=True,
                        has_row_header=False,
                    )
                )
                for row in rows:
                    while len(row) < width:
                        row.append("")
                    blocks.append(
                        _make_block(
                            "table_row",
                            cells=[_inline_to_rich(cell) for cell in row],
                        )
                    )
            continue
        checkbox_match = _CHECKBOX.match(stripped)
        if checkbox_match:
            checked = checkbox_match.group(1).lower() == "x"
            blocks.append(
                _make_block(
                    "to_do",
                    rich_text=_inline_to_rich(checkbox_match.group(2).strip()),
                    checked=checked,
                )
            )
            index += 1
            continue
        bullet_match = _BULLET.match(stripped)
        if bullet_match and not _CHECKBOX.match(stripped):
            blocks.append(
                _make_block(
                    "bulleted_list_item",
                    rich_text=_inline_to_rich(bullet_match.group(1).strip()),
                )
            )
            index += 1
            continue
        numbered_match = _NUMBERED.match(stripped)
        if numbered_match:
            blocks.append(
                _make_block(
                    "numbered_list_item",
                    rich_text=_inline_to_rich(numbered_match.group(1).strip()),
                )
            )
            index += 1
            continue
        quote_match = _QUOTE.match(stripped)
        if quote_match:
            quote_lines = [quote_match.group(1)]
            index += 1
            while index < len(lines) and _QUOTE.match(lines[index].strip()):
                quote_lines.append(_QUOTE.match(lines[index].strip()).group(1))
                index += 1
            blocks.append(
                _make_block(
                    "quote",
                    rich_text=_inline_to_rich("\n".join(quote_lines)),
                )
            )
            continue
        para_lines = [line]
        index += 1
        while index < len(lines):
            nxt = lines[index]
            nxt_stripped = nxt.strip()
            if (
                not nxt_stripped
                or _HEADING.match(nxt_stripped)
                or _BULLET.match(nxt_stripped)
                or _NUMBERED.match(nxt_stripped)
                or _QUOTE.match(nxt_stripped)
                or _DIVIDER.match(nxt_stripped)
                or nxt_stripped.startswith("```")
                or nxt_stripped.startswith("+++")
                or _TABLE_ROW.match(nxt_stripped)
            ):
                break
            para_lines.append(nxt)
            index += 1
        blocks.append(
            _make_block(
                "paragraph",
                rich_text=_inline_to_rich("\n".join(para_lines).strip()),
            )
        )
    return blocks


def notion_markdown_canonical(markdown: str) -> str:
    """Normalize markdown via block-children round-trip."""
    blocks = markdown_to_blocks(markdown)
    return blocks_to_markdown(blocks)


def simulate_block_children_round_trip(markdown: str) -> str:
    return notion_markdown_canonical(markdown)


def snapshot_from_notion_markdown(
    *,
    title: str,
    markdown: str,
    state: str = "open",
    labels: list[str] | None = None,
    comments: list[dict[str, Any]] | None = None,
) -> IssueSnapshot:
    body = notion_markdown_canonical(markdown)
    comment_records = [
        CommentRecord(
            id=str(c.get("id", "")),
            body=notion_markdown_canonical(str(c.get("body", ""))),
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
    assert_block_children_contract(data)
    if isinstance(data.get("markdown"), str):
        return notion_markdown_canonical(data["markdown"])
    if isinstance(data.get("blocks"), list):
        return blocks_to_markdown([b for b in data["blocks"] if isinstance(b, dict)])
    raise NotionCanonicalContractError(
        "missing-block-children",
        "fixture requires markdown or blocks (block-children contract)",
    )


def snapshot_from_fixture(data: dict[str, Any]) -> IssueSnapshot:
    assert_block_children_contract(data)
    return snapshot_from_notion_markdown(
        title=str(data.get("title") or "notion-canonical-fixture"),
        markdown=_body_from_fixture(data),
        state=str(data.get("state") or "open"),
        labels=list(data.get("labels") or []),
        comments=list(data.get("comments") or []),
    )


def split_rich_text_chunks(text: str, *, limit: int = NOTION_RICH_TEXT_CHAR_LIMIT) -> list[str]:
    """Split text so each segment fits Notion rich_text content limits (R11)."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, limit + 1)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip("\n")
    return chunks


def paginate_blocks(blocks: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Paginate block children for Notion append cap (R11)."""
    if not blocks:
        return []
    batches: list[list[dict[str, Any]]] = []
    for index in range(0, len(blocks), NOTION_BLOCK_APPEND_LIMIT):
        batches.append(blocks[index : index + NOTION_BLOCK_APPEND_LIMIT])
    return batches


def _overflow_comment_chunks(overflow: str, comments: list[CommentRecord]) -> list[CommentRecord]:
    new_comments = list(comments)
    prefix = CHUNK_OVERFLOW_MARKER
    remaining = overflow
    while remaining:
        max_piece = NOTION_RICH_TEXT_CHAR_LIMIT - len(prefix)
        if max_piece <= 0:
            raise RuntimeError("Notion overflow marker exceeds rich_text limit")
        piece = remaining[:max_piece]
        if not piece:
            break
        remaining = remaining[len(piece):]
        chunk_id = f"chunk-{len(new_comments)}"
        new_comments.append(
            CommentRecord(
                id=chunk_id,
                body=f"{prefix}{piece}",
                markers=["sw-chunk-overflow"],
            )
        )
    return new_comments


def _block_text_length(block: dict[str, Any]) -> int:
    block_type = str(block.get("type") or "")
    payload = block.get(block_type)
    if not isinstance(payload, dict):
        return 0
    rich_text = payload.get("rich_text")
    if not isinstance(rich_text, list):
        return 0
    return sum(
        len(str(item.get("text", {}).get("content") or ""))
        for item in rich_text
        if isinstance(item, dict) and isinstance(item.get("text"), dict)
    )


def chunk_body_for_notion(
    body: str,
    comments: list[CommentRecord],
) -> tuple[str, list[CommentRecord]]:
    """Split markdown for Notion block-append and rich_text limits (R11)."""
    blocks = markdown_to_blocks(body)
    overflow_markdown = ""
    if len(blocks) > NOTION_BLOCK_APPEND_LIMIT:
        overflow_markdown = blocks_to_markdown(blocks[NOTION_BLOCK_APPEND_LIMIT:])
        blocks = blocks[:NOTION_BLOCK_APPEND_LIMIT]
    elif any(_block_text_length(block) > NOTION_RICH_TEXT_CHAR_LIMIT for block in blocks):
        overflow_markdown = body
        blocks = []
    head = blocks_to_markdown(blocks) if blocks else ""
    if overflow_markdown:
        overflow_markdown = f"\n{overflow_markdown}" if head else overflow_markdown
    extra = _overflow_comment_chunks(overflow_markdown, list(comments)) if overflow_markdown else list(comments)
    if not extra[len(comments):]:
        return head, extra
    manifest = {
        "version": 1,
        "chunks": [
            {"index": idx, "commentId": c.id}
            for idx, c in enumerate(extra[len(comments):])
        ],
    }
    marker = f"<!-- sw-chunk-manifest: {json.dumps(manifest, sort_keys=True, ensure_ascii=False)} -->"
    if MARKER_CHUNK_MANIFEST.search(head):
        head = MARKER_CHUNK_MANIFEST.sub(marker, head)
    else:
        head = append_chunk_manifest_marker(head, marker)
    return head, extra


def normalize_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    snap = snapshot_from_fixture(data)
    return {
        "verdict": "ok",
        "contract": SUPPORTED_CONTRACT,
        "canonical": canonical_form(snap),
        "hash": canonical_hash(snap),
        "body": snap.body,
        "markdown": snap.body,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Notion block-children canonicalization (PRD 327)")
    sub = parser.add_subparsers(dest="command", required=True)
    norm = sub.add_parser("normalize", help="Normalize a Notion canonical fixture")
    norm.add_argument("--fixture", required=True, help="Path to fixture JSON")
    args = parser.parse_args(argv)
    if args.command == "normalize":
        try:
            result = normalize_fixture(Path(args.fixture))
        except (NotionCanonicalContractError, NotionCanonicalDegradeError) as exc:
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
