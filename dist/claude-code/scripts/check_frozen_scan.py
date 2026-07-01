
#!/usr/bin/env python3
"""Frozen artifact diff scanner (extracted from check-frozen)."""
from __future__ import annotations
import json, os, subprocess, sys, tempfile
from pathlib import Path
import pathlib

from phase_sizing import has_advisory_block

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent

def git_root() -> Path:
    p = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=False)
    if p.returncode == 0 and p.stdout.strip():
        return Path(p.stdout.strip())
    return Path.cwd()

def resolve_base(base: str | None) -> str:
    if base: return base
    for ref in ("origin/main", "main"):
        p = subprocess.run(["git","-C",str(git_root()),"rev-parse","--verify",ref], capture_output=True)
        if p.returncode == 0: return ref
    p = subprocess.run(["git","-C",str(git_root()),"merge-base","HEAD", "origin/main"], capture_output=True, text=True)
    return p.stdout.strip() if p.returncode==0 and p.stdout.strip() else "HEAD~1"



def is_frozen_at_ref(path: str, ref: str) -> bool:
    root = git_root()
    proc = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return False
    in_fm = False
    for line in proc.stdout.splitlines():
        if line.strip() == "---":
            if in_fm:
                break
            in_fm = True
            continue
        if in_fm and line.strip().startswith("frozen:"):
            return line.split(":", 1)[1].strip().lower() == "true"
    return False


def is_checkbox_only_ref_change(path: str, base_ref: str) -> bool:
    root = git_root()
    with tempfile.TemporaryDirectory() as tmpdir:
        old = pathlib.Path(tmpdir) / "old"
        new = pathlib.Path(tmpdir) / "new"
        o = subprocess.run(["git", "-C", str(root), "show", f"{base_ref}:{path}"], capture_output=True, text=True, check=False)
        n = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{path}"], capture_output=True, text=True, check=False)
        if o.returncode != 0 or n.returncode != 0:
            return False
        old.write_text(o.stdout, encoding="utf-8")
        new.write_text(n.stdout, encoding="utf-8")
        chk = subprocess.run([sys.executable, str(SCRIPT_DIR / "checkbox_diff.py"), "is-checkbox-only", str(old), str(new)], capture_output=True, check=False)
        return chk.returncode == 0


def is_format_normalization_only(path: str, base_ref: str) -> bool:
    root = git_root()
    with tempfile.TemporaryDirectory() as tmpdir:
        base = pathlib.Path(tmpdir)
        old, new, old_norm = base / "old", base / "new", base / "old_norm"
        o = subprocess.run(["git", "-C", str(root), "show", f"{base_ref}:{path}"], capture_output=True, text=True, check=False)
        n = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{path}"], capture_output=True, text=True, check=False)
        if o.returncode != 0 or n.returncode != 0:
            return False
        old.write_text(o.stdout, encoding="utf-8")
        new.write_text(n.stdout, encoding="utf-8")
        norm = subprocess.run([sys.executable, str(SCRIPT_DIR / "doc_format.py"), "write", str(old)], capture_output=True, text=True, check=False)
        if norm.returncode != 0:
            return False
        old_norm.write_text(norm.stdout, encoding="utf-8")
        return old_norm.read_bytes() == new.read_bytes()


def amended_dirs(diff_out: str) -> list[str]:
    dirs: list[str] = []
    for line in diff_out.splitlines():
        parts = line.split("	", 1)
        if len(parts) != 2:
            continue
        status, p = parts
        if status != "A" or not p.startswith("docs/prds/") or "/amendments/" not in p:
            continue
        if is_frozen_at_ref(p, "HEAD"):
            dirs.append(p.rsplit("/amendments/", 1)[0])
    return dirs


def is_amendment_companion_tasklist(path: str, amended: list[str]) -> bool:
    name = pathlib.Path(path).name
    if not (name.startswith("tasks-") and name.endswith(".md")):
        return False
    if str(pathlib.Path(path).parent) not in amended:
        return False
    return subprocess.run([sys.executable, str(SCRIPT_DIR / "doc_format.py"), "check", path], cwd=str(git_root()), capture_output=True, check=False).returncode == 0

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
    proc = subprocess.run(["git", "-C", str(root), "diff", "--name-status", f"{base}...HEAD"], capture_output=True, text=True)
    diff_out = proc.stdout
    if proc.returncode != 0:
        proc = subprocess.run(["git", "-C", str(root), "diff", "--name-status", base, "HEAD"], capture_output=True, text=True)
        diff_out = proc.stdout
        if proc.returncode != 0:
            print(json.dumps({"verdict":"fail","reason":"unable to compute diff against base"}), file=sys.stderr); return 2
    amended = amended_dirs(diff_out)
    violations = []
    for line in diff_out.splitlines():
        parts = line.split("	", 1)
        if len(parts) != 2:
            continue
        status, p = parts
        if p.startswith("docs/plans/") or status in ("A",) or status.startswith("R"):
            continue
        if status not in ("D", "M"):
            continue
        if subprocess.run(["git", "-C", str(root), "cat-file", "-e", f"{base}:{p}"], check=False).returncode != 0:
            continue
        if not is_frozen_at_ref(p, base):
            continue
        if is_checkbox_only_ref_change(p, base):
            continue
        if is_format_normalization_only(p, base):
            continue
        if is_amendment_companion_tasklist(p, amended):
            continue
        violations.append(p)
    advisory_violations = []
    for line in diff_out.splitlines():
        parts = line.split("	", 1)
        if len(parts) != 2:
            continue
        status, path = parts
        if status not in ("D", "M"):
            continue
        if not is_frozen_at_ref(path, "HEAD"):
            continue
        show = subprocess.run(["git", "-C", str(root), "show", f"HEAD:{path}"], capture_output=True, text=True, check=False)
        if show.returncode != 0:
            continue
        if has_advisory_block(show.stdout):
            advisory_violations.append(path)
    if advisory_violations:
        print(json.dumps({"verdict":"fail","reason":"advisory block in modified frozen file","files":advisory_violations})); return 1
    if violations:
        print(json.dumps({"verdict":"fail","reason":"frozen artifact modified","files":violations})); return 1
    print(json.dumps({"verdict":"pass","reason":"no frozen artifacts modified"})); return 0
    proc = subprocess.run(["git","-C",str(root),"diff","--name-only", f"{base}...HEAD"], capture_output=True, text=True)
    changed = [l for l in proc.stdout.splitlines() if l.strip()]
    violations = [p for p in changed if any(p == f or p.startswith(f.rstrip("/")+"/") for f in frozen)]
    if violations:
        print(json.dumps({"verdict":"fail","violations":violations,"base":base}), file=sys.stderr); return 1
    print(json.dumps({"verdict":"pass","checked":len(changed),"base":base})); return 0

if __name__ == "__main__":
    from _sw.cli import run_module_main
    run_module_main(main)
