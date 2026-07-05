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
    canonical_form,
    canonical_hash,
    normalize_body,
)

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
        return f"```\n{text}\n```\n"
    return ""


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
