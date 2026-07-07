#!/usr/bin/env python3
"""Per-task execute status writer (TDD + refactor rollup, PRD 039 R2)."""
from __future__ import annotations
import argparse, json, os, re, sys
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
    verdict = str(data.get("verdict") or "")
    task_list = os.environ.get("SW_TASK_LIST", "")
    phase_slug = os.environ.get("SW_PHASE_SLUG", "")
    if verdict in ("green", "pass") and task_list and phase_slug:
        import importlib.util
        gate = Path(__file__).resolve().parent / "phase_acceptance_gate.py"
        spec = importlib.util.spec_from_file_location("phase_acceptance_gate", gate)
        if spec is not None and spec.loader is not None:
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            completion = mod.record_ref_completion(root, ns.task_ref, task_list, phase_slug)
            if completion.get("verdict") != "pass":
                print(json.dumps(completion))
                return 1
            status_out = {"verdict": "pass", "path": str(path)}
            if completion.get("issueSync"):
                status_out["issueSync"] = completion["issueSync"]
            print(json.dumps(status_out))
            return 0
    print(json.dumps({"verdict": "pass", "path": str(path)}))
    return 0

if __name__ == "__main__":
    run_module_main(main)
