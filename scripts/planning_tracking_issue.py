#!/usr/bin/env python3
"""inFlight tracking-issue redaction and refusal (PRD 046 R89 / PRD 043 R28)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_paths as pp  # noqa: E402
import planning_visibility as pv  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402
from planning_store import store_section  # noqa: E402
from planning_visibility import resolve_unit_visibility  # noqa: E402


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def refuse_private_on_public_store(root: Path, visibility: str) -> dict[str, Any] | None:
    """Refuse tracking issue for private/memory units on public/shared store (R89, R28)."""
    if not pv.body_is_redacted(visibility):
        return None
    probe = pv.probe_remote_visibility(root)
    remote_vis = str(probe.get("remoteVisibility", "absent"))
    if remote_vis == "public":
        return {
            "verdict": "refused",
            "error": "private-tracking-on-public-store",
            "visibility": pv.normalize_visibility(visibility),
            "remoteVisibility": remote_vis,
            "remoteProbe": probe,
            "failClosed": True,
        }
    return None


def prepare_tracking_issue(
    root: Path,
    unit_id: str,
    tuple_data: dict[str, Any],
    *,
    visibility: str | None = None,
    unit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Prepare redacted tracking issue payload; refuse when unsafe (R89)."""
    worktree = pp.git_root(root)
    cfg = load_workflow_config(worktree)
    unit_obj = dict(unit or {"id": unit_id})
    if visibility is None:
        vis = resolve_unit_visibility(unit_obj, cfg)["visibility"]
    else:
        vis = pv.normalize_visibility(visibility)

    refusal = refuse_private_on_public_store(worktree, vis)
    if refusal is not None:
        return refusal

    redacted = pv.redact_inflight_tuple(dict(tuple_data), vis)
    title = f"{unit_id}: [private]" if pv.body_is_redacted(vis) else f"[sw] inflight:{unit_id}"
    body_lines = [
        f"<!-- sw-unit-id: {unit_id} -->",
        f"<!-- sw-tracking-issue: inflight -->",
        "```json",
        json.dumps({"unitId": unit_id, "tuple": redacted, "visibility": vis}, indent=2),
        "```",
    ]
    body = "\n".join(body_lines) + "\n"
    confidential = pv.body_is_redacted(vis)

    return {
        "verdict": "ok",
        "unitId": unit_id,
        "visibility": vis,
        "title": title,
        "body": body,
        "tuple": redacted,
        "confidential": confidential,
        "remoteProbe": pv.probe_remote_visibility(worktree),
    }


def _cmd_prepare(args: argparse.Namespace) -> int:
    payload = json.loads(args.payload_json)
    result = prepare_tracking_issue(
        Path(args.root),
        str(payload["unitId"]),
        dict(payload.get("tuple") or {}),
        visibility=payload.get("visibility"),
        unit=payload.get("unit"),
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "ok" else 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRD 046 inFlight tracking issue helper")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--payload-json", required=True)
    p.set_defaults(func=_cmd_prepare)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
