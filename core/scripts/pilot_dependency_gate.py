#!/usr/bin/env python3
"""TR0 dependency gate — proposed pilot refused until PRD-022 persist fixtures pass."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REQUIRED_PERSIST_FIXTURES = frozenset(
    {
        "exec-fidelity-out-of-order-halt",
        "resume-two-tier-deterministic",
        "resume-corrupt-plan-fail-closed",
    }
)

_PREREQ_SCRIPT = "test/pilot_022_prerequisite_check.py"


def _gate_scripts_dir() -> Path:
    return Path(__file__).resolve().parent


def _prerequisite_script() -> Path:
    return _gate_scripts_dir() / _PREREQ_SCRIPT


def proposed_pilot_enabled(root: Path | None = None) -> bool:
    """Return True when 022 exec-fidelity + resume fixtures pass."""
    _ = root
    return run_dependency_checks().get("verdict") == "pass"


def run_dependency_checks(root: Path | None = None) -> dict[str, Any]:
    _ = root
    script = _prerequisite_script()
    repo_root = _gate_scripts_dir().parent
    if not script.is_file():
        return {
            "verdict": "fail",
            "error": f"missing prerequisite script: {script}",
            "requiredFixtures": sorted(REQUIRED_PERSIST_FIXTURES),
        }
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    passed: list[str] = []
    failed: list[str] = []
    for line in (proc.stdout or "").splitlines():
        if line.startswith("OK  "):
            name = line.removeprefix("OK  ").strip()
            if name in REQUIRED_PERSIST_FIXTURES:
                passed.append(name)
        elif line.startswith("FAIL "):
            name = line.removeprefix("FAIL ").strip()
            if name in REQUIRED_PERSIST_FIXTURES:
                failed.append(name)
    if proc.returncode == 0 and not failed and len(passed) == len(REQUIRED_PERSIST_FIXTURES):
        return {
            "verdict": "pass",
            "requiredFixtures": sorted(REQUIRED_PERSIST_FIXTURES),
            "passed": sorted(passed),
        }
    return {
        "verdict": "fail",
        "requiredFixtures": sorted(REQUIRED_PERSIST_FIXTURES),
        "passed": sorted(passed),
        "failed": sorted(failed) or sorted(REQUIRED_PERSIST_FIXTURES - set(passed)),
        "exitCode": proc.returncode,
        "stderr": (proc.stderr or "").strip() or None,
    }


def emit_status(root: Path | None = None) -> None:
    _ = root
    print(json.dumps(run_dependency_checks(), ensure_ascii=False, indent=2))


def main() -> None:
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "error": "usage: pilot_dependency_gate.py <root> [status|enabled]",
                },
                indent=2,
            )
        )
        sys.exit(2)
    root = Path(sys.argv[1])
    cmd = sys.argv[2] if len(sys.argv) > 2 else "status"
    if cmd == "enabled":
        sys.exit(0 if proposed_pilot_enabled(root) else 20)
    emit_status(root)
    sys.exit(0 if proposed_pilot_enabled(root) else 1)


if __name__ == "__main__":
    main()
