"""PRD 091 R1 — stale planning-cache backend naming regression guard."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPO_ROOT / "scripts"

FORBIDDEN_PATTERNS = [
    re.compile(r"MemoryLocalCacheBackend"),
    re.compile(r'backend_id\s*=\s*["\']memory["\']'),
    re.compile(r'["\']memory["\']\s*:\s*ReplicatedPlanningCacheBackend'),
]

ALLOWLIST_SUBSTRINGS = [
    "BACKEND_CONFIG_ALIASES",
    "test_planning_cache_rename.py",
]


def _iter_script_sources() -> list[Path]:
    paths: list[Path] = []
    for path in SCRIPTS_ROOT.rglob("*.py"):
        rel = path.relative_to(SCRIPTS_ROOT)
        if "_sw/vendor" in rel.parts or path.name == "test_planning_cache_rename.py":
            continue
        paths.append(path)
    return paths


def test_no_stale_planning_cache_backend_names() -> None:
    violations: list[str] = []
    for path in _iter_script_sources():
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_PATTERNS:
            for match in pattern.finditer(text):
                line = text[: match.start()].count("\n") + 1
                snippet = text.splitlines()[line - 1].strip()
                if any(allow in snippet for allow in ALLOWLIST_SUBSTRINGS):
                    continue
                violations.append(f"{path.relative_to(REPO_ROOT)}:{line}: {snippet}")
    assert not violations, "stale planning-cache backend naming:\n" + "\n".join(violations)


def test_legacy_cache_dir_migrates_to_planning_cache(tmp_path: Path) -> None:
    import sys

    if str(SCRIPTS_ROOT) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_ROOT))

    from _planning_pkg_loader import load_backends_package

    backends = load_backends_package()
    ReplicatedPlanningCacheBackend = backends.ReplicatedPlanningCacheBackend

    cfg = {"version": 1, "planning": {"store": {"backend": "planning-cache"}}, "memory": {"project": "proj"}}
    legacy = tmp_path / ".cursor" / "sw-memory" / "planning-bodies" / "proj" / "unit.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy-body", encoding="utf-8")

    backend = ReplicatedPlanningCacheBackend(tmp_path, cfg)
    new_dir = backend._local_cache_dir()
    assert new_dir.is_dir()
    assert (new_dir / "unit.md").read_text(encoding="utf-8") == "legacy-body"
    assert not legacy.is_file()

    # idempotent second run
    backend._local_cache_dir()
    assert (new_dir / "unit.md").read_text(encoding="utf-8") == "legacy-body"
