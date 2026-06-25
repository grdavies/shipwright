#!/usr/bin/env python3
"""CI/review base-branch preflight for /sw-deliver phase-mode (R49)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent


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


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_preflight.py <root> <command> [args...]")
    root = Path(sys.argv[1])
    cmd = sys.argv[2]
    args = sys.argv[3:]
    if cmd == "base-check":
        cmd_base_check(root, args)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
