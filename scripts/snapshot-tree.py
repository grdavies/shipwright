#!/usr/bin/env python3
"""Snapshot emittable plugin content to parity manifest."""
from __future__ import annotations
import argparse, hashlib, sys
from pathlib import Path
from _sw.cli import run_module_main

EMITTABLE = ("commands","skills","rules","agents","providers")

def should_skip(relpath: str) -> bool:
    if "__pycache__" in relpath or relpath.endswith(".pyc"): return True
    if relpath.endswith(".bak"): return True
    if "/.git/" in relpath or "/node_modules/" in relpath: return True
    if relpath == "scripts/test" or relpath.startswith("scripts/test/"): return True
    if relpath == "scripts/install.py": return True
    if relpath.startswith("hooks"): return True
    return False

def collect(snapshot_root: Path):
    for d in EMITTABLE:
        base = snapshot_root/d
        if base.is_dir():
            for f in sorted(base.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(snapshot_root).as_posix()
                    if not should_skip(rel): yield rel, f
    scripts = snapshot_root/"scripts"
    if scripts.is_dir():
        for f in sorted(scripts.rglob("*")):
            if f.is_file():
                rel = f.relative_to(snapshot_root).as_posix()
                if not should_skip(rel): yield rel, f

def main(argv=None):
    root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser()
    p.add_argument("out", nargs="?", default="-")
    ns = p.parse_args(list(sys.argv[1:] if argv is None else argv))
    if (root/"dist/cursor/providers").is_dir() or (root/"dist/cursor/commands").is_dir():
        snap = root/"dist/cursor"
    elif (root/"core/providers").is_dir() or (root/"core/commands").is_dir():
        snap = root/"core"
    else:
        snap = root
    lines = []
    seen = set()
    for rel, f in collect(snap):
        if rel in seen: continue
        seen.add(rel)
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        lines.append(f"{rel}\t{h}")
    out = "\n".join(sorted(lines)) + ("\n" if lines else "")
    if ns.out == "-": sys.stdout.write(out)
    else:
        out_p = Path(ns.out); out_p.parent.mkdir(parents=True, exist_ok=True); out_p.write_text(out, encoding="utf-8")
    return 0
if __name__ == "__main__": run_module_main(main)
