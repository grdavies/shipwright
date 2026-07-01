#!/usr/bin/env python3
"""Deterministic verification-gate verdict helper (IM1 / U1; hardened plan 005)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import verify_evidence_lib as vel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verification-gate verdict from structured evidence")
    parser.add_argument("--root", default=".")
    parser.add_argument("--verify-status", required=True)
    parser.add_argument("--gate-json", default=None)
    parser.add_argument("--review-status", default=None)
    parser.add_argument("--baseline-verify", default=None)
    parser.add_argument("--baseline-gate", default=None)
    parser.add_argument("--require-gate", action="store_true")
    parser.add_argument("--pr-context", choices=["on", "off", "auto"], default="auto")
    parser.add_argument("--behavioral-status", default=None)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    verdict, code = vel.compute_and_record(
        root,
        verify_path=Path(args.verify_status),
        gate_path=Path(args.gate_json) if args.gate_json else None,
        review_path=Path(args.review_status) if args.review_status else None,
        baseline_verify_path=Path(args.baseline_verify) if args.baseline_verify else None,
        baseline_gate_path=Path(args.baseline_gate) if args.baseline_gate else None,
        require_gate=args.require_gate,
        pr_context=args.pr_context,
        behavioral_status_path=Path(args.behavioral_status) if args.behavioral_status else None,
    )
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
