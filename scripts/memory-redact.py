#!/usr/bin/env python3
"""Deterministic R41 redaction chokepoint — stdin or file arg → stdout."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory_redact import main

if __name__ == "__main__":
    main()
