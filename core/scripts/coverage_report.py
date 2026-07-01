#!/usr/bin/env python3
"""Aggregate trace .cover files under a coverdir (PRD 051 R8 — stdlib-only)."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from _sw.cli import run_module_main

EXEC_LINE = re.compile(r"^\s+(\d+):\s*(.*)$")
UNEXEC_LINE = re.compile(r"^\s{4,}([^:\d].*)$")


def resolve_source_for_cover(cover_path: Path, header_source: str, scripts_root: Path) -> Path | None:
    header = header_source.strip()
    if header.startswith("/") and header.endswith(".py"):
        candidate = Path(header)
        if candidate.is_file():
            return candidate.resolve()
    stem = cover_path.stem
    direct = scripts_root / f"{stem}.py"
    if direct.is_file():
        return direct.resolve()
    matches = [p for p in scripts_root.rglob(f"{stem}.py") if p.is_file()]
    if len(matches) == 1:
        return matches[0].resolve()
    return None


def parse_cover_file(path: Path, *, scripts_root: Path | None = None) -> tuple[Path | None, int, int]:
    """Return (resolved_source_path, executed_lines, total_lines)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines:
        return None, 0, 0
    header = lines[0]
    header_source = header[2:].strip() if header.startswith("# ") else ""
    source = resolve_source_for_cover(path, header_source, scripts_root) if scripts_root else None
    executed = 0
    total = 0
    for raw in lines[1:]:
        m_exec = EXEC_LINE.match(raw)
        if m_exec:
            total += 1
            if int(m_exec.group(1)) > 0:
                executed += 1
            continue
        if UNEXEC_LINE.match(raw):
            total += 1
    return source, executed, total


def aggregate_coverdir(coverdir: Path, *, scripts_root: Path) -> dict[str, dict[str, int]]:
    scripts_prefix = scripts_root.resolve()
    per_script: dict[str, dict[str, int]] = {}
    for cover in sorted(coverdir.glob("*.cover")):
        source, executed, total = parse_cover_file(cover, scripts_root=scripts_prefix)
        if source is None:
            continue
        try:
            rel = str(source.relative_to(scripts_prefix))
        except ValueError:
            continue
        bucket = per_script.setdefault(rel, {"executed": 0, "total": 0})
        bucket["executed"] += executed
        bucket["total"] += total
    return per_script


def print_report(coverdir: Path, *, scripts_root: Path) -> dict[str, object]:
    per_script = aggregate_coverdir(coverdir, scripts_root=scripts_root)
    total_executed = 0
    total_lines = 0
    for rel in sorted(per_script):
        row = per_script[rel]
        executed = row["executed"]
        total = row["total"]
        total_executed += executed
        total_lines += total
        pct = (100.0 * executed / total) if total else 0.0
        print(f"{rel}: {executed}/{total} lines ({pct:.1f}%)")
    aggregate_pct = (100.0 * total_executed / total_lines) if total_lines else 0.0
    print(f"aggregate scripts/: {total_executed}/{total_lines} lines ({aggregate_pct:.1f}%)")
    return {
        "perScript": per_script,
        "aggregate": {"executed": total_executed, "total": total_lines, "percent": aggregate_pct},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coverage_report.py")
    parser.add_argument("--coverdir", required=True)
    parser.add_argument("--scripts-root", default="scripts")
    args = parser.parse_args(argv)
    coverdir = Path(args.coverdir)
    if not coverdir.is_dir():
        print(f"coverage_report: missing coverdir {coverdir}", file=sys.stderr)
        return 2
    scripts_root = Path(args.scripts_root).resolve()
    print_report(coverdir, scripts_root=scripts_root)
    return 0


if __name__ == "__main__":
    run_module_main(main)
