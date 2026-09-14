#!/usr/bin/env python3
"""Codex hook entry — processes stdin via lifecycle (PRD 352 R5)."""
from __future__ import annotations
import sys
from pathlib import Path
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import lifecycle  # noqa: E402
raise SystemExit(lifecycle.main(sys.argv[1:]))
