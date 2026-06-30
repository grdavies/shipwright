"""CI readiness gate computation — shared library for check-gate (PRD 042 phase 3)."""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

from _sw import jsonio, logging_setup, proc

SCRIPT_DIR = Path(__file__).resolve().parent

PENDING_STATES = frozenset(
    {"PENDING", "QUEUED", "IN_PROGRESS", "REQUESTED", "WAITING", "EXPECTED"}
)

VERDICT_EXIT = {"green": 0, "yellow": 10, "red": 20, "blocked": 30}


def resolve_plugin_root(script_dir: Path | None = None) -> Path:
    """Resolve plugin content root (mirrors sw-resolve-plugin-root.sh)."""
    script_dir = script_dir or SCRIPT_DIR
    parent = script_dir.parent
    if (parent / "providers").is_dir() or (parent / "commands").is_dir():
        return parent
    if (parent / "core" / "providers").is_dir():
        return parent / "core"
    return parent


def git_root(start: Path | None = None) -> Path:
    start = start or Path.cwd()
    completed = proc.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=str(start),
    )
    if completed.returncode == 0 and completed.stdout.strip():
        return Path(completed.stdout.strip())
    return start


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return {}


def cfg_bool(cfg: dict[str, Any], key: str, default: bool) -> bool:
    checks = cfg.get("checks")
    if not isinstance(checks, dict):
        return default
    value = checks
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("true", "1", "yes")
    return default


def cfg_value(cfg: dict[str, Any], *path: str, default: Any = None) -> Any:
    value: Any = cfg
    for part in path:
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def host_verb(root: Path, *args: str) -> dict[str, Any]:
    host_sh = SCRIPT_DIR / "host.sh"
    completed = proc.run(["bash", str(host_sh), "--root", str(root), *args], cwd=str(root))
    try:
        return json.loads(completed.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return {"verdict": "fail", "reason": completed.stderr.strip() or "invalid host output"}


def host_data(root: Path, *args: str) -> Any:
    payload = host_verb(root, *args)
    if payload.get("verdict") == "ok":
        return payload.get("data")
    return None


def load_pr_test_plan(root: Path, cfg: dict[str, Any]) -> tuple[Any, list[str], list[str]]:
    manifest_path = root / "core/sw-reference/pr-test-plan.manifest.json"
    manifest_cfg = cfg_value(cfg, "ci", "prTestPlanManifest") or cfg_value(
        cfg, "verify", "prTestPlanManifest"
    )
    if manifest_cfg:
        candidate = root / str(manifest_cfg)
        if candidate.is_file():
            manifest_path = candidate
    pr_test_plan: Any = None
    advisory_jobs: list[str] = []
    required_jobs: list[str] = []
    if manifest_path.is_file():
        try:
            pr_test_plan = json.loads(manifest_path.read_text(encoding="utf-8"))
            fixtures = pr_test_plan.get("fixtures") if isinstance(pr_test_plan, dict) else []
            if isinstance(fixtures, list):
                for item in fixtures:
                    if not isinstance(item, dict):
                        continue
                    name = item.get("ciJobName")
                    if not name:
                        continue
                    if item.get("classification") == "advisory":
                        advisory_jobs.append(str(name))
                    elif item.get("classification") == "required":
                        required_jobs.append(str(name))
        except json.JSONDecodeError:
            pr_test_plan = None
    return pr_test_plan, advisory_jobs, required_jobs


def classify_checks(
    checks: list[dict[str, Any]],
    *,
    neutral_pass: bool,
    allowlist: list[str],
) -> list[dict[str, Any]]:
    classified: list[dict[str, Any]] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        state = str(item.get("state", ""))
        name = str(item.get("name", ""))
        if state in ("SUCCESS", "SKIPPED"):
            klass = "pass"
        elif state == "NEUTRAL":
            klass = "pass" if neutral_pass or name in allowlist else "block"
        elif state in PENDING_STATES:
            klass = "pending"
        else:
            klass = "fail"
        classified.append({"name": name, "state": state, "class": klass})
    return classified


def split_failing(
    failing: list[str],
    advisory_jobs: list[str],
) -> tuple[list[str], list[str]]:
    advisory_set = set(advisory_jobs)
    required = [name for name in failing if name not in advisory_set]
    advisory = [name for name in failing if name in advisory_set]
    return required, advisory


def compute_verdict(
    *,
    required_failing: list[str],
    blocking: list[str],
    pending: list[str],
    cr_landed: bool,
    check_count: int,
    actionable: int,
) -> str:
    if required_failing:
        return "red"
    if blocking:
        return "blocked"
    if pending:
        return "yellow"
    if not cr_landed:
        return "yellow"
    if check_count == 0:
        return "blocked"
    if actionable > 0:
        return "blocked"
    return "green"


def build_reason(
    verdict: str,
    *,
    pending: list[str],
    required_failing: list[str],
    advisory_failing: list[str],
    actionable: int,
    cr_landed: bool,
    cr_state: str,
    head_sha: str,
    review_provider: str,
) -> str:
    if verdict == "yellow":
        if not cr_landed:
            short = head_sha[:8] if head_sha else ""
            return (
                f"review not yet landed for head {short} "
                f"(state={cr_state} provider={review_provider})"
            )
        return f"checks pending: {','.join(pending)}"
    if verdict == "red":
        return f"failing checks: {','.join(required_failing)}"
    if verdict == "blocked":
        if actionable > 0:
            return f"{actionable} unresolved actionable review thread(s)"
        return "blocking/neutral or empty check set"
    if advisory_failing:
        return (
            f"required checks pass; advisory failing (non-blocking): "
            f"{','.join(advisory_failing)}"
        )
    if cr_state == "off":
        return "all checks pass; review gating off; 0 actionable threads"
    if cr_state == "unconfigured":
        return (
            "all checks pass; review off by default — never configured; "
            "0 actionable threads"
        )
    if cr_state == "skipped":
        short = head_sha[:8] if head_sha else ""
        return f"all checks pass; review skipped head {short}; 0 actionable threads"
    short = head_sha[:8] if head_sha else ""
    return f"all checks pass; review landed for head {short}; 0 actionable threads"


def build_gate_payload(
    *,
    verdict: str,
    reason: str,
    head_sha: str,
    review_provider: str,
    cr_reviewed_head: str,
    cr_status: str,
    cr_state: str,
    cr_landed: bool,
    cr_marker: bool,
    cr_skipped: bool,
    mins_since: int,
    unresolved: int,
    actionable: int,
    failing: list[str],
    required_failing: list[str],
    advisory_failing: list[str],
    pr_test_plan: Any,
    required_jobs: list[str],
    advisory_jobs: list[str],
    pending: list[str],
    blocking: list[str],
    check_count: int,
    deprecations: list[str],
    pr: int | None = None,
    branch: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "verdict": verdict,
        "reason": reason,
        "head": head_sha,
        "reviewProvider": review_provider,
        "deprecations": deprecations,
        "coderabbitReviewedHead": cr_reviewed_head or None,
        "coderabbitReviewedCurrentHead": bool(
            cr_reviewed_head and cr_reviewed_head == head_sha
        ),
        "coderabbitStatus": cr_status,
        "coderabbitState": cr_state,
        "coderabbitLanded": cr_landed,
        "coderabbitSkipped": cr_skipped,
        "coderabbitInProgressMarker": cr_marker,
        "minutesSinceHeadPush": mins_since,
        "unresolvedThreads": unresolved,
        "unresolvedActionable": actionable,
        "failingChecks": failing,
        "requiredFailingChecks": required_failing,
        "advisoryFailingChecks": advisory_failing,
        "pendingChecks": pending,
        "blockingNeutral": blocking,
        "checkCount": check_count,
    }
    if pr is not None:
        payload["pr"] = pr
    if branch is not None:
        payload["branch"] = branch
    if source is not None:
        payload["source"] = source
    if pr_test_plan is not None:
        payload["prTestPlan"] = {
            "manifest": pr_test_plan,
            "requiredJobs": required_jobs,
            "advisoryJobs": advisory_jobs,
        }
    else:
        payload["prTestPlan"] = None
    return payload


def resolve_review_state(
    root: Path,
    plugin_root: Path,
    cfg: dict[str, Any],
    *,
    pr: str,
    head_sha: str,
    owner: str,
    repo: str,
    owner_repo: str,
    checks_file: Path,
    issue_comments_file: Path,
    grace_min: int,
) -> tuple[dict[str, Any], list[str]]:
    review = cfg.get("review") if isinstance(cfg.get("review"), dict) else {}
    review_provider_raw = review.get("provider")
    review_provider_set = "provider" in review
    review_provider = str(review_provider_raw or "none")
    review_enabled = True
    if "enabled" in review:
        review_enabled = bool(review.get("enabled"))

    deprecations: list[str] = []
    if review_enabled is False:
        deprecations.append('review.enabled is deprecated; use review.provider:"none"')
        logging_setup.warning(
            "review.enabled is deprecated; use review.provider:\"none\""
        )

    if not re.fullmatch(r"[a-z0-9-]*", review_provider):
        return (
            {
                "error": True,
                "payload": {
                    "verdict": "blocked",
                    "reason": f"invalid review.provider: {review_provider}",
                },
                "exit_code": 30,
            },
            deprecations,
        )

    cr_state = "off"
    cr_landed = True
    cr_reviewed_head = ""
    cr_status = "off"
    cr_marker = False
    cr_skipped = False
    mins_since = 0

    if review_enabled is False or (review_provider_set and review_provider_raw == "none"):
        pass
    elif not review_provider_set:
        cr_state = "unconfigured"
        cr_status = "unconfigured"
    elif review_provider == "none":
        pass
    else:
        adapter = plugin_root / "providers" / "review" / f"{review_provider}.py"
        if not adapter.is_file():
            return (
                {
                    "error": True,
                    "payload": {
                        "verdict": "blocked",
                        "reason": f"unknown review provider: {review_provider}",
                    },
                    "exit_code": 30,
                },
                deprecations,
            )
        env = {
            **os.environ,
            "SW_PR": str(pr),
            "SW_HEAD_SHA": head_sha,
            "SW_OWNER": owner,
            "SW_REPO": repo,
            "SW_OWNER_REPO": owner_repo,
            "SW_ROOT": str(root),
            "SW_CHECKS_FILE": str(checks_file),
            "SW_ISSUE_COMMENTS_FILE": str(issue_comments_file),
            "SW_GRACE_MIN": str(grace_min),
        }
        completed = proc.run([sys.executable, str(adapter)], cwd=str(root), env=env)
        try:
            review_json = json.loads(completed.stdout.strip() or "{}")
        except json.JSONDecodeError:
            review_json = {}
        has_per_head = review_json.get("capabilities", {}).get("perHeadState", False)
        cr_state = str(review_json.get("perHeadState", "in-flight"))
        cr_landed = bool(review_json.get("perHeadLanded", False))
        cr_reviewed_head = str(review_json.get("reviewedHead") or "")
        cr_status = str(review_json.get("statusContext", "absent"))
        cr_marker = bool(review_json.get("inProgressMarker", False))
        cr_skipped = bool(review_json.get("skipped", False))
        mins_since = int(review_json.get("minutesSinceHeadPush", 0) or 0)
        if not has_per_head:
            cr_state = "in-flight"
            cr_landed = False

    return (
        {
            "error": False,
            "review_provider": review_provider,
            "cr_state": cr_state,
            "cr_landed": cr_landed,
            "cr_reviewed_head": cr_reviewed_head,
            "cr_status": cr_status,
            "cr_marker": cr_marker,
            "cr_skipped": cr_skipped,
            "mins_since": mins_since,
        },
        deprecations,
    )


def scripts_touch_advisory(root: Path, pr_view: dict[str, Any], head_sha: str, reason: str) -> str:
    base_ref = pr_view.get("baseRefName") if isinstance(pr_view, dict) else None
    if not base_ref:
        return reason
    proc.run(["git", "-C", str(root), "fetch", "-q", "origin", str(base_ref)], cwd=str(root))
    merge_base = proc.run(
        ["git", "-C", str(root), "merge-base", f"origin/{base_ref}", head_sha],
        cwd=str(root),
    )
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        return reason
    diff = proc.run(
        ["git", "-C", str(root), "diff", "--name-only", merge_base.stdout.strip(), head_sha],
        cwd=str(root),
    )
    if diff.returncode == 0 and any(
        line.startswith("scripts/") for line in diff.stdout.splitlines()
    ):
        return f"{reason}; advisory: PR touches scripts/ — consider bash scripts/build-chain-sync.sh"
    return reason


def run_local_evidence_gate(root: Path, cfg: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    head_proc = proc.run(["git", "-C", str(root), "rev-parse", "HEAD"], cwd=str(root))
    head_sha = head_proc.stdout.strip() if head_proc.returncode == 0 else ""
    branch_proc = proc.run(
        ["git", "-C", str(root), "branch", "--show-current"],
        cwd=str(root),
    )
    branch = branch_proc.stdout.strip() if branch_proc.returncode == 0 else ""
    if not head_sha:
        payload = {
            "verdict": "blocked",
            "reason": "not a git repository",
            "source": "local-evidence",
        }
        jsonio.emit(payload)
        return 30, payload

    neutral_pass = bool(cfg_value(cfg, "checks", "treatNeutralAsPass", default=True))
    allowlist = cfg_value(cfg, "checks", "neutralAllowlist", default=[]) or []
    if not isinstance(allowlist, list):
        allowlist = []
    review_provider = str(cfg_value(cfg, "review", "provider", default="none") or "none")
    pr_test_plan, advisory_jobs, required_jobs = load_pr_test_plan(root, cfg)

    if not re.fullmatch(r"[a-z0-9-]*", review_provider):
        payload = {
            "verdict": "blocked",
            "reason": f"invalid review.provider: {review_provider}",
        }
        jsonio.emit(payload)
        return 30, payload

    repo_meta = host_data(root, "repo-meta") or {}
    owner_repo = str(repo_meta.get("nameWithOwner") or "local/repo")
    checks_raw = host_data(root, "checks", "--sha", head_sha) or []
    if not isinstance(checks_raw, list):
        checks_raw = []

    classified = classify_checks(checks_raw, neutral_pass=neutral_pass, allowlist=allowlist)
    failing = [c["name"] for c in classified if c["class"] == "fail"]
    pending = [c["name"] for c in classified if c["class"] == "pending"]
    blocking = [c["name"] for c in classified if c["class"] == "block"]
    required_failing, advisory_failing = split_failing(failing, advisory_jobs)
    verdict = compute_verdict(
        required_failing=required_failing,
        blocking=blocking,
        pending=pending,
        cr_landed=True,
        check_count=len(classified),
        actionable=0,
    )
    reason = verdict
    if verdict == "yellow":
        reason = f"checks pending: {','.join(pending)}"
    elif verdict == "red":
        reason = f"failing checks: {','.join(required_failing)}"
    elif verdict == "blocked":
        reason = "blocking/neutral or empty check set"
    elif verdict == "green":
        reason = (
            "local-evidence: all local checks pass; review gating off; "
            "0 actionable threads"
        )

    payload = build_gate_payload(
        verdict=verdict,
        reason=reason,
        head_sha=head_sha,
        review_provider=review_provider,
        cr_reviewed_head="",
        cr_status="off",
        cr_state="off",
        cr_landed=True,
        cr_marker=False,
        cr_skipped=False,
        mins_since=0,
        unresolved=0,
        actionable=0,
        failing=failing,
        required_failing=required_failing,
        advisory_failing=advisory_failing,
        pr_test_plan=pr_test_plan,
        required_jobs=required_jobs,
        advisory_jobs=advisory_jobs,
        pending=pending,
        blocking=blocking,
        check_count=len(classified),
        deprecations=[],
        branch=branch,
        source="local-evidence",
        pr=None,
    )
    jsonio.emit(payload)
    return VERDICT_EXIT.get(verdict, 1), payload


def run_gate(root: Path, pr_arg: str | None = None) -> tuple[int, dict[str, Any]]:
    """Compute gate verdict; emit JSON to stdout; return (exit_code, payload)."""
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    from host_lib import resolve_provider

    cfg = load_workflow_config(root)
    plugin_root = resolve_plugin_root(SCRIPT_DIR)
    neutral_pass = bool(cfg_value(cfg, "checks", "treatNeutralAsPass", default=True))
    grace_min = int(cfg_value(cfg, "coderabbit", "reviewGraceMinutes", default=15) or 15)
    allowlist = cfg_value(cfg, "checks", "neutralAllowlist", default=[]) or []
    if not isinstance(allowlist, list):
        allowlist = []
    pr_test_plan, advisory_jobs, required_jobs = load_pr_test_plan(root, cfg)

    resolved = resolve_provider(root)
    host_provider = str(resolved.get("provider") or "")
    if host_provider == "none":
        return run_local_evidence_gate(root, cfg)

    pr = pr_arg
    if not pr:
        items = host_data(root, "resolve-pr-for-branch") or []
        if isinstance(items, list) and items:
            pr = str(items[0].get("number") or "")
    if not pr:
        payload = {"verdict": "blocked", "reason": "no open PR for current branch"}
        jsonio.emit(payload)
        return 30, payload

    pr_view = host_data(root, "pr-view", "--number", pr) or {}
    head_sha = str(pr_view.get("headRefOid") or "")
    mergeable = str(pr_view.get("mergeable") or "")
    merge_state = str(pr_view.get("mergeStateStatus") or "")
    repo_meta = host_data(root, "repo-meta") or {}
    owner_repo = str(repo_meta.get("nameWithOwner") or "")
    if not head_sha or not owner_repo:
        payload = {"verdict": "blocked", "reason": "incomplete host metadata (head or repo)"}
        jsonio.emit(payload)
        return 30, payload
    if mergeable == "CONFLICTING" or merge_state == "DIRTY":
        payload = {
            "verdict": "blocked",
            "reason": "merge-conflict",
            "mergeable": mergeable,
            "mergeStateStatus": merge_state,
            "recommendedCommand": "/sw-stabilize",
        }
        jsonio.emit(payload)
        return 30, payload

    owner = owner_repo.split("/", 1)[0] if "/" in owner_repo else owner_repo
    repo = owner_repo.split("/", 1)[1] if "/" in owner_repo else owner_repo

    checks_raw = host_data(root, "checks", "--number", pr, "--sha", head_sha) or []
    if not isinstance(checks_raw, list):
        checks_raw = []
    classified = classify_checks(checks_raw, neutral_pass=neutral_pass, allowlist=allowlist)
    failing = [c["name"] for c in classified if c["class"] == "fail"]
    pending = [c["name"] for c in classified if c["class"] == "pending"]
    blocking = [c["name"] for c in classified if c["class"] == "block"]
    required_failing, advisory_failing = split_failing(failing, advisory_jobs)

    threads = host_data(root, "review-threads", "--number", pr) or {}
    unresolved = int(threads.get("unresolved", 0) or 0) if isinstance(threads, dict) else 0
    actionable = int(threads.get("actionable", 0) or 0) if isinstance(threads, dict) else 0

    with tempfile.NamedTemporaryFile(prefix="sw-gate-checks.", delete=False) as checks_f:
        checks_path = Path(checks_f.name)
        checks_f.write(json.dumps(checks_raw).encode("utf-8"))
    with tempfile.NamedTemporaryFile(prefix="sw-gate-comments.", delete=False) as comments_f:
        comments_path = Path(comments_f.name)

    try:
        review_result, deprecations = resolve_review_state(
            root,
            plugin_root,
            cfg,
            pr=pr,
            head_sha=head_sha,
            owner=owner,
            repo=repo,
            owner_repo=owner_repo,
            checks_file=checks_path,
            issue_comments_file=comments_path,
            grace_min=grace_min,
        )
    finally:
        checks_path.unlink(missing_ok=True)
        comments_path.unlink(missing_ok=True)

    if review_result.get("error"):
        payload = review_result["payload"]
        jsonio.emit(payload)
        return int(review_result.get("exit_code", 30)), payload

    verdict = compute_verdict(
        required_failing=required_failing,
        blocking=blocking,
        pending=pending,
        cr_landed=bool(review_result["cr_landed"]),
        check_count=len(classified),
        actionable=actionable,
    )
    reason = build_reason(
        verdict,
        pending=pending,
        required_failing=required_failing,
        advisory_failing=advisory_failing,
        actionable=actionable,
        cr_landed=bool(review_result["cr_landed"]),
        cr_state=str(review_result["cr_state"]),
        head_sha=head_sha,
        review_provider=str(review_result["review_provider"]),
    )
    if verdict == "green" and pr and head_sha:
        reason = scripts_touch_advisory(root, pr_view, head_sha, reason)

    payload = build_gate_payload(
        verdict=verdict,
        reason=reason,
        head_sha=head_sha,
        review_provider=str(review_result["review_provider"]),
        cr_reviewed_head=str(review_result["cr_reviewed_head"]),
        cr_status=str(review_result["cr_status"]),
        cr_state=str(review_result["cr_state"]),
        cr_landed=bool(review_result["cr_landed"]),
        cr_marker=bool(review_result["cr_marker"]),
        cr_skipped=bool(review_result["cr_skipped"]),
        mins_since=int(review_result["mins_since"]),
        unresolved=unresolved,
        actionable=actionable,
        failing=failing,
        required_failing=required_failing,
        advisory_failing=advisory_failing,
        pr_test_plan=pr_test_plan,
        required_jobs=required_jobs,
        advisory_jobs=advisory_jobs,
        pending=pending,
        blocking=blocking,
        check_count=len(classified),
        deprecations=deprecations,
        pr=int(pr),
    )
    jsonio.emit(payload)
    return VERDICT_EXIT.get(verdict, 1), payload
