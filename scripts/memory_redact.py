#!/usr/bin/env python3
"""Deterministic R41 redaction chokepoint — stdin or file arg → stdout."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from secret_patterns import REDACTIONS

DESTINATION_VALUES = frozenset({"local", "committed", "external", "cross-project", "logs"})


def redact(text: str, *, destination: str) -> str:
    if destination not in DESTINATION_VALUES:
        raise ValueError(f"invalid destination: {destination!r}")
    out = text
    for pattern, replacement in REDACTIONS:
        out = pattern.sub(replacement, out)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="R41 redaction chokepoint")
    parser.add_argument(
        "--destination",
        required=True,
        choices=sorted(DESTINATION_VALUES),
        help="Redaction destination tier (required; no default)",
    )
    parser.add_argument("file", nargs="?", help="Input file (stdin if omitted)")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    else:
        text = sys.stdin.read()
    sys.stdout.write(redact(text, destination=args.destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
