#!/usr/bin/env python3
"""CLI: semantic near-duplicate detection (PRD 064 R24/R25)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import gap_similarity_lib as lib


def emit(obj: dict, code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(code)


def _load_json(path: str | None) -> dict | list:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gap semantic near-duplicate detection")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("config", help="Resolve near-duplicate config")

    vec = sub.add_parser("vectorize", help="Feature-hash vectorize text")
    vec.add_argument("--text", required=True)

    sim = sub.add_parser("similarity", help="Cosine similarity between two texts")
    sim.add_argument("--left", required=True)
    sim.add_argument("--right", required=True)

    corpus_p = sub.add_parser("corpus", help="Load gap-unit corpus from planning store")
    corpus_p.add_argument("--out")

    scan_p = sub.add_parser("scan", help="Scan candidate against corpus with two-tier flagging")
    scan_p.add_argument("--candidate", required=True)
    scan_p.add_argument("--corpus")
    scan_p.add_argument("--out")
    scan_p.add_argument("--handoff-out")

    handoff = sub.add_parser("handoff-summary", help="Format scan result for human confirm")
    handoff.add_argument("--scan", required=True)

    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    cfg = lib.load_workflow_config(root)
    near_cfg = lib.resolve_near_duplicate_config(cfg)

    if args.command == "config":
        emit({"nearDuplicate": near_cfg})

    if args.command == "vectorize":
        vec_data = lib.feature_vector(args.text, dim=int(near_cfg["featureDim"]))
        emit(
            {
                "dim": near_cfg["featureDim"],
                "nonZero": len(vec_data),
                "vector": {str(k): v for k, v in sorted(vec_data.items())},
            }
        )

    if args.command == "similarity":
        dim = int(near_cfg["featureDim"])
        score = lib.cosine_similarity(
            lib.feature_vector(args.left, dim=dim),
            lib.feature_vector(args.right, dim=dim),
        )
        emit({"similarity": round(score, 6), "dim": dim})

    if args.command == "corpus":
        items = lib.load_gap_corpus(root)
        payload = {"count": len(items), "items": items}
        if args.out:
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        emit(payload)

    if args.command == "scan":
        if not near_cfg.get("enabled"):
            emit({"verdict": "skip", "reason": "disabled", "autoSuppress": False, "matches": []})
        corpus_raw = _load_json(args.corpus) if args.corpus else {"items": lib.load_gap_corpus(root)}
        corpus = corpus_raw.get("items") if isinstance(corpus_raw, dict) else corpus_raw
        if not isinstance(corpus, list):
            corpus = []
        result = lib.scan_candidate(args.candidate, corpus, near_cfg)
        if args.out:
            lib.persist_scan(Path(args.out), result)
        if args.handoff_out:
            summary = lib.format_handoff_summary(result)
            out = Path(args.handoff_out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(summary + "\n", encoding="utf-8")
            result = {**result, "handoffSummaryPath": str(out)}
        emit(result)

    if args.command == "handoff-summary":
        scan = _load_json(args.scan)
        if not isinstance(scan, dict):
            emit({"verdict": "fail", "error": "scan must be object"}, 20)
        emit({"summary": lib.format_handoff_summary(scan)})

    return 0


if __name__ == "__main__":
    main()
