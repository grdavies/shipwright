#!/usr/bin/env python3
"""PRD 039 R10 — advisory over-mock scan for tests/fixtures/conftest."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from _sw.cli import run_module_main

MOCK_PATTERNS = (
    re.compile(r"\bunittest\.mock\b"),
    re.compile(r"\bfrom\s+mock\s+import\b"),
    re.compile(r"\b@patch\b"),
    re.compile(r"\bMagicMock\b"),
    re.compile(r"\bMock\s*\("),
    re.compile(r"\bmocker\.patch\b"),
    re.compile(r"\bmonkeypatch\.setattr\b"),
)
SUT_HINTS = re.compile(r"\b(import|from)\s+(\w+)")


def scan_file(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"path": str(path), "error": "unreadable"}
    mock_hits = sum(len(p.findall(text)) for p in MOCK_PATTERNS)
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    sut_hints = len(SUT_HINTS.findall(text))
    ratio = mock_hits / max(len(lines), 1)
    flags: list[str] = []
    if mock_hits >= 6 and ratio >= 0.35:
        flags.append("high_mock_ratio")
    if mock_hits >= 10:
        flags.append("mock_fan_in")
    return {
        "path": str(path),
        "mockHits": mock_hits,
        "lineCount": len(lines),
        "mockRatio": round(ratio, 3),
        "sutHints": sut_hints,
        "flags": flags,
    }


def discover(root: Path) -> list[Path]:
    patterns = ("tests/**", "test/**", "**/fixtures/**", "**/conftest.py")
    found: set[Path] = set()
    for pat in patterns:
        for p in root.glob(pat):
            if p.is_file() and p.suffix in {".py", ".ts", ".js"}:
                found.add(p)
    return sorted(found)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="over_mock_scan")
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--path", action="append", default=[], help="Additional file paths")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    root = Path(args.root).resolve()
    paths = discover(root)
    for raw in args.path:
        p = Path(raw)
        if not p.is_absolute():
            p = root / raw
        if p.is_file():
            paths.append(p)
    paths = sorted(set(paths))

    findings = [scan_file(p) for p in paths]
    flagged = [f for f in findings if f.get("flags")]

    payload = {
        "verdict": "advisory" if flagged else "pass",
        "advisory": True,
        "filesScanned": len(findings),
        "flagged": flagged,
        "findings": findings,
    }
    print(json.dumps(payload))
    return 10 if flagged else 0


if __name__ == "__main__":
    run_module_main(main)
