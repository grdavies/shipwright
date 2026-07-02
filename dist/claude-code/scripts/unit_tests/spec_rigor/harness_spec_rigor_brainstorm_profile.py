#!/usr/bin/env python3
"""spec-rigor brainstorm artifact profile fixtures (PRD 051 TR3)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _fixture_lib import repo_root

FAIL = 0


def ok(msg: str) -> None:
    print(f"OK  {msg}")


def bad(msg: str) -> None:
    global FAIL
    print(f"FAIL {msg}")
    FAIL = 1


def run_check(root: Path, path: Path) -> tuple[int, dict]:
    proc = subprocess.run(
        [
            sys.executable,
            str(root / "scripts/spec-rigor-check.py"),
            "--artifact",
            "brainstorm",
            "--path",
            str(path),
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"verdict": "fail", "raw": proc.stdout, "stderr": proc.stderr}
    return proc.returncode, data


def main() -> int:
    root = repo_root(__file__)
    fix = root / "scripts/test/fixtures/spec-rigor-brainstorm-profile-required-sections"
    fail_doc = fix / "brainstorm-fail-missing-success-criteria.md"
    pass_doc = fix / "brainstorm-pass.md"

    ec_fail, data_fail = run_check(root, fail_doc)
    if ec_fail == 20 and data_fail.get("verdict") == "fail":
        ok("spec-rigor-brainstorm-profile-required-sections: negative missing Success Criteria")
    else:
        bad(
            "spec-rigor-brainstorm-profile-required-sections: expected exit 20 fail for missing Success Criteria"
        )

    ec_pass, data_pass = run_check(root, pass_doc)
    if ec_pass == 0 and data_pass.get("verdict") == "pass":
        ok("spec-rigor-brainstorm-profile-required-sections: positive compliant doc")
    else:
        bad("spec-rigor-brainstorm-profile-required-sections: expected pass for compliant doc")

    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
