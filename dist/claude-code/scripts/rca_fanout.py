#!/usr/bin/env python3
"""CLI: multi-hypothesis RCA fan-out (PRD 064 R1/R2)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import rca_fanout_lib as lib


def emit(obj: dict, code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def _load_json(path: str | None) -> dict:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _load_json_list(path: str | None) -> list:
    if not path:
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="RCA fan-out driver")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="Resolve rca.fanout config")

    gate = sub.add_parser("should-fanout", help="Evaluate D5 gating")
    gate.add_argument("--signal", required=True)
    gate.add_argument("--initial-count", type=int)

    plan = sub.add_parser("plan", help="Plan generator partitions")
    plan.add_argument("--signal", required=True)

    brief = sub.add_parser("generator-brief", help="Build generator brief JSON")
    brief.add_argument("--plan", required=True)
    brief.add_argument("--generator-id", required=True)
    brief.add_argument("--run-id")

    synth = sub.add_parser("synthesize", help="Merge generator outputs")
    synth.add_argument("--results", required=True)

    ref_brief = sub.add_parser("refuter-brief", help="Build refuter brief JSON")
    ref_brief.add_argument("--hypothesis", required=True)
    ref_brief.add_argument("--signal-summary")
    ref_brief.add_argument("--run-id")

    evaluate = sub.add_parser("evaluate", help="Evaluate refuter outputs")
    evaluate.add_argument("--hypotheses", required=True)
    evaluate.add_argument("--refutations", required=True)

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    cfg = lib.load_workflow_config(root)
    fanout_cfg = lib.resolve_fanout_config(cfg)

    if args.command == "config":
        emit({"fanout": fanout_cfg})

    if args.command == "should-fanout":
        signal = _load_json(args.signal)
        emit(lib.should_fanout(signal, fanout_cfg, initial_hypothesis_count=args.initial_count))

    if args.command == "plan":
        signal = _load_json(args.signal)
        emit(lib.plan_generators(signal, fanout_cfg))

    if args.command == "generator-brief":
        plan_obj = _load_json(args.plan)
        generators = plan_obj.get("generators") or []
        match = next((g for g in generators if g.get("id") == args.generator_id), None)
        if not match:
            emit({"verdict": "fail", "error": f"unknown generator {args.generator_id}"}, 20)
        emit(lib.build_generator_brief(match, run_id=args.run_id))

    if args.command == "synthesize":
        results = _load_json_list(args.results)
        normalized = [lib.normalize_generator_result(r, generator_id=r.get("generatorId")) for r in results]
        emit(lib.synthesize_hypotheses(normalized, min_hypotheses=int(fanout_cfg.get("min_hypotheses") or 3)))

    if args.command == "refuter-brief":
        hypothesis = _load_json(args.hypothesis)
        summary = _load_json(args.signal_summary) if args.signal_summary else {}
        emit(lib.build_refuter_brief(hypothesis, signal_summary=summary, run_id=args.run_id))

    if args.command == "evaluate":
        hypotheses = _load_json_list(args.hypotheses)
        refutations = _load_json_list(args.refutations)
        by_id = {str(h.get("id")): h for h in hypotheses if isinstance(h, dict)}
        evaluated = []
        for raw in refutations:
            if not isinstance(raw, dict):
                continue
            hyp_id = str(raw.get("hypothesisId") or raw.get("id") or "")
            hyp = by_id.get(hyp_id) or {"id": hyp_id, "statement": raw.get("statement")}
            evaluated.append(lib.evaluate_refutation(hyp, lib.normalize_refuter_result(raw)))
        out = lib.evaluate_survivors(evaluated)
        out["refutations"] = evaluated
        emit(out)

    return 0


if __name__ == "__main__":
    from _sw.cli import run_module_main
    run_module_main(main)
