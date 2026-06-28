#!/usr/bin/env python3
"""Shared authoring-guard preflight for unit-writing commands (PRD 032 R5-R9/R14)."""
from __future__ import annotations

import getpass
import hashlib
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
import planning_index_gen as pig  # noqa: E402
import planning_paths as pp  # noqa: E402
from wave_json_io import read_json, write_json  # noqa: E402

HANDOFFS_REL = ".cursor/authoring-handoffs.json"
UNIT_ID_RE = re.compile(r"docs/prds/(\d+)-([^/]+)/")
PLANNING_UNIT_RE = re.compile(
    r"docs/planning/(brainstorm|gap|prd|decision|amendment)/([^/]+)/"
)
AMEND_ALLOWED_STATUSES = frozenset({"planned", "in-progress"})


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
    match = PLANNING_UNIT_RE.search(norm)
    if match:
        return match.group(2)
    match = UNIT_ID_RE.search(norm)
    if not match:
        return None
    return f"prd-{match.group(1)}-{match.group(2)}"


def unit_folder_from_rel(rel: str) -> str | None:
    norm = rel.replace("\\", "/").rstrip("/")
    match = PLANNING_UNIT_RE.search(norm + "/")
    if match:
        return norm[: match.end()].rstrip("/")
    match = UNIT_ID_RE.search(norm + "/")
    if match:
        return norm[: match.end()].rstrip("/")
    return None


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


def derived_region_populated(derived_body: str) -> bool:
    for line in derived_body.splitlines():
        line = line.strip()
        if not line or line.startswith("|") or line.startswith("-"):
            continue
        if ":" in line:
            return True
    return False


def reconcile_generation_token(root: Path, unit_id: str) -> dict[str, Any]:
    """Bind evaluation to derived+inFlight+structural snapshot (PRD 032 R9)."""
    index_path = pig.index_path(root)
    derived_body = ""
    inflight_body = ""
    if index_path.is_file():
        regions = pig.parse_regions(index_path.read_text(encoding="utf-8"))
        derived_body = regions.derived
        inflight_body = regions.inFlight

    units = {u.id: u for u in pig.discover_units(root)}
    unit = units.get(unit_id)
    structural_status = unit.status if unit else ""

    if derived_region_populated(derived_body):
        mode = "derived"
        consumer_status = (
            pig.resolve_consumer_status(unit, derived_body) if unit else ""
        )
    else:
        mode = "structural-degraded"
        consumer_status = structural_status
        if unit and unit.type != "gap":
            tup = read_tuples(root).get(unit_id)
            if tup and is_run_live(root, tup.run_id):
                consumer_status = "in-progress"

    token_src = "\0".join(
        [derived_body, inflight_body, unit_id, structural_status, mode]
    )
    token = hashlib.sha256(token_src.encode("utf-8")).hexdigest()[:16]
    return {
        "token": token,
        "mode": mode,
        "consumerStatus": consumer_status,
        "unitId": unit_id,
        "structuralStatus": structural_status,
        "unitType": unit.type if unit else None,
    }


def propose_complete_change_route(root: Path, unit_id: str) -> dict[str, Any]:
    """Route completed-unit change requests to a new unit or gap (PRD 032 R8)."""
    units = {u.id: u for u in pig.discover_units(root)}
    unit = units.get(unit_id)
    if not unit:
        fail(f"unit not found for route: {unit_id}")
    stamp = utc_now()[:10].replace("-", "")
    if unit.type == "gap":
        new_id = f"gap-{unit_id}-followup-{stamp}"
        return {
            "kind": "gap",
            "suggestedUnitId": new_id,
            "edges": {"depends": [unit_id]},
            "suggestedPath": f"docs/planning/gap/{new_id}/{new_id}.md",
            "message": (
                "Complete gap units cannot be amended in-place; "
                "file a follow-up gap unit."
            ),
        }
    new_id = f"{unit_id}-followup-{stamp}"
    return {
        "kind": "extending-unit",
        "suggestedUnitId": new_id,
        "edges": {"extends": [unit_id]},
        "suggestedPath": f"docs/planning/{unit.type}/{new_id}/{new_id}.md",
        "message": (
            "Complete units cannot be amended in-place; fork a new unit with "
            "extends:/supersedes: or append a gap unit."
        ),
    }


def amend_status_guard(root: Path, unit_id: str, artifact: str | None) -> None:
    """Enforce /sw-amend allowed statuses and route complete-unit requests (R7/R8)."""
    info = reconcile_generation_token(root, unit_id)
    status = info["consumerStatus"]
    if status == "complete":
        route = propose_complete_change_route(root, unit_id)
        emit(
            {
                "verdict": "pass",
                "action": "authoring-guard-amend",
                "outcome": "route",
                "unitId": unit_id,
                "artifact": artifact,
                "generationToken": info["token"],
                "route": route,
            },
            exit_code=21,
        )
    if status not in AMEND_ALLOWED_STATUSES:
        fail(
            f"/sw-amend refused: unit status is {status!r} "
            f"(allowed: {sorted(AMEND_ALLOWED_STATUSES)})",
            unitId=unit_id,
            consumerStatus=status,
            generationToken=info["token"],
        )


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


def staged_unit_paths(root: Path) -> dict[str, list[str]]:
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return {}
    grouped: dict[str, list[str]] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        rel = line.strip().replace("\\", "/")
        uid = unit_id_from_rel(rel)
        if not uid:
            continue
        grouped.setdefault(uid, []).append(rel)
    return grouped


def check_staged_mutations(root: Path, args: list[str]) -> None:
    """Pre-commit guard for complete-unit folder immutability (R9/R12)."""
    expect_token = parse_kv(args, "--expect-token")
    unit_filter = parse_kv(args, "--unit")
    warnings: list[str] = []
    violations: list[str] = []
    token_after: dict[str, Any] | None = None

    grouped = staged_unit_paths(root)
    if unit_filter:
        grouped = {unit_filter: grouped.get(unit_filter, [])}

    for unit_id, paths in grouped.items():
        if not paths:
            continue
        token_before = reconcile_generation_token(root, unit_id)
        inline_reconcile(root, unit_id, commit=False)
        token_after = reconcile_generation_token(root, unit_id)

        if expect_token and token_before["token"] != expect_token:
            violations.append(
                f"{unit_id}: reconcile-generation token mismatch (TOCTOU)"
            )
            continue
        if token_before["token"] != token_after["token"]:
            violations.append(
                f"{unit_id}: reconcile-generation token changed during evaluation"
            )
            continue

        status = token_after["consumerStatus"]
        if status != "complete":
            continue

        if token_after["mode"] == "structural-degraded":
            warnings.append(
                f"{unit_id}: structural-degraded mode — complete unit mutation "
                f"on {', '.join(paths)} (warning only; derived region empty)"
            )
            continue

        violations.append(
            f"{unit_id}: mutation rejected on complete unit — {', '.join(paths)}"
        )

    if violations:
        fail(
            "completed-unit immutability violation",
            violations=violations,
            generationToken=token_after.get("token") if token_after else None,
        )
    if warnings:
        for w in warnings:
            print(f"sw-completed-unit: warning: {w}", file=sys.stderr)
    emit(
        {
            "verdict": "pass",
            "action": "completed-unit-guard",
            "warnings": warnings,
            "checkedUnits": list(grouped.keys()),
        }
    )


def cmd_preflight(root: Path, args: list[str]) -> None:
    unit_id, artifact = resolve_unit_id(root, args)
    handoff = parse_kv(args, "--handoff")
    command = parse_kv(args, "--command")
    do_commit = parse_kv(args, "--no-commit") is None

    inline_reconcile(root, unit_id, commit=do_commit)
    live = provably_in_flight(root, unit_id)

    if command == "sw-amend":
        amend_status_guard(root, unit_id, artifact)

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
        fail("subcommand required: preflight|list-handoffs|check-staged")
    cmd = rest[0]
    tail = rest[1:]
    if cmd == "preflight":
        cmd_preflight(root, tail)
    elif cmd == "list-handoffs":
        cmd_list_handoffs(root, tail)
    elif cmd == "check-staged":
        check_staged_mutations(root, tail)
    else:
        fail(f"unknown subcommand: {cmd}")


if __name__ == "__main__":
    main()
