#!/usr/bin/env python3
"""CLI for context-compression default-flip parity gate (PRD 058 R30)."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from _sw.cli import run_module_main

SCRIPT_DIR = Path(__file__).resolve().parent
PASS_ARTIFACT_REL = Path(".cursor/context-compress-parity.pass.json")


def _load_harness():
    path = SCRIPT_DIR / "test/fixtures/context-compress-parity/harness.py"
    spec = importlib.util.spec_from_file_location("context_compress_parity_harness", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _pass_artifact_path(root: Path) -> Path:
    return root / PASS_ARTIFACT_REL


def cmd_run(_root: Path) -> int:
    mod = _load_harness()
    result = mod.run_parity_check()
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "pass" else 1


def cmd_record_pass(root: Path) -> int:
    mod = _load_harness()
    result = mod.run_parity_check()
    if result.get("verdict") != "pass":
        print(json.dumps({"verdict": "fail", "action": "record-pass", "parity": result}))
        return 1
    artifact = {
        "verdict": "pass",
        "recordedAt": result.get("recordedAt"),
        "parity": result,
    }
    from dispatch_prompt import utc_now

    artifact["recordedAt"] = utc_now()
    path = _pass_artifact_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"verdict": "pass", "action": "record-pass", "path": str(path)}))
    return 0


def cmd_assert_default_flip(root: Path) -> int:
    from check_gate_lib import load_workflow_config
    from dispatch_prompt import DEFAULT_CONTEXT_COMPRESSION_ENABLED, load_context_compression_config

    cfg = load_context_compression_config(root)
    enabled = bool(cfg.get("enabled", DEFAULT_CONTEXT_COMPRESSION_ENABLED))
    artifact = _pass_artifact_path(root)
    has_pass = artifact.is_file() and json.loads(artifact.read_text(encoding="utf-8")).get("verdict") == "pass"

    if enabled and not has_pass:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "action": "assert-default-flip",
                    "error": "contextCompression.enabled true without parity pass artifact",
                    "artifact": str(artifact),
                }
            )
        )
        return 1

    print(
        json.dumps(
            {
                "verdict": "pass",
                "action": "assert-default-flip",
                "enabled": enabled,
                "parityPassRecorded": has_pass,
            }
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="context_compress_parity_check.py")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="Run parity harness and emit verdict JSON")
    sub.add_parser("record-pass", help="Run harness and persist pass artifact on green")
    sub.add_parser("assert-default-flip", help="Fail closed when default enabled without pass artifact")
    ns = parser.parse_args(argv)
    root = Path(ns.root).resolve()
    if ns.cmd == "run":
        return cmd_run(root)
    if ns.cmd == "record-pass":
        return cmd_record_pass(root)
    if ns.cmd == "assert-default-flip":
        return cmd_assert_default_flip(root)
    parser.print_help()
    return 2


if __name__ == "__main__":
    run_module_main(main)
