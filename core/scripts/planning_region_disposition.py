#!/usr/bin/env python3
"""Region disposition + committed inFlight projection (PRD 046 R80, D22, D23)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig  # noqa: E402
import planning_paths as pp  # noqa: E402
from inflight_signal import parse_region_body, read_tuples, render_region_body  # noqa: E402
from planning_cutover import load_cutover_gate, region_authority  # noqa: E402

INFLIGHT_RUNSTATE_REL = ".cursor/hooks/state/inflight-run-state.json"


def run_state_path(root: Path) -> Path:
    return pp.git_root(root) / INFLIGHT_RUNSTATE_REL


def load_run_state_tuples(root: Path) -> dict[str, Any]:
    path = run_state_path(root)
    if not path.is_file():
        return read_tuples(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return read_tuples(root)
    tuples = data.get("tuples")
    if isinstance(tuples, dict):
        from inflight_signal import InflightTuple

        out: dict[str, Any] = {}
        for unit_id, raw in tuples.items():
            if not isinstance(raw, dict):
                continue
            out[unit_id] = InflightTuple(
                run_id=str(raw.get("runId", raw.get("run-id", ""))),
                epoch=int(raw.get("epoch", 1)),
                branch=raw.get("branch"),
                branch_token=raw.get("branchToken") or raw.get("branch-token"),
            )
        return out
    return read_tuples(root)


def save_run_state_tuples(root: Path, tuples: dict[str, Any]) -> None:
    path = run_state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {}
    for unit_id, tup in tuples.items():
        serializable[unit_id] = {
            "runId": tup.run_id,
            "epoch": tup.epoch,
            "branch": tup.branch,
            "branchToken": tup.branch_token,
        }
    path.write_text(
        json.dumps({"version": 1, "tuples": serializable}, indent=2) + "\n",
        encoding="utf-8",
    )


def project_inflight_to_index(root: Path, *, dry_run: bool = False) -> str:
    """Project run-state tuples read-only into committed INDEX inFlight region (R80)."""
    worktree = pp.git_root(root)
    authority = region_authority(worktree, "inFlight")
    if authority != "deliver":
        raise ValueError(f"inFlight authority is {authority!r}, not deliver")
    tuples = load_run_state_tuples(worktree)
    body = render_region_body(tuples)
    index_path = pig.index_path(worktree)
    existing = index_path.read_text(encoding="utf-8") if index_path.is_file() else None
    content = pig.read_merge_write(existing, writer="deliver", new_region_body=body, root=worktree)
    if not dry_run:
        pig.write_index(worktree, content)
    return content


def doctor_inflight_divergence(root: Path) -> list[dict[str, Any]]:
    """Fail closed on run-state vs committed projection skew (R80)."""
    worktree = pp.git_root(root)
    run_tuples = load_run_state_tuples(worktree)
    index_path = pig.index_path(worktree)
    if not index_path.is_file():
        if run_tuples:
            return [{"error": "missing-index-projection", "runStateUnits": sorted(run_tuples)}]
        return []
    regions = pig.parse_regions(index_path.read_text(encoding="utf-8"))
    try:
        projected = parse_region_body(regions.inFlight)
    except ValueError as exc:
        return [{"error": "invalid-index-inflight", "message": str(exc)}]
    issues: list[dict[str, Any]] = []
    run_ids = set(run_tuples)
    proj_ids = set(projected)
    for unit_id in sorted(run_ids | proj_ids):
        run_tup = run_tuples.get(unit_id)
        proj_tup = projected.get(unit_id)
        if run_tup is None or proj_tup is None:
            issues.append({"unitId": unit_id, "error": "tuple-presence-skew"})
            continue
        if run_tup.run_id != proj_tup.run_id or run_tup.epoch != proj_tup.epoch:
            issues.append(
                {
                    "unitId": unit_id,
                    "error": "tuple-value-skew",
                    "runState": {"runId": run_tup.run_id, "epoch": run_tup.epoch},
                    "projection": {"runId": proj_tup.run_id, "epoch": proj_tup.epoch},
                }
            )
    return issues


def region_disposition_matrix(root: Path) -> dict[str, str]:
    gate = load_cutover_gate(pp.git_root(root))
    return {
        "structural": gate.get("structural", "file"),
        "derived": gate.get("derived", "file"),
        "inFlight": gate.get("inFlight", "deliver"),
    }


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def cmd_project(root: Path, args: list[str]) -> None:
    dry_run = "--dry-run" in args
    try:
        project_inflight_to_index(root, dry_run=dry_run)
    except ValueError as exc:
        fail(str(exc))
    emit({"verdict": "pass", "action": "project-inflight", "dryRun": dry_run})


def cmd_doctor(root: Path, _args: list[str]) -> None:
    issues = doctor_inflight_divergence(root)
    if issues:
        fail("inflight-divergence", issues=issues, exit_code=20)
    emit({"verdict": "pass", "action": "inflight-divergence-doctor"})


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        fail("usage: planning_region_disposition.py <repo-root> <command>")
    root = Path(args[0]).resolve()
    command = args[1]
    if command == "project":
        cmd_project(root, args[2:])
    elif command == "doctor":
        cmd_doctor(root, args[2:])
    elif command == "matrix":
        emit({"verdict": "pass", "matrix": region_disposition_matrix(root)})
    else:
        fail(f"unknown command: {command}")


if __name__ == "__main__":
    main()
