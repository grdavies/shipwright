#!/usr/bin/env python3
"""Issue-store freeze compatibility checks (PRD 323 R23)."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from frozen_spec_ledger import frozen_body_hash  # noqa: E402


def test_resilience_artifact_hash_stable(tmp_path: Path) -> None:
    body = tmp_path / "tasks-323-debug-and-resilience.md"
    content = "# frozen resilience tasks\n\n- [ ] 5.1 generation fence\n"
    body.write_text(content, encoding="utf-8")
    text = body.read_text(encoding="utf-8")
    first = frozen_body_hash(text)
    second = frozen_body_hash(text)
    assert first == second
    assert len(first) >= 16


def test_tampered_body_changes_hash(tmp_path: Path) -> None:
    body = tmp_path / "unit.md"
    body.write_text("stable\n", encoding="utf-8")
    before = frozen_body_hash(body.read_text(encoding="utf-8"))
    body.write_text("stable\ntampered\n", encoding="utf-8")
    after = frozen_body_hash(body.read_text(encoding="utf-8"))
    assert before != after


def test_harness_modules_exist_for_freeze_surface() -> None:
    root = Path(__file__).resolve().parents[2]
    required = [
        root / "unit_tests" / "resilience" / "harness.py",
        root / "unit_tests" / "resilience" / "fuzz_transitions.py",
    ]
    missing = [str(path) for path in required if not path.is_file()]
    assert missing == []
