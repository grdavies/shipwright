#!/usr/bin/env python3
"""Deterministic Shipwright CI readiness gate (PRD 042 phase 3)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import build_parser, run_module_main
import check_gate_lib as gate


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(
        prog="check-gate",
        description="Deterministic CI readiness gate — JSON verdict on stdout.",
    )
    parser.add_argument("pr", nargs="?", help="PR number (optional; resolved from branch)")
    parser.add_argument(
        "--section",
        default="",
        help="Validate a single config section (e.g. models.routing) and exit",
    )
    args = parser.parse_args(argv)
    root = gate.git_root()

    if args.section == "models.routing":
        cfg = gate.load_workflow_config(root)
        errors = gate.validate_models_routing(cfg)
        warnings = gate.validate_models_routing_warnings(cfg)
        # SC-M8 raw-prompt scan (attribution records must not contain fixture prompts).
        errors.extend(gate.scan_attribution_raw_prompts(root))
        payload = {
            "section": "models.routing",
            "errors": errors,
            "warnings": warnings,
            "verdict": "fail" if errors else "pass",
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 20 if errors else 0

    if args.section == "attribution.sc-m8":
        errors = gate.scan_attribution_raw_prompts(root)
        payload = {
            "section": "attribution.sc-m8",
            "errors": errors,
            "warnings": [],
            "verdict": "fail" if errors else "pass",
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 20 if errors else 0

    if args.section:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "errors": [f"unknown section: {args.section}"],
                },
                ensure_ascii=False,
            )
        )
        return 20

    exit_code, _payload = gate.run_gate(root, args.pr)
    return exit_code


if __name__ == "__main__":
    run_module_main(main)
