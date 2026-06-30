#!/usr/bin/env python3
"""Resolve plugin content root for workflow scripts."""
from __future__ import annotations
import sys
from pathlib import Path

def resolve_plugin_root(script_dir: Path) -> Path:
    parent = script_dir.parent.resolve()
    if (parent/"providers").is_dir() or (parent/"commands").is_dir():
        return parent
    if (parent/"core"/"providers").is_dir():
        return parent/"core"
    return parent

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    script_dir = Path(args[0]).resolve() if args else Path(__file__).resolve().parent
    print(resolve_plugin_root(script_dir))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
