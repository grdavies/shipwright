#!/usr/bin/env python3
"""Neutral verify.test sentinel for shipped example configs."""
from __future__ import annotations
import sys
from _sw.cli import run_module_main

def main(argv=None):
    print("verify.test not configured — run /sw-init", file=sys.stderr)
    return 1
if __name__ == "__main__": run_module_main(main)
