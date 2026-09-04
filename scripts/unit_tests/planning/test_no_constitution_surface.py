"""PRD 342 R36 — no constitution surface alongside ProjectDoctrine."""
from __future__ import annotations

from pathlib import Path

import pytest

# Doctrine remains the sole project-governance surface (PRD 330 / PRD 342 R36).
FORBIDDEN_BASENAMES = frozenset(
    {
        "constitution.md",
        "constitution.json",
        "constitution.yaml",
        "constitution.yml",
        "sw-constitution.md",
        "project-constitution.md",
        "project-constitution.json",
    }
)
FORBIDDEN_COMMAND_STEMS = frozenset(
    {
        "sw-constitution",
        "constitution",
    }
)
FORBIDDEN_SKILL_DIRS = frozenset(
    {
        "constitution",
        "sw-constitution",
        "project-constitution",
    }
)
SCAN_ROOTS = (
    "core/commands",
    "core/skills",
    "core/sw-reference",
    "scripts",
    "docs/guides",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_no_constitution_surface_alongside_doctrine() -> None:
    """R36 — ProjectDoctrine stays the governance surface; no constitution sibling."""
    root = _repo_root()
    doctrine = root / "scripts" / "project_doctrine.py"
    assert doctrine.is_file(), "ProjectDoctrine script missing"

    offenders: list[str] = []
    for rel in SCAN_ROOTS:
        base = root / rel
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            # Ignore this test file and vendored trees.
            if "unit_tests" in path.parts and path.name.startswith("test_no_constitution"):
                continue
            if any(part in {"node_modules", ".git", "__pycache__", "vendor"} for part in path.parts):
                continue
            name = path.name.lower()
            if name in FORBIDDEN_BASENAMES:
                offenders.append(str(path.relative_to(root)))
            if rel == "core/commands" and path.stem.lower() in FORBIDDEN_COMMAND_STEMS:
                offenders.append(str(path.relative_to(root)))

    for skill_dir in FORBIDDEN_SKILL_DIRS:
        candidate = root / "core" / "skills" / skill_dir
        if candidate.exists():
            offenders.append(str(candidate.relative_to(root)))

    assert offenders == [], f"constitution surface must not exist alongside doctrine: {offenders}"
