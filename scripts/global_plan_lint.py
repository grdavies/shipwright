#!/usr/bin/env python3
"""Build-time lint for legacy repository-global deliver plan references (PRD 081 R18)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from _sw.cli import build_parser, run_module_main

REMEDIATION = "python3 scripts/global_plan_lint.py --check"

LEGACY_PLAN_LITERAL_RE = re.compile(r"sw-deliver-plan\.json")
GLOBAL_PLAN_REL_RE = re.compile(r"\bGLOBAL_PLAN_REL\b")

HELPER_REL = Path("scripts/wave_run_paths.py")
OWN_TEST_REL = Path("scripts/unit_tests/wave/test_global_plan_lint.py")

# Migrated readers — must not reference the legacy global plan path or constant.
CONVERTED_READERS = frozenset(
    {
        "scripts/wave_merge.py",
        "scripts/wave_terminal.py",
        "scripts/wave_failure.py",
        "scripts/wave_memory.py",
        "scripts/wave_living_docs.py",
        "scripts/cleanup_lib.py",
        "scripts/docs-currency-gate.py",
    }
)

# Transitional modules that still compare against or default to the legacy path.
TRANSITIONAL_CONSTANT_USERS = frozenset(
    {
        "scripts/wave_deliver_loop.py",
        "scripts/wave_lifecycle.py",
        "scripts/wave_deliver.py",
        "scripts/unit_tests/wave/test_reader_migration_core.py",
        "scripts/unit_tests/wave/test_reader_migration_aux.py",
    }
)

# Visibility / ignore templates — not plan readers.
PERMITTED_LITERAL_ONLY = frozenset(
    {
        "scripts/wave_run_paths.py",
        "scripts/unit_tests/wave/test_global_plan_lint.py",
        "scripts/gitignore_generate.py",
    }
)

SKIP_SUFFIX_PARTS = (
    "/_sw/vendor/",
    "/dist/",
    "/scripts/test/fixtures/",
)


def is_skipped_harness(path: Path) -> bool:
    if path.name.startswith("harness_"):
        return True
    if path.parent.name == "test" and path.name.startswith("run_") and path.name.endswith("_fixtures.py"):
        return True
    return False


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def rel_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def permitted_literal_paths() -> frozenset[str]:
    return frozenset(str(p) for p in PERMITTED_LITERAL_ONLY)


def permitted_constant_paths() -> frozenset[str]:
    return permitted_literal_paths() | frozenset(TRANSITIONAL_CONSTANT_USERS)


def iter_scan_files(root: Path) -> list[Path]:
    scripts = root / "scripts"
    if not scripts.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(scripts.rglob("*.py")):
        posix = path.as_posix()
        if any(part in posix for part in SKIP_SUFFIX_PARTS):
            continue
        if path.name == "global_plan_lint.py":
            continue
        if is_skipped_harness(path):
            continue
        files.append(path)
    return files


def scan_text(rel: str, text: str) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    has_literal = bool(LEGACY_PLAN_LITERAL_RE.search(text))
    has_constant = bool(GLOBAL_PLAN_REL_RE.search(text))
    if not has_literal and not has_constant:
        return hits

    if rel in CONVERTED_READERS:
        if has_literal:
            hits.append({"file": rel, "kind": "legacy-plan-literal", "scope": "converted-reader"})
        if has_constant:
            hits.append({"file": rel, "kind": "global-plan-constant", "scope": "converted-reader"})
        return hits

    if has_literal and rel not in permitted_literal_paths():
        hits.append({"file": rel, "kind": "legacy-plan-literal", "scope": "repository"})

    if has_constant and rel not in permitted_constant_paths():
        hits.append({"file": rel, "kind": "global-plan-constant", "scope": "repository"})

    return hits


def scan_file(root: Path, path: Path) -> list[dict[str, str]]:
    rel = rel_posix(root, path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return scan_text(rel, text)


def check(root: Path | None = None) -> dict[str, object]:
    root = root or repo_root()
    violations: list[dict[str, str]] = []
    files = iter_scan_files(root)
    for path in files:
        violations.extend(scan_file(root, path))
    if violations:
        payload = {
            "verdict": "fail",
            "error": "global-plan-literal",
            "violations": violations,
            "remediation": REMEDIATION,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return payload
    result = {"verdict": "pass", "action": "global-plan-lint", "filesScanned": len(files)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="global-plan-lint",
        description="Fail when source files reference the legacy repository-global deliver plan.",
    )
    parser.add_argument("--check", action="store_true", help="Scan the repository and exit non-zero on violations.")
    args = parser.parse_args(argv)
    if not args.check:
        print(json.dumps({"verdict": "fail", "error": "usage: global_plan_lint.py --check"}), file=sys.stderr)
        return 2
    result = check()
    return 0 if result.get("verdict") == "pass" else 1


if __name__ == "__main__":
    run_module_main(main)
