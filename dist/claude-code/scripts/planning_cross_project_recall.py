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
import planning_cross_project_trust as trust  # noqa: E402
import planning_visibility as pv  # noqa: E402
from planning_store import PROJECT_KEY_PATTERN  # noqa: E402

MEMORY_POINTER_MARKER = "sw-memory-pointer"


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def redact_text(text: str) -> str | None:
    """Redact excerpt text; refuse emission (return None) on any chokepoint failure."""
    destination = pv.resolve_emission_destination("issue-derived-ingest")
    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "memory-redact.py"), "--destination", destination],
            input=text,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    if not proc.stdout and text:
        return None
    return proc.stdout


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
    caller_project_key: str | None = None,
    query: str,
    pointers: list[dict[str, Any]] | None = None,
    authorized_projects: list[str] | None = None,
    allow_payload_trust: bool | None = None,
) -> dict[str, Any]:
    """Recall rationale via project-scoped memory pointers; redact on dereference (R90)."""
    worktree = pp.git_root(root)
    trust_result = trust.resolve_trusted_sources(
        worktree,
        payload_authorized_projects=authorized_projects,
        allow_payload_trust=allow_payload_trust,
    )
    if trust_result.get("verdict") != "pass":
        return trust_result

    resolved_caller = str(trust_result["callerProjectKey"])
    if caller_project_key is not None and caller_project_key != resolved_caller:
        return {
            "verdict": "denied",
            "error": "caller-project-key-mismatch",
            "callerProjectKey": resolved_caller,
        }

    if not PROJECT_KEY_PATTERN.fullmatch(source_project_key):
        fail("invalid-source-project-key")

    effective_trusted = set(trust_result.get("effectiveTrustedSources") or [])
    if not trust.authorize_cross_project(resolved_caller, source_project_key, effective_trusted):
        return {
            "verdict": "denied",
            "error": "cross-project-unauthorized",
            "sourceProjectKey": source_project_key,
            "callerProjectKey": resolved_caller,
        }

    cross_project = resolved_caller != source_project_key
    hits: list[dict[str, Any]] = []
    for ptr in rank_pointers(pointers or []):
        if str(ptr.get("projectKey", "")) != source_project_key:
            continue
        if trust.cross_project_dereference_blocked(ptr, cross_project=cross_project):
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
            redacted_excerpt = redact_text(excerpt)
            if redacted_excerpt is None:
                continue
            hits.append({
                "projectKey": source_project_key,
                "unitId": ptr.get("unitId"),
                "memoryId": ptr.get("memoryId"),
                "visibility": vis,
                "excerpt": redacted_excerpt,
                "redacted": False,
            })
    if query:
        q = query.lower()
        hits = [h for h in hits if q in str(h.get("excerpt", "")).lower() or q in str(h.get("unitId", "")).lower()]
    return {
        "verdict": "pass",
        "sourceProjectKey": source_project_key,
        "callerProjectKey": resolved_caller,
        "query": query,
        "hits": hits,
        "duplicatesDeliverable": False,
        "payloadTrustApplied": bool(trust_result.get("payloadTrustApplied")),
    }


def _cmd_recall(args: argparse.Namespace) -> int:
    payload = json.loads(args.payload_json)
    result = recall_cross_project(
        Path(args.root),
        source_project_key=str(payload["sourceProjectKey"]),
        caller_project_key=payload.get("callerProjectKey"),
        query=str(payload.get("query", "")),
        pointers=list(payload.get("pointers") or []),
        authorized_projects=list(payload.get("authorizedProjects") or []) or None,
        allow_payload_trust=bool(payload.get(trust.PAYLOAD_TRUST_TEST_FLAG))
        if trust.PAYLOAD_TRUST_TEST_FLAG in payload
        else None,
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
