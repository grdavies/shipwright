#!/usr/bin/env python3
"""Refuse bare-branch filter-branch (R42/R52)."""
from __future__ import annotations
import re, sys
from _sw.cli import run_module_main

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "check-command":
        print("usage: redaction-guard check-command -- <git args...>", file=sys.stderr); return 2
    rest = args[1:]; rest = rest[1:] if rest and rest[0]=="--" else rest
    joined = " ".join(rest)
    if "filter-branch" not in joined or ".." in joined: return 0
    print("redaction-guard: refuse bare-branch filter-branch", file=sys.stderr); return 20
if __name__ == "__main__": run_module_main(main)
