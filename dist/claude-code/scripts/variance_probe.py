#!/usr/bin/env python3
"""Once-at-authoring variance probe for orchestrator adoption mode (PRD 024 R36)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from kernel_classification import normalize_step
from orchestrator_step_plan import VALID_ORCHESTRATOR_TYPES, canonical_orchestrator_chain, orchestrator_type_spec
from wave_plan_validate import validate_orchestrator_plan

DEFAULT_CONSISTENCY_ONLY = frozenset({"doc"})

PROPOSED_FIXTURE_EXEMPT_PATTERNS: dict[str, list[str]] = {
    "debug": [
        "*-proposed-*",
        "*-022-parity-under-proposed",
        "debug-route-confirm-halt-required",
        "debug-rca-human-decision-halt-required",
    ],
    "doc": [
        "*-proposed-*",
        "*-022-parity-under-proposed",
        "doc-review-halt-manual-required",
        "doc-review-halt-gated-auto-required",
        "doc-afterTasks-checkpoint-required",
    ],
    "feedback": [
        "*-proposed-*",
        "*-022-parity-under-proposed",
    ],
}

LATITUDE_CHECKS: dict[str, dict[str, Any]] = {
    "debug": {"kind": "omit", "steps": ["enrich"]},
    "doc": {"kind": "omit", "steps": ["sw-brainstorm"]},
    "feedback": {"kind": "insert_after", "step": "hook-trigger-halt", "after": "route"},
}


def _latitude_alternate_steps(orchestrator_type: str, canonical: list[str]) -> list[str] | None:
    check = LATITUDE_CHECKS.get(orchestrator_type)
    if not check:
        return None
    steps = list(canonical)
    if check["kind"] == "omit":
        omit = {normalize_step(s) for s in check.get("steps") or []}
        alt = [s for s in steps if s not in omit]
        return alt if alt != steps else None
    if check["kind"] == "insert_after":
        step = normalize_step(str(check["step"]))
        after = normalize_step(str(check["after"]))
        if step in steps:
            return None
        try:
            idx = steps.index(after) + 1
        except ValueError:
            return None
        alt = steps[:idx] + [step] + steps[idx:]
        return alt
    return None


def detect_plan_shape_latitude(root: Path, orchestrator_type: str) -> dict[str, Any]:
    canonical = canonical_orchestrator_chain(root, orchestrator_type)
    alternate = _latitude_alternate_steps(orchestrator_type, canonical)
    result: dict[str, Any] = {
        "orchestratorType": orchestrator_type,
        "canonicalSteps": canonical,
        "latitudeCheck": LATITUDE_CHECKS.get(orchestrator_type),
        "alternateSteps": alternate,
        "latitudeDetected": False,
    }
    if not alternate or alternate == canonical:
        return result
    proposal = {"steps": alternate, "orchestratorType": orchestrator_type}
    validation = validate_orchestrator_plan(
        root,
        proposal,
        orchestrator_type=orchestrator_type,
        signal_context=None,
    )
    result["alternateValidation"] = validation.get("verdict")
    result["latitudeDetected"] = validation.get("verdict") == "pass"
    return result


def probe_orchestrator(root: Path, orchestrator_type: str) -> dict[str, Any]:
    if orchestrator_type not in VALID_ORCHESTRATOR_TYPES:
        raise KeyError(f"unknown orchestrator type: {orchestrator_type!r}")
    latitude = detect_plan_shape_latitude(root, orchestrator_type)
    if orchestrator_type in DEFAULT_CONSISTENCY_ONLY:
        # R36c: /sw-doc defaults consistency-only (009 audit — no routine yields).
        canonical_equiv = True
    else:
        canonical_equiv = not latitude["latitudeDetected"]
    adoption_mode = "consistency-only" if canonical_equiv else "full"
    return {
        "orchestratorType": orchestrator_type,
        "canonicalEquivProposed": canonical_equiv,
        "adoptionMode": adoption_mode,
        "proposedPackDeferred": canonical_equiv,
        "latitude": latitude,
        "defaultsConsistencyOnly": orchestrator_type in DEFAULT_CONSISTENCY_ONLY,
    }


def proposed_fixture_exempt(root: Path, orchestrator_type: str, fixture_name: str) -> bool:
    if probe_orchestrator(root, orchestrator_type)["adoptionMode"] != "consistency-only":
        return False
    patterns = PROPOSED_FIXTURE_EXEMPT_PATTERNS.get(orchestrator_type) or []
    import fnmatch

    return any(fnmatch.fnmatch(fixture_name, pattern) for pattern in patterns)


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def main() -> None:
    if len(sys.argv) < 3:
        emit({"verdict": "fail", "error": "usage: variance_probe.py <root> <command> [args...]"}, 2)
    root = Path(sys.argv[1])
    cmd = sys.argv[2]
    args = sys.argv[3:]
    if cmd == "probe":
        orchestrator_type = args[0] if args else ""
        if orchestrator_type not in VALID_ORCHESTRATOR_TYPES:
            emit({"verdict": "fail", "error": "--orchestrator-type debug|doc|feedback required"}, 2)
        emit({"verdict": "pass", **probe_orchestrator(root, orchestrator_type)}, 0)
    elif cmd == "proposed-fixture-exempt":
        if len(args) < 2:
            emit({"verdict": "fail", "error": "proposed-fixture-exempt <orchestrator> <fixture>"}, 2)
        orch, fixture = args[0], args[1]
        exempt = proposed_fixture_exempt(root, orch, fixture) if orch in VALID_ORCHESTRATOR_TYPES else False
        emit(
            {
                "verdict": "pass",
                "orchestratorType": orch,
                "fixture": fixture,
                "exempt": exempt,
                "adoptionMode": probe_orchestrator(root, orch)["adoptionMode"] if orch in VALID_ORCHESTRATOR_TYPES else None,
            },
            0,
        )
    else:
        emit({"verdict": "fail", "error": f"unknown command: {cmd}"}, 2)


if __name__ == "__main__":
    main()
