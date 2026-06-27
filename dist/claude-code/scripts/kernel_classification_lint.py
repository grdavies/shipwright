#!/usr/bin/env python3
"""Author-time kernel classification lint (PRD 022 R28)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from kernel_classification import (
    canonical_ship_chain,
    check_ship_chain_parity,
    chokepoints_reachable_before_merge_push,
    lint_completeness,
    load_classification,
    validate_chain_order,
)


def emit(obj: dict[str, Any], code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lint kernel classification artifact")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        data = load_classification(root)
        chain = canonical_ship_chain(root, data)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        emit({"verdict": "fail", "error": str(exc)}, 1)

    ok_complete, missing = lint_completeness(root, data)
    ok_order, order_reasons = validate_chain_order(chain, data)
    ok_reach, reach_missing = chokepoints_reachable_before_merge_push(data, chain)
    try:
        from ship_phase_steps import SHIP_CHAIN
    except ImportError:
        SHIP_CHAIN = []
    ok_parity, parity_msg = check_ship_chain_parity(root, SHIP_CHAIN)

    failures: list[str] = []
    if not ok_complete:
        failures.append(f"unclassified orchestrator steps: {', '.join(missing)}")
    if not ok_order:
        failures.extend(order_reasons)
    if not ok_reach:
        failures.append(f"unreachable chokepoints: {', '.join(reach_missing)}")
    if not ok_parity:
        failures.append(parity_msg)

    if failures:
        emit({"verdict": "fail", "failures": failures}, 1)
    emit({"verdict": "pass", "chainLength": len(chain)})


if __name__ == "__main__":
    main()
