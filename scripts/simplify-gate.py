#!/usr/bin/env python3
"""Behavior-preservation gate after /sw-simplify."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from _sw.cli import run_module_main
import evidence_read as er

def read_verify_pass(path: Path) -> str:
    if not path.is_file(): return "missing"
    if not er.safe_read_check(path): return "invalid"
    try:
        data = er.safe_json_load(path)
    except (PermissionError, json.JSONDecodeError):
        return "invalid"
    ec = data.get("exitCode", data.get("overall", {}).get("exitCode", 1))
    status = data.get("status", data.get("overall", {}).get("status", "fail"))
    return "pass" if ec == 0 and status == "pass" else "fail"

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--baseline-verify"); p.add_argument("--post-verify")
    ns = p.parse_args(list(sys.argv[1:] if argv is None else argv))
    if not ns.baseline_verify or not ns.post_verify:
        print("Usage: simplify-gate --baseline-verify PATH --post-verify PATH", file=sys.stderr); return 2
    b, post = read_verify_pass(Path(ns.baseline_verify)), read_verify_pass(Path(ns.post_verify))
    if b in ("missing","invalid") or post in ("missing","invalid"):
        print(json.dumps({"verdict":"inconclusive","reason":"missing or invalid verify status","baseline":b,"post":post})); return 10
    if b != "pass":
        print(json.dumps({"verdict":"inconclusive","reason":"baseline verify was not passing","baseline":b,"post":post})); return 10
    if post == "pass":
        print(json.dumps({"verdict":"preserved","baseline":ns.baseline_verify,"post":ns.post_verify})); return 0
    print(json.dumps({"verdict":"regressed","reason":"post-simplify verify failed","baseline":ns.baseline_verify,"post":ns.post_verify})); return 20
if __name__ == "__main__": run_module_main(main)
