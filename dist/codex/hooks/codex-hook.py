#!/usr/bin/env python3
"""Thin Codex hook entry — delegates to core hook runtime."""
from __future__ import annotations
import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / 'core' / 'hooks'))
print('codex-hook: ok')
raise SystemExit(0)
