#!/usr/bin/env python3
"""Refuse merge-ready-green without binding-valid mandatory gate evidence (PRD 065 R8)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gate_evidence import resolve_authoritative_record, resolve_head_sha, repo_root
from gate_manifest import iter_gates_ordered, load_manifest, resolve_gate_class

REFUSAL_HALT = "merge-ready:mandatory-gate-evidence"


def mandatory_gate_ids(root: Path) -> list[str]:
    manifest = load_manifest(root)
    out: list[str] = []
    for gate in iter_gates_ordered(manifest):
        gate_id = str(gate.get("id") or "")
        if not gate_id:
            continue
        if resolve_gate_class(gate_id, manifest, root=root) == "mandatory":
            out.append(gate_id)
    return out


def evaluate_mandatory_gate_evidence(
    root: Path,
    phase_slug: str,
    *,
    head_sha: str | None = None,
) -> dict[str, Any]:
    root = repo_root(root)
    head = head_sha or resolve_head_sha(root)
    failures: list[dict[str, str]] = []
    for gate_id in mandatory_gate_ids(root):
        record, cause = resolve_authoritative_record(root, phase_slug, gate_id, head_sha=head)
        if record is None:
            failures.append({"gateId": gate_id, "cause": cause or "gate-evidence:missing"})
            continue
        verdict = str(record.get("verdict") or "")
        if verdict != "pass":
            failures.append(
                {
                    "gateId": gate_id,
                    "cause": f"gate-evidence:non-pass:{verdict or 'unknown'}",
                }
            )
    if failures:
        return {
            "verdict": "fail",
            "halt": REFUSAL_HALT,
            "cause": failures[0]["cause"],
            "gateId": failures[0]["gateId"],
            "failures": failures,
        }
    return {"verdict": "pass", "checked": mandatory_gate_ids(root)}


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Merge-ready mandatory gate evidence check")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--phase-slug", required=True)
    parser.add_argument("--head", default="")
    args = parser.parse_args(argv)
    payload = evaluate_mandatory_gate_evidence(
        args.root,
        args.phase_slug,
        head_sha=args.head or None,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("verdict") == "pass" else 20


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
