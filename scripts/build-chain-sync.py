#!/usr/bin/env python3
"""Unified build-chain sync."""
from __future__ import annotations
import hashlib, subprocess, sys
from pathlib import Path
from _sw.cli import run_module_main

def dist_hash(root: Path) -> str:
    dirs = [root/"dist/cursor", root/"dist/claude-code"]
    if not any(d.is_dir() for d in dirs): return ""
    h = hashlib.sha256()
    for d in dirs:
        if not d.is_dir(): continue
        for f in sorted(d.rglob("*")):
            if f.is_file():
                h.update(f.relative_to(root).as_posix().encode()); h.update(f.read_bytes())
    return h.hexdigest()

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parent.parent
    golden = root/"scripts/test/fixtures/parity/cursor-golden.manifest"
    check_only = args == ["--check"]
    if check_only:
        fail = 0
        for cmd in ([sys.executable, str(root/"scripts/build-chain-sot-lint.py")],
                    [sys.executable, str(root/"scripts/test/run_core_scripts_parity_fixtures.py")],
                    [sys.executable, str(root/"scripts/test/run_parity_fixtures.py")]):
            if subprocess.run(cmd, cwd=str(root), capture_output=True).returncode != 0: fail = 1
        before = dist_hash(root)
        if subprocess.run([sys.executable,"-m","sw","generate","--all"], cwd=str(root), capture_output=True).returncode != 0: fail = 1
        after = dist_hash(root)
        if before and before != after: fail = 1
        if fail:
            print("build-chain-sync --check: parity drift detected", file=sys.stderr); return 20
        print("build-chain-sync --check: parity OK"); return 0
    before = dist_hash(root)
    subprocess.run([sys.executable, str(root/"scripts/copy-to-core.py")], cwd=str(root), check=True)
    subprocess.run([sys.executable,"-m","sw","generate","--all"], cwd=str(root), check=True)
    after = dist_hash(root)
    if before != after:
        subprocess.run([sys.executable, str(root/"scripts/snapshot-tree.py"), str(golden)], cwd=str(root), check=True)
        print(f"build-chain-sync: dist changed — updated {golden}")
    print("build-chain-sync: complete"); return 0
if __name__ == "__main__": run_module_main(main)
