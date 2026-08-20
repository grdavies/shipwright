#!/usr/bin/env python3
"""Property suite rollup coverage (PRD 323 R8)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent

REQUIRED_MODULES = {
    "test_property_generation_fence.py": {"fencing", "generation"},
    "test_property_cancel_fence.py": {"cancel"},
    "test_property_cache_identity.py": {"cache"},
    "test_property_finalize_checkpoint.py": {"checkpoint", "finalize"},
}


def test_suite_files_present() -> None:
    missing = [name for name in REQUIRED_MODULES if not (_HERE / name).is_file()]
    assert missing == [], f"missing property suite modules: {missing}"


def test_suite_defines_executable_tests() -> None:
    for name in REQUIRED_MODULES:
        path = _HERE / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        tests = [
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ]
        assert tests, f"{name} must define at least one test_* function"


@pytest.mark.parametrize("name,needles", sorted(REQUIRED_MODULES.items()))
def test_suite_covers_required_classes(name: str, needles: set[str]) -> None:
    text = (_HERE / name).read_text(encoding="utf-8").lower()
    assert any(needle in text for needle in needles), f"{name} missing class markers {needles}"
