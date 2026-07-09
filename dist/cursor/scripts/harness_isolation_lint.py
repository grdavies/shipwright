#!/usr/bin/env python3
"""Harness isolation lint — shared workflow.config + baseline I/O (PRD 060 R14–R15)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REMEDIATION = "python3 scripts/harness_isolation_lint.py --check"
OPT_OUT_PREFIX = "harness-isolation-opt-out:"


def emit(obj: dict, exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def has_opt_out(text: str) -> bool:
    return OPT_OUT_PREFIX in text


def mutates_shared_workflow_config(text: str) -> bool:
    if "workflow.config.json" not in text:
        return False
    if "CFG_BACKUP" in text and "restore_config" in text and "write_text" not in text:
        return False
    if "write_text" in text and "workflow.config.json" in text:
        return True
    if re.search(r"cp\s+[^\n]*workflow\.config\.json", text):
        return True
    if re.search(r">\s*[^\n]*workflow\.config\.json", text):
        return True
    return False


def baseline_io_without_isolation(text: str) -> bool:
    if "verify-baseline" not in text and "baseline.verify.json" not in text and ".shipwright/baseline" not in text:
        return False
    safe_markers = ("$TMP", "$FIXTURES", "mktemp", "tempfile", "baseline_path_for", "ctx.mktemp")
    if ".shipwright/baseline" in text and not any(marker in text for marker in safe_markers):
        return True
    if "verify-baseline" in text and not any(marker in text for marker in safe_markers):
        return True
    return False


def scan_file(root: Path, path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if has_opt_out(text):
        return None
    mutates = mutates_shared_workflow_config(text)
    baseline = baseline_io_without_isolation(text)
    if mutates and baseline:
        return {
            "file": str(path.relative_to(root)),
            "mutatesSharedConfig": mutates,
            "baselineIoWithoutIsolation": baseline,
        }
    return None


def check(root: Path) -> dict:
    violations: list[dict] = []
    unit_tests = root / "scripts/unit_tests"
    files = sorted(unit_tests.rglob("*.py")) if unit_tests.is_dir() else []
    for path in files:
        hit = scan_file(root, path)
        if hit:
            violations.append(hit)
    if violations:
        emit(
            {
                "verdict": "fail",
                "error": "harness-isolation",
                "violations": violations,
                "remediation": REMEDIATION,
            },
            1,
        )
    emit({"verdict": "pass", "action": "harness-isolation-lint", "filesScanned": len(files)})
    return 0


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    root = Path(__file__).resolve().parent.parent
    if args == ["--check"]:
        result = check(root)
        emit(result, 0 if result.get("verdict") == "pass" else 1)
    emit({"verdict": "fail", "error": "usage: harness_isolation_lint.py --check"})


if __name__ == "__main__":
    main()
