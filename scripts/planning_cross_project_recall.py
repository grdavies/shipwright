#!/usr/bin/env python3
"""Cross-project planning recall with redacted pointer dereference (PRD 046 R90 / PRD 043 R27)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_paths as pp  # noqa: E402
import planning_visibility as pv  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402
from planning_store import PROJECT_KEY_PATTERN  # noqa: E402

MEMORY_POINTER_MARKER = "sw-memory-pointer"


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def redact_text(text: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "memory-redact.py")],
        input=text,
        capture_output=True,
        text=True,
    )
    return proc.stdout if proc.returncode == 0 else text


def authorize_cross_project(caller_key: str, source_key: str, authorized: list[str] | None) -> bool:
    if caller_key == source_key:
        return True
    if authorized and source_key in authorized:
        return True
    return False


def rank_pointers(pointers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        pointers,
        key=lambda p: (
            str(p.get("projectKey", "")),
            str(p.get("unitId", "")),
            str(p.get("memoryId", "")),
        ),
    )


def recall_cross_project(
    root: Path,
    *,
    source_project_key: str,
    caller_project_key: str,
    query: str,
    pointers: list[dict[str, Any]] | None = None,
    authorized_projects: list[str] | None = None,
) -> dict[str, Any]:
    """Recall rationale via project-scoped memory pointers; redact on dereference (R90)."""
    worktree = pp.git_root(root)
    if not PROJECT_KEY_PATTERN.fullmatch(caller_project_key):
        fail("invalid-caller-project-key")
    if not PROJECT_KEY_PATTERN.fullmatch(source_project_key):
        fail("invalid-source-project-key")
    if not authorize_cross_project(caller_project_key, source_project_key, authorized_projects):
        return {"verdict": "denied", "error": "cross-project-unauthorized", "sourceProjectKey": source_project_key}

    hits: list[dict[str, Any]] = []
    for ptr in rank_pointers(pointers or []):
        if str(ptr.get("projectKey", "")) != source_project_key:
            continue
        vis = pv.normalize_visibility(str(ptr.get("visibility", "private")))
        excerpt = str(ptr.get("excerpt", ""))
        if pv.body_is_redacted(vis):
            hits.append({
                "projectKey": source_project_key,
                "unitId": ptr.get("unitId"),
                "memoryId": ptr.get("memoryId"),
                "visibility": vis,
                "excerpt": f"{ptr.get('unitId', 'unit')}: [private]",
                "redacted": True,
            })
        else:
            hits.append({
                "projectKey": source_project_key,
                "unitId": ptr.get("unitId"),
                "memoryId": ptr.get("memoryId"),
                "visibility": vis,
                "excerpt": redact_text(excerpt),
                "redacted": False,
            })
    if query:
        q = query.lower()
        hits = [h for h in hits if q in str(h.get("excerpt", "")).lower() or q in str(h.get("unitId", "")).lower()]
    return {
        "verdict": "pass",
        "sourceProjectKey": source_project_key,
        "callerProjectKey": caller_project_key,
        "query": query,
        "hits": hits,
        "duplicatesDeliverable": False,
    }


def _cmd_recall(args: argparse.Namespace) -> int:
    payload = json.loads(args.payload_json)
    result = recall_cross_project(
        Path(args.root),
        source_project_key=str(payload["sourceProjectKey"]),
        caller_project_key=str(payload["callerProjectKey"]),
        query=str(payload.get("query", "")),
        pointers=list(payload.get("pointers") or []),
        authorized_projects=list(payload.get("authorizedProjects") or []),
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "pass" else 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PRD 046 cross-project recall")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("recall")
    p.add_argument("--payload-json", required=True)
    p.set_defaults(func=_cmd_recall)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
