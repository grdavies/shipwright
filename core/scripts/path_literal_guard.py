#!/usr/bin/env python3
"""Relocated-path literal regression guard (PRD 342 R11).

Static literal-string detector for inventory legacy path families and the
configuration file path. Mirror-aware so a ``scripts/`` + ``core/scripts/``
pair reports once. Monotonic ratchet: only *new* references fail.

Exit codes: 0 pass, 20 fail.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from _sw.cli import build_parser, run_module_main

INVENTORY_REL = Path("core/sw-reference/state-root-inventory.json")
RATCHET_REL = Path("core/sw-reference/path-literal-ratchet.json")
GUARD_REL = Path("scripts/path_literal_guard.py")

SCAN_ROOTS = (
    "scripts",
    "core/scripts",
    "core/hooks",
    "hooks",
    "sw",
    "platforms",
)

# False-negative class: literals in test fixtures and generated data files.
SKIP_PATH_MARKERS = (
    "/unit_tests/",
    "/unit-tests/",
    "/test/",
    "/tests/",
    "/fixtures/",
    "/_sw/vendor/",
    "/generated/",
)

CONFIG_PATH_NEEDLES = (
    ".cursor/workflow.config.json",
    "workflow.config.json",
)

FALSE_NEGATIVE_CLASSES = (
    "runtime-fragments",
    "fstring-or-format",
    "config-or-env",
    "fixtures-and-generated",
)


def repo_root(start: Path | None = None) -> Path:
    start = (start or Path(__file__).resolve()).resolve()
    if start.is_file():
        start = start.parent
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists() or (candidate / ".git").is_file():
            return candidate
        if (candidate / "core" / "sw-reference").is_dir() and (candidate / "scripts").is_dir():
            return candidate
    return Path(__file__).resolve().parent.parent


def load_inventory(root: Path) -> dict[str, Any]:
    path = root / INVENTORY_REL
    if not path.is_file():
        raise FileNotFoundError(f"missing inventory: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("inventory must be an object")
    return data


def _needle_usable(legacy: str) -> bool:
    """Drop bare roots that substring-match unrelated tokens (e.g. ``.sw``)."""
    if not legacy:
        return False
    # Exact single-segment roots are too broad for literal substring detection;
    # their child inventory entries still cover relocated families.
    if legacy in {".sw", ".cursor"}:
        return False
    return True


def legacy_needles(inventory: dict[str, Any]) -> tuple[str, ...]:
    needles: list[str] = []
    for entry in inventory.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        legacy = str(entry.get("legacyPath") or "").strip()
        if _needle_usable(legacy):
            needles.append(legacy)
    for extra in CONFIG_PATH_NEEDLES:
        if extra not in needles and _needle_usable(extra):
            needles.append(extra)
    # Longest first so more specific families win when recording which needle hit.
    needles.sort(key=len, reverse=True)
    return tuple(needles)


def canonicalize_rel(rel: str) -> str:
    """Collapse ``core/scripts/X`` onto ``scripts/X`` for mirror-awareness."""
    if rel.startswith("core/scripts/"):
        return "scripts/" + rel[len("core/scripts/") :]
    return rel


def mirror_pair_rel(rel: str) -> str | None:
    if rel.startswith("scripts/"):
        return "core/scripts/" + rel[len("scripts/") :]
    if rel.startswith("core/scripts/"):
        return "scripts/" + rel[len("core/scripts/") :]
    return None


def should_skip_rel(rel: str) -> bool:
    posix = f"/{rel}"
    if any(marker in posix for marker in SKIP_PATH_MARKERS):
        return True
    if rel in {GUARD_REL.as_posix(), "core/scripts/path_literal_guard.py"}:
        return True
    if rel.endswith("path_literal_guard.py"):
        return True
    return False


def iter_scan_files(root: Path) -> Iterable[Path]:
    for tree in SCAN_ROOTS:
        base = root / tree
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if should_skip_rel(rel):
                continue
            yield path


def _string_constants(tree: ast.AST) -> list[tuple[int, str]]:
    """Return (lineno, value) for static string constants only.

    Intentionally ignores JoinedStr (f-strings), FormattedValue, and non-constant
    expressions so the named false-negative classes stay undetected.
    """
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lineno = int(getattr(node, "lineno", 1) or 1)
            out.append((lineno, node.value))
    return out


def find_literal_hits(text: str, needles: tuple[str, ...]) -> list[tuple[int, str, str]]:
    """Return (lineno, needle, literal) for AST string constants containing a needle."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    hits: list[tuple[int, str, str]] = []
    for lineno, value in _string_constants(tree):
        for needle in needles:
            if needle in value:
                hits.append((lineno, needle, value))
                break
    return hits


def site_key(canonical_rel: str, literal: str) -> str:
    return f"{canonical_rel}::{literal}"


def scan_repo(root: Path, needles: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    inventory = load_inventory(root)
    needles = needles if needles is not None else legacy_needles(inventory)
    findings: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for path in iter_scan_files(root):
        rel = path.relative_to(root).as_posix()
        canonical = canonicalize_rel(rel)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, needle, literal in find_literal_hits(text, needles):
            key = site_key(canonical, literal)
            if key in seen_keys:
                continue
            # Prefer reporting the scripts/ side when both mirrors exist.
            pair = mirror_pair_rel(rel)
            if rel.startswith("core/scripts/") and pair is not None:
                pair_path = root / pair
                if pair_path.is_file():
                    # Defer to scripts/ scan; skip duplicate mirror hit.
                    continue
            seen_keys.add(key)
            findings.append(
                {
                    "key": key,
                    "path": canonical,
                    "sourcePath": rel,
                    "line": lineno,
                    "needle": needle,
                    "literal": literal,
                }
            )
    findings.sort(key=lambda item: (item["path"], item["line"], item["literal"]))
    return findings


def load_ratchet(root: Path) -> set[str]:
    path = root / RATCHET_REL
    if not path.is_file():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    refs = data.get("refs") if isinstance(data, dict) else None
    if not isinstance(refs, list):
        return set()
    return {str(item) for item in refs}


def write_ratchet(root: Path, findings: list[dict[str, Any]]) -> Path:
    path = root / RATCHET_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    refs = sorted({str(item["key"]) for item in findings})
    payload = {
        "schemaVersion": 1,
        "description": (
            "Monotonic ratchet of known relocated-path literal sites (PRD 342 R11). "
            "Only keys absent from this list fail the guard."
        ),
        "refs": refs,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def evaluate(root: Path | None = None, *, write_baseline: bool = False) -> dict[str, Any]:
    root = (root or repo_root()).resolve()
    findings = scan_repo(root)
    if write_baseline:
        write_ratchet(root, findings)
        return {
            "verdict": "pass",
            "reason": "baseline-written",
            "action": "path-literal-guard",
            "refCount": len(findings),
            "ratchetPath": RATCHET_REL.as_posix(),
            "falseNegativeClasses": list(FALSE_NEGATIVE_CLASSES),
        }

    baseline = load_ratchet(root)
    new_refs = [item for item in findings if item["key"] not in baseline]
    if new_refs:
        return {
            "verdict": "fail",
            "reason": "new-path-literal",
            "action": "path-literal-guard",
            "newRefCount": len(new_refs),
            "knownRefCount": len(baseline),
            "scannedRefCount": len(findings),
            "newRefs": new_refs[:50],
            "falseNegativeClasses": list(FALSE_NEGATIVE_CLASSES),
        }
    return {
        "verdict": "pass",
        "reason": "no-new-path-literals",
        "action": "path-literal-guard",
        "newRefCount": 0,
        "knownRefCount": len(baseline),
        "scannedRefCount": len(findings),
        "falseNegativeClasses": list(FALSE_NEGATIVE_CLASSES),
    }


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="path_literal_guard",
        description="Fail on new relocated-path string literals (PRD 342 R11).",
    )
    parser.add_argument("--root", type=Path, default=None, help="Repository root")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Write current findings into the monotonic ratchet and exit 0",
    )
    args = parser.parse_args(argv)
    root = (args.root or repo_root()).resolve()
    payload = evaluate(root, write_baseline=bool(args.write_baseline))
    print(json.dumps(payload, indent=2))
    if payload.get("verdict") == "pass":
        return 0
    return 20


if __name__ == "__main__":
    run_module_main(main)
