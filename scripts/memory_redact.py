#!/usr/bin/env python3
"""Deterministic R41 redaction chokepoint — stdin or file arg → stdout."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from secret_patterns import DENY_PATTERNS, REDACTIONS

DESTINATION_VALUES = frozenset({"local", "committed", "external", "cross-project", "logs"})
MANDATORY_REMOVAL_DESTINATIONS = frozenset({"external", "cross-project", "logs"})
ADVISORY_DESTINATIONS = frozenset({"local", "committed"})


class RedactionError(Exception):
    def __init__(self, message: str, *, detector: str | None = None) -> None:
        super().__init__(message)
        self.detector = detector


def scan_residual_detectors(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for deny in DENY_PATTERNS:
        hits = len(deny.pattern.findall(text))
        if hits:
            counts[deny.name] = hits
    return counts


def apply_substitutions(text: str) -> str:
    if not REDACTIONS:
        raise RedactionError("missing pattern set")
    out = text
    for pattern, replacement in REDACTIONS:
        out = pattern.sub(replacement, out)
    return out


def redact_with_postcondition(text: str, *, destination: str) -> tuple[str, dict[str, int]]:
    if destination not in DESTINATION_VALUES:
        raise ValueError(f"invalid destination: {destination!r}")
    substituted = apply_substitutions(text)
    residuals = scan_residual_detectors(substituted)
    if residuals and destination in MANDATORY_REMOVAL_DESTINATIONS:
        detector = sorted(residuals)[0]
        raise RedactionError(f"residual:{detector}", detector=detector)
    return substituted, residuals


def redact(text: str, *, destination: str) -> str:
    out, _residuals = redact_with_postcondition(text, destination=destination)
    return out


def redact_learning_derivation(text: str, *, may_egress: bool) -> tuple[str, dict[str, int]]:
    """Learning-store derivation write path — redact when store may egress (PRD 272 R14)."""
    destination = "external" if may_egress else "local"
    return redact_with_postcondition(text, destination=destination)


def emit_advisory_warnings(residuals: dict[str, int]) -> None:
    for detector, count in sorted(residuals.items()):
        print(f"warning: residual detector {detector}: {count}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if os.environ.get("SW_HARNESS") == "1" and "--destination" not in argv:
        argv = ["--destination", "external", *argv]
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

    try:
        out, residuals = redact_with_postcondition(text, destination=args.destination)
    except RedactionError as exc:
        if exc.detector:
            print(f"redaction failed: detector {exc.detector}", file=sys.stderr)
        else:
            print(str(exc), file=sys.stderr)
        return 1

    if residuals and args.destination in ADVISORY_DESTINATIONS:
        emit_advisory_warnings(residuals)
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
