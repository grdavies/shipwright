
#!/usr/bin/env python3
"""Frozen artifact diff scanner (extracted from check-frozen)."""
from __future__ import annotations
import json, os, subprocess, sys, tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent

def git_root() -> Path:
    p = subprocess.run(["git","-C",str(ROOT),"rev-parse","--show-toplevel"], capture_output=True, text=True)
    return Path(p.stdout.strip()) if p.returncode==0 else ROOT

def resolve_base(base: str | None) -> str:
    if base: return base
    for ref in ("origin/main", "main"):
        p = subprocess.run(["git","-C",str(git_root()),"rev-parse","--verify",ref], capture_output=True)
        if p.returncode == 0: return ref
    p = subprocess.run(["git","-C",str(git_root()),"merge-base","HEAD", "origin/main"], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode==0 and p.stdout.strip() else "HEAD~1"

def load_frozen_paths() -> list[str]:
    cfg = None
    for c in (git_root()/".cursor/workflow.config.json", git_root()/"workflow.config.json"):
        if c.is_file(): cfg = json.loads(c.read_text()); break
    paths = []
    if cfg:
        for item in cfg.get("doc", {}).get("frozenArtifacts", []) or []:
            if isinstance(item, str): paths.append(item)
            elif isinstance(item, dict) and item.get("path"): paths.append(item["path"])
    return paths

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    base = resolve_base(args[0] if args else None)
    root = git_root()
    frozen = load_frozen_paths()
    if not frozen:
        print(json.dumps({"verdict":"pass","reason":"no frozen artifacts configured"})); return 0
    proc = subprocess.run(["git","-C",str(root),"diff","--name-only", f"{base}...HEAD"], capture_output=True, text=True)
    changed = [l for l in proc.stdout.splitlines() if l.strip()]
    violations = [p for p in changed if any(p == f or p.startswith(f.rstrip("/")+"/") for f in frozen)]
    if violations:
        print(json.dumps({"verdict":"fail","violations":violations,"base":base}), file=sys.stderr); return 1
    print(json.dumps({"verdict":"pass","checked":len(changed),"base":base})); return 0

if __name__ == "__main__":
    from _sw.cli import run_module_main
    run_module_main(main)
