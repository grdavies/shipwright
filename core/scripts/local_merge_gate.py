#!/usr/bin/env python3
"""Local merge gate artifact — terminal-tier local-evidence authorization (PRD 026 R10/TR5)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ARTIFACT_NAME = "local-merge-gate.json"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def resolve_run_dir(root: Path, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        return p if p.is_absolute() else root / p
    env = os.environ.get("SW_RUN_DIR", "").strip()
    if env:
        p = Path(env)
        return p if p.is_absolute() else root / env
    return root / ".cursor"


def artifact_path(root: Path, run_dir: str | None = None) -> Path:
    return resolve_run_dir(root, run_dir) / ARTIFACT_NAME


def local_evidence_authorizing(status: dict[str, Any], expected_head: str) -> bool:
    if status.get("verdict") not in ("merge-ready-green", "green"):
        gate = status.get("gate")
        if not isinstance(gate, dict) or gate.get("verdict") != "green":
            return False
    if str(status.get("head") or "") != expected_head:
        return False
    gate = status.get("gate")
    if gate is None:
        return True
    if not isinstance(gate, dict):
        return False
    if gate.get("verdict") != "green":
        return False
    if gate.get("coderabbitLanded") is False:
        return False
    return True


def build_artifact(head: str, gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": gate.get("verdict", "blocked"),
        "source": "local-evidence",
        "head": head,
        "gate": gate,
        "writtenAt": utc_now(),
    }


def cmd_write(root: Path, args: argparse.Namespace) -> None:
    head = (args.head or "").strip()
    if not head:
        fail("--head required")
    if args.gate_json:
        gate = json.loads(Path(args.gate_json).read_text(encoding="utf-8"))
    elif args.gate_inline:
        gate = json.loads(args.gate_inline)
    else:
        fail("--gate-json or --gate-inline required")
    artifact = build_artifact(head, gate)
    path = artifact_path(root, args.run_dir)
    write_json(path, artifact)
    emit({"verdict": "pass", "action": "local-merge-gate-write", "path": str(path), "artifact": artifact})


def cmd_read(root: Path, args: argparse.Namespace) -> None:
    path = artifact_path(root, args.run_dir)
    if not path.is_file():
        fail("artifact not found", exit_code=20, path=str(path))
    emit({"verdict": "pass", "action": "local-merge-gate-read", "path": str(path), "artifact": read_json(path)})


def cmd_authorize(root: Path, args: argparse.Namespace) -> None:
    path = artifact_path(root, args.run_dir)
    artifact = read_json(path)
    if not artifact:
        fail("artifact not found", exit_code=20, path=str(path))
    expected = (args.head or "").strip()
    ok = local_evidence_authorizing(artifact, expected) if expected else artifact.get("verdict") == "green"
    emit({"verdict": "pass" if ok else "blocked", "action": "local-merge-gate-authorize", "authorized": ok, "path": str(path), "artifact": artifact}, 0 if ok else 20)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local merge gate artifact (PRD 026 Phase 3)")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="cmd", required=True)
    write = sub.add_parser("write")
    write.add_argument("--head", required=True)
    write.add_argument("--gate-json")
    write.add_argument("--gate-inline")
    write.add_argument("--run-dir")
    read = sub.add_parser("read")
    read.add_argument("--run-dir")
    auth = sub.add_parser("authorize")
    auth.add_argument("--head")
    auth.add_argument("--run-dir")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.cmd == "write":
        cmd_write(root, args)
    elif args.cmd == "read":
        cmd_read(root, args)
    elif args.cmd == "authorize":
        cmd_authorize(root, args)
    else:
        parser.error(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
