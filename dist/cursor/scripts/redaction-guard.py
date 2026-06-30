#!/usr/bin/env python3
"""Mechanical guard: refuse bare-branch filter-branch rewriting shared history (R42/R52)."""
from __future__ import annotations
import re
import sys

USAGE = "usage: redaction-guard.py check-command -- <git args...>"


def check_filter_branch(args: list[str]) -> int:
    joined = " ".join(args)
    if "filter-branch" not in joined:
        return 0
    if ".." in joined:
        return 0
    print("redaction-guard: refuse bare-branch filter-branch — use range-scoped redaction (base..branch)", file=sys.stderr)
    print("See rules/sw-redaction-scope.mdc", file=sys.stderr)
    return 20


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] != "check-command":
        print(USAGE, file=sys.stderr)
        return 2
    args = sys.argv[2:]
    if args and args[0] == "--":
        args = args[1:]
    return check_filter_branch(args)


if __name__ == "__main__":
    raise SystemExit(main())
