#!/usr/bin/env python3
"""Base-branch resolution, persistence, and fail-closed OID contract (PRD 018 TR4/TR5)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
STATE_REL = Path(".cursor/sw-base-state.json")
SCHEMA_DEFAULT = "main"
SHIPWRIGHT_BRANCH_RE = re.compile(
    r"^(feat|fix|docs|hotfix|release|chore|refactor|test|perf|revert)/"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def git_top(start: Path | None = None) -> Path:
    cwd = start or Path.cwd()
    proc = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("not a git repository")
    return Path(proc.stdout.strip())


def git_run(args: list[str], cwd: Path, *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), text=True, capture_output=True, check=check)


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                continue
    return {}


def schema_default_base(root: Path) -> str:
    schema_path = root / ".sw/config.schema.json"
    if not schema_path.is_file():
        for candidate in (
            root / "core" / "sw-reference" / "config.schema.json",
            Path(os.environ.get("CURSOR_PLUGIN_ROOT", "")) / ".sw/config.schema.json",
        ):
            if candidate.is_file():
                schema_path = candidate
                break
    if schema_path.is_file():
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            props = schema.get("properties") or {}
            dbb = (props.get("defaultBaseBranch") or {}).get("default")
            if isinstance(dbb, str) and dbb:
                return dbb
        except json.JSONDecodeError:
            pass
    return SCHEMA_DEFAULT


def is_user_set_default_base(cfg: dict[str, Any], root: Path) -> tuple[bool, str | None]:
    value = cfg.get("defaultBaseBranch")
    if not isinstance(value, str) or not value.strip():
        return False, None
    schema_def = schema_default_base(root)
    if value != schema_def:
        return True, value.strip()
    if cfg.get("defaultBaseBranchUserSet") is True:
        return True, value.strip()
    return False, None


def state_path(root: Path) -> Path:
    return root / STATE_REL


def read_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def write_state(root: Path, data: dict[str, Any]) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def resolve_ref_name(root: Path, name: str) -> tuple[str | None, str | None]:
    for candidate in (name, f"origin/{name}"):
        proc = git_run(["rev-parse", "--verify", candidate], root, check=False)
        if proc.returncode == 0:
            sha = proc.stdout.strip()
            return sha, candidate
    return None, None


def current_head(root: Path) -> tuple[str, str]:
    branch = git_run(["branch", "--show-current"], root, check=False).stdout.strip()
    sha = git_run(["rev-parse", "HEAD"], root, check=False).stdout.strip()
    return branch, sha


def is_detached(root: Path) -> bool:
    branch, _ = current_head(root)
    return not branch


def is_shipwright_work_branch(name: str) -> bool:
    return bool(SHIPWRIGHT_BRANCH_RE.match(name or ""))


def entry_guard(root: Path, *, explicit_base: str | None) -> None:
    if is_detached(root):
        fail(
            "detached HEAD — checkout a branch or pass --base <branch>",
            exit_code=20,
            halt="detached-head",
            remediation="git checkout <trunk-branch>  # or: bash scripts/resolve-base-branch.sh capture --base <branch>",
        )
    branch, _ = current_head(root)
    if branch and is_shipwright_work_branch(branch) and not explicit_base:
        fail(
            f"HEAD on Shipwright work branch {branch!r} — unsafe base capture",
            exit_code=20,
            halt="work-branch-head",
            remediation=(
                f"git checkout $(bash scripts/resolve-base-branch.sh resolve --quiet --name-only) "
                f"&& bash scripts/resolve-base-branch.sh capture"
            ),
            currentBranch=branch,
        )


def compute_resolution(root: Path, *, explicit_base: str | None = None) -> dict[str, Any]:
    cfg = load_workflow_config(root)
    if explicit_base:
        sha, ref = resolve_ref_name(root, explicit_base)
        if not sha:
            fail(f"base branch not found: {explicit_base!r}")
        return {
            "name": explicit_base,
            "sha": sha,
            "ref": ref,
            "source": "explicit-base",
        }

    user_set, user_value = is_user_set_default_base(cfg, root)
    if user_set and user_value:
        sha, ref = resolve_ref_name(root, user_value)
        if sha:
            return {
                "name": user_value,
                "sha": sha,
                "ref": ref,
                "source": "defaultBaseBranch",
            }

    branch, sha = current_head(root)
    if not branch:
        fail("cannot capture base from detached HEAD")
    return {
        "name": branch,
        "sha": sha,
        "ref": "HEAD",
        "source": "captured-from-head",
    }


def capture(root: Path, *, explicit_base: str | None = None, force: bool = False) -> dict[str, Any]:
    entry_guard(root, explicit_base=explicit_base)
    existing = read_state(root)
    trunk = (existing.get("trunkBase") or {}) if isinstance(existing.get("trunkBase"), dict) else {}
    if trunk.get("name") and trunk.get("sha") and not force and not explicit_base:
        return {
            "verdict": "pass",
            "action": "capture",
            "skipped": True,
            "trunkBase": trunk,
        }
    resolved = compute_resolution(root, explicit_base=explicit_base)
    payload = {
        "trunkBase": {
            **resolved,
            "capturedAt": utc_now(),
        }
    }
    write_state(root, payload)
    return {
        "verdict": "pass",
        "action": "capture",
        "trunkBase": payload["trunkBase"],
        "disclosure": format_disclosure(payload["trunkBase"]),
    }


def load_persisted_trunk(root: Path) -> dict[str, Any]:
    state = read_state(root)
    trunk = state.get("trunkBase")
    if not isinstance(trunk, dict) or not trunk.get("name") or not trunk.get("sha"):
        fail(
            "persisted base missing or corrupt — re-enter from trunk branch or pass --base",
            exit_code=20,
            halt="needs-base-replay",
            remediation="git checkout <trunk> && bash scripts/resolve-base-branch.sh capture",
        )
    return trunk


def resolve(root: Path, *, explicit_base: str | None = None, require_persisted: bool = False) -> dict[str, Any]:
    if require_persisted:
        trunk = load_persisted_trunk(root)
        return {"verdict": "pass", "action": "resolve", "trunkBase": trunk, "persisted": True}
    if explicit_base:
        resolved = compute_resolution(root, explicit_base=explicit_base)
        return {"verdict": "pass", "action": "resolve", "trunkBase": resolved, "persisted": False}
    state = read_state(root)
    trunk = state.get("trunkBase")
    if isinstance(trunk, dict) and trunk.get("name") and trunk.get("sha"):
        return {"verdict": "pass", "action": "resolve", "trunkBase": trunk, "persisted": True}
    resolved = compute_resolution(root)
    return {"verdict": "pass", "action": "resolve", "trunkBase": resolved, "persisted": False}


def format_disclosure(trunk: dict[str, Any]) -> str:
    name = trunk.get("name", "?")
    source = trunk.get("source", "?")
    source_label = {
        "explicit-base": "--base",
        "defaultBaseBranch": "defaultBaseBranch",
        "captured-from-head": "captured from HEAD",
    }.get(source, source)
    return f"base: {name} ({source_label})"


def validate_base_oid(root: Path, base_sha: str, head_sha: str | None = None) -> dict[str, Any]:
    head_sha = head_sha or git_run(["rev-parse", "HEAD"], root, check=False).stdout.strip()
    if not base_sha:
        return {"ok": False, "reason": "missing-base-oid"}
    proc = git_run(["cat-file", "-e", f"{base_sha}^{{commit}}"], root, check=False)
    if proc.returncode != 0:
        return {"ok": False, "reason": "base-oid-unresolvable"}
    if base_sha == head_sha:
        return {"ok": False, "reason": "base-equals-head"}
    if not git_run(["merge-base", "--is-ancestor", base_sha, head_sha], root, check=False).returncode == 0:
        return {"ok": False, "reason": "base-not-ancestor-of-head"}
    diff = git_run(["diff", "--name-only", f"{base_sha}..{head_sha}"], root, check=False)
    if diff.returncode != 0:
        return {"ok": False, "reason": "diff-failed"}
    if not diff.stdout.strip():
        return {"ok": False, "reason": "empty-diff"}
    return {"ok": True, "baseSha": base_sha, "headSha": head_sha}


def resolve_diff_base(root: Path, *, explicit_base: str | None = None, ci: bool = False) -> dict[str, Any]:
    """Fail-closed base for secret-scan / frozen checks (R19)."""
    head_sha = git_run(["rev-parse", "HEAD"], root, check=False).stdout.strip()
    source = "persisted"
    base_sha: str | None = None
    base_name: str | None = None

    if explicit_base:
        sha, _ = resolve_ref_name(root, explicit_base)
        if not sha:
            fail(f"explicit --base not found: {explicit_base!r}", exit_code=2)
        base_sha, base_name, source = sha, explicit_base, "explicit-base"
    elif ci and os.environ.get("GITHUB_BASE_REF"):
        ref = os.environ["GITHUB_BASE_REF"]
        sha, _ = resolve_ref_name(root, ref)
        if sha:
            base_sha, base_name, source = sha, ref, "GITHUB_BASE_REF"
    if not base_sha:
        trunk = read_state(root).get("trunkBase")
        if isinstance(trunk, dict) and trunk.get("sha"):
            base_sha = str(trunk["sha"])
            base_name = str(trunk.get("name", ""))
            source = "persisted"
    if not base_sha:
        cfg = load_workflow_config(root)
        user_set, user_value = is_user_set_default_base(cfg, root)
        if user_set and user_value:
            sha, _ = resolve_ref_name(root, user_value)
            if sha:
                base_sha, base_name, source = sha, user_value, "defaultBaseBranch"
    if not base_sha:
        fail("fail-closed: no resolvable base OID", exit_code=2, halt="missing-base")

    check = validate_base_oid(root, base_sha, head_sha)
    if not check.get("ok"):
        fail(
            f"fail-closed base contract: {check.get('reason')}",
            exit_code=1,
            halt="base-contract",
            base={"name": base_name, "sha": base_sha, "source": source},
        )
    return {
        "verdict": "pass",
        "base": {"name": base_name, "sha": base_sha, "source": source},
        "headSha": head_sha,
        "range": f"{base_sha}..{head_sha}",
    }


def trunk_base_name(root: Path) -> str:
    data = resolve(root, require_persisted=False)
    trunk = data.get("trunkBase") or {}
    name = trunk.get("name")
    if isinstance(name, str) and name:
        return name
    return schema_default_base(root)


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        fail(
            "usage: resolve_base_branch.py capture|resolve|disclose|diff-base|trunk-name "
            "[--base BRANCH] [--require-persisted] [--force] [--quiet] [--name-only] [--ci]"
        )
    cmd = args[0]
    rest = args[1:]
    explicit_base = None
    require_persisted = "--require-persisted" in rest
    force = "--force" in rest
    quiet = "--quiet" in rest
    name_only = "--name-only" in rest
    ci = "--ci" in rest
    if "--base" in rest:
        i = rest.index("--base")
        if i + 1 < len(rest):
            explicit_base = rest[i + 1]

    root = git_top()

    if cmd == "capture":
        result = capture(root, explicit_base=explicit_base, force=force)
        if quiet and name_only:
            print(result["trunkBase"]["name"])
            sys.exit(0)
        emit(result)

    if cmd == "resolve":
        result = resolve(root, explicit_base=explicit_base, require_persisted=require_persisted)
        if quiet and name_only:
            print(result["trunkBase"]["name"])
            sys.exit(0)
        emit(result)

    if cmd == "disclose":
        result = resolve(root, require_persisted=True)
        line = format_disclosure(result["trunkBase"])
        if quiet or name_only:
            print(line)
            sys.exit(0)
        emit({"verdict": "pass", "action": "disclose", "line": line, **result})

    if cmd == "diff-base":
        emit(resolve_diff_base(root, explicit_base=explicit_base, ci=ci))

    if cmd == "trunk-name":
        name = trunk_base_name(root)
        print(name)
        sys.exit(0)

    fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
