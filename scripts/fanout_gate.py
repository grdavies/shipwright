#!/usr/bin/env python3
"""TR0 program gate — PRD-024 fan-out refused until 023 prerequisites + positive R31."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from pilot_dependency_gate import run_dependency_checks
from wave_plan_benefit import (
    DEFAULT_MIN_N_PER_STRATUM,
    DEFAULT_WALL_CLOCK_EPSILON,
    evaluate_decision_rule,
    load_pairs,
)

DEFAULT_PAIRS_REL = "scripts/test/fixtures/benefit-metric/positive-pairs.json"


def _gate_scripts_dir() -> Path:
    return Path(__file__).resolve().parent


def _repo_root(root: Path | None) -> Path:
    if root is not None:
        return root.resolve()
    return _gate_scripts_dir().parent


def _pairs_path(root: Path, pairs_rel: str | None = None) -> Path:
    rel = pairs_rel or DEFAULT_PAIRS_REL
    path = Path(rel)
    if not path.is_absolute():
        path = root / rel
    return path


def evaluate_r31_decision(
    root: Path,
    *,
    pairs_path: Path | None = None,
    min_n: int = DEFAULT_MIN_N_PER_STRATUM,
    epsilon: float = DEFAULT_WALL_CLOCK_EPSILON,
) -> dict[str, Any]:
    path = pairs_path or _pairs_path(root)
    if not path.is_file():
        return {
            "verdict": "fail",
            "error": f"benefit pairs file not found: {path}",
            "recommendation": "canonical",
            "failClosed": True,
        }
    pairs = load_pairs(path)
    decision = evaluate_decision_rule(pairs, min_n=min_n, epsilon=epsilon)
    positive = decision.get("recommendation") == "proposed-eligible" and not decision.get(
        "failClosed", True
    )
    return {
        "verdict": "pass" if positive else "fail",
        "positive": positive,
        "recommendation": decision.get("recommendation"),
        "failClosed": decision.get("failClosed"),
        "minNPerStratum": decision.get("minNPerStratum"),
        "pairCount": decision.get("pairCount"),
        "stratumCount": decision.get("stratumCount"),
        "strata": decision.get("strata"),
        "pairsPath": str(path),
    }


def run_fanout_checks(
    root: Path | None = None,
    *,
    pairs_path: Path | None = None,
    min_n: int = DEFAULT_MIN_N_PER_STRATUM,
    epsilon: float = DEFAULT_WALL_CLOCK_EPSILON,
) -> dict[str, Any]:
    repo = _repo_root(root)
    pilot = run_dependency_checks(repo)
    r31 = evaluate_r31_decision(repo, pairs_path=pairs_path, min_n=min_n, epsilon=epsilon)
    pilot_pass = pilot.get("verdict") == "pass"
    r31_positive = bool(r31.get("positive"))
    if pilot_pass and r31_positive:
        return {
            "verdict": "pass",
            "pilot": pilot,
            "r31": r31,
        }
    reasons: list[str] = []
    if not pilot_pass:
        reasons.append("pilot-prerequisites")
    if not r31_positive:
        reasons.append("r31-non-positive")
    return {
        "verdict": "fail",
        "reasons": reasons,
        "pilot": pilot,
        "r31": r31,
    }


def fanout_enabled(root: Path | None = None, **kwargs: Any) -> bool:
    return run_fanout_checks(root, **kwargs).get("verdict") == "pass"


def emit_status(root: Path | None = None, **kwargs: Any) -> None:
    print(json.dumps(run_fanout_checks(root, **kwargs), ensure_ascii=False, indent=2))


def main() -> None:
    if len(sys.argv) < 2:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "error": "usage: fanout_gate.py <root> [status|enabled] [--pairs <path>] [--min-n N]",
                },
                indent=2,
            )
        )
        sys.exit(2)
    root = Path(sys.argv[1])
    args = sys.argv[2:]
    cmd = "status"
    pairs_arg: str | None = None
    min_n = DEFAULT_MIN_N_PER_STRATUM
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("status", "enabled"):
            cmd = arg
            i += 1
            continue
        if arg == "--pairs" and i + 1 < len(args):
            pairs_arg = args[i + 1]
            i += 2
            continue
        if arg == "--min-n" and i + 1 < len(args):
            min_n = int(args[i + 1])
            i += 2
            continue
        i += 1

    pairs_path = Path(pairs_arg) if pairs_arg else None
    kwargs = {"pairs_path": pairs_path, "min_n": min_n}
    if cmd == "enabled":
        sys.exit(0 if fanout_enabled(root, **kwargs) else 20)
    emit_status(root, **kwargs)
    sys.exit(0 if fanout_enabled(root, **kwargs) else 1)


if __name__ == "__main__":
    main()
