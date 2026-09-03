#!/usr/bin/env python3
"""Idempotent spec-seed onto <type>/<slug> — single owner for /sw-doc, /sw-freeze, and deliver-loop."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SHIPWRIGHT_ROOT = SCRIPT_DIR.parent

import sys as _sys
if str(SCRIPT_DIR) not in _sys.path:
    _sys.path.insert(0, str(SCRIPT_DIR))
from worktree_lib import docs_branch_for_topic, refuse_default_branch

import planning_paths
import planning_path_redirect
import planning_index_gen as planning_index
import planning_visibility as planning_vis
from host_lib import load_workflow_config
from planning_artifact_handle import issue_store_separate_project_effective, resolve_repo_file

_VALID_TYPES = frozenset(
    {"feat", "fix", "perf", "revert", "docs", "chore", "refactor", "test"}
)


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


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[`/]", " ", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def parse_frontmatter(content: str) -> dict[str, str]:
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end == -1:
        return {}
    block = content[4:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            out[key.strip()] = val.strip()
    return out


def git_toplevel(start: Path) -> Path:
    out = subprocess.check_output(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
    ).strip()
    return Path(out)


def git_run(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check)


def load_trunk_base(root: Path) -> str:
    script = SHIPWRIGHT_ROOT / "scripts" / "resolve_base_branch.py"
    if script.is_file():
        proc = subprocess.run(
            [sys.executable, str(script), "trunk-name"],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return load_default_branch(root)


def load_default_branch(root: Path) -> str:
    from host_lib import default_base_branch

    return default_base_branch(root)


def resolve_type_from_frontmatter(frontmatter: dict[str, str]) -> str:
    branch_type = frontmatter.get("type") or "feat"
    if branch_type not in _VALID_TYPES:
        fail(f"invalid branch type {branch_type!r}; want one of {sorted(_VALID_TYPES)}")
    return branch_type


def resolve_target_branch(root: Path, task_list_rel: str) -> tuple[str, str, Path]:
    proc = subprocess.run(
        [
            sys.executable,
            str(SHIPWRIGHT_ROOT / "scripts/wave_deliver.py"),
            str(root),
            "preflight",
            "--task-list",
            task_list_rel,
            "--skip-base-check",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or proc.stdout.strip() or "preflight failed")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        fail(f"preflight returned invalid JSON: {exc}")
    branch = (data.get("target") or {}).get("branch")
    if not branch:
        fail("preflight missing target.branch")
    import planning_materialize as pm

    pm.ensure_run_entry_materialized(root, task_list_rel)
    _resolved_rel, task_path = planning_path_redirect.resolve_readable_path(root, task_list_rel)
    if task_path is None:
        task_list_rel = planning_path_redirect.resolve_path(root, task_list_rel)
        fail(f"task list not found: {task_list_rel}")
    docs_dir = task_path.parent
    slug = branch.split("/", 1)[1] if "/" in branch else branch
    return branch, slug, docs_dir


def prd_docs_dir_for_artifact(root: Path, artifact: Path) -> Path:
    dirs = planning_paths.load_planning_dirs(root)
    try:
        return planning_paths.prd_unit_dir_for_artifact(root, artifact)
    except planning_paths.PathEscapeError as exc:
        fail(f"artifact must live under {dirs.prds}: {artifact} ({exc})")


def resolve_target_from_artifact(root: Path, artifact_rel: str) -> tuple[str, str, Path]:
    artifact = (root / artifact_rel).resolve()
    if not artifact.is_file():
        fail(f"artifact not found: {artifact_rel}")
    docs_dir = prd_docs_dir_for_artifact(root, artifact)

    for task_path in sorted(docs_dir.glob("tasks-*.md")):
        if task_path.is_file():
            rel = str(task_path.relative_to(root))
            branch, slug, _ = resolve_target_branch(root, rel)
            return branch, slug, docs_dir

    m = re.match(r"^(\d+)-(.+)$", docs_dir.name)
    slug = m.group(2) if m else slugify(docs_dir.name)
    branch_type = "feat"
    for prd_path in sorted(docs_dir.glob("*-prd-*.md")):
        if prd_path.is_file():
            fm = parse_frontmatter(prd_path.read_text(encoding="utf-8"))
            branch_type = resolve_type_from_frontmatter(fm)
            if fm.get("topic"):
                slug = slugify(fm["topic"])
            break
    return f"{branch_type}/{slug}", slug, docs_dir


def docs_paths(docs_dir: Path, root: Path, *, single: Path | None = None) -> list[Path]:
    paths: list[Path] = []
    if single is not None:
        if single.is_file() and "brainstorms" not in single.parts:
            paths.append(single)
        return paths
    if docs_dir.is_dir():
        for p in sorted(docs_dir.rglob("*")):
            if p.is_file() and "brainstorms" not in p.parts:
                paths.append(p)
    return paths


def _parse_brainstorm_link_paths(raw: str | None) -> list[str]:
    if not raw:
        return []
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
    return [raw]


def referenced_brainstorm_paths(root: Path, docs_dir: Path) -> list[Path]:
    """Collect brainstorm files referenced by PRDs in docs_dir (PRD 081 R14)."""
    from doc_link import brainstorm_ref_unit_id
    from planning_artifact_handle import materialize_artifact_file, normalize_body_path

    paths: list[Path] = []
    seen: set[str] = set()
    if not docs_dir.is_dir():
        return paths
    for prd_path in sorted(docs_dir.rglob("*.md")):
        name = prd_path.name.lower()
        if "prd" not in name and not name.endswith("-prd.md"):
            continue
        fm = parse_frontmatter(prd_path.read_text(encoding="utf-8"))
        back = fm.get("brainstorm") or fm.get("source_brainstorm")
        if not back:
            continue
        for target in _parse_brainstorm_link_paths(back):
            rel = normalize_body_path(target.strip().strip("'\""))
            resolved = resolve_repo_file(root, rel)
            if resolved is not None and resolved.is_file():
                key = str(resolved.resolve())
                if key not in seen:
                    seen.add(key)
                    paths.append(resolved)
                continue
            uid = brainstorm_ref_unit_id(rel)
            materialized = materialize_artifact_file(root, rel, unit_id=uid)
            if materialized is None or not materialized.is_file():
                continue
            dest = (root / rel).resolve()
            if not dest.is_file():
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(materialized.read_text(encoding="utf-8"), encoding="utf-8")
            key = str(dest.resolve())
            if key not in seen:
                seen.add(key)
                paths.append(dest)
    return paths



def docs_paths_all(root: Path, topic: str) -> list[Path]:
    """Tracked doc artifacts for a topic incl. brainstorms (R31)."""
    slug = topic.lower().replace(" ", "-")
    paths: list[Path] = []
    dirs = planning_paths.load_planning_dirs(root)
    for base in (root / planning_paths.brainstorms_rel(), root / dirs.prds):
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file() and slug in p.name.lower():
                paths.append(p)
    return paths

def tracked_paths(root: Path, paths: list[Path]) -> list[Path]:
    tracked: list[Path] = []
    for p in paths:
        rel = str(p.relative_to(root))
        if git_run(["ls-files", "--error-unmatch", rel], root, check=False).returncode == 0:
            tracked.append(p)
    return tracked


def rel_paths(root: Path, paths: list[Path]) -> list[str]:
    return [str(p.relative_to(root)) for p in paths]



def resolve_path_visibility(root: Path, path: Path) -> str:
    cfg = load_workflow_config(root)
    fm = parse_frontmatter(path.read_text(encoding="utf-8"))
    unit = {
        "id": fm.get("id") or path.stem,
        "type": fm.get("type") or "prd",
        "status": fm.get("status") or "proposed",
        "title": fm.get("title") or path.stem,
    }
    if fm.get("visibility"):
        unit["visibility"] = fm["visibility"]
    if fm.get("contentClass"):
        unit["contentClass"] = fm["contentClass"]
    return planning_vis.resolve_unit_visibility(unit, cfg)["visibility"]


def filter_public_docs(root: Path, paths: list[Path]) -> tuple[list[Path], list[str]]:
    public: list[Path] = []
    skipped: list[str] = []
    for p in paths:
        vis = resolve_path_visibility(root, p)
        if planning_vis.body_is_redacted(vis):
            skipped.append(str(p.relative_to(root)))
        else:
            public.append(p)
    return public, skipped


def assert_no_tracked_private_bodies(root: Path, paths: list[Path], *, feature_branch: str | None = None) -> None:
    tracked_private: list[str] = []
    for p in paths:
        rel = str(p.relative_to(root))
        if git_run(["ls-files", "--error-unmatch", rel], root, check=False).returncode != 0:
            continue
        vis = resolve_path_visibility(root, p)
        if planning_vis.body_is_redacted(vis):
            tracked_private.append(rel)
    if tracked_private:
        fail(
            "tracked private/memory body path(s) — remove from index or set visibility public",
            exit_code=20,
            halt="tracked-private-body",
            remediation=(
                f"add visibility: public on feature branch {feature_branch!r}, not on main"
                if feature_branch
                else "git rm --cached <path> or change visibility to public on the feature branch"
            ),
            paths=tracked_private,
        )


def ensure_redacted_index(root: Path) -> str | None:
    """Regenerate + write the redacted planning INDEX for spec-seed.

    Guarded by the effective backend (PRD 057 R2): under issue-store
    ``separate-project`` the code-repo INDEX is not the authoritative surface
    (deliver run-entry materialize and the issue store itself supply task
    content), so the local write is skipped entirely — never a tracked write
    in that mode. ``same-repo`` and non-issue-store backends are unaffected.
    """
    if issue_store_separate_project_effective(root):
        return None
    rel = planning_index.index_rel(root)
    index = root / rel
    content = planning_index.generate_index(root)
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(content, encoding="utf-8")
    if git_run(["ls-files", "--error-unmatch", rel], root, check=False).returncode == 0:
        return rel
    return None


VERIFIED_COMPLETION_OUTCOMES = frozenset({"committed", "already-present"})


def branch_head_commit(top: Path, branch: str) -> str | None:
    proc = git_run(["rev-parse", branch], top, check=False)
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha or None


def verify_commit_on_branch(top: Path, commit_sha: str, branch: str) -> bool:
    proc = git_run(
        ["merge-base", "--is-ancestor", commit_sha, branch],
        top,
        check=False,
    )
    return proc.returncode == 0


def build_verified_completion(
    top: Path,
    branch: str,
    commit_sha: str,
    outcome: str,
) -> dict[str, Any]:
    verified = verify_commit_on_branch(top, commit_sha, branch)
    complete = outcome in VERIFIED_COMPLETION_OUTCOMES and verified and commit_sha
    return {
        "outcome": outcome,
        "verified": verified,
        "commit": commit_sha,
        "complete": bool(complete),
        "branch": branch,
        "dryRun": False,
    }


def build_incomplete_completion(
    branch: str,
    *,
    outcome: str = "incomplete",
    reason: str | None = None,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "outcome": outcome,
        "verified": False,
        "commit": None,
        "complete": False,
        "branch": branch,
    }
    if dry_run is not None:
        payload["dryRun"] = dry_run
    if reason:
        payload["reason"] = reason
    return payload


def completion_from_seed_payload(top: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Report feature-seed completion — verified commit outcome only (PRD 089 R6)."""
    branch = str(payload.get("branch") or "")
    if payload.get("dry_run"):
        return build_incomplete_completion(
            branch,
            outcome="failed",
            reason="dry-run",
            dry_run=True,
        )
    commit_sha = payload.get("commit")
    if isinstance(commit_sha, str) and commit_sha and branch:
        outcome = "already-present" if payload.get("skipped") else "committed"
        return build_verified_completion(top, branch, commit_sha, outcome)
    if payload.get("skipped") and branch:
        head = branch_head_commit(top, branch)
        if head:
            return build_verified_completion(top, branch, head, "already-present")
    return build_incomplete_completion(
        branch,
        outcome="incomplete",
        reason="missing-verified-commit",
    )


def ambiguous_remote_state_default(branch: str) -> dict[str, Any]:
    """Pre-seed remote state — not a completion signal (R6)."""
    return {"branch": branch, "commit": None, "dryRun": True}


def branch_has_docs_commit(top: Path, branch: str, doc_rels: list[str]) -> bool:
    if not doc_rels:
        return False
    show = git_run(["show-ref", "--verify", f"refs/heads/{branch}"], top, check=False)
    if show.returncode != 0:
        return False
    for rel in doc_rels:
        log = git_run(["log", "-1", "--format=%H", branch, "--", rel], top, check=False)
        if log.returncode != 0 or not log.stdout.strip():
            return False
    diff = git_run(["diff", "--quiet", branch, "--", *doc_rels], top, check=False)
    if diff.returncode == 1:
        return False
    return True


def commit_docs_seed(
    top: Path,
    *,
    branch: str,
    slug: str,
    docs_dir: Path,
    doc_rels: list[str],
    default: str,
    dry_run: bool,
    scope: str,
    skipped_private: list[str] | None = None,
    target_lock: dict[str, Any] | None = None,
) -> None:
    current = git_run(["branch", "--show-current"], top, check=False).stdout.strip()
    status = git_run(["status", "--porcelain"], top, check=False).stdout

    if current == branch and status.strip():
        fail(
            f"primary checkout is dirty on {branch} — commit or stash before spec-seed",
            exit_code=20,
            halt="dirty-primary",
            remediation=f"git stash push -m 'pre-spec-seed' && git checkout {default}",
        )

    if branch_has_docs_commit(top, branch, doc_rels):
        head = branch_head_commit(top, branch)
        completion = (
            build_verified_completion(top, branch, head, "already-present")
            if head
            else build_incomplete_completion(branch, reason="missing-branch-head")
        )
        emit(
            {
                "verdict": "pass",
                "action": "spec-seed",
                "branch": branch,
                "docsDir": str(docs_dir.relative_to(top)),
                "scope": scope,
                "note": "already seeded (idempotent no-op)",
                "skipped": True,
                "commit": head,
                "completion": completion,
            }
        )

    if dry_run:
        completion = build_incomplete_completion(
            branch,
            outcome="failed",
            reason="dry-run",
            dry_run=True,
        )
        emit(
            {
                "verdict": "pass",
                "action": "spec-seed",
                "dry_run": True,
                "branch": branch,
                "docsDir": str(docs_dir.relative_to(top)),
                "scope": scope,
                "files": doc_rels,
                "skippedPrivate": skipped_private or [],
                "completion": completion,
            }
        )

    prev = current or default
    base_ref = default
    if git_run(["show-ref", "--verify", f"refs/heads/{branch}"], top, check=False).returncode == 0:
        base_ref = branch

    git_run(["checkout", "-B", branch, base_ref], top)
    git_run(["add", "--"] + doc_rels, top)
    diff_cached = git_run(["diff", "--cached", "--quiet"], top, check=False)
    if diff_cached.returncode == 0:
        if prev and prev != branch:
            git_run(["checkout", prev], top, check=False)
        head = branch_head_commit(top, branch)
        completion = (
            build_verified_completion(top, branch, head, "already-present")
            if head
            else build_incomplete_completion(branch, reason="missing-branch-head")
        )
        emit(
            {
                "verdict": "pass",
                "action": "spec-seed",
                "branch": branch,
                "scope": scope,
                "note": "docs already match branch HEAD (idempotent)",
                "skipped": True,
                "commit": head,
                "completion": completion,
            }
        )

    msg = (
        f"docs: freeze artifact for {slug}"
        if scope == "artifact"
        else f"docs: freeze PRD and tasks for {slug}"
    )
    git_run(["commit", "-m", msg], top)
    head = git_run(["rev-parse", "HEAD"], top).stdout.strip()
    if prev and prev != branch:
        git_run(["checkout", prev], top, check=False)

    completion = build_verified_completion(top, branch, head, "committed")
    emit(
        {
            "verdict": "pass",
            "action": "spec-seed",
            "branch": branch,
            "commit": head,
            "docsDir": str(docs_dir.relative_to(top)),
            "scope": scope,
            "files": doc_rels,
            "skippedPrivate": skipped_private or [],
            "completion": completion,
            **({"targetLock": target_lock} if target_lock else {}),
        }
    )


def _resolve_run_id(args: list[str]) -> str | None:
    import os

    run_id = parse_kv(args, "--run-id") or os.environ.get("SW_DELIVER_RUN_ID")
    return run_id.strip() if run_id else None


def cmd_spec_seed(root: Path, args: list[str]) -> None:
    task_list = parse_kv(args, "--task-list")
    artifact = parse_kv(args, "--artifact")
    if bool(task_list) == bool(artifact):
        fail("exactly one of --task-list or --artifact required")
    dry_run = has_flag(args, "--dry-run")
    run_id = _resolve_run_id(args)
    top = Path.cwd().resolve()
    default = load_trunk_base(top)
    scope = "artifact" if artifact else "task-list"

    # Separate-project issue-store: check *before* resolving the branch, since
    # branch resolution reads the frozen task-list body via run-entry
    # materialize, which is a deliberate no-op under CI/host (R19) — a fixture
    # or CI-only frozen unit would otherwise never resolve and this skip would
    # be unreachable (gap discovered post-Phase-9 CI run).
    if issue_store_separate_project_effective(top):
        current = git_run(["branch", "--show-current"], top, check=False).stdout.strip()
        branch = current if current and current != default else f"{scope}-separate-project-skip"
        emit(
            {
                "verdict": "pass",
                "action": "spec-seed",
                "skipped": True,
                "reason": "separate-project-issue-store",
                "branch": branch,
                "scope": scope,
                "note": (
                    "code-repo doc copy skipped; deliver run-entry materialize supplies "
                    "task content from issue store"
                ),
            }
        )

    single: Path | None = None
    if artifact:
        branch, slug, docs_dir = resolve_target_from_artifact(top, artifact)
        single = (top / artifact).resolve()
    else:
        assert task_list is not None
        branch, slug, docs_dir = resolve_target_branch(top, task_list)

    if branch == default:
        fail(f"refused: spec-seed never targets default branch {default!r}")

    if not run_id:
        fail(
            "spec-seed requires --run-id or SW_DELIVER_RUN_ID",
            exit_code=20,
            halt="target-lock-required",
        )
    from wave_spec_seed_guard import (
        assert_handoff_lock_for_seed,
        assert_target_lock_for_seed,
        is_doc_loop_run_id,
    )

    if is_doc_loop_run_id(run_id):
        try:
            lock_guard = assert_handoff_lock_for_seed(top, branch, run_id)
        except PermissionError as exc:
            message = str(exc)
            halt = (
                "target-lock-conflict"
                if "target-lock-conflict" in message
                else "handoff-lock-required"
            )
            fail(
                message,
                exit_code=20,
                halt=halt,
                targetBranch=branch,
                runId=run_id,
            )
    else:
        try:
            lock_guard = assert_target_lock_for_seed(top, branch, run_id)
        except PermissionError as exc:
            fail(
                str(exc),
                exit_code=20,
                halt="target-lock-required",
                targetBranch=branch,
                runId=run_id,
            )

    from primary_checkout_guard import enforce_guard
    enforce_guard(top, branch)

    candidate_files = docs_paths(docs_dir, top, single=single)
    brainstorm_files = referenced_brainstorm_paths(top, docs_dir)
    assert_no_tracked_private_bodies(top, candidate_files + brainstorm_files, feature_branch=branch)
    public_files, skipped_private = filter_public_docs(top, candidate_files + brainstorm_files)
    doc_files = tracked_paths(top, public_files)
    doc_rels = rel_paths(top, doc_files)
    index_rel = ensure_redacted_index(top)
    if index_rel and index_rel not in doc_rels:
        doc_rels.append(index_rel)
    if not doc_rels:
        fail("no tracked public doc files to seed (private/memory bodies skipped)")

    commit_docs_seed(
        top,
        branch=branch,
        slug=slug,
        docs_dir=docs_dir,
        doc_rels=doc_rels,
        default=default,
        dry_run=dry_run,
        scope=scope,
        skipped_private=skipped_private,
        target_lock=lock_guard,
    )




def cmd_docs_commit(root: Path, args: list[str]) -> None:
    """Commit brainstorm + PRD artifacts on docs/<topic> (R31); separate from feature spec-seed (R32)."""
    topic = parse_kv(args, "--topic")
    if not topic:
        fail("docs-commit requires --topic")
    dry_run = has_flag(args, "--dry-run")
    top = git_toplevel(root)
    default = load_trunk_base(top)
    branch = docs_branch_for_topic(topic)
    try:
        refuse_default_branch(branch, default)
    except ValueError as exc:
        fail(str(exc))

    doc_files = tracked_paths(top, docs_paths_all(top, topic))
    doc_rels = rel_paths(top, doc_files)
    if not doc_rels:
        fail("no tracked doc files for topic (brainstorms/prds)")

    commit_docs_seed(
        top,
        branch=branch,
        slug=topic,
        docs_dir=top / "docs",
        doc_rels=doc_rels,
        default=default,
        dry_run=dry_run,
        scope="docs-commit",
    )


def cmd_post_freeze_durability(root: Path, args: list[str]) -> None:
    """Eager spec-seed onto integration branch — no deliver-loop wait (R48 GAP-016)."""
    task_list = parse_kv(args, "--task-list")
    integration = parse_kv(args, "--integration-branch")
    if not task_list or not integration:
        fail("--task-list and --integration-branch required")
    dry_run = has_flag(args, "--dry-run")
    top = git_toplevel(root)
    default = load_trunk_base(top)
    if integration == default:
        fail(f"refused: post-freeze durability never targets default branch {default!r}")
    _branch, slug, docs_dir = resolve_target_branch(top, task_list)
    candidate_files = docs_paths(docs_dir, top, single=None)
    assert_no_tracked_private_bodies(top, candidate_files, feature_branch=integration)
    public_files, skipped_private = filter_public_docs(top, candidate_files)
    doc_files = tracked_paths(top, public_files)
    doc_rels = rel_paths(top, doc_files)
    index_rel = ensure_redacted_index(top)
    if index_rel and index_rel not in doc_rels:
        doc_rels.append(index_rel)
    if not doc_rels:
        fail("no tracked public doc files for post-freeze durability")
    commit_docs_seed(
        top,
        branch=integration,
        slug=slug,
        docs_dir=docs_dir,
        doc_rels=doc_rels,
        default=default,
        dry_run=dry_run,
        scope="post-freeze-durability",
        skipped_private=skipped_private,
    )


def main() -> None:
    if len(sys.argv) < 2:
        fail("usage: wave_spec_seed.py <root> {spec-seed|docs-commit|post-freeze-durability} ...")
    root = Path(sys.argv[1])
    cmd = sys.argv[2] if len(sys.argv) > 2 else "spec-seed"
    args = sys.argv[3:]
    if cmd == "spec-seed":
        cmd_spec_seed(root, args)
    elif cmd == "docs-commit":
        cmd_docs_commit(root, args)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
