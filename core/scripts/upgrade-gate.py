#!/usr/bin/env python3
"""Refuse upgrade while /sw-deliver durable state is non-terminal (R42)."""
from __future__ import annotations
import json
import sys
from pathlib import Path

from _sw.cli import build_parser, run_module_main

TERMINAL = frozenset({"complete", "blocked", "rejected"})


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def deliver_states(root: Path) -> list[dict]:
    cursor = root / ".cursor"
    states: list[dict] = []
    for path in sorted(cursor.glob("sw-deliver-state*.json")):
        try:
            states.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            states.append({"path": str(path), "corrupt": True})
    runs = cursor / "sw-deliver-runs"
    if runs.is_dir():
        for path in runs.glob("*/status.json"):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                doc["path"] = str(path)
                states.append(doc)
            except json.JSONDecodeError:
                states.append({"path": str(path), "corrupt": True})
    return states


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(prog="upgrade-gate", description="Block upgrade during in-flight deliver.")
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)
    root = Path(args.root) if args.root else repo_root()
    blocking: list[dict] = []
    for state in deliver_states(root):
        verdict = str(state.get("verdict") or state.get("status") or "").lower()
        if state.get("corrupt"):
            blocking.append(state)
            continue
        if verdict and verdict not in TERMINAL and verdict not in {"merge-ready-green"}:
            blocking.append(state)
        if state.get("phaseStatus") == "in-flight":
            blocking.append(state)
    if blocking:
        print(json.dumps({
            "verdict": "blocked",
            "cause": "in-flight-deliver",
            "states": blocking,
            "remediation": "Finish or abort in-flight /sw-deliver runs before upgrading.",
        }, indent=2))
        return 20
    print(json.dumps({"verdict": "pass"}))
    return 0


if __name__ == "__main__":
    run_module_main(main)
