#!/usr/bin/env python3
"""CI merge-event close-out driver: observe-only gate and mutate fallback (PRD 070)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from deliver_closeout import resolve_delivery_for_merge, resolve_delivery_for_pr, run_closeout
from host_lib import load_workflow_config

_MERGE_PR_RE = re.compile(r"(?:Merge pull request #|#)(\d+)\b")
_SQUASH_PR_RE = re.compile(r"\(#(\d+)\)\s*$")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def load_github_event() -> dict[str, Any]:
    path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _default_branch(cfg: dict[str, Any]) -> str:
    branch = str(cfg.get("defaultBaseBranch") or "main").strip()
    return branch or "main"


def _ref_is_default(event: dict[str, Any], default_branch: str) -> bool:
    ref = str(event.get("ref") or os.environ.get("GITHUB_REF") or "").strip()
    if not ref:
        return True
    return ref in {default_branch, f"refs/heads/{default_branch}"}


def extract_merge_sha(event: dict[str, Any]) -> str:
    after = str(event.get("after") or "").strip().lower()
    if after and after != "0000000000000000000000000000000000000000":
        return after
    head = event.get("head_commit") or {}
    commit_id = str(head.get("id") or "").strip().lower()
    if commit_id:
        return commit_id
    env_sha = str(os.environ.get("GITHUB_SHA") or "").strip().lower()
    return env_sha


def extract_pr_number(event: dict[str, Any]) -> int | None:
    head = event.get("head_commit") or {}
    message = str(head.get("message") or "")
    for pattern in (_MERGE_PR_RE, _SQUASH_PR_RE):
        match = pattern.search(message)
        if match:
            return int(match.group(1))
    return None


def resolve_ci_gate(*, mode_arg: str | None = None, cfg: dict[str, Any] | None = None) -> str:
    if mode_arg in {"observe", "mutate"}:
        return mode_arg
    env_gate = str(os.environ.get("SW_CLOSEOUT_CI_GATE") or "").strip().lower()
    if env_gate in {"observe", "mutate"}:
        return env_gate
    deliver = (cfg or {}).get("deliver") or {}
    closeout = deliver.get("closeout") or {}
    cfg_gate = str(closeout.get("ciGate") or "").strip().lower()
    if cfg_gate in {"observe", "mutate"}:
        return cfg_gate
    return "observe"


def resolve_planning_token_env(cfg: dict[str, Any]) -> str:
    planning = cfg.get("planning") or {}
    store = planning.get("store") or {}
    issues = store.get("issues") or {}
    token_env = str(issues.get("tokenEnv") or "SW_PLANNING_ISSUES_TOKEN").strip()
    return token_env or "SW_PLANNING_ISSUES_TOKEN"


def build_observe_report(
    *,
    gate: str,
    merge_sha: str,
    pr_number: int | None,
    resolution: dict[str, Any],
    closeout_preview: dict[str, Any] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "verdict": "observe",
        "gate": gate,
        "mode": "observe",
        "mutations": False,
        "mergeSha": merge_sha,
        "prNumber": pr_number,
        "resolution": resolution,
    }
    if closeout_preview is not None:
        report["closeoutPreview"] = closeout_preview
    return report


def run_ci_closeout(root: Path, *, mode: str | None = None) -> dict[str, Any]:
    cfg = load_workflow_config(root)
    gate = resolve_ci_gate(mode_arg=mode, cfg=cfg)
    event = load_github_event()
    default_branch = _default_branch(cfg)
    if event and not _ref_is_default(event, default_branch):
        return {
            "verdict": "skipped",
            "reason": "non-default-branch",
            "gate": gate,
            "ref": event.get("ref"),
            "defaultBranch": default_branch,
        }

    merge_sha = extract_merge_sha(event)
    if not merge_sha:
        return {"verdict": "fail", "error": "merge-sha-missing", "gate": gate}

    pr_number = extract_pr_number(event)
    if pr_number is not None:
        resolution = resolve_delivery_for_pr(root, pr_number)
    else:
        resolution = resolve_delivery_for_merge(root, merge_sha=merge_sha)

    if resolution.get("verdict") != "pass":
        return {
            "verdict": "skipped",
            "reason": "no-delivery-mapping",
            "gate": gate,
            "mode": gate,
            "mergeSha": merge_sha,
            "prNumber": pr_number,
            "resolution": resolution,
        }

    prd_unit_id = str(resolution.get("prdUnitId") or "")
    if gate == "observe":
        os.environ.setdefault("SW_CLOSEOUT_TRIGGER", "ci-observe")
        preview = run_closeout(
            root,
            prd_unit_id=prd_unit_id,
            merge_sha=merge_sha,
            pr_number=pr_number,
            dry_run=True,
        )
        return build_observe_report(
            gate=gate,
            merge_sha=merge_sha,
            pr_number=pr_number,
            resolution=resolution,
            closeout_preview=preview,
        )

    token_env = resolve_planning_token_env(cfg)
    if not os.environ.get(token_env, "").strip():
        return {
            "verdict": "fail",
            "error": "planning-token-missing",
            "tokenEnv": token_env,
            "gate": gate,
            "mergeSha": merge_sha,
            "prNumber": pr_number,
            "resumeCommand": (
                f"export {token_env}=<token> && python3 scripts/closeout_ci.py run --mode mutate"
            ),
        }

    os.environ.setdefault("SW_CLOSEOUT_TRIGGER", "ci-mutate")
    result = run_closeout(
        root,
        prd_unit_id=prd_unit_id,
        merge_sha=merge_sha,
        pr_number=pr_number,
        dry_run=False,
    )
    verdict = str(result.get("verdict") or "not-ready")
    payload: dict[str, Any] = {
        "verdict": verdict,
        "gate": gate,
        "mode": "mutate",
        "mutations": True,
        "mergeSha": merge_sha,
        "prNumber": pr_number,
        "resolution": resolution,
        "closeout": result,
    }
    if verdict not in {"ready", "dry-run"}:
        payload["resumeCommand"] = result.get("resumeCommand")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="CI merge-event close-out driver (PRD 070)")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("command", nargs="?", default="run")
    parser.add_argument("rest", nargs=argparse.REMAINDER)
    ns = parser.parse_args()
    root = Path(ns.root).resolve()
    rest = list(ns.rest)
    if ns.command not in {"run", "closeout"}:
        fail(f"unknown command: {ns.command}")

    mode = None
    if "--mode" in rest:
        idx = rest.index("--mode")
        if idx + 1 < len(rest):
            mode = rest[idx + 1]

    result = run_ci_closeout(root, mode=mode)
    verdict = str(result.get("verdict") or "fail")
    if verdict in {"observe", "skipped"}:
        emit(result, 0)
    if verdict in {"ready", "dry-run"}:
        emit(result, 0)
    emit(result, 20 if verdict == "not-ready" else 2)


if __name__ == "__main__":
    main()
