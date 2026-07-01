#!/usr/bin/env python3
"""Per-task execute status writer (TDD + refactor rollup, PRD 039 R2)."""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path
from _sw.cli import run_module_main

def sanitize_ref(task_ref: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", task_ref).strip("-") or "unknown"

def status_path(root: Path, task_ref: str) -> Path:
    return root / ".cursor" / "sw-execute-runs" / sanitize_ref(task_ref) / "status.json"

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--task-ref", required=True)
    p.add_argument("--write", default="")
    p.add_argument("--read", action="store_true")
    ns = p.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path.cwd()
    path = status_path(root, ns.task_ref)
    if ns.read:
        if not path.is_file():
            print(json.dumps({"verdict": "missing", "taskRef": ns.task_ref}))
            return 2
        print(path.read_text(encoding="utf-8"))
        return 0
    if not ns.write:
        print("Usage: execute_task_status.py --task-ref REF --write '{...}'", file=sys.stderr)
        return 2
    data = json.loads(ns.write)
    data.setdefault("taskRef", ns.task_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": "pass", "path": str(path)}))
    return 0

if __name__ == "__main__":
    run_module_main(main)
