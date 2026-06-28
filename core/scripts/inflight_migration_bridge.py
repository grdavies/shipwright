#!/usr/bin/env python3
"""One-shot migration bridge: promote legacy deliver in-progress markers into INDEX inFlight (PRD 032 R10/R18)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig  # noqa: E402
from inflight_signal import (  # noqa: E402
    InflightTuple,
    git_commit_inflight,
    is_run_live,
    prd_unit_id_from_state,
    read_tuples,
    render_region_body,
    run_id_from_slug,
    validate_tuple_text,
    write_tuples,
)
from wave_json_io import read_json, write_json  # noqa: E402
from wave_state import TERMINAL_VERDICTS, enumerate_scoped_runs  # noqa: E402

BRIDGE_RECORD = ".cursor/inflight-migration-bridge.json"
LIVE_VERDICTS = frozenset({"running", "in-flight"})


@dataclass(frozen=True)
class LegacyMarker:
    unit_id: str
    run_id: str
    branch: str
    epoch: int
    state_path: str
    slug: str
    source: str


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def bridge_record_path(root: Path) -> Path:
    return root / BRIDGE_RECORD


def load_bridge_record(root: Path) -> dict[str, Any]:
    path = bridge_record_path(root)
    if not path.is_file():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def save_bridge_record(root: Path, record: dict[str, Any]) -> None:
    path = bridge_record_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, record)


def _read_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return read_json(path)
    except Exception:
        return {}


def _is_live_deliver_state(state: dict[str, Any]) -> bool:
    verdict = str(state.get("verdict") or "")
    if verdict in LIVE_VERDICTS:
        return True
    phases = state.get("phases") or {}
    if isinstance(phases, dict):
        return any(
            isinstance(p, dict) and str(p.get("status")) == "in-flight" for p in phases.values()
        )
    return False


def _marker_from_state(
    *,
    slug: str,
    state_path: str,
    state: dict[str, Any],
) -> LegacyMarker | None:
    if not _is_live_deliver_state(state):
        return None

    explicit = state.get("legacyInFlightMarker")
    if isinstance(explicit, dict):
        unit_id = explicit.get("unitId") or explicit.get("unit")
        run_id = str(explicit.get("runId") or run_id_from_slug(slug))
        branch = explicit.get("branch") or (state.get("target") or {}).get("branch")
        epoch = int(explicit.get("epoch") or 1)
        source = "legacyInFlightMarker"
    else:
        unit_id = prd_unit_id_from_state(state)
        if not unit_id:
            return None
        lease = state.get("inflightLease") or {}
        run_id = str(lease.get("runId") or run_id_from_slug(slug))
        branch = (state.get("target") or {}).get("branch")
        epoch = int(lease.get("epoch") or 1)
        source = "deliver-run-state"

    if not branch or not isinstance(branch, str):
        return None
    if not unit_id or not isinstance(unit_id, str):
        return None
    return LegacyMarker(
        unit_id=unit_id,
        run_id=run_id,
        branch=branch,
        epoch=epoch,
        state_path=state_path,
        slug=slug,
        source=source,
    )


def discover_legacy_markers(root: Path) -> tuple[list[LegacyMarker], list[str]]:
    markers: list[LegacyMarker] = []
    by_unit: dict[str, LegacyMarker] = {}
    conflicts: list[str] = []
    for run in enumerate_scoped_runs(root):
        state_path = root / str(run.get("statePath") or "")
        state = _read_state(state_path)
        slug = str(run.get("slug") or "")
        if slug == "(legacy)":
            slug = "legacy"
        marker = _marker_from_state(slug=slug, state_path=str(run.get("statePath")), state=state)
        if marker is None:
            continue
        prior = by_unit.get(marker.unit_id)
        if prior is not None:
            if prior.run_id != marker.run_id:
                conflicts.append(
                    f"{marker.unit_id}: conflicting live markers "
                    f"({prior.run_id} vs {marker.run_id})"
                )
            continue
        by_unit[marker.unit_id] = marker
        markers.append(marker)
    return markers, conflicts


def tuples_compatible(committed: InflightTuple | None, proposed: InflightTuple) -> bool:
    if committed is None:
        return True
    if committed.run_id != proposed.run_id:
        return False
    if committed.branch and proposed.branch and committed.branch != proposed.branch:
        return False
    if committed.epoch != proposed.epoch and committed.epoch > proposed.epoch:
        return False
    return True


def would_desync_live_run(root: Path, committed: InflightTuple | None, proposed: InflightTuple) -> bool:
    if committed is None:
        return False
    if committed.run_id == proposed.run_id:
        return not tuples_compatible(committed, proposed)
    if is_run_live(root, committed.run_id) and committed.run_id != proposed.run_id:
        return True
    if is_run_live(root, proposed.run_id) and committed.run_id != proposed.run_id:
        return True
    return False


def cmd_reconcile(root: Path, args: list[str]) -> None:
    from wave_living_doc_lock import living_doc_write_lock

    dry_run = has_flag(args, "--dry-run")
    force = has_flag(args, "--force")
    do_commit = has_flag(args, "--commit")
    record = load_bridge_record(root)
    if record.get("completedAt") and not force:
        emit(
            {
                "verdict": "pass",
                "action": "inflight-migration-bridge",
                "skipped": True,
                "reason": "already-completed",
                "completedAt": record.get("completedAt"),
                "promoted": record.get("promoted") or [],
            }
        )

    markers, marker_conflicts = discover_legacy_markers(root)
    errors: list[str] = list(marker_conflicts)
    committed = read_tuples(root)
    promoted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    proposed_map = dict(committed)
    for marker in markers:
        proposed = InflightTuple(
            run_id=marker.run_id,
            epoch=marker.epoch,
            branch=marker.branch,
        )
        try:
            proposed.validate_shape()
        except ValueError as exc:
            errors.append(f"{marker.unit_id}: invalid tuple: {exc}")
            continue

        existing = committed.get(marker.unit_id)
        if existing is not None:
            if (
                existing.run_id == proposed.run_id
                and existing.branch == proposed.branch
                and existing.epoch == proposed.epoch
            ):
                skipped.append(
                    {
                        "unitId": marker.unit_id,
                        "runId": marker.run_id,
                        "reason": "already-committed",
                    }
                )
                continue

        if would_desync_live_run(root, existing, proposed):
            errors.append(
                f"{marker.unit_id}: would desync live run "
                f"(committed={existing.run_id if existing else None}, proposed={proposed.run_id})"
            )
            continue

        proposed_map[marker.unit_id] = proposed
        promoted.append(
            {
                "unitId": marker.unit_id,
                "runId": marker.run_id,
                "branch": marker.branch,
                "epoch": marker.epoch,
                "source": marker.source,
                "statePath": marker.state_path,
            }
        )

    if errors:
        fail(
            "migration bridge would desync live runs",
            exit_code=20,
            halt="migration-bridge-desync",
            errors=errors,
            promoted=promoted,
            skipped=skipped,
        )

    if not promoted:
        out_record = {
            "completedAt": utc_now(),
            "promoted": [],
            "skipped": skipped,
            "dryRun": dry_run,
        }
        if not dry_run:
            save_bridge_record(root, out_record)
        emit(
            {
                "verdict": "pass",
                "action": "inflight-migration-bridge",
                "promoted": [],
                "skipped": skipped,
                "markersScanned": len(markers),
                "dryRun": dry_run,
            }
        )

    target_branch = promoted[0].get("branch") if promoted else None
    with living_doc_write_lock(root, target=target_branch, holder="inflight-migration-bridge"):
        body = render_region_body(proposed_map)
        validate_tuple_text(body, path=str(pig.index_rel(root)))
        write_tuples(root, proposed_map, dry_run=dry_run)
        commit_sha = None
        if do_commit and not dry_run:
            unit_label = promoted[0]["unitId"] if len(promoted) == 1 else f"{len(promoted)}-units"
            env = {**os.environ, "SW_INDEX_REGION_WRITER": "deliver"}
            rel = pig.index_rel(root)
            proc = subprocess.run(
                ["git", "-C", str(root), "status", "--porcelain", "--", rel],
                text=True,
                capture_output=True,
            )
            if proc.stdout.strip():
                subprocess.run(["git", "-C", str(root), "add", rel], check=True, env=env)
                msg = f"chore(planning): migration-bridge inFlight backfill for {unit_label}"
                cproc = subprocess.run(
                    ["git", "-C", str(root), "commit", "-m", msg],
                    text=True,
                    capture_output=True,
                    env=env,
                )
                if cproc.returncode != 0:
                    fail(cproc.stderr.strip() or cproc.stdout.strip() or "migration bridge commit failed")
                sha_proc = subprocess.run(
                    ["git", "-C", str(root), "rev-parse", "HEAD"],
                    text=True,
                    capture_output=True,
                    check=True,
                )
                commit_sha = sha_proc.stdout.strip()
            else:
                commit_sha = git_commit_inflight(root, unit_label, dry_run=True)

    out_record = {
        "completedAt": utc_now(),
        "promoted": promoted,
        "skipped": skipped,
        "commit": commit_sha,
        "dryRun": dry_run,
    }
    if not dry_run:
        save_bridge_record(root, out_record)

    emit(
        {
            "verdict": "pass",
            "action": "inflight-migration-bridge",
            "promoted": promoted,
            "skipped": skipped,
            "markersScanned": len(markers),
            "commit": commit_sha,
            "dryRun": dry_run,
            "path": pig.index_rel(root),
        }
    )


def cmd_discover(root: Path, args: list[str]) -> None:
    markers, marker_conflicts = discover_legacy_markers(root)
    errors: list[str] = list(marker_conflicts)
    emit(
        {
            "verdict": "pass",
            "action": "inflight-migration-bridge-discover",
            "conflicts": conflicts,
            "markers": [
                {
                    "unitId": m.unit_id,
                    "runId": m.run_id,
                    "branch": m.branch,
                    "epoch": m.epoch,
                    "source": m.source,
                    "statePath": m.state_path,
                }
                for m in markers
            ],
        }
    )


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        fail("usage: inflight_migration_bridge.py <repo-root> <command> [options]")
    root = Path(args[0]).resolve()
    rest = args[1:]
    if not rest:
        fail("subcommand required: reconcile|discover")
    cmd = rest[0]
    tail = rest[1:]
    if cmd == "reconcile":
        cmd_reconcile(root, tail)
    elif cmd == "discover":
        cmd_discover(root, tail)
    else:
        fail(f"unknown subcommand: {cmd}")


if __name__ == "__main__":
    main()
