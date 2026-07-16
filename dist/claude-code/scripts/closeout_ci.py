#!/usr/bin/env python3
"""CI merge-event close-out driver: observe-only gate, N-per-wave, surfacing, SLO (PRD 070)."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from deliver_closeout import resolve_delivery_for_merge, resolve_delivery_for_pr, run_closeout
from host_lib import load_workflow_config, parse_owner_repo, remote_name, git_remote_url

_MERGE_PR_RE = re.compile(r"(?:Merge pull request #|#)(\d+)\b")
_SQUASH_PR_RE = re.compile(r"\(#(\d+)\)\s*$")
DEFAULT_SLO_SECONDS = 300
DEFAULT_SLO_OWNER = "platform-ops"
DEFAULT_SLO_SURFACE = "job-annotation"


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


def _pr_numbers_from_message(message: str, found: set[int]) -> None:
    for pattern in (_MERGE_PR_RE, _SQUASH_PR_RE):
        for match in pattern.finditer(message):
            found.add(int(match.group(1)))


def extract_pr_numbers(event: dict[str, Any]) -> list[int]:
    found: set[int] = set()
    head = event.get("head_commit") or {}
    _pr_numbers_from_message(str(head.get("message") or ""), found)
    for commit in event.get("commits") or []:
        if not isinstance(commit, dict):
            continue
        _pr_numbers_from_message(str(commit.get("message") or ""), found)
    return sorted(found)


def extract_pr_number(event: dict[str, Any]) -> int | None:
    numbers = extract_pr_numbers(event)
    return numbers[0] if numbers else None


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


def closeout_slo_config(cfg: dict[str, Any]) -> dict[str, Any]:
    deliver = cfg.get("deliver") or {}
    closeout = deliver.get("closeout") or {}
    slo = closeout.get("latencySlo") or {}
    return {
        "maxSeconds": int(slo.get("maxSeconds") or DEFAULT_SLO_SECONDS),
        "owner": str(slo.get("owner") or DEFAULT_SLO_OWNER),
        "failureSurface": str(slo.get("failureSurface") or DEFAULT_SLO_SURFACE),
    }


def build_slo_report(*, started_at: float, finished_at: float, slo: dict[str, Any], verdict: str) -> dict[str, Any]:
    elapsed = max(0.0, finished_at - started_at)
    max_seconds = int(slo.get("maxSeconds") or DEFAULT_SLO_SECONDS)
    within = elapsed <= max_seconds
    report: dict[str, Any] = {
        "elapsedSeconds": round(elapsed, 3),
        "maxSeconds": max_seconds,
        "withinSlo": within,
        "owner": slo.get("owner") or DEFAULT_SLO_OWNER,
        "failureSurface": slo.get("failureSurface") or DEFAULT_SLO_SURFACE,
    }
    if not within:
        report["verdict"] = "slo-breach"
        report["error"] = "closeout-latency-slo-breach"
    elif verdict in {"ready", "observe", "skipped", "dry-run"}:
        report["verdict"] = "pass"
    else:
        report["verdict"] = "recorded"
    return report


def _gha_escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def surface_operator_failure(
    root: Path,
    cfg: dict[str, Any],
    *,
    error: str,
    resume_command: str | None,
    pr_number: int | None = None,
    prd_unit_id: str | None = None,
    slo: dict[str, Any] | None = None,
    surface_hook: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if surface_hook is not None:
        return surface_hook(
            root=root,
            cfg=cfg,
            error=error,
            resume_command=resume_command,
            pr_number=pr_number,
            prd_unit_id=prd_unit_id,
            slo=slo,
        )

    owner = (slo or {}).get("owner") or DEFAULT_SLO_OWNER
    surface = (slo or {}).get("failureSurface") or DEFAULT_SLO_SURFACE
    lines = [f"Close-out blocked: {error}"]
    if resume_command:
        lines.append(f"Resume: {resume_command}")
    lines.append(f"Owner: {owner}")
    message = "\n".join(lines)
    channels: list[str] = []

    if surface in {"job-annotation", "all"} or not os.environ.get("GITHUB_ACTIONS"):
        print(f"::error title=deliver-closeout::{_gha_escape(message)}", file=sys.stderr)
        channels.append("job-annotation")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("### deliver-closeout failure\n")
            handle.write(message)
            handle.write("\n")
        channels.append("step-summary")

    if pr_number is not None and surface in {"pr-comment", "all"}:
        remote = remote_name(cfg)
        owner_repo = parse_owner_repo(git_remote_url(root, remote))
        token_env = str((cfg.get("host") or {}).get("tokenEnv") or "GITHUB_TOKEN")
        if owner_repo and os.environ.get(token_env, "").strip():
            repo_owner, repo_name = owner_repo
            body = message.replace("'", "")
            proc = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{repo_owner}/{repo_name}/issues/{int(pr_number)}/comments",
                    "-f",
                    f"body={body}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode == 0:
                channels.append("pr-comment")

    if prd_unit_id and surface in {"prd-unit-comment", "all"}:
        try:
            from planning_store import IssueStoreBackend, get_backend

            backend = get_backend(root, cfg, override="issue-store")
            if isinstance(backend, IssueStoreBackend):
                record = backend._lookup_record(prd_unit_id, "")
                if record is not None:
                    backend._client.issue_comment(record.id, message, markers=["sw-closeout-failure"])
                    channels.append("prd-unit-comment")
        except Exception:
            pass

    return {
        "verdict": "surfaced",
        "channels": channels,
        "owner": owner,
        "failureSurface": surface,
        "resumeCommand": resume_command,
    }


def resolve_wave_deliveries(root: Path, *, event: dict[str, Any], merge_sha: str) -> list[dict[str, Any]]:
    deliveries: list[dict[str, Any]] = []
    seen_units: set[str] = set()
    pr_numbers = extract_pr_numbers(event)
    if pr_numbers:
        for pr_number in pr_numbers:
            resolution = resolve_delivery_for_pr(root, pr_number)
            if resolution.get("verdict") != "pass":
                continue
            prd_unit_id = str(resolution.get("prdUnitId") or "")
            if not prd_unit_id or prd_unit_id in seen_units:
                continue
            seen_units.add(prd_unit_id)
            deliveries.append({**resolution, "prNumber": pr_number})
        return deliveries

    resolution = resolve_delivery_for_merge(root, merge_sha=merge_sha)
    if resolution.get("verdict") == "pass":
        pr_number = extract_pr_number(event)
        deliveries.append({**resolution, "prNumber": pr_number})
    return deliveries


def build_observe_report(
    *,
    gate: str,
    merge_sha: str,
    deliveries: list[dict[str, Any]],
    closeout_previews: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "verdict": "observe",
        "gate": gate,
        "mode": "observe",
        "mutations": False,
        "mergeSha": merge_sha,
        "deliveryCount": len(deliveries),
        "deliveries": deliveries,
    }
    if closeout_previews is not None:
        report["closeoutPreviews"] = closeout_previews
    return report


def _aggregate_closeout_verdict(results: list[dict[str, Any]]) -> str:
    if not results:
        return "not-ready"
    verdicts = {str(item.get("verdict") or "not-ready") for item in results}
    if verdicts <= {"ready", "dry-run"}:
        return "ready"
    if "not-ready" in verdicts:
        return "not-ready"
    return next(iter(verdicts - {"ready", "dry-run"}), "not-ready")


def run_delivery_closeouts(
    root: Path,
    *,
    deliveries: list[dict[str, Any]],
    merge_sha: str,
    dry_run: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for delivery in deliveries:
        prd_unit_id = str(delivery.get("prdUnitId") or "")
        pr_number = delivery.get("prNumber")
        closeout = run_closeout(
            root,
            prd_unit_id=prd_unit_id,
            merge_sha=merge_sha,
            pr_number=int(pr_number) if pr_number is not None else None,
            dry_run=dry_run,
        )
        results.append(
            {
                "prdUnitId": prd_unit_id,
                "prNumber": pr_number,
                "resolution": delivery,
                "closeout": closeout,
                "verdict": str(closeout.get("verdict") or "not-ready"),
                "resumeCommand": closeout.get("resumeCommand"),
            }
        )
    return results


def run_ci_closeout(
    root: Path,
    *,
    mode: str | None = None,
    surface_hook: Callable[..., dict[str, Any]] | None = None,
    monotonic: Callable[[], float] | None = None,
) -> dict[str, Any]:
    clock = monotonic or time.monotonic
    started_at = clock()
    cfg = load_workflow_config(root)
    gate = resolve_ci_gate(mode_arg=mode, cfg=cfg)
    slo = closeout_slo_config(cfg)
    event = load_github_event()
    default_branch = _default_branch(cfg)
    if event and not _ref_is_default(event, default_branch):
        finished_at = clock()
        return {
            "verdict": "skipped",
            "reason": "non-default-branch",
            "gate": gate,
            "ref": event.get("ref"),
            "defaultBranch": default_branch,
            "slo": build_slo_report(started_at=started_at, finished_at=finished_at, slo=slo, verdict="skipped"),
        }

    merge_sha = extract_merge_sha(event)
    if not merge_sha:
        finished_at = clock()
        payload = {"verdict": "fail", "error": "merge-sha-missing", "gate": gate}
        payload["slo"] = build_slo_report(started_at=started_at, finished_at=finished_at, slo=slo, verdict="fail")
        payload["surface"] = surface_operator_failure(
            root,
            cfg,
            error="merge-sha-missing",
            resume_command="python3 scripts/closeout_ci.py run --mode mutate",
            slo=slo,
            surface_hook=surface_hook,
        )
        return payload

    deliveries = resolve_wave_deliveries(root, event=event, merge_sha=merge_sha)
    if not deliveries:
        finished_at = clock()
        resolution = resolve_delivery_for_merge(root, merge_sha=merge_sha)
        pr_numbers = extract_pr_numbers(event)
        if pr_numbers:
            resolution = resolve_delivery_for_pr(root, pr_numbers[0])
        return {
            "verdict": "skipped",
            "reason": "no-delivery-mapping",
            "gate": gate,
            "mode": gate,
            "mergeSha": merge_sha,
            "prNumbers": pr_numbers,
            "resolution": resolution,
            "slo": build_slo_report(started_at=started_at, finished_at=finished_at, slo=slo, verdict="skipped"),
        }

    if gate == "observe":
        os.environ.setdefault("SW_CLOSEOUT_TRIGGER", "ci-observe")
        previews = run_delivery_closeouts(root, deliveries=deliveries, merge_sha=merge_sha, dry_run=True)
        finished_at = clock()
        report = build_observe_report(
            gate=gate,
            merge_sha=merge_sha,
            deliveries=deliveries,
            closeout_previews=previews,
        )
        report["slo"] = build_slo_report(started_at=started_at, finished_at=finished_at, slo=slo, verdict="observe")
        return report

    token_env = resolve_planning_token_env(cfg)
    if not os.environ.get(token_env, "").strip():
        resume_command = f"export {token_env}=<token> && python3 scripts/closeout_ci.py run --mode mutate"
        finished_at = clock()
        payload = {
            "verdict": "fail",
            "error": "planning-token-missing",
            "tokenEnv": token_env,
            "gate": gate,
            "mergeSha": merge_sha,
            "deliveryCount": len(deliveries),
            "deliveries": deliveries,
            "resumeCommand": resume_command,
        }
        payload["slo"] = build_slo_report(started_at=started_at, finished_at=finished_at, slo=slo, verdict="fail")
        payload["surface"] = surface_operator_failure(
            root,
            cfg,
            error="planning-token-missing",
            resume_command=resume_command,
            pr_number=deliveries[0].get("prNumber"),
            prd_unit_id=str(deliveries[0].get("prdUnitId") or ""),
            slo=slo,
            surface_hook=surface_hook,
        )
        return payload

    os.environ.setdefault("SW_CLOSEOUT_TRIGGER", "ci-mutate")
    results = run_delivery_closeouts(root, deliveries=deliveries, merge_sha=merge_sha, dry_run=False)
    finished_at = clock()
    verdict = _aggregate_closeout_verdict(results)
    resume_command = next((item.get("resumeCommand") for item in results if item.get("resumeCommand")), None)
    payload: dict[str, Any] = {
        "verdict": verdict,
        "gate": gate,
        "mode": "mutate",
        "mutations": True,
        "mergeSha": merge_sha,
        "deliveryCount": len(deliveries),
        "deliveries": deliveries,
        "closeoutResults": results,
    }
    slo_report = build_slo_report(started_at=started_at, finished_at=finished_at, slo=slo, verdict=verdict)
    payload["slo"] = slo_report
    if verdict not in {"ready", "dry-run"}:
        payload["resumeCommand"] = resume_command
        payload["surface"] = surface_operator_failure(
            root,
            cfg,
            error=str(verdict),
            resume_command=str(resume_command) if resume_command else None,
            pr_number=next((item.get("prNumber") for item in results if item.get("resumeCommand")), None),
            prd_unit_id=next((item.get("prdUnitId") for item in results if item.get("resumeCommand")), None),
            slo=slo,
            surface_hook=surface_hook,
        )
    elif not slo_report.get("withinSlo", True):
        payload["verdict"] = "fail"
        payload["error"] = "closeout-latency-slo-breach"
        payload["resumeCommand"] = (
            f"Investigate deliver-closeout latency (owner: {slo.get('owner')}); "
            "then rerun python3 scripts/closeout_ci.py run --mode mutate"
        )
        payload["surface"] = surface_operator_failure(
            root,
            cfg,
            error="closeout-latency-slo-breach",
            resume_command=payload["resumeCommand"],
            pr_number=deliveries[0].get("prNumber"),
            prd_unit_id=str(deliveries[0].get("prdUnitId") or ""),
            slo=slo,
            surface_hook=surface_hook,
        )
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
