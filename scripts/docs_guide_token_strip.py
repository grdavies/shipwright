#!/usr/bin/env python3
"""Line-local provenance token strip for adopter-facing guides (PRD 068 R11)."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROVENANCE = re.compile(r"\bPRD\s*\d+|\bR\d+\b|\bGAP-\d+", re.IGNORECASE)
INLINE_WHITESPACE = re.compile(r"[ \t]{2,}")


def split_line_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    return line, ""


def strip_provenance_line(line: str) -> str:
    """Remove PRD/R-ID/GAP tokens on one line; preserve blank lines."""
    body, ending = split_line_ending(line)
    if not body.strip():
        return line
    cleaned = PROVENANCE.sub(" ", body)
    cleaned = INLINE_WHITESPACE.sub(" ", cleaned).strip()
    if not cleaned:
        return ending or ""
    return f"{cleaned}{ending}"


def strip_guide_text(text: str) -> str:
    """Strip provenance tokens line-locally without cross-newline whitespace collapse."""
    if not text:
        return text
    lines = text.splitlines(keepends=True)
    if not lines:
        return strip_provenance_line(text)
    return "".join(strip_provenance_line(line) for line in lines)


def strip_guide_file(path: Path) -> str:
    return strip_guide_text(path.read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strip PRD/R-ID/GAP tokens from guide markdown")
    parser.add_argument("paths", nargs="+", help="Markdown files to strip in place")
    parser.add_argument("--check", action="store_true", help="Exit non-zero when any file would change")
    args = parser.parse_args(argv)

    changed = 0
    for raw in args.paths:
        path = Path(raw)
        original = path.read_text(encoding="utf-8")
        stripped = strip_guide_text(original)
        if stripped != original:
            changed += 1
            if not args.check:
                path.write_text(stripped, encoding="utf-8")
    if args.check and changed:
        print(f"docs-guide-token-strip: {changed} file(s) need stripping", file=sys.stderr)
        return 1
    print(f"docs-guide-token-strip: ok ({len(args.paths)} file(s))")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
