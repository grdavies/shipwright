#!/usr/bin/env python3
"""Fixture gate for PRD 040 phase sizing scorer (Phase 2–4)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAIL = 0
SCRIPT = ROOT / "scripts" / "phase_sizing.py"
ENV = {"PYTHONPATH": str(ROOT / "scripts")}


def ok(name: str) -> None:
    print(f"OK  {name}")


def bad(name: str) -> None:
    global FAIL
    print(f"FAIL {name}")
    FAIL = 1


def run_cmd(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(ROOT), *args],
        env={**dict(__import__("os").environ), **ENV},
        text=True,
        capture_output=True,
        check=False,
    )


def run_score(task_list: str) -> dict:
    proc = run_cmd("score", task_list)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def main() -> int:
    task_list = "docs/prds/040-phase-granularity-parallelism/tasks-040-phase-granularity-parallelism.md"
    first = run_score(task_list)
    second = run_score(task_list)
    if json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True):
        ok("phase-sizing-determinism")
    else:
        bad("phase-sizing-determinism")
    phase2 = next(p for p in first["phases"] if p["phase"] == "2")
    if phase2["size"] in {"small", "medium", "large"} and isinstance(phase2["separableSets"], list):
        ok("phase-sizing-classification-shape")
    else:
        bad("phase-sizing-classification-shape")
    if "scopeUnderDeclared" in phase2:
        ok("phase-sizing-scope-under-declared")
    else:
        bad("phase-sizing-scope-under-declared")
    frozen = run_cmd("check-frozen", task_list)
    if frozen.returncode == 20:
        ok("phase-sizing-check-frozen-failclosed")
    else:
        bad("phase-sizing-check-frozen-failclosed")
    if (ROOT / "core/sw-reference/phase-sizing.schema.json").is_file():
        ok("phase-sizing-schema-present")
    else:
        bad("phase-sizing-schema-present")

    split_path = "scripts/test/fixtures/phase-sizing/tasks-split-candidate.md"
    split_score = run_score(split_path)
    split_phase = split_score["phases"][0]
    suggestion = split_phase.get("splitSuggestion") or {}
    units = suggestion.get("units") or []
    if not suggestion.get("rejected") and len(units) >= 2:
        ok("phase-sizing-split-proposal")
    else:
        bad("phase-sizing-split-proposal")

    contention_path = "scripts/test/fixtures/phase-sizing/tasks-contention-candidate.md"
    contention_score = run_score(contention_path)
    contention_phase = contention_score["phases"][0]
    if len(contention_phase.get("separableSets") or []) == 1 and not contention_phase.get("splitSuggestion"):
        ok("phase-sizing-contention-integrity")
    else:
        bad("phase-sizing-contention-integrity")

    advisory = run_cmd("advisory", split_path)
    if advisory.returncode == 0 and "## Sizing & Split Suggestions" in advisory.stdout:
        ok("phase-sizing-advisory-render")
    else:
        bad("phase-sizing-advisory-render")

    with tempfile.TemporaryDirectory() as tmpdir:
        adv_proc = run_cmd("advisory", split_path)
        if adv_proc.returncode != 0:
            bad("phase-sizing-advisory-render")
            return FAIL

        def with_advisory(name: str) -> Path:
            copy = Path(tmpdir) / name
            shutil.copy(ROOT / split_path, copy)
            base_text = copy.read_text(encoding="utf-8")
            copy.write_text(base_text.rstrip() + "\n\n" + adv_proc.stdout, encoding="utf-8")
            return copy

        reject_copy = with_advisory("tasks-with-advisory.md")
        reject = run_cmd("check-frozen", str(reject_copy))
        if reject.returncode == 20:
            ok("phase-sizing-frozen-advisory-reject")
        else:
            bad("phase-sizing-frozen-advisory-reject")

        strip_copy = with_advisory("tasks-strip-target.md")
        strip_proc = run_cmd("strip-advisory", str(strip_copy), "--inplace")
        stripped = strip_copy.read_text(encoding="utf-8")
        if strip_proc.returncode == 0 and "## Sizing & Split Suggestions" not in stripped:
            ok("phase-sizing-strip-advisory")
        else:
            bad("phase-sizing-strip-advisory")

    preflight_score = run_score(split_path)
    preflight_phase = preflight_score["phases"][0]
    preflight = (preflight_phase.get("splitSuggestion") or {}).get("preflight") or {}
    if preflight.get("verdict") == "pass":
        ok("phase-sizing-preflight-accept")
    else:
        bad("phase-sizing-preflight-accept")

    max_path = "scripts/test/fixtures/phase-sizing/tasks-max-phase-count.md"
    max_score = run_score(max_path)
    max_phase = next(p for p in max_score["phases"] if p["phase"] == "13")
    max_suggestion = max_phase.get("splitSuggestion") or {}
    max_preflight = max_suggestion.get("preflight") or {}
    if max_suggestion.get("rejected") and (
        max_suggestion.get("reason") == "maxPhaseCount exceeded"
        or max_preflight.get("reason") == "maxPhaseCount exceeded"
    ):
        ok("phase-sizing-max-phase-count-bound")
    else:
        bad("phase-sizing-max-phase-count-bound")

    reject_score = run_score(max_path)
    reject_phase = next(p for p in reject_score["phases"] if p["phase"] == "13")
    reject_suggestion = reject_phase.get("splitSuggestion") or {}
    reject_preflight = reject_suggestion.get("preflight") or {}
    reject_reason = reject_suggestion.get("reason") or reject_preflight.get("reason") or ""
    if reject_suggestion.get("rejected") and (
        "cycle" in reject_reason
        or reject_reason == "maxPhaseCount exceeded"
        or reject_reason == "width-1 collapse"
    ):
        ok("phase-sizing-preflight-reject-cycle-or-max")
    else:
        bad("phase-sizing-preflight-reject-cycle-or-max")

    sizing_report = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "wave.py"), "sizing-report", "--task-list", split_path],
        env={**dict(__import__("os").environ), **ENV},
        text=True,
        capture_output=True,
        check=False,
        cwd=str(ROOT),
    )
    if sizing_report.returncode == 0 and "phase-sizing-score" in sizing_report.stdout:
        ok("phase-sizing-wave-sizing-report")
    else:
        bad("phase-sizing-wave-sizing-report")

    preflight_cmd = run_cmd("preflight", split_path)
    if preflight_cmd.returncode == 0 and "phase-sizing-preflight" in preflight_cmd.stdout:
        ok("phase-sizing-preflight-command")
    else:
        bad("phase-sizing-preflight-command")

    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
