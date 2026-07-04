#!/usr/bin/env python3
"""Zero-shell enforcement guard — hard-fail end state (R30, R41 scaffold)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from _sw.cli import build_parser, run_module_main

ENFORCED_TREES = (
    "scripts",
    "core/scripts",
    "core/hooks",
    "core/providers",
    "hooks",
    "dist/cursor",
    "dist/claude-code",
)

SHELL_SUFFIXES = (".sh", ".bash", ".ps1")
SHELL_OUT_PATTERNS = (
    re.compile(r"subprocess\.(?:run|call|Popen)\([^)]*shell\s*=\s*True"),
    re.compile(r"os\.system\s*\("),
    re.compile(r"os\.popen\s*\("),
)

# gap-004 Defect A: `["bash", ..., "<script>.py", ...]` argv lists invoke a Python target
# via the bash interpreter instead of sys.executable — silently broken on the .sh->.py
# PRD-042 migration, not caught by SHELL_OUT_PATTERNS (no shell=True/os.system involved).
BASH_PY_INVOCATION_PATTERN = re.compile(r'\[\s*["\']bash["\']\s*,[^\]]*\.py["\']')


def find_bash_py_invocations(root: Path) -> list[str]:
    hits: list[str] = []
    for rel in ("scripts", "core/hooks", "core/scripts"):
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            posix = path.as_posix()
            if "/test/" in posix or "/_sw/vendor/" in posix or path.name == "zero-shell-guard.py":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            if BASH_PY_INVOCATION_PATTERN.search(text):
                hits.append(f"{path.relative_to(root).as_posix()}: bash-invokes-py")
    return hits


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_ledger(root: Path) -> dict:
    path = root / "core" / "sw-reference" / "script-port-ledger.json"
    if not path.is_file():
        return {"entries": []}
    return json.loads(path.read_text(encoding="utf-8"))


def ported_targets(ledger: dict) -> set[str]:
    closed: set[str] = set()
    for entry in ledger.get("entries", []):
        if entry.get("disposition") == "port" and entry.get("phase") == 1:
            target = entry.get("target", "")
            if target:
                closed.add(target)
    return closed


def find_shell_files(root: Path) -> list[str]:
    hits: list[str] = []
    for rel in ENFORCED_TREES:
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.suffix.lower() in SHELL_SUFFIXES and path.is_file():
                hits.append(path.relative_to(root).as_posix())
    return hits


def find_shell_outs(root: Path) -> list[str]:
    hits: list[str] = []
    for rel in ("scripts", "core/scripts", "sw"):
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            posix = path.as_posix()
            if "/_sw/vendor/" in posix:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            for pattern in SHELL_OUT_PATTERNS:
                if pattern.search(text):
                    hits.append(f"{path.relative_to(root).as_posix()}: {pattern.pattern}")
                    break
    return hits


def find_stale_bash_refs(root: Path, closed: set[str]) -> list[str]:
    if not closed:
        return []
    hits: list[str] = []
    needle = re.compile(r"bash\s+scripts/[^\s\"']+\.sh")
    search_roots = [root / "core", root / "docs", root / "scripts"]
    for base in search_roots:
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in {".md", ".mdc", ".py", ".json"}:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for match in needle.finditer(text):
                script = match.group(0).split()[-1]
                py_target = script.replace(".sh", ".py")
                if py_target in closed or script.replace("scripts/", "scripts/") in closed:
                    hits.append(f"{path.relative_to(root).as_posix()}: stale {match.group(0)}")
    return hits


def mode() -> str:
    return os.environ.get("SW_ZERO_SHELL_MODE", "fail").strip().lower()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="zero-shell-guard",
        description="Warn/fail on shell scripts and shell-outs in enforced trees (R30/R41).",
    )
    parser.add_argument("--mode", choices=["warn", "fail"], default=None)
    args = parser.parse_args(argv)
    root = repo_root()
    ledger = load_ledger(root)
    closed = ported_targets(ledger)
    shell_files = find_shell_files(root)
    shell_outs = find_shell_outs(root)
    stale = find_stale_bash_refs(root, closed)
    bash_py = find_bash_py_invocations(root)
    issues = shell_files + shell_outs + stale + bash_py
    active_mode = (args.mode or mode()).lower()
    if not issues:
        print("OK zero-shell-guard: no issues")
        return 0
    for issue in issues:
        line = f"{'WARN' if active_mode == 'warn' else 'FAIL'} zero-shell-guard: {issue}"
        print(line, file=sys.stderr)
    print(f"zero-shell-guard: {len(issues)} issue(s) mode={active_mode}", file=sys.stderr)
    return 0 if active_mode == "warn" else 1


if __name__ == "__main__":
    run_module_main(lambda: main())
