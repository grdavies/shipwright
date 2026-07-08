#!/usr/bin/env python3
"""CI/review base-branch preflight for /sw-deliver phase-mode (R49)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
DISPATCH_PREFLIGHT_DIR = Path(".cursor/hooks/state/task-dispatch-preflight")
DISPATCH_PREFLIGHT_LEGACY = Path(".cursor/hooks/state/task-dispatch-preflight.json")

sys.path.insert(0, str(SCRIPT_DIR))
from capability_index import check_freshness  # noqa: E402


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
    return {}


def pull_request_block(text: str) -> str:
    match = re.search(
        r"^(\s*)pull_request\s*:(.*?)(?=^\1\S|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    return match.group(2) if match else ""


def pr_trigger_restricted_to_default(block: str, default_branch: str) -> bool:
    if not block.strip():
        return False
    if "branches:" not in block and "branches-" not in block:
        return False
    branches = re.findall(r"['\"]([^'\"]+)['\"]", block)
    if not branches:
        # YAML inline list: branches: [main] or branches: [main, develop]
        inline = re.search(r"branches:\s*\[([^\]]+)\]", block)
        if inline:
            branches = [b.strip() for b in inline.group(1).split(",") if b.strip()]
    if not branches:
        return False
    allowed_non_default = tuple(
        b
        for b in branches
        if b not in (default_branch, "master")
        and ("*" in b or "**" in b or "/" in b)
    )
    if allowed_non_default:
        return False
    return all(b in (default_branch, "master") for b in branches)


def scan_ci_workflows(root: Path, default_branch: str) -> dict[str, Any]:
    workflows_dir = root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return {
            "ok": False,
            "error": "no .github/workflows directory",
            "workflows": [],
            "restricted": [],
        }
    pr_workflows: list[str] = []
    restricted: list[str] = []
    for path in sorted(workflows_dir.glob("*.y*ml")):
        text = path.read_text(encoding="utf-8")
        if "pull_request" not in text:
            continue
        pr_workflows.append(path.name)
        block = pull_request_block(text)
        if pr_trigger_restricted_to_default(block, default_branch):
            restricted.append(path.name)
    if not pr_workflows:
        return {
            "ok": False,
            "error": "no pull_request workflows found",
            "workflows": [],
            "restricted": [],
        }
    return {
        "ok": len(restricted) == 0,
        "workflows": pr_workflows,
        "restricted": restricted,
    }


def scan_review_provider(root: Path, config: dict[str, Any]) -> dict[str, Any]:
    review = config.get("review") or {}
    provider = str(review.get("provider") or "none").strip().lower()
    if provider in ("", "none", "off", "unconfigured"):
        return {
            "ok": True,
            "provider": provider or "none",
            "note": "review gating off — no async review barrier for phase PRs",
        }
    config_candidates = [
        ".coderabbit.yaml",
        ".github/coderabbit.yaml",
        "coderabbit.yaml",
        ".coderabbit.yml",
    ]
    has_config = any((root / name).is_file() for name in config_candidates)
    if provider == "coderabbit" and not has_config:
        return {
            "ok": False,
            "provider": provider,
            "error": (
                "review.provider is coderabbit but no repo config found; "
                "phase PRs targeting <type>/<slug> may never land reviews (R52)"
            ),
            "remediation": (
                "Add .coderabbit.yaml with reviews enabled for non-default base branches, "
                "or set review.provider to none until configured"
            ),
        }
    return {"ok": True, "provider": provider, "configured": has_config}


def run_base_check(root: Path, target_branch: str, default_branch: str) -> dict[str, Any]:
    if "/" not in target_branch:
        fail(f"target branch must be <type>/<slug>, got {target_branch!r}")
    branch_type = target_branch.split("/", 1)[0]
    config = load_workflow_config(root)
    default = str(config.get("defaultBaseBranch") or default_branch)
    ci = scan_ci_workflows(root, default)
    review = scan_review_provider(root, config)
    ok = ci.get("ok") and review.get("ok")
    result: dict[str, Any] = {
        "verdict": "pass" if ok else "fail",
        "action": "base-preflight",
        "targetBranch": target_branch,
        "branchType": branch_type,
        "defaultBaseBranch": default,
        "ci": ci,
        "review": review,
    }
    if not ok:
        hints: list[str] = []
        if ci.get("restricted"):
            hints.append(
                "CI workflows only trigger on the default branch — phase PRs into "
                f"{branch_type}/** will get checkCount==0 and block (R49). "
                f"Update: {', '.join(ci['restricted'])} to include pull_request "
                f"without a main-only branches filter, or add {branch_type}/**."
            )
        if not ci.get("ok") and ci.get("error"):
            hints.append(str(ci["error"]))
        if not review.get("ok"):
            hints.append(review.get("remediation") or review.get("error", "review misconfigured"))
        result["remediation"] = hints
    return result


def cmd_base_check(root: Path, args: list[str]) -> None:
    target = parse_kv(args, "--target")
    if not target:
        fail("--target <type>/<slug> required")
    default = parse_kv(args, "--default-base", "main") or "main"
    result = run_base_check(root, target, default)
    if result["verdict"] != "pass":
        fail(
            "base-branch preflight failed",
            exit_code=20,
            halt="preflight",
            cause="base-preflight:ci-or-review",
            **result,
        )
    emit(result)


def run_json_cmd(root: Path, argv: list[str]) -> dict[str, Any]:
    proc = subprocess.run(argv, cwd=str(root), capture_output=True, text=True, check=False)
    try:
        parsed = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        parsed = {}
    if proc.returncode != 0:
        # R18: propagate a resolver-emitted remediation (agent map -> models.roles ->
        # remediation, see resolve-model-tier.py resolve_inherit_agent_fallback) verbatim
        # instead of collapsing every nonzero resolver exit onto the generic
        # binding:no-model cause — an inherit orchestrator + unmapped agent gets an
        # actionable remediation, never a bare binding:no-model dead end.
        if isinstance(parsed, dict) and parsed.get("remediation"):
            fail(
                parsed.get("error") or "dispatch preflight resolver failed",
                exit_code=20,
                cause=parsed.get("cause") or "no-model:remediation",
                command=parsed.get("command") or argv[0],
                agent=parsed.get("agent"),
                remediation=parsed["remediation"],
            )
        fail(
            "dispatch preflight resolver failed",
            exit_code=20,
            cause="binding:no-model",
            command=argv[0],
            stderr=(proc.stderr or "").strip() or None,
        )
    if not isinstance(parsed, dict):
        return {}
    return parsed


def run_capability_index_check(root: Path, args: list[str]) -> dict[str, Any]:
    index_rel = parse_kv(args, "--index", "core/sw-reference/capability-index.json")
    index_path = root / str(index_rel)
    core_root = root / "core"
    if not index_path.is_file():
        return {
            "verdict": "pass",
            "action": "capability-index-check",
            "skipped": True,
            "reason": "no committed capability-index.json",
        }
    ok, message = check_freshness(core_root, index_path)
    if not ok:
        fail(
            message,
            exit_code=20,
            halt="preflight",
            cause="capability-index:stale",
            action="capability-index-check",
            indexPath=str(index_path),
        )
    return {
        "verdict": "pass",
        "action": "capability-index-check",
        "indexPath": str(index_path),
        "message": message,
    }


def cmd_capability_index_check(root: Path, args: list[str]) -> None:
    emit(run_capability_index_check(root, args))



def git_toplevel(start: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise ValueError("not a git repository")
    return Path(proc.stdout.strip()).resolve()


def assert_hook_root_aligned(root: Path) -> None:
    from primary_checkout_guard import canonical_repo_root, primary_worktree_path
    from worktree_root import is_shipwright_worktree

    cwd_top = git_toplevel(root)
    primary = primary_worktree_path(canonical_repo_root(root))
    if cwd_top == primary:
        return
    if is_shipwright_worktree(cwd_top, primary):
        return
    fail(
        "hook-state root mismatch: cwd toplevel differs from primary and is not a recognized worktree",
        exit_code=20,
        remediation=(
            f"move_agent_to_root {cwd_top}  # or cd {cwd_top} and align IDE workspace"
        ),
        cwdToplevel=str(cwd_top),
        primaryCheckout=str(primary),
    )

def cmd_dispatch(root: Path, args: list[str]) -> None:
    assert_hook_root_aligned(root)
    if not args:
        fail("dispatch subcommand required: preflight")
    sub = args[0]
    rest = args[1:]
    if sub != "preflight":
        fail(f"unknown dispatch subcommand: {sub}")

    run_capability_index_check(root, [])
    dispatch_id = parse_kv(rest, "--dispatch-id")
    agent = parse_kv(rest, "--agent")
    command = parse_kv(rest, "--command")
    skill = parse_kv(rest, "--skill")
    config = parse_kv(rest, "--config")
    ttl_raw = parse_kv(rest, "--ttl-seconds", "900") or "900"

    if not dispatch_id or not agent:
        fail("--dispatch-id and --agent are required for dispatch preflight")

    try:
        ttl_seconds = int(ttl_raw)
    except ValueError:
        ttl_seconds = 900
    if ttl_seconds < 30:
        ttl_seconds = 30

    model_cmd = [sys.executable, str(SCRIPT_DIR / "resolve-model-tier.py"), "--agent", agent]
    intensity_cmd = [sys.executable, str(SCRIPT_DIR / "resolve-intensity.py"), "--agent", agent]
    if command:
        model_cmd.extend(["--command", command])
        intensity_cmd.extend(["--command", command])
    if skill:
        intensity_cmd.extend(["--skill", skill])
    if config:
        model_cmd.extend(["--config", config])
        intensity_cmd.extend(["--config", config])

    model_payload = run_json_cmd(root, model_cmd)
    intensity_payload = run_json_cmd(root, intensity_cmd)

    model_id = str(model_payload.get("modelId") or "")
    tier = str(model_payload.get("tier") or "")
    intensity = str(intensity_payload.get("intensity") or "")
    if not model_id or tier == "inherit":
        fail(
            "dispatch preflight missing concrete model",
            exit_code=20,
            cause="binding:no-model",
            dispatchId=dispatch_id,
            agent=agent,
        )
    if intensity not in {"normal", "lite", "full", "ultra"}:
        fail(
            "dispatch preflight missing resolved intensity",
            exit_code=20,
            cause="binding:no-intensity",
            dispatchId=dispatch_id,
            agent=agent,
        )

    now = int(time.time())
    record = {
        "dispatchId": dispatch_id,
        "agent": agent,
        "command": command,
        "skill": skill,
        "modelId": model_id,
        "modelTier": tier,
        "intensity": intensity,
        "nonce": uuid.uuid4().hex,
        "createdAt": now,
        "expiresAt": now + ttl_seconds,
        "consumedAt": None,
    }
    out_dir = root / DISPATCH_PREFLIGHT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{dispatch_id}.json"
    out_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    emit(
        {
            "verdict": "pass",
            "action": "dispatch-preflight",
            "recordPath": str(out_path),
            "dispatchId": dispatch_id,
            "agent": agent,
            "modelId": model_id,
            "intensity": intensity,
            "nonce": record["nonce"],
            "expiresAt": record["expiresAt"],
        }
    )


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_preflight.py <root> <command> [args...]")
    root = Path(sys.argv[1])
    cmd = sys.argv[2]
    args = sys.argv[3:]
    if cmd == "base-check":
        cmd_base_check(root, args)
    elif cmd == "capability-index-check":
        cmd_capability_index_check(root, args)
    elif cmd == "dispatch":
        cmd_dispatch(root, args)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
