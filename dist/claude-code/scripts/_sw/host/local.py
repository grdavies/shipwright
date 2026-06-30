"""Local / no-remote host adapter (PRD 026 Phase 3 / 042)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from _sw.host import _common as common  # noqa: E402
import host_local_lib  # noqa: E402

PROVIDER = "none"


def dispatch(root: Path, verb: str, args: list[str]) -> tuple[dict[str, Any], int]:
    handlers = {
        "repo-meta": _repo_meta,
        "resolve-pr-for-branch": _resolve_pr,
        "pr-view": _pr_view,
        "pr-list": _pr_list,
        "pr-head": _pr_head,
        "checks": _checks,
        "review-threads": _review_threads,
        "pr-create": _capability_missing,
        "merge": _capability_missing,
        "pr-close": _capability_missing,
    }
    handler = handlers.get(verb)
    if handler is None:
        return common.degraded_json(verb, PROVIDER, "capability-missing"), 0
    return handler(root, args)


def _capability_missing(root: Path, args: list[str]) -> tuple[dict[str, Any], int]:
    verb = common.kv_get(args, "_verb", "capability-missing")
    return common.degraded_json(verb, PROVIDER, "capability-missing"), 0


def _repo_meta(root: Path, args: list[str]) -> tuple[dict[str, Any], int]:
    repo = host_local_lib.repo_label(root)
    data = {
        "nameWithOwner": f"local/{repo}",
        "defaultBranch": host_local_lib.default_base(root),
        "localEvidence": True,
    }
    return common.emit_verb_ok("repo-meta", PROVIDER, data), 0


def _resolve_pr(root: Path, args: list[str]) -> tuple[dict[str, Any], int]:
    view = host_local_lib.pr_view_data(root, "0")
    data = [
        {
            "number": view["number"],
            "headRefName": view["headRefName"],
            "headRefOid": view["headRefOid"],
            "localEvidence": True,
        }
    ]
    return common.emit_verb_ok("resolve-pr-for-branch", PROVIDER, data), 0


def _pr_view(root: Path, args: list[str]) -> tuple[dict[str, Any], int]:
    number = common.kv_get(args, "number", "0")
    return common.emit_verb_ok("pr-view", PROVIDER, host_local_lib.pr_view_data(root, number)), 0


def _pr_list(root: Path, args: list[str]) -> tuple[dict[str, Any], int]:
    head = common.kv_get(args, "head", "")
    branch = host_local_lib.git_branch(root)
    if head and branch != head:
        return common.emit_verb_ok("pr-list", PROVIDER, []), 0
    return common.emit_verb_ok("pr-list", PROVIDER, [host_local_lib.pr_view_data(root, "0")]), 0


def _pr_head(root: Path, args: list[str]) -> tuple[dict[str, Any], int]:
    number = common.kv_get(args, "number", "0")
    head = host_local_lib.git_head(root)
    num = int(number) if str(number).isdigit() else 0
    return common.emit_verb_ok(
        "pr-head",
        PROVIDER,
        {"headRefOid": head, "number": num, "localEvidence": True},
    ), 0


def _checks(root: Path, args: list[str]) -> tuple[dict[str, Any], int]:
    fix = common.local_fixture_name()
    checks_file = root / "scripts" / "test" / "fixtures" / "host" / f"checks-{fix}.json"
    if fix and checks_file.is_file():
        payload = host_local_lib.checks_from_file(checks_file)
    else:
        payload = host_local_lib.checks_default()
    return payload, 0


def _review_threads(root: Path, args: list[str]) -> tuple[dict[str, Any], int]:
    return {
        "verdict": "ok",
        "verb": "review-threads",
        "provider": PROVIDER,
        "data": {"unresolved": 0, "actionable": 0, "localEvidence": True},
    }, 0
