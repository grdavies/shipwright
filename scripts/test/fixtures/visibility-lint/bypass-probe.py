"""Fixture probe — unwrapped planning body read (must fail lint)."""
from pathlib import Path

def leak(root: Path) -> str:
    return (root / "docs/planning/prd/x/body.md").read_text(encoding="utf-8")
