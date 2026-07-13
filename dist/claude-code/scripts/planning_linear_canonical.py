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
from pathlib import Path
from typing import Any

from planning_canonical import (
    CommentRecord,
    IssueSnapshot,
    canonical_form,
    canonical_hash,
    normalize_body,
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
