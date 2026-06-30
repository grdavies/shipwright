#!/usr/bin/env python3
"""Detect Cursor vs Claude Code platform."""
from __future__ import annotations
import json, os, sys
from _sw.cli import run_module_main

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h","--help"): print("usage: detect-platform [--json]"); return 0
    if args and args[0] not in ("--json",):
        print(json.dumps({"verdict":"fail","error":"unknown argument"}), file=sys.stderr); return 2
    platform = os.environ.get("SW_SETUP_PLATFORM","").strip()
    if not platform:
        if os.environ.get("CURSOR_AGENT") or os.environ.get("CURSOR_PLUGIN_ROOT"): platform="cursor"
        elif os.environ.get("CLAUDE_CODE") or os.environ.get("CLAUDE_CODE_SSE_PORT") or os.environ.get("CLAUDE_PLUGIN_ROOT"): platform="claude-code"
        else: platform="cursor"
    if platform not in ("cursor","claude-code"):
        print(json.dumps({"verdict":"fail","error":"unknown platform"}), file=sys.stderr); return 2
    print(json.dumps({"platform":platform}) if "--json" in args else platform); return 0
if __name__ == "__main__": run_module_main(main)
