#!/usr/bin/env python3
"""PRD 039 phase-4 heterogeneous review fixtures."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent.parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from review_synthesize import resolve_review_providers, synthesize_findings, synthesize_gate_adapters


def ok(msg: str) -> None:
    print(f"OK  {msg}")


def bad(msg: str) -> int:
    print(f"FAIL {msg}")
    return 1


def main() -> int:
    fail = 0
    scalar = resolve_review_providers({"provider": "coderabbit"})
    if scalar == ["coderabbit"]:
        ok("scalar review.provider coerced to single-element providers")
    else:
        fail = bad(f"scalar back-compat: {scalar}") or fail

    arr = resolve_review_providers({"providers": ["coderabbit", "pr-agent"]})
    if arr == ["coderabbit", "pr-agent"]:
        ok("review.providers array preserved")
    else:
        fail = bad(f"providers array: {arr}") or fail

    bundles = [
        {
            "provider": "a",
            "findings": [
                {"path": "x.py", "line": 1, "severity": "P2", "body": "issue alpha"},
                {"path": "y.py", "line": 2, "severity": "P1", "body": "issue beta"},
            ],
        },
        {
            "provider": "b",
            "findings": [
                {"path": "z.py", "line": 3, "severity": "P0", "body": "issue gamma"},
                {"path": "x.py", "line": 1, "severity": "P3", "body": "issue alpha"},
            ],
        },
    ]
    merged = synthesize_findings(bundles)
    paths = {f["path"] for f in merged["findings"]}
    if paths == {"x.py", "y.py", "z.py"} and merged["findingCount"] == 3:
        ok("union synthesis keeps non-overlapping findings")
    else:
        fail = bad(f"union synthesis: {merged}") or fail
    x_find = next(f for f in merged["findings"] if f["path"] == "x.py")
    if x_find.get("severity") == "P2":
        ok("severity-weighted dedup keeps higher severity on overlap")
    else:
        fail = bad(f"overlap dedup severity: {x_find}") or fail

    gate = synthesize_gate_adapters(
        [
            ("coderabbit", {"capabilities": {"perHeadState": True}, "perHeadLanded": True, "perHeadState": "landed"}),
            ("pr-agent", {"capabilities": {"perHeadState": True}, "perHeadLanded": False, "perHeadState": "in-flight"}),
        ]
    )
    if gate.get("reviewLanded") is False:
        ok("reviewLanded false when any provider unsettled")
    else:
        fail = bad(f"reviewLanded barrier: {gate}") or fail

    schema = ROOT / ".sw/config.schema.json"
    data = json.loads(schema.read_text(encoding="utf-8"))
    if "providers" in data["properties"]["review"]["properties"]:
        ok("config schema exposes review.providers")
    else:
        fail = bad("review.providers missing from schema") or fail

    return fail


if __name__ == "__main__":
    raise SystemExit(main())
