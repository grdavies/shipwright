#!/usr/bin/env python3
"""Severity gate for local code-review normalized output."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from _sw.cli import run_module_main

def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--input"); p.add_argument("--gate-config")
    ns = p.parse_args(list(sys.argv[1:] if argv is None else argv))
    if not ns.input or not ns.gate_config:
        print("Usage: code-review-gate --input PATH --gate-config PATH", file=sys.stderr); return 2
    inp, gcfg = Path(ns.input), Path(ns.gate_config)
    if not inp.is_file():
        print(json.dumps({"verdict":"skip","reason":"missing normalized input"})); return 0
    if not gcfg.is_file():
        print(json.dumps({"verdict":"skip","reason":"missing gate config"})); return 0
    gate = json.loads(gcfg.read_text(encoding="utf-8"))
    data = json.loads(inp.read_text(encoding="utf-8"))
    halt_on = gate.get("haltOn") or []
    surface = gate.get("surface") or ["P0","P1","P2","P3"]
    if data.get("status") != "complete":
        print(json.dumps({"verdict":"skip","status":data.get("status","failed"),"reason":data.get("reason","non-complete local review"),"halt":False,"surfaced":[]})); return 0
    surfaced, halt_findings = [], []
    for row in data.get("findings") or []:
        sev = row.get("severity","P3")
        if sev in surface: surfaced.append(row)
        if sev in halt_on: halt_findings.append(row)
    if halt_findings:
        print(json.dumps({"verdict":"halt","halt":True,"surfaced":surfaced,"halt_findings":halt_findings})); return 20
    print(json.dumps({"verdict":"continue","halt":False,"surfaced":surfaced})); return 0
if __name__ == "__main__": run_module_main(main)
