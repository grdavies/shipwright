#!/usr/bin/env python3
"""Enumeration and safe cleanup for merged branches, stale worktrees, deliver run-state (R28–R34, R56)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

MergeStatus = Literal["merged", "unmerged", "indeterminate", "gone", "protected"]
TERMINAL_DELIVER_VERDICTS = frozenset({"complete", "blocked", "rejected"})


@dataclass
class Item:
    kind: str
    name: str
    reason: str
    detail: str = ""


@dataclass
class DeliverStateView:
    canonical_root: Path
    state: dict[str, Any]
    stale_roots: list[Path] = field(default_factory=list)


@dataclass
class Report:
    dry_run: bool
    would_remove: list[Item] = field(default_factory=list)
    protected: list[Item] = field(default_factory=list)
    removed: list[Item] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def items(xs: list[Item]) -> list[dict[str, str]]:
            return [{"kind": i.kind, "name": i.name, "reason": i.reason, "detail": i.detail} for i in xs]

        return {
            "dryRun": self.dry_run,
            "wouldRemove": items(self.would_remove),
            "protected": items(self.protected),
            "removed": items(self.removed),
            "errors": self.errors,
        }


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
    )


def git_ok(root: Path, *args: str) -> bool:
    return git(root, *args).returncode == 0


def git_out(root: Path, *args: str) -> str:
    proc = git(root, *args)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def load_default_branch(root: Path) -> str:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
                base = cfg.get("defaultBaseBranch")
                if isinstance(base, str) and base:
                    return base
            except json.JSONDecodeError:
                pass
    for candidate in ("main", "master"):
        if git_ok(root, "rev-parse", "--verify", candidate):
            return candidate
    return "main"


def current_branch(root: Path) -> str:
    proc = git(root, "branch", "--show-current")
    return (proc.stdout or "").strip()


def _read_deliver_state_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _prefer_orchestrator_state(root_state: dict[str, Any], orch_state: dict[str, Any]) -> bool:
    root_verdict = str(root_state.get("verdict", ""))
    orch_verdict = str(orch_state.get("verdict", ""))
    if root_verdict == "running" and orch_verdict in TERMINAL_DELIVER_VERDICTS:
        return True
    if orch_verdict == "running" and root_verdict in TERMINAL_DELIVER_VERDICTS:
        return False
    root_at = str(root_state.get("updatedAt", ""))
    orch_at = str(orch_state.get("updatedAt", ""))
    if orch_at > root_at:
        return True
    if root_at > orch_at:
        return False
    if orch_state.get("phases") and not root_state.get("phases"):
        return True
    return bool(orch_state) and bool(orch_verdict)


def resolve_deliver_state(repo_root: Path) -> DeliverStateView:
    """Canonical deliver state lives at repo-root scoped path only (PRD 013 R28)."""
    from wave_state import _read_state_optional, enumerate_scoped_runs, resolve_state_path

    repo_root = repo_root.resolve()
    stale_roots: list[Path] = []

    state_path = resolve_state_path(repo_root)
    state = _read_state_optional(state_path)
    if not state:
        runs = enumerate_scoped_runs(repo_root)
        for run in runs:
            if run.get("verdict") == "running":
                candidate = repo_root / run["statePath"]
                state = _read_state_optional(candidate)
                if state:
                    state_path = candidate
                    break

    orch_state: dict[str, Any] = {}
    orch_root: Path | None = None
    orch_raw = (state.get("orchestratorWorktree") or {}).get("path")
    if isinstance(orch_raw, str) and orch_raw.strip():
        orch_root = Path(orch_raw).resolve()
        if orch_root != repo_root and (orch_root / ".cursor").is_dir():
            for path in sorted((orch_root / ".cursor").glob("sw-deliver-state*.json")):
                candidate = _read_state_optional(path)
                if candidate:
                    orch_state = candidate
                    break

    if orch_state and _prefer_orchestrator_state(state, orch_state):
        if state:
            stale_roots.append(repo_root)
        state = orch_state
    elif orch_state and orch_root is not None:
        stale_roots.append(orch_root)

    return DeliverStateView(canonical_root=repo_root, state=state, stale_roots=stale_roots)


def load_deliver_state(root: Path) -> dict[str, Any]:
    return resolve_deliver_state(root).state


def rel_to_repo(repo_root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        return str(path.resolve())


def _collect_terminal_run_state(
    report: Report,
    repo_root: Path,
    state_root: Path,
    tag: str,
) -> None:
    cursor = state_root / ".cursor"
    for state_file in sorted(cursor.glob("sw-deliver-state*.json")):
        report.would_remove.append(
            Item("run-state", rel_to_repo(repo_root, state_file), tag, "terminal deliver run")
        )
    plan_file = cursor / "sw-deliver-plan.json"
    if plan_file.is_file():
        report.would_remove.append(
            Item("run-state", rel_to_repo(repo_root, plan_file), tag, "terminal deliver run")
        )
    runs_dir = cursor / "sw-deliver-runs"
    if runs_dir.is_dir():
        report.would_remove.append(
            Item("run-state", rel_to_repo(repo_root, runs_dir), tag, "terminal deliver run")
        )


def deliver_inflight(repo_root: Path) -> tuple[bool, str]:
    from wave_state import enumerate_scoped_runs

    view = resolve_deliver_state(repo_root)
    for run in enumerate_scoped_runs(repo_root):
        if run.get("lockHeld"):
            return True, f"deliver lock present ({run.get('slug')})"
    verdict = str(view.state.get("verdict", ""))
    if verdict == "running":
        if view.state.get("mergeJournal"):
            return True, "open merge journal"
        return True, "deliver run verdict=running"
    return False, ""


def gh_merged(root: Path, branch: str, default: str) -> bool | None:
    if not git_ok(root, "rev-parse", "--verify", "HEAD"):
        return None
    proc = subprocess.run(
        ["gh", "pr", "list", "--head", branch, "--state", "merged", "--json", "number", "--limit", "1"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout or "[]")
        if isinstance(data, list) and data:
            return True
    except json.JSONDecodeError:
        return None
    proc2 = subprocess.run(
        ["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number", "--limit", "1"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc2.returncode == 0:
        try:
            open_prs = json.loads(proc2.stdout or "[]")
            if isinstance(open_prs, list) and open_prs:
                return False
        except json.JSONDecodeError:
            pass
    return None


def merged_status(root: Path, branch: str, default: str, current: str) -> tuple[MergeStatus, str]:
    if branch in (default, current):
        return "protected", "default or current branch"
    if not git_ok(root, "rev-parse", "--verify", branch):
        return "gone", "branch ref missing"

    if git_ok(root, "merge-base", "--is-ancestor", branch, default):
        return "merged", "ancestor-of-default"

    try:
        diff = git_out(root, "log", f"{default}..{branch}", "--oneline")
    except RuntimeError:
        diff = ""
    if not diff.strip():
        return "merged", "no-commits-ahead-of-default"

    try:
        cherry = git_out(root, "cherry", default, branch)
    except RuntimeError:
        cherry = ""
    plus = [ln for ln in cherry.splitlines() if ln.startswith("+")]
    minus_only = cherry.strip() and not plus
    if minus_only:
        return "merged", "squash-cherry"

    host = gh_merged(root, branch, default)
    if host is True:
        return "merged", "host-merged"
    if host is False:
        return "unmerged", "host-open-pr"

    if plus:
        return "unmerged", "cherry-plus"

    return "indeterminate", "squash-merge-indeterminate"


def list_local_branches(root: Path) -> list[str]:
    proc = git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
    if proc.returncode != 0:
        return []
    return [b.strip() for b in proc.stdout.splitlines() if b.strip()]


def list_remote_branches(root: Path) -> list[str]:
    proc = git(root, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin/")
    if proc.returncode != 0:
        return []
    out: list[str] = []
    for b in proc.stdout.splitlines():
        b = b.strip()
        if not b or b.endswith("/HEAD") or b == "origin/HEAD":
            continue
        out.append(b)
    return out


def parse_worktrees(root: Path) -> list[dict[str, str]]:
    proc = git(root, "worktree", "list", "--porcelain")
    if proc.returncode != 0:
        return []
    entries: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                entries.append(current)
            current = {"path": line.split(" ", 1)[1].strip()}
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1].strip().removeprefix("refs/heads/")
        elif line == "bare":
            current["bare"] = "true"
        elif line == "detached":
            current["detached"] = "true"
    if current:
        entries.append(current)
    top = str(root.resolve())
    return [e for e in entries if e.get("path") and e["path"] != top]


def enumerate_cleanup(root: Path) -> Report:
    report = Report(dry_run=True)
    default = load_default_branch(root)
    current = current_branch(root)
    deliver_view = resolve_deliver_state(root)
    inflight, inflight_reason = deliver_inflight(root)

    for branch in list_local_branches(root):
        status, detail = merged_status(root, branch, default, current)
        if status == "protected":
            report.protected.append(Item("branch", branch, status, detail))
        elif status == "merged":
            report.would_remove.append(Item("branch", branch, status, detail))
        elif status == "unmerged":
            report.protected.append(Item("branch", branch, status, detail))
        else:
            report.protected.append(Item("branch", branch, status, detail))

    for remote in list_remote_branches(root):
        if remote == "origin" or "/" not in remote.removeprefix("origin"):
            continue
        short = remote.removeprefix("origin/")
        if short in (default, current):
            report.protected.append(Item("remote", remote, "protected", "default or current"))
            continue
        local_status, detail = merged_status(root, short, default, current)
        if local_status == "merged":
            report.would_remove.append(Item("remote", remote, "merged-local", detail))
        elif local_status == "unmerged":
            report.protected.append(Item("remote", remote, "unmerged", detail))
        else:
            report.protected.append(
                Item("remote", remote, "indeterminate", "remote deletion guarded — " + detail)
            )

    main_path = str(root.resolve())
    for wt in parse_worktrees(root):
        path = wt.get("path", "")
        branch = wt.get("branch", "")
        if path == main_path:
            report.protected.append(Item("worktree", path, "protected", "primary checkout"))
            continue
        if os.getcwd() == path:
            report.protected.append(Item("worktree", path, "protected", "active cwd"))
            continue
        orch = (deliver_view.state.get("orchestratorWorktree") or {}).get("path")
        if orch and path == orch and inflight:
            report.protected.append(Item("worktree", path, "protected", inflight_reason))
            continue
        if branch:
            st, detail = merged_status(root, branch, default, current)
            if st == "merged" or st == "gone":
                report.would_remove.append(Item("worktree", path, st, branch + ": " + detail))
            elif st == "unmerged":
                report.protected.append(Item("worktree", path, st, branch + ": " + detail))
            else:
                report.protected.append(Item("worktree", path, st, branch + ": " + detail))
        else:
            report.would_remove.append(Item("worktree", path, "detached-stale", "no branch"))

    from wave_state import resolve_state_path

    if inflight:
        state_rel = rel_to_repo(root, resolve_state_path(root, state_hint=deliver_view.state))
        report.protected.append(Item("run-state", state_rel, "protected", inflight_reason))
    elif deliver_view.state:
        verdict = str(deliver_view.state.get("verdict", ""))
        if verdict in TERMINAL_DELIVER_VERDICTS:
            _collect_terminal_run_state(report, root, deliver_view.canonical_root, verdict)
            for stale_root in deliver_view.stale_roots:
                _collect_terminal_run_state(report, root, stale_root, "stale-copy")
        elif verdict:
            state_rel = rel_to_repo(root, resolve_state_path(root, state_hint=deliver_view.state))
            report.protected.append(Item("run-state", state_rel, "protected", verdict))

    return report


def apply_report(root: Path, report: Report) -> Report:
    report.dry_run = False
    for item in list(report.would_remove):
        try:
            if item.kind == "branch":
                proc = git(root, "branch", "-D", item.name)
                if proc.returncode != 0:
                    report.errors.append(f"branch {item.name}: {proc.stderr.strip()}")
                    continue
                report.removed.append(item)
            elif item.kind == "remote":
                ref = item.name
                proc = git(root, "push", "origin", "--delete", ref.removeprefix("origin/"))
                if proc.returncode != 0:
                    report.errors.append(f"remote {item.name}: {proc.stderr.strip()}")
                    continue
                report.removed.append(item)
            elif item.kind == "worktree":
                proc = git(root, "worktree", "remove", item.name, "--force")
                if proc.returncode != 0:
                    report.errors.append(f"worktree {item.name}: {proc.stderr.strip()}")
                    continue
                git(root, "worktree", "prune")
                report.removed.append(item)
            elif item.kind == "run-state":
                path = root / item.name
                if path.is_dir():
                    for child in sorted(path.rglob("*"), reverse=True):
                        if child.is_file():
                            child.unlink(missing_ok=True)
                    for child in sorted(path.rglob("*"), reverse=True):
                        if child.is_dir():
                            child.rmdir()
                    path.rmdir()
                elif path.is_file():
                    path.unlink(missing_ok=True)
                report.removed.append(item)
        except OSError as exc:
            report.errors.append(f"{item.kind} {item.name}: {exc}")
    report.would_remove = []
    return report


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    confirm = "--confirm" in sys.argv
    report = enumerate_cleanup(root)
    if confirm:
        if "--yes" not in sys.argv and os.environ.get("SW_CLEANUP_CONFIRM") != "1":
            report.dry_run = True
            print(
                json.dumps(
                    {
                        "verdict": "fail",
                        "error": "confirm requires --yes or SW_CLEANUP_CONFIRM=1",
                        "report": report.to_dict(),
                    },
                    indent=2,
                )
            )
            sys.exit(2)
        report = apply_report(root, report)
    else:
        report.dry_run = True
    out = {"verdict": "pass", "action": "cleanup", "report": report.to_dict()}
    print(json.dumps(out, indent=2))
    sys.exit(1 if report.errors else 0)


if __name__ == "__main__":
    main()
