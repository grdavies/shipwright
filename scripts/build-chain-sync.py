#!/usr/bin/env python3
"""Unified build-chain sync (PRD 060 R12 — generate → golden → core content sync)."""
from __future__ import annotations

import hashlib
import shutil
import tempfile
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
            # Bytecode caches under dist/ are environmental and must not fail freshness.
            if "__pycache__" in f.parts or f.suffix in {".pyc", ".pyo"}:
                continue
            if f.is_file():
                h.update(f.relative_to(root).as_posix().encode())
                h.update(f.read_bytes())
    return h.hexdigest()


def _dist_dirs(root: Path) -> list[Path]:
    return [root / "dist/cursor", root / "dist/claude-code"]


def _snapshot_dist(root: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for d in _dist_dirs(root):
        if d.is_dir():
            shutil.copytree(d, dest / d.name, dirs_exist_ok=True, symlinks=True)


def _restore_dist_snapshot(root: Path, snap: Path) -> None:
    (root / "dist").mkdir(parents=True, exist_ok=True)
    for name in ("cursor", "claude-code"):
        src = snap / name
        dst = root / "dist" / name
        if dst.exists():
            shutil.rmtree(dst, ignore_errors=True)
        if src.is_dir():
            shutil.copytree(src, dst, symlinks=True)



def _refresh_planning_store_shims(root: Path) -> int:
    proc = subprocess.run(
        [sys.executable, str(root / "scripts/planning_shim_gen.py"), "--root", str(root), "generate"],
        cwd=str(root),
    )
    return proc.returncode


def _run_generate_pipeline(root: Path, *, capture: bool = False) -> int:
    kwargs = {"cwd": str(root), "capture_output": capture}
    copy_to_core = root / "scripts" / "copy-to-core.py"
    if copy_to_core.is_file():
        gen_cmd = [sys.executable, str(copy_to_core), "generate"]
    else:
        gen_cmd = [sys.executable, "-m", "sw", "generate", "--all"]
    if subprocess.run(gen_cmd, **kwargs).returncode != 0:
        return 1
    sync_script = copy_to_core if copy_to_core.is_file() else root / "scripts/core_content_sync.py"
    sync_argv = [sys.executable, str(sync_script)]
    if sync_script == copy_to_core:
        sync_argv.append("sync")
    if subprocess.run(sync_argv, **kwargs).returncode != 0:
        return 1
    if _refresh_planning_store_shims(root) != 0:
        return 1
    return 0


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
            [sys.executable, str(root / "scripts/test/run_pytest.py"), "scripts/unit_tests/test_zipapp_manifest_completeness.py", "-q"],
            [sys.executable, str(root / "scripts/test/run_pytest.py"), "scripts/unit_tests/meta/test_parity.py", "-q"],
        ):
            if subprocess.run(cmd, cwd=str(root), capture_output=True).returncode != 0:
                fail = 1
        snap_dir = Path(tempfile.mkdtemp(prefix="sw-dist-snap-"))
        try:
            _snapshot_dist(root, snap_dir)
            before = dist_hash(root)
            if _run_generate_pipeline(root, capture=True) != 0:
                fail = 1
            after = dist_hash(root)
            if before and before != after:
                fail = 1
        finally:
            _restore_dist_snapshot(root, snap_dir)
            shutil.rmtree(snap_dir, ignore_errors=True)
        if fail:
            return _emit_fail("freshness-check", "parity drift detected", exit_code=20)
        print("build-chain-sync --check: parity OK")
        return 0

    before = dist_hash(root)
    if _run_generate_pipeline(root) != 0:
        return _emit_fail("generate", "build-chain generate pipeline failed")
    after = dist_hash(root)
    if before != after:
        if subprocess.run([sys.executable, str(root / "scripts/snapshot-tree.py"), str(golden)], cwd=str(root)).returncode != 0:
            return _emit_fail("golden-manifest", "snapshot-tree failed")
        print(f"build-chain-sync: dist changed — updated {golden}")
    print("build-chain-sync: complete")
    return 0


if __name__ == "__main__":
    run_module_main(main)
