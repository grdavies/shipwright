#!/usr/bin/env python3
"""Health check: stale pre-port layout + Python floor (R34)."""
from __future__ import annotations
import json
import sys
from pathlib import Path

from _sw.cli import build_parser, run_module_main
from _sw.interpreter import probe

SHELL_SUFFIXES = {".sh", ".bash", ".ps1"}
HOOK_NAMES = ("pre-commit", "pre-push", "commit-msg")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    build_parser(prog="doctor", description="Detect stale layout and Python issues.").parse_args(argv)
    root = repo_root()
    issues: list[str] = []
    remediation: list[str] = []

    for rel in ("hooks", "core/hooks", "scripts"):
        base = root / rel
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.suffix.lower() in SHELL_SUFFIXES and path.is_file():
                issues.append(f"stale-shell:{path.relative_to(root).as_posix()}")
    for hook in HOOK_NAMES:
        py_hook = root / "core" / "hooks" / f"{hook}.py"
        sh_hook = root / "hooks" / f"{hook}.sh"
        if sh_hook.is_file() and not py_hook.is_file():
            issues.append(f"missing-python-hook:{hook}")
            remediation.append(f"Run: python3 scripts/install.py --force")

    try:
        result = probe()
        python_ok = result.ok
        python_detail = result.version_text
    except Exception as exc:  # pragma: no cover
        python_ok = False
        python_detail = str(exc)

    if not python_ok:
        issues.append(f"python-floor:{python_detail}")
        remediation.append("Install CPython >= 3.9 and ensure python3 is on PATH")

    verdict = "pass" if not issues else "warn"
    out = {
        "verdict": verdict,
        "issues": issues,
        "remediation": remediation,
        "python": python_detail,
    }
    print(json.dumps(out, indent=2))
    return 0 if verdict == "pass" else 1


if __name__ == "__main__":
    run_module_main(main)
