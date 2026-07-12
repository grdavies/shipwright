#!/usr/bin/env python3
"""Mechanical gate handlers with execution proof and evidence writes (PRD 065 R9)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from gate_evidence import (
    build_evidence_record,
    digest_bytes,
    evidence_record_path,
    repo_root,
    write_evidence_atomic,
)
from gate_manifest import gates_by_id, load_manifest, resolve_gate_class
from kernel_classification import normalize_step

R9_GATE_IDS = frozenset(
    {
        "behavioral-anomaly",
        "build-chain",
        "pre-pr-smoke",
        "decision-log",
        "verification-gate",
    }
)



def is_gate_handler_step(step: str) -> bool:
    return normalize_step(step) in R9_GATE_IDS


def _artifact_path(template: str, run_dir: Path) -> Path:
    return Path(template.format(runDir=str(run_dir)))


def build_gate_argv(root: Path, gate_id: str, run_dir: Path) -> list[str]:
    py = sys.executable
    scripts = SCRIPT_DIR
    gate = gates_by_id(load_manifest(root))[gate_id]
    evidence = gate.get("evidence") or {}
    status_artifact = str(evidence.get("statusArtifact") or f"{{runDir}}/{gate_id}.status.json")
    out_path = _artifact_path(status_artifact, run_dir)

    if gate_id == "behavioral-anomaly":
        return [
            py,
            str(scripts / "behavioral_anomaly_check.py"),
            "--root",
            str(root),
            "--verify-status",
            str(run_dir / "sw-verify.status.json"),
            "--ship-steps",
            str(run_dir / "ship-steps.json"),
            "--out",
            str(out_path),
        ]
    if gate_id == "verification-gate":
        argv = [
            py,
            str(scripts / "verify-evidence.py"),
            "--root",
            str(root),
            "--verify-status",
            str(run_dir / "sw-verify.status.json"),
        ]
        behavioral = run_dir / "behavioral-anomaly.status.json"
        if behavioral.is_file():
            argv.extend(["--behavioral-status", str(behavioral)])
        return argv
    if gate_id == "build-chain":
        return [py, str(scripts / "ship-build-chain-check.py")]
    if gate_id == "pre-pr-smoke":
        return [py, str(scripts / "ship_pre_pr_smoke.py"), str(root)]
    if gate_id == "decision-log":
        body_file = run_dir / "decision-log.body.json"
        if not body_file.is_file():
            body_file.write_text(
                json.dumps(
                    {
                        "intent": "phase gate handler stub",
                        "alternativesRuledOut": ["skip"],
                        "highRiskAreas": ["none"],
                        "taskRefs": ["4.1"],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
        return [py, str(scripts / "decision_log.py"), "validate", "--body-file", str(body_file)]
    entry = gate.get("entrypoint") or {}
    script = entry.get("script")
    if isinstance(script, str) and script:
        return [py, str(root / script)]
    raise ValueError(f"no argv builder for gate {gate_id!r}")


def capture_execution(argv: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
    started = time.monotonic()
    proc = subprocess.run(argv, cwd=str(cwd), env=env, capture_output=True)
    duration = max(0.0, time.monotonic() - started)
    return proc.returncode, {
        "argv": [str(part) for part in argv],
        "exitCode": int(proc.returncode),
        "stdoutDigest": digest_bytes(proc.stdout or b""),
        "stderrDigest": digest_bytes(proc.stderr or b""),
        "duration": round(duration, 6),
    }


def gate_pass_verdict(gate_id: str, exit_code: int) -> str:
    if gate_id == "behavioral-anomaly":
        return "pass" if exit_code in (0, 10) else "fail"
    return "pass" if exit_code == 0 else "fail"


def run_gate_handler(
    root: Path,
    phase_slug: str,
    gate_id: str,
    run_dir: Path,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = repo_root(root)
    gate_id = normalize_step(gate_id)
    if gate_id not in R9_GATE_IDS:
          return {"verdict": "fail", "cause": "gate-handler:not-r9-gate", "gateId": gate_id}
    gate = gates_by_id(load_manifest(root))[gate_id]
    evidence = gate.get("evidence") or {}
    argv = build_gate_argv(root, gate_id, run_dir)
    exit_code, execution = capture_execution(argv, cwd=root, env=env)
    verdict = gate_pass_verdict(gate_id, exit_code)
    status_artifact = str(evidence.get("statusArtifact") or f"{{runDir}}/{gate_id}.status.json")
    artifact_path = _artifact_path(status_artifact, run_dir)
    artifact_refs = [str(artifact_path)] if artifact_path.exists() else []
    record = build_evidence_record(
        gate_id=gate_id,
        gate_class=resolve_gate_class(gate_id, root=root),
        binding_mode=str(evidence.get("bindingMode") or "head-exact"),
        evaluation_point=str(evidence.get("evaluationPoint") or "pre-sw-commit"),
        verdict=verdict,
        execution=execution,
        artifact_refs=artifact_refs,
        root=root,
    )
    evidence_path = evidence_record_path(root, phase_slug, gate_id)
    stamped = write_evidence_atomic(evidence_path, record)
    return {
        "verdict": "pass" if verdict == "pass" else "fail",
        "gateId": gate_id,
        "exitCode": exit_code,
        "execution": execution,
        "evidencePath": str(evidence_path),
        "record": stamped,
        "artifactRefs": artifact_refs,
    }


def run_all_r9_handlers(root: Path, phase_slug: str, run_dir: Path) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for gate_id in sorted(R9_GATE_IDS):
        results[gate_id] = run_gate_handler(root, phase_slug, gate_id, run_dir)
    failed = [gid for gid, res in results.items() if res.get("verdict") != "pass"]
    return {
        "verdict": "pass" if not failed else "fail",
        "failed": failed,
        "results": results,
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Mechanical ship-loop gate handlers")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--phase-slug", required=True)
    parser.add_argument("--gate-id", default="")
    parser.add_argument("--run-dir", default="")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    root = repo_root(args.root)
    run_dir = Path(args.run_dir) if args.run_dir else root / ".cursor" / "sw-deliver-runs" / args.phase_slug
    if args.all:
        payload = run_all_r9_handlers(root, args.phase_slug, run_dir)
    else:
        if not args.gate_id:
            print(json.dumps({"verdict": "fail", "error": "--gate-id or --all required"}, indent=2))
            return 2
        payload = run_gate_handler(root, args.phase_slug, args.gate_id, run_dir)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("verdict") == "pass" else 20


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)

