#!/usr/bin/env python3
"""Shared authoring-guard preflight for unit-writing commands (PRD 032 R5/R6/R14)."""
from __future__ import annotations

import getpass
import json
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from inflight_signal import InflightTuple, is_run_live, read_tuples  # noqa: E402
import planning_paths as pp  # noqa: E402
from wave_json_io import read_json, write_json  # noqa: E402

HANDOFFS_REL = ".cursor/authoring-handoffs.json"
UNIT_ID_RE = re.compile(r"docs/prds/(\d+)-([^/]+)/")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def actor_id() -> str:
    return f"{getpass.getuser()}@{socket.gethostname()}"


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, "halt": "authoring-guard", **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def unit_id_from_rel(rel: str) -> str | None:
    norm = rel.replace("\\", "/")
    match = UNIT_ID_RE.search(norm)
    if not match:
        return None
    return f"prd-{match.group(1)}-{match.group(2)}"


def resolve_unit_id(root: Path, args: list[str]) -> tuple[str, str | None]:
    unit = parse_kv(args, "--unit")
    artifact = parse_kv(args, "--path")
    if unit:
        return unit, artifact
    if artifact:
        try:
            rel = pp.rel_contained(root, artifact)
        except pp.PathEscapeError as exc:
            fail(str(exc))
        uid = unit_id_from_rel(rel)
        if not uid:
            fail(f"cannot resolve planning unit id from path: {rel}")
        return uid, rel
    fail("--unit or --path required")


def handoffs_path(root: Path) -> Path:
    return root / HANDOFFS_REL


def load_handoffs(root: Path) -> list[dict[str, Any]]:
    path = handoffs_path(root)
    if not path.is_file():
        return []
    try:
        data = read_json(path)
    except Exception:
        return []
    items = data.get("handoffs") if isinstance(data, dict) else None
    return list(items) if isinstance(items, list) else []


def save_handoffs(root: Path, handoffs: list[dict[str, Any]]) -> None:
    path = handoffs_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, {"version": 1, "updatedAt": utc_now(), "handoffs": handoffs})


def record_handoff(
    root: Path,
    *,
    unit_id: str,
    artifact: str | None,
    command: str | None,
    reason: str,
    run_id: str | None,
    branch: str | None,
) -> dict[str, Any]:
    entry = {
        "unitId": unit_id,
        "artifact": artifact,
        "command": command,
        "reason": reason,
        "runId": run_id,
        "branch": branch,
        "who": actor_id(),
        "when": utc_now(),
    }
    handoffs = load_handoffs(root)
    handoffs.append(entry)
    save_handoffs(root, handoffs)
    return entry


def inline_reconcile(root: Path, unit_id: str, *, commit: bool) -> None:
    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "inflight_reconcile.py"),
        str(root),
        "reconcile",
        "--unit",
        unit_id,
    ]
    if commit:
        cmd.append("--commit")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        fail(
            "inline inflight reconcile failed",
            cause="reconcile-failed",
            stderr=proc.stderr.strip(),
            stdout=proc.stdout.strip(),
            exit_code=20,
        )


def provably_in_flight(root: Path, unit_id: str) -> dict[str, Any] | None:
    tuples = read_tuples(root)
    tup: InflightTuple | None = tuples.get(unit_id)
    if tup is None:
        return None
    if is_run_live(root, tup.run_id):
        return {
            "unitId": unit_id,
            "runId": tup.run_id,
            "branch": tup.branch,
            "branchToken": tup.branch_token,
            "epoch": tup.epoch,
        }
    return None


def cmd_preflight(root: Path, args: list[str]) -> None:
    unit_id, artifact = resolve_unit_id(root, args)
    handoff = parse_kv(args, "--handoff")
    command = parse_kv(args, "--command")
    do_commit = parse_kv(args, "--no-commit") is None

    inline_reconcile(root, unit_id, commit=do_commit)
    live = provably_in_flight(root, unit_id)

    if handoff:
        if not live:
            fail(
                "handoff requires a provably in-flight unit after reconcile",
                unitId=unit_id,
            )
        entry = record_handoff(
            root,
            unit_id=unit_id,
            artifact=artifact,
            command=command,
            reason=handoff,
            run_id=live.get("runId"),
            branch=live.get("branch"),
        )
        emit(
            {
                "verdict": "pass",
                "action": "authoring-guard-preflight",
                "outcome": "handoff",
                "unitId": unit_id,
                "handoff": entry,
            }
        )

    if live:
        fail(
            "unit is in-flight; wait for deliver run or pass --handoff <reason>",
            unitId=unit_id,
            runId=live.get("runId"),
            branch=live.get("branch"),
            exit_code=20,
        )
    emit(
        {
            "verdict": "pass",
            "action": "authoring-guard-preflight",
            "outcome": "proceed",
            "unitId": unit_id,
            "artifact": artifact,
        }
    )


def cmd_list_handoffs(root: Path, _args: list[str]) -> None:
    handoffs = load_handoffs(root)
    emit(
        {
            "verdict": "pass",
            "action": "authoring-guard-list-handoffs",
            "handoffs": handoffs,
            "pullInScan": [h.get("artifact") for h in handoffs if h.get("artifact")],
        }
    )


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        fail("usage: authoring_guard.py <repo-root> <command> [options]")
    root = Path(args[0]).resolve()
    rest = args[1:]
    if not rest:
        fail("subcommand required: preflight|list-handoffs")
    cmd = rest[0]
    tail = rest[1:]
    if cmd == "preflight":
        cmd_preflight(root, tail)
    elif cmd == "list-handoffs":
        cmd_list_handoffs(root, tail)
    else:
        fail(f"unknown subcommand: {cmd}")


if __name__ == "__main__":
    main()
