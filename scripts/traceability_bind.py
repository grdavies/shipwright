#!/usr/bin/env python3
"""PRD 039 R9 — freeze immutable test baseline at traceability-bind (pre-red)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from _sw.cli import run_module_main

BASELINE_VERSION = 1
TEST_GLOBS = (
    "tests/**",
    "test/**",
    "**/test_*.py",
    "**/*_test.py",
    "**/conftest.py",
)
COVERAGE_CANDIDATES = (
    "pyproject.toml",
    "setup.cfg",
    ".coveragerc",
    "tox.ini",
    ".github/workflows/*.yml",
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _repo_rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _discover_test_files(root: Path) -> list[Path]:
    found: set[Path] = set()
    for pattern in TEST_GLOBS:
        for p in root.glob(pattern):
            if p.is_file() and not p.name.startswith("."):
                found.add(p.resolve())
    return sorted(found)


def _discover_coverage_configs(root: Path) -> list[Path]:
    out: list[Path] = []
    for pattern in COVERAGE_CANDIDATES:
        for p in root.glob(pattern):
            if p.is_file():
                out.append(p.resolve())
    return sorted(set(out))


def _count_assertions(text: str) -> int:
    patterns = (
        re.compile(r"\bassert\b"),
        re.compile(r"self\.assert\w+\s*\("),
        re.compile(r"\bexpect\s*\("),
    )
    return sum(len(p.findall(text)) for p in patterns)


def _coverage_thresholds(text: str) -> list[float]:
    pat = re.compile(
        r"(fail_under|cov-fail-under|--cov-fail-under)\s*[=:]?\s*(\d+(?:\.\d+)?)",
        re.I,
    )
    out: list[float] = []
    for m in pat.finditer(text):
        try:
            out.append(float(m.group(2)))
        except ValueError:
            continue
    return out


def _file_entry(path: Path, root: Path) -> dict:
    data = path.read_bytes()
    text = data.decode("utf-8", errors="replace")
    ent = {
        "path": _repo_rel(path, root),
        "sha256": _sha256_bytes(data),
        "size": len(data),
    }
    if path.suffix == ".py" or "test" in path.name.lower():
        ent["assertionCount"] = _count_assertions(text)
    return ent


def bind_baseline(root: Path, *, task_ref: str, rid: str, extra_paths: list[str]) -> dict:
    root = root.resolve()
    files: dict[str, dict] = {}
    for p in _discover_test_files(root):
        ent = _file_entry(p, root)
        files[ent["path"]] = ent
    for raw in extra_paths:
        p = (root / raw).resolve()
        if p.is_file():
            ent = _file_entry(p, root)
            files[ent["path"]] = ent
    coverage: list[dict] = []
    for p in _discover_coverage_configs(root):
        ent = _file_entry(p, root)
        cfg_text = p.read_text(encoding="utf-8", errors="replace")
        ent["coverageThresholds"] = _coverage_thresholds(cfg_text)
        coverage.append(ent)
    return {
        "version": BASELINE_VERSION,
        "taskRef": task_ref,
        "rid": rid,
        "boundAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "root": str(root),
        "files": files,
        "coverageConfig": coverage,
    }


def cmd_bind(args: argparse.Namespace) -> int:
    root = Path(args.root or ".").resolve()
    if not root.is_dir():
        print(json.dumps({"verdict": "fail", "error": "invalid root"}))
        return 20
    extra = list(args.path or [])
    baseline = bind_baseline(
        root,
        task_ref=str(args.task_ref or ""),
        rid=str(args.rid or ""),
        extra_paths=extra,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    try:
        out.chmod(0o600)
    except OSError:
        pass
    print(
        json.dumps(
            {
                "verdict": "pass",
                "out": str(out),
                "fileCount": len(baseline["files"]),
                "coverageConfigCount": len(baseline["coverageConfig"]),
            }
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="traceability_bind")
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("bind", help="Capture pre-red test baseline")
    b.add_argument("--root", default=".", help="Repository root")
    b.add_argument("--out", required=True, help="Baseline JSON output path")
    b.add_argument("--task-ref", default="", help="Task ref (e.g. 1.2)")
    b.add_argument("--rid", default="", help="Requirement id")
    b.add_argument(
        "--path",
        action="append",
        default=[],
        help="Additional relative file paths to include",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.command == "bind":
        return cmd_bind(args)
    print(json.dumps({"verdict": "fail", "error": "unknown command"}))
    return 20


if __name__ == "__main__":
    run_module_main(main)
