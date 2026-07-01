#!/usr/bin/env python3
"""Per-task refactor step gate (PRD 039 R1/R2)."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from _sw.cli import run_module_main

def has_metric_delta(metric_delta: dict | None) -> bool:
    if not isinstance(metric_delta, dict) or not metric_delta:
        return False
    for v in metric_delta.values():
        if v == "unavailable":
            continue
        if isinstance(v, (int, float)) and v != 0:
            return True
    return False

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--status", required=True)
    p.add_argument("--signal", default="")
    ns = p.parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        data = json.loads(Path(ns.status).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(json.dumps({"verdict": "fail", "reason": "invalid status json"}))
        return 20
    signal = {}
    if ns.signal and Path(ns.signal).is_file():
        try:
            signal = json.loads(Path(ns.signal).read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            signal = {}
    refactor = data.get("refactor") if isinstance(data.get("refactor"), dict) else data
    skipped = bool(refactor.get("skipped"))
    ran = bool(refactor.get("ran"))
    skip_reason = str(refactor.get("skipReason") or "").strip()
    verdict = str(refactor.get("verdict") or "")
    metric_delta = refactor.get("metricDelta")
    if skipped and not skip_reason:
        print(json.dumps({"verdict": "fail", "reason": "refactor skipped without skipReason", "taskRef": data.get("taskRef")}))
        return 20
    if not ran and not skipped:
        print(json.dumps({"verdict": "fail", "reason": "refactor step not run or recorded", "taskRef": data.get("taskRef")}))
        return 20
    sig_verdict = str(signal.get("verdict") or "none")
    hints = signal.get("refactorHints") or []
    if ran and sig_verdict in ("advise", "poor") and hints and not has_metric_delta(metric_delta):
        print(json.dumps({"verdict": "fail", "reason": "anti-gaming: ran without metric delta on non-empty hints", "taskRef": data.get("taskRef")}))
        return 20
    if verdict == "regressed":
        print(json.dumps({"verdict": "fail", "reason": "refactor regressed verify", "taskRef": data.get("taskRef")}))
        return 20
    out = {"verdict": "pass" if not skipped else "skipped", "taskRef": data.get("taskRef"), "refactorVerdict": verdict or ("clean" if ran else "skipped")}
    print(json.dumps(out))
    return 10 if skipped else 0

if __name__ == "__main__":
    run_module_main(main)
