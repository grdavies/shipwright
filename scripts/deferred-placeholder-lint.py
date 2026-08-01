#!/usr/bin/env python3
"""Deferral-marker lint — untracked placeholders fail closed (PRD 085 R17)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from _sw.cli import build_parser, run_module_main

REMEDIATION = "python3 scripts/deferred-placeholder-lint.py --check"
OPT_OUT_PREFIX = "deferred-placeholder-opt-out:"
DEFAULT_WINDOW = 3

DEFERRAL_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"until\s+later\s+phases?", re.I),
    re.compile(r"not\s+yet\s+implemented", re.I),
    re.compile(r"skeleton\s+stage", re.I),
    re.compile(r"\bTODO\b.*(?:phase|later|follow-?up|subsequent)", re.I),
    re.compile(r"(?:deferred|placeholder)\s+until", re.I),
    re.compile(r"until\s+(?:a\s+)?(?:later|subsequent|future)\s+phase", re.I),
)

TRACKED_REF_RE = re.compile(
    r"(?:"
    r"gap-0?\d+"
    r"|GAP-0?\d+"
    r"|PRD\s+0?\d+"
    r"|0\d{2}-prd-"
    r"|\bR\d+[a-z]?\b"
    r")",
    re.I,
)

SKIP_PARTS = (
    "/dist/",
    "/_sw/vendor/",
    "/scripts/test/fixtures/",
    "/scripts/unit_tests/",
)


def is_under_nested_worktree(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    return ".sw-worktrees" in rel.parts

SKIP_FILES = frozenset(
    {
        "deferred-placeholder-lint.py",
    }
)


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def has_opt_out(text: str) -> bool:
    return OPT_OUT_PREFIX in text


def is_skipped(path: Path, root: Path) -> bool:
    if path.name in SKIP_FILES:
        return True
    if path.name.startswith("harness_"):
        return True
    posix = path.as_posix()
    if any(part in posix for part in SKIP_PARTS):
        return True
    return is_under_nested_worktree(path, root)


def iter_scan_files(root: Path) -> list[Path]:
    scripts = root / "scripts"
    if not scripts.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(scripts.rglob("*.py")):
        if is_skipped(path, root):
            continue
        files.append(path)
    return files


def rel_path(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def window_has_tracked_reference(lines: list[str], index: int, window: int) -> bool:
    start = max(0, index - window)
    end = min(len(lines), index + window + 1)
    chunk = "\n".join(lines[start:end])
    return bool(TRACKED_REF_RE.search(chunk))


def line_has_deferral_marker(line: str) -> bool:
    return any(pattern.search(line) for pattern in DEFERRAL_MARKERS)


def scan_text(rel: str, text: str, *, window: int) -> list[dict[str, object]]:
    if has_opt_out(text):
        return []
    lines = text.splitlines()
    hits: list[dict[str, object]] = []
    for index, line in enumerate(lines):
        if not line_has_deferral_marker(line):
            continue
        if window_has_tracked_reference(lines, index, window):
            continue
        hits.append(
            {
                "file": rel,
                "line": index + 1,
                "text": line.strip()[:200],
            }
        )
    return hits


def scan_file(root: Path, path: Path, *, window: int) -> list[dict[str, object]]:
    rel = rel_path(root, path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return scan_text(rel, text, window=window)


def check(root: Path | None = None, *, window: int = DEFAULT_WINDOW) -> dict[str, object]:
    root = root or repo_root()
    violations: list[dict[str, object]] = []
    files = iter_scan_files(root)
    for path in files:
        violations.extend(scan_file(root, path, window=window))
    if violations:
        payload = {
            "verdict": "fail",
            "error": "deferred-placeholder",
            "violations": violations,
            "remediation": REMEDIATION,
            "window": window,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return payload
    result = {
        "verdict": "pass",
        "action": "deferred-placeholder-lint",
        "filesScanned": len(files),
        "window": window,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="deferred-placeholder-lint",
        description="Fail closed on untracked deferral markers in source comments.",
    )
    parser.add_argument("--check", action="store_true", help="Scan repository and exit non-zero on violations.")
    parser.add_argument(
        "--window",
        type=int,
        default=DEFAULT_WINDOW,
        help="Line window for adjacent tracked references (gap id, R-ID, PRD token).",
    )
    parser.add_argument("--file", type=Path, help="Scan a single file instead of the repository tree.")
    args = parser.parse_args(argv)
    if not args.check:
        print(
            json.dumps({"verdict": "fail", "error": "usage: deferred-placeholder-lint.py --check"}),
            file=sys.stderr,
        )
        return 2
    root = repo_root()
    window = max(0, int(args.window))
    if args.file is not None:
        path = args.file if args.file.is_absolute() else root / args.file
        violations = scan_file(root, path, window=window)
        if violations:
            print(
                json.dumps(
                    {
                        "verdict": "fail",
                        "error": "deferred-placeholder",
                        "violations": violations,
                        "remediation": REMEDIATION,
                        "window": window,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 1
        print(
            json.dumps(
                {
                    "verdict": "pass",
                    "action": "deferred-placeholder-lint",
                    "filesScanned": 1,
                    "window": window,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    result = check(root, window=window)
    return 0 if result.get("verdict") == "pass" else 1


if __name__ == "__main__":
    run_module_main(main)
