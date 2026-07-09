#!/usr/bin/env python3
"""Unified build-chain sync (PRD 060 R12 — generate → golden → copy-to-core)."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from _sw.cli import run_module_main

REMEDIATION = "python3 scripts/build-chain-sync.py"


def dist_hash(root: Path) -> str:
    dirs = [root / "dist/cursor", root / "dist/claude-code"]
    if not any(d.is_dir() for d in dirs):
        return ""
    h = hashlib.sha256()
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*")):
            if f.is_file():
                h.update(f.relative_to(root).as_posix().encode())
                h.update(f.read_bytes())
    return h.hexdigest()


def _emit_fail(step: str, error: str, *, exit_code: int = 1) -> int:
    payload = {
        "verdict": "fail",
        "step": step,
        "error": error,
        "remediation": REMEDIATION,
    }
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
    return exit_code


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parent.parent
    golden = root / "scripts/test/fixtures/parity/cursor-golden.manifest"
    check_only = args == ["--check"]
    if check_only:
        fail = 0
        for cmd in (
            [sys.executable, str(root / "scripts/build-chain-sot-lint.py")],
            [sys.executable, str(root / "scripts/test/run_pytest.py"), "scripts/unit_tests/meta/test_core_scripts_parity.py", "-q"],
            [sys.executable, str(root / "scripts/test/run_pytest.py"), "scripts/unit_tests/meta/test_parity.py", "-q"],
        ):
            if subprocess.run(cmd, cwd=str(root), capture_output=True).returncode != 0:
                fail = 1
        before = dist_hash(root)
        if subprocess.run([sys.executable, "-m", "sw", "generate", "--all"], cwd=str(root), capture_output=True).returncode != 0:
            fail = 1
        after = dist_hash(root)
        if before and before != after:
            fail = 1
        if fail:
            return _emit_fail("freshness-check", "parity drift detected", exit_code=20)
        print("build-chain-sync --check: parity OK")
        return 0

    before = dist_hash(root)
    if subprocess.run([sys.executable, "-m", "sw", "generate", "--all"], cwd=str(root)).returncode != 0:
        return _emit_fail("generate", "sw generate --all failed")
    after = dist_hash(root)
    if before != after:
        if subprocess.run([sys.executable, str(root / "scripts/snapshot-tree.py"), str(golden)], cwd=str(root)).returncode != 0:
            return _emit_fail("golden-manifest", "snapshot-tree failed")
        print(f"build-chain-sync: dist changed — updated {golden}")
    if subprocess.run([sys.executable, str(root / "scripts/copy-to-core.py")], cwd=str(root)).returncode != 0:
        return _emit_fail("copy-to-core", "copy-to-core failed")
    print("build-chain-sync: complete")
    return 0


if __name__ == "__main__":
    run_module_main(main)
