#!/usr/bin/env python3
"""Shared safe evidence reads — library surface."""
from __future__ import annotations
import sys
from _sw.cli import run_module_main
def main(argv=None):
    print("evidence-read: import evidence_read module", file=sys.stderr); return 0
if __name__ == "__main__": run_module_main(main)
