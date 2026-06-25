#!/usr/bin/env python3
"""Deterministic R41 redaction chokepoint — stdin or file arg → stdout."""
import sys
from pathlib import Path

from secret_patterns import REDACTIONS


def redact(text: str) -> str:
    out = text
    for pattern, replacement in REDACTIONS:
        out = pattern.sub(replacement, out)
    return out


def main() -> None:
    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    else:
        text = sys.stdin.read()
    sys.stdout.write(redact(text))


if __name__ == "__main__":
    main()
