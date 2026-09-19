#!/usr/bin/env python3
"""Snapshot emittable plugin content to parity manifest."""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from _sw.cli import run_module_main

EMITTABLE = ("commands", "skills", "rules", "agents", "providers")
_COMMAND_DOC_MIRROR_NAMES = (
    "sw-doc.md",
    "sw-tasks.md",
    "sw-freeze.md",
    "sw-deliver.md",
)


def should_skip(relpath: str) -> bool:
    if "__pycache__" in relpath or relpath.endswith(".pyc"):
        return True
    if relpath.endswith(".bak"):
        return True
    if "/.git/" in relpath or "/node_modules/" in relpath:
        return True
    if "/.cursor/sw-coverage/" in relpath or relpath.startswith(".cursor/sw-coverage/"):
        return True
    if relpath.startswith("scripts/.cursor/sw-coverage/"):
        return True
    if relpath == "scripts/test" or relpath.startswith("scripts/test/"):
        return True
    if relpath == "scripts/install.py":
        return True
    if relpath.startswith("hooks"):
        return True
    return False


def collect(snapshot_root: Path):
    for d in EMITTABLE:
        base = snapshot_root / d
        if base.is_dir():
            for f in sorted(base.rglob("*")):
                if f.is_file():
                    rel = f.relative_to(snapshot_root).as_posix()
                    if not should_skip(rel):
                        yield rel, f
    scripts = snapshot_root / "scripts"
    if scripts.is_dir():
        for f in sorted(scripts.rglob("*")):
            if f.is_file():
                rel = f.relative_to(snapshot_root).as_posix()
                if not should_skip(rel):
                    yield rel, f


def resolve_snapshot_root(root: Path) -> Path:
    """Prefer post-generate ``dist/cursor`` when present (PRD 362 R15/R16)."""
    dist_cursor = root / "dist" / "cursor"
    if (dist_cursor / "providers").is_dir() or (dist_cursor / "commands").is_dir():
        return dist_cursor
    core = root / "core"
    if (core / "providers").is_dir() or (core / "commands").is_dir():
        return core
    return root


def is_golden_manifest_path(root: Path, out: Path) -> bool:
    rel = out.resolve()
    golden = (root / "scripts/test/fixtures/parity/cursor-golden.manifest").resolve()
    return rel == golden or rel.name == "cursor-golden.manifest"


def stale_dist_command_mirrors(root: Path) -> list[str]:
    """Return command doc basenames whose dist/cursor mirror lags core (snapshot-before-generate guard)."""
    stale: list[str] = []
    for name in _COMMAND_DOC_MIRROR_NAMES:
        core_doc = root / "core" / "commands" / name
        dist_doc = root / "dist" / "cursor" / "commands" / name
        if not core_doc.is_file():
            continue
        if not dist_doc.is_file():
            stale.append(name)
            continue
        if hashlib.sha256(core_doc.read_bytes()).digest() != hashlib.sha256(dist_doc.read_bytes()).digest():
            stale.append(name)
    return stale


def validate_golden_snapshot_preconditions(root: Path, out_path: Path) -> str | None:
    if not is_golden_manifest_path(root, out_path):
        return None
    dist_cursor = root / "dist" / "cursor"
    if not dist_cursor.is_dir():
        return "golden-snapshot:dist-cursor-missing"
    stale = stale_dist_command_mirrors(root)
    if stale:
        return f"golden-snapshot:dist-stale-before-generate:{','.join(stale)}"
    return None


def main(argv=None):
    default_root = Path(__file__).resolve().parent.parent
    p = argparse.ArgumentParser()
    p.add_argument("out", nargs="?", default="-")
    p.add_argument("--root", type=Path, default=None, help="Repository root (default: parent of scripts/)")
    ns = p.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = (ns.root or default_root).resolve()
    snap = resolve_snapshot_root(root)
    if ns.out != "-":
        out_p = Path(ns.out)
        if not out_p.is_absolute():
            out_p = (root / out_p).resolve()
        pre = validate_golden_snapshot_preconditions(root, out_p)
        if pre:
            sys.stderr.write(f"snapshot-tree: {pre}\n")
            return 20
        if is_golden_manifest_path(root, out_p) and snap != root / "dist" / "cursor":
            sys.stderr.write("snapshot-tree: golden manifest requires dist/cursor snapshot root\n")
            return 20
    lines = []
    seen = set()
    for rel, f in collect(snap):
        if rel in seen:
            continue
        seen.add(rel)
        h = hashlib.sha256(f.read_bytes()).hexdigest()
        lines.append(f"{rel}\t{h}")
    out = "\n".join(sorted(lines)) + ("\n" if lines else "")
    if ns.out == "-":
        sys.stdout.write(out)
    else:
        out_p = Path(ns.out)
        if not out_p.is_absolute():
            out_p = root / out_p
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(out, encoding="utf-8")
    return 0


if __name__ == "__main__":
    run_module_main(main)
