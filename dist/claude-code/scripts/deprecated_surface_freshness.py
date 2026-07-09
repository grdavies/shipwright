#!/usr/bin/env python3
"""Fail-closed deprecated-surface freshness for plugin harness scope (PRD 060 R10)."""
from __future__ import annotations

import fnmatch
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

MANIFEST_REL = "core/sw-reference/deprecated-surface-manifest.json"
REMEDIATION = "python3 scripts/deprecated_surface_freshness.py --check"
DISABLE_PREFIX = "deprecated-surface-disable:"


def emit(obj: dict, exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def load_manifest(root: Path) -> dict:
    path = root / MANIFEST_REL
    if not path.is_file():
        return {"version": 1, "surfaces": []}
    return json.loads(path.read_text(encoding="utf-8"))


def iter_harness_files(root: Path, globs: list[str]) -> list[Path]:
    files: list[Path] = []
    for pattern in globs:
        for path in root.glob(pattern):
            if path.is_file() and path.suffix in {".py", ".sh", ".md"}:
                files.append(path)
    return sorted(set(files))


def has_disable_annotation(text: str, surface_id: str) -> bool:
    needle = f"{DISABLE_PREFIX} {surface_id}"
    return needle in text or f"{DISABLE_PREFIX}{surface_id}" in text


def check_surface(root: Path, surface: dict) -> list[dict]:
    surface_id = str(surface.get("id") or "").strip()
    deprecated = str(surface.get("deprecatedPath") or "").strip()
    globs = list(surface.get("harnessGlobs") or ["scripts/unit_tests/**"])
    if not surface_id or not deprecated:
        return []
    violations: list[dict] = []
    for path in iter_harness_files(root, globs):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if deprecated not in text:
            continue
        if has_disable_annotation(text, surface_id):
            continue
        violations.append(
            {
                "surfaceId": surface_id,
                "deprecatedPath": deprecated,
                "file": str(path.relative_to(root)),
                "replacementPath": surface.get("replacementPath"),
            }
        )
    return violations


def check(root: Path) -> dict:
    manifest = load_manifest(root)
    surfaces = list(manifest.get("surfaces") or [])
    violations: list[dict] = []
    for surface in surfaces:
        if surface.get("disabled"):
            continue
        violations.extend(check_surface(root, surface))
    if violations:
        return {
            "verdict": "fail",
            "error": "deprecated-surface-freshness",
            "violations": violations,
            "remediation": REMEDIATION,
        }
    return {"verdict": "pass", "action": "deprecated-surface-freshness", "surfacesChecked": len(surfaces)}


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    root = Path(__file__).resolve().parent.parent
    if args == ["--check"]:
        result = check(root)
        emit(result, 0 if result.get("verdict") == "pass" else 1)
    emit({"verdict": "fail", "error": "usage: deprecated_surface_freshness.py --check"})


if __name__ == "__main__":
    main()
