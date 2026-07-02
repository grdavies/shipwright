#!/usr/bin/env python3
"""PRD 039 phase-3 TDD hardening fixtures (R8–R12)."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from _fixture_lib import repo_root

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
ROOT = repo_root(__file__)
FX = _TEST_DIR / "fixtures" / "tdd-gate"
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))


def ok(msg: str) -> None:
    print(f"OK  {msg}")


def fail(msg: str) -> int:
    print(f"FAIL {msg}")
    return 1


def run_json(cmd: list[str]) -> tuple[int, dict]:
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    try:
        data = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        data = {"raw": proc.stdout, "err": proc.stderr}
    return proc.returncode, data


def main() -> int:
    errors = 0
    py = sys.executable
    tdd = [py, str(ROOT / "scripts/tdd-gate.py")]

    # R8 silent skip rejected in require-skip-reason mode
    st = FX / "silent-skip-status.json"
    ec, data = run_json(tdd + ["--status", str(st), "--require-skip-reason"])
    if ec == 20 and data.get("verdict") == "fail":
        ok("R8 silent skip rejected")
    else:
        errors = fail(f"R8 silent skip: ec={ec} {data}") or errors

    # R8 bound scenario skip rejected
    st2 = FX / "bound-skip-status.json"
    ec, data = run_json(tdd + ["--status", str(st2), "--require-skip-reason"])
    if ec == 20:
        ok("R8 skip with bound testScenario rejected")
    else:
        errors = fail(f"R8 bound skip: ec={ec}") or errors

    # R8 valid pass
    st3 = FX / "valid-pass-status.json"
    ec, data = run_json(tdd + ["--status", str(st3)])
    if ec == 0 and data.get("verdict") == "pass":
        ok("R8 red-green pass")
    else:
        errors = fail(f"R8 pass: ec={ec}") or errors

    # R9 traceability bind + tamper
    with tempfile.TemporaryDirectory() as tmp:
        mini = Path(tmp)
        (mini / "tests").mkdir(parents=True, exist_ok=True)
        shutil.copy(FX / "tamper-mini/tests_test_sample.py", mini / "tests/test_sample.py")
        shutil.copy(FX / "tamper-mini/pyproject.toml", mini / "pyproject.toml")
        (mini / "tests").mkdir(parents=True, exist_ok=True)
        baseline_path = mini / "baseline.json"
        ec, data = run_json(
            [
                py,
                str(ROOT / "scripts/traceability_bind.py"),
                "bind",
                "--root",
                str(mini),
                "--out",
                str(baseline_path),
                "--task-ref",
                "3.2",
            ]
        )
        if ec != 0:
            errors = fail(f"R9 bind: {data}") or errors
        else:
            ok("R9 traceability bind")
        ec, data = run_json(
            [
                py,
                str(ROOT / "scripts/test_tamper_check.py"),
                "--baseline",
                str(baseline_path),
                "--root",
                str(mini),
            ]
        )
        if ec == 0:
            ok("R9 tamper clean tree")
        else:
            errors = fail(f"R9 tamper clean: {data}") or errors
        # delete test file
        (mini / "tests/test_sample.py").unlink()
        ec, data = run_json(
            [
                py,
                str(ROOT / "scripts/test_tamper_check.py"),
                "--baseline",
                str(baseline_path),
                "--root",
                str(mini),
            ]
        )
        if ec == 20 and any(f.get("code") == "test_file_deleted" for f in data.get("blocking", [])):
            ok("R9a deleted test flagged")
        else:
            errors = fail(f"R9a delete: {data}") or errors

        # assertion drop + testWeakened disagreement
        shutil.copy(FX / "tamper-mini/tests_test_weakened.py", mini / "tests/test_sample.py")
        baseline2 = json.loads(baseline_path.read_text(encoding="utf-8"))
        status_path = mini / "status.json"
        status_path.write_text(json.dumps({"testWeakened": False}) + "\n", encoding="utf-8")
        ec, data = run_json(
            [
                py,
                str(ROOT / "scripts/test_tamper_check.py"),
                "--baseline",
                str(baseline_path),
                "--root",
                str(mini),
                "--status",
                str(status_path),
            ]
        )
        if ec == 20:
            ok("R9 assertion drop / disagreement")
        else:
            errors = fail(f"R9 weaken: ec={ec} {data}") or errors

        # coverage threshold drop
        shutil.copy(FX / "tamper-mini/tests_test_sample.py", mini / "tests/test_sample.py")
        run_json(
            [
                py,
                str(ROOT / "scripts/traceability_bind.py"),
                "bind",
                "--root",
                str(mini),
                "--out",
                str(baseline_path),
            ]
        )
        shutil.copy(FX / "tamper-mini/pyproject_lower.toml", mini / "pyproject.toml")
        ec, data = run_json(
            [
                py,
                str(ROOT / "scripts/test_tamper_check.py"),
                "--baseline",
                str(baseline_path),
                "--root",
                str(mini),
            ]
        )
        if ec == 20 and any(f.get("code") == "coverage_threshold_drop" for f in data.get("blocking", [])):
            ok("R9a coverage threshold drop")
        else:
            errors = fail(f"R9 coverage: {data}") or errors

    # R10 over-mock advisory
    ec, data = run_json(
        [py, str(ROOT / "scripts/over_mock_scan.py"), "--path", str(FX / "overmock_sample.py")]
    )
    if ec == 10 and data.get("verdict") == "advisory":
        ok("R10 over-mock advisory")
    else:
        errors = fail(f"R10 over-mock: ec={ec} {data}") or errors

    # R11 zombies gate
    zg = [py, str(ROOT / "scripts/zombies_gate.py")]
    ec, data = run_json(zg + ["--record", str(FX / "zombies-missing-record.json")])
    if ec == 20:
        ok("R11 zombies missing checklist")
    else:
        errors = fail(f"R11 missing: {ec}") or errors
    ec, data = run_json(zg + ["--record", str(FX / "zombies-ok-record.json")])
    if ec == 0:
        ok("R11 zombies checklist present")
    else:
        errors = fail(f"R11 ok: {ec}") or errors

    # R12 verify mutation skipped by default
    ec, data = run_json([py, str(ROOT / "scripts/verify_mutation.py"), "--root", str(ROOT)])
    if ec == 0 and data.get("status") == "skipped":
        ok("R12 mutation hook skipped when disabled")
    else:
        errors = fail(f"R12 mutation: {data}") or errors

    # Phase 3 doc integration smoke
    skill = (ROOT / "core/skills/execute-discipline/SKILL.md").read_text(encoding="utf-8")
    if "traceability_bind" in skill and "test_tamper_check" in skill:
        ok("execute-discipline phase-3 hooks documented")
    else:
        errors = fail("execute-discipline integration") or errors

    schema = (ROOT / ".sw/config.schema.json").read_text(encoding="utf-8")
    if "verifyMutation" in schema:
        ok("config.schema verifyMutation present")
    else:
        errors = fail("config.schema verifyMutation") or errors

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
