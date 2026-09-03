#!/usr/bin/env python3
"""Enumeration and safe cleanup for merged branches, stale worktrees, deliver run-state (R28–R34, R56).

Orphan worktrees (PRD 095): directories under ``.sw-worktrees/`` absent from ``git worktree list``.

- ``enumerate_orphan_worktrees(root)`` — direct children only; skips symlinks and registered paths;
  surfaces ``volume_inaccessible`` on ``OSError`` from ``iterdir``.
- ``_classify_orphan(path)`` — evaluation order **ghost → park → husk**:
  ghost (no ``.git``), park (name matches ``r'\\.park-\\d+$'``), husk (``.git`` present, unregistered).
- Report kind ``orphan-worktree`` — listed in dry-run ``would_remove``; apply uses leaves-first
  ``os.scandir`` walk (never shell-recursive delete or ``shutil.rmtree``); park-class always
  requires confirm (SC6).
"""
from __future__ import annotations

import json
import os
import re
import subprocess

from host_invoke import host_verb
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import load_workflow_config, remote_name, remote_ref

import planning_ledger_store as pls
import planning_refusal_ledger as prl


def host_remote_name(root: Path) -> str:
    return remote_name(load_workflow_config(root))

MergeStatus = Literal["merged", "unmerged", "indeterminate", "gone", "protected"]
TERMINAL_DELIVER_VERDICTS = frozenset({"complete", "rejected"})
RESUMABLE_DELIVER_VERDICTS = frozenset({"running", "blocked", "halted", "watching"})


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
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def items(xs: list[Item]) -> list[dict[str, str]]:
            return [{"kind": i.kind, "name": i.name, "reason": i.reason, "detail": i.detail} for i in xs]

        return {
            "dryRun": self.dry_run,
            "wouldRemove": items(self.would_remove),
            "protected": items(self.protected),
            "removed": items(self.removed),
            "errors": self.errors,
            "notes": self.notes,
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
    from host_lib import default_base_branch

    base = default_base_branch(root)
    if base != "main" or git_ok(root, "rev-parse", "--verify", base):
        return base
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
    from wave_state import (
        _is_migration_breadcrumb,
        _read_state_optional,
        _run_scoped_path_from_breadcrumb,
        enumerate_scoped_runs,
        resolve_state_path,
    )

    repo_root = repo_root.resolve()
    stale_roots: list[Path] = []

    state_path = resolve_state_path(repo_root)
    state = _read_state_optional(state_path)
    if state and _is_migration_breadcrumb(state):
        followed = _run_scoped_path_from_breadcrumb(repo_root, state)
        if followed:
            followed_state = _read_state_optional(followed)
            if followed_state:
                state_path = followed
                state = followed_state
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


def load_workflow_config(root: Path) -> dict[str, Any]:
    from shipwright_paths import load_workflow_config as _load_workflow_config

    return _load_workflow_config(root)
def cleanup_autonomy_mode(root: Path) -> str:
    cfg = load_workflow_config(root)
    cleanup = cfg.get("cleanup") or {}
    mode = cleanup.get("autonomy", "confirm")
    return mode if mode in ("confirm", "auto") else "confirm"


def has_indeterminate_protected(report: Report) -> bool:
    return any(item.reason == "indeterminate" for item in report.protected)


def can_autonomous_apply(root: Path, report: Report) -> tuple[bool, str]:
    if cleanup_autonomy_mode(root) != "auto":
        return False, "cleanup.autonomy is confirm (default)"
    inflight, reason = deliver_inflight(root)
    if inflight:
        return False, reason
    if has_indeterminate_protected(report):
        return False, "indeterminate merge status — human gate required"
    default = load_default_branch(root)
    current = current_branch(root)
    for item in report.would_remove:
        if item.kind == "branch" and item.name in (current, default):
            return False, f"would remove protected branch {item.name}"
    for item in report.would_remove:
        if item.kind == "orphan-worktree" and item.reason == "park":
            return False, f"park-class orphan {item.name!r} requires operator confirmation (SC6)"
    return True, "ok"


def apply_autonomous_cleanup(root: Path) -> dict[str, Any]:
    report = enumerate_cleanup(root)
    ok, reason = can_autonomous_apply(root, report)
    if not ok:
        return {
            "verdict": "halt",
            "action": "cleanup-autonomous-apply",
            "reason": reason,
            "report": report.to_dict(),
        }
    applied = apply_report(root, report)
    return {
        "verdict": "pass",
        "action": "cleanup-autonomous-apply",
        "report": applied.to_dict(),
    }


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
    from wave_run_paths import runs_root

    runs_base = runs_root(state_root)
    if runs_base.is_dir():
        for child in sorted(runs_base.iterdir()):
            if child.is_dir() and child.name.startswith("deliver-"):
                report.would_remove.append(
                    Item("run-state", rel_to_repo(repo_root, child), tag, "terminal deliver run")
                )

    cursor = state_root / ".cursor"
    for state_file in sorted(cursor.glob("sw-deliver-state*.json")):
        report.would_remove.append(
            Item("run-state", rel_to_repo(repo_root, state_file), tag, "terminal deliver run")
        )


def _stale_state_rel_paths(view: DeliverStateView, repo_root: Path) -> set[str]:
    rels: set[str] = set()
    for stale_root in view.stale_roots:
        cursor = stale_root / ".cursor"
        if not cursor.is_dir():
            continue
        for path in cursor.glob("sw-deliver-state*.json"):
            rels.add(rel_to_repo(repo_root, path))
    return rels


def _all_deliver_runs(repo_root: Path) -> list[dict[str, Any]]:
    from wave_state import enumerate_run_scoped_dirs, enumerate_scoped_runs

    runs = list(enumerate_run_scoped_dirs(repo_root))
    seen_paths = {str(entry.get("statePath") or "") for entry in runs}
    for entry in enumerate_scoped_runs(repo_root):
        state_path = str(entry.get("statePath") or "")
        if state_path and state_path not in seen_paths:
            runs.append(entry)
    return runs


def _scoped_run_inflight(repo_root: Path, run: dict[str, Any]) -> tuple[bool, str]:
    from wave_state import (
        _is_migration_breadcrumb,
        _read_state_optional,
        _run_scoped_path_from_breadcrumb,
        _scoped_path_from_breadcrumb,
    )

    state_path = repo_root / run["statePath"]
    state = _read_state_optional(state_path)
    label = str(run.get("slug") or run.get("runId") or "unknown")
    if _is_migration_breadcrumb(state):
        followed = _run_scoped_path_from_breadcrumb(repo_root, state) or _scoped_path_from_breadcrumb(
            repo_root, state
        )
        if followed:
            followed_state = _read_state_optional(followed)
            if followed_state and not _is_migration_breadcrumb(followed_state):
                state = followed_state
            elif not followed_state:
                return True, f"migration breadcrumb unresolvable ({label})"
        else:
            bc_target = state.get("target")
            if isinstance(bc_target, str) and _slug_from_target(bc_target):
                return True, f"migration breadcrumb without live state ({label})"
            return True, f"migration breadcrumb unresolvable ({label})"
    if run.get("lockHeld"):
        return True, f"deliver lock present ({label})"
    verdict = str(state.get("verdict") or run.get("verdict") or "")
    if state.get("mergeJournal"):
        return True, f"open merge journal ({label})"
    if verdict in RESUMABLE_DELIVER_VERDICTS:
        return True, f"deliver run verdict={verdict} ({label})"
    return False, ""


def _slug_from_target(target: str) -> str | None:
    if not target or "/" not in target:
        return None
    return target.split("/", 1)[1]


def _active_scope_slugs(repo_root: Path, view: DeliverStateView) -> set[str]:
    from wave_state import _is_migration_breadcrumb, _read_state_optional, legacy_paths, target_branch_from_state

    active: set[str] = set()
    current = current_branch(repo_root)
    if current:
        current_slug = _slug_from_target(current)
        if current_slug:
            active.add(current_slug)
        parent = parent_wave_branch(current)
        if parent:
            parent_slug = _slug_from_target(parent)
            if parent_slug:
                active.add(parent_slug)
    if not active:
        target = target_branch_from_state(view.state)
        if target:
            target_slug = _slug_from_target(target)
            if target_slug:
                active.add(target_slug)
    legacy = legacy_paths(repo_root)["state"]
    if legacy.is_file():
        leg = _read_state_optional(legacy)
        if _is_migration_breadcrumb(leg):
            bc_target = leg.get("target")
            if isinstance(bc_target, str):
                bc_slug = _slug_from_target(bc_target)
                if bc_slug:
                    active.add(bc_slug)
    return active


def _breadcrumb_widens_inflight_scope(repo_root: Path) -> bool:
    from wave_state import _is_migration_breadcrumb, _read_state_optional, legacy_paths, resolve_state_path

    for path in (resolve_state_path(repo_root), legacy_paths(repo_root)["state"]):
        state = _read_state_optional(path)
        if _is_migration_breadcrumb(state):
            return True
    cursor = repo_root / ".cursor"
    if cursor.is_dir():
        for path in cursor.glob("sw-deliver-state.*.json"):
            state = _read_state_optional(path)
            if _is_migration_breadcrumb(state):
                return True
    return False


def _run_slug(run: dict[str, Any]) -> str | None:
    slug = str(run.get("slug") or "").strip()
    if slug and slug != "(legacy)":
        return slug
    run_id = str(run.get("runId") or "").strip()
    if run_id.startswith("legacy-"):
        return run_id.removeprefix("legacy-")
    target = str(run.get("target") or "").strip()
    return _slug_from_target(target)


def _run_in_active_scope(run: dict[str, Any], active_slugs: set[str]) -> bool:
    if not active_slugs:
        return True
    slug = _run_slug(run)
    return bool(slug and slug in active_slugs)


def deliver_inflight(repo_root: Path) -> tuple[bool, str]:
    view = resolve_deliver_state(repo_root)
    stale = _stale_state_rel_paths(view, repo_root)
    active_slugs = _active_scope_slugs(repo_root, view)
    widen = _breadcrumb_widens_inflight_scope(repo_root)
    for run in _all_deliver_runs(repo_root):
        if run.get("statePath") in stale:
            continue
        if not widen and not _run_in_active_scope(run, active_slugs):
            continue
        inflight, reason = _scoped_run_inflight(repo_root, run)
        if inflight:
            return True, reason
    return False, ""


def _run_state_item_protected(repo_root: Path, rel_path: str) -> tuple[bool, str]:
    from wave_state import _read_state_optional

    view = resolve_deliver_state(repo_root)
    stale = _stale_state_rel_paths(view, repo_root)
    if rel_path in stale:
        return False, ""
    for run in _all_deliver_runs(repo_root):
        if run.get("statePath") != rel_path:
            continue
        return _scoped_run_inflight(repo_root, run)
    path = repo_root / rel_path
    state = _read_state_optional(path)
    if not state:
        return False, ""
    verdict = str(state.get("verdict") or "")
    if verdict in RESUMABLE_DELIVER_VERDICTS:
        return True, f"deliver run verdict={verdict}"
    if verdict and verdict not in TERMINAL_DELIVER_VERDICTS:
        return True, f"deliver run verdict={verdict}"
    return False, ""

def _protect_inflight_scoped_runs(report: Report, repo_root: Path) -> None:
    view = resolve_deliver_state(repo_root)
    stale = _stale_state_rel_paths(view, repo_root)
    for run in _all_deliver_runs(repo_root):
        if run.get("statePath") in stale:
            continue
        inflight, reason = _scoped_run_inflight(repo_root, run)
        if inflight:
            report.protected.append(
                Item("run-state", run["statePath"], "protected", reason)
            )


def parent_wave_branch(branch: str) -> str | None:
    """Derive deliver integration branch from a phase branch (feat/foo-phase-bar -> feat/foo)."""
    marker = "-phase-"
    idx = branch.find(marker)
    if idx == -1:
        return None
    parent = branch[:idx]
    if not parent or "/" not in parent:
        return None
    return parent


def host_merged(root: Path, branch: str, default: str) -> bool | None:
    if not git_ok(root, "rev-parse", "--verify", "HEAD"):
        return None
    merged_out = host_verb(root, "pr-list", head=branch, state="closed", limit="5")
    if merged_out.get("verdict") != "ok":
        return None
    merged_items = merged_out.get("data") or []
    if isinstance(merged_items, list):
        for item in merged_items:
            if isinstance(item, dict) and item.get("state") == "MERGED":
                return True
    open_out = host_verb(root, "pr-list", head=branch, state="open", limit="1")
    if open_out.get("verdict") == "ok":
        open_items = open_out.get("data") or []
        if isinstance(open_items, list) and open_items:
            return False
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

    from wave_phase_pr import phase_green_merged_branch
    if phase_green_merged_branch(root, branch):
        return "merged", "phase-green-merged"

    host = host_merged(root, branch, default)
    if host is True:
        return "merged", "host-merged"
    if host is False:
        return "unmerged", "host-open-pr"

    parent = parent_wave_branch(branch)
    if parent and parent not in (default, current):
        parent_host = host_merged(root, parent, default)
        if parent_host is True:
            return "merged", "parent-wave-merged"
        if parent_host is False:
            return "unmerged", "parent-wave-open-pr"

    if plus:
        return "unmerged", "cherry-plus"

    return "indeterminate", "squash-merge-indeterminate"


def list_local_branches(root: Path) -> list[str]:
    proc = git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
    if proc.returncode != 0:
        return []
    return [b.strip() for b in proc.stdout.splitlines() if b.strip()]


def list_remote_branches(root: Path) -> list[str]:
    host_remote = host_remote_name(root)
    proc = git(root, "for-each-ref", "--format=%(refname:short)", f"refs/remotes/{host_remote}/")
    if proc.returncode != 0:
        return []
    out: list[str] = []
    for b in proc.stdout.splitlines():
        b = b.strip()
        if not b or b.endswith("/HEAD") or b == f"{host_remote}/HEAD":
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


_PARK_SUFFIX_RE = re.compile(r"\.park-\d+$")


def _classify_orphan(path: Path) -> str:
    """Classify orphan worktree path: ghost (no .git) → park (.park-N suffix) → husk (.git present)."""
    if not (path / ".git").exists():
        return "ghost"
    if _PARK_SUFFIX_RE.search(path.name):
        return "park"
    return "husk"


def _safe_tree_remove(path: Path) -> None:
    """Leaves-first directory removal with symlink safety. No-op if path is already absent.

    Raises OSError on I/O failure so callers can emit partial_removal_error (R3).
    """
    if not path.exists() and not path.is_symlink():
        return

    def _remove(p: Path) -> None:
        if p.is_symlink():
            os.unlink(p)
            return
        if p.is_dir():
            with os.scandir(p) as it:
                for entry in it:
                    _remove(Path(entry.path))
            p.rmdir()
            return
        os.unlink(p)

    _remove(path)


def enumerate_orphan_worktrees(root: Path) -> list[tuple[Path, str]]:
    """Return (path, classification) for each orphan dir under .sw-worktrees.

    Raises OSError (tagged volume_inaccessible) if .sw-worktrees cannot be listed.
    Skips symlinks, non-dirs, git-registered paths, and adopt-pending paths.
    """
    registered = {Path(wt["path"]).resolve() for wt in parse_worktrees(root)}
    sw_worktrees = root / ".sw-worktrees"
    if not sw_worktrees.is_dir():
        return []

    deliver_view = resolve_deliver_state(root)
    stall_name = str((deliver_view.state or {}).get("_stallWorktreeName") or "")

    try:
        children = list(sw_worktrees.iterdir())
    except OSError:
        raise  # volume_inaccessible — caller must catch and surface

    result: list[tuple[Path, str]] = []
    for child in children:
        if child.is_symlink():
            continue
        if not child.is_dir():
            continue
        if child.resolve() in registered:
            continue
        # skip provisioning-in-progress directories
        if stall_name and child.name == stall_name:
            continue
        if (sw_worktrees / (".sw-provisioning-" + child.name)).exists():
            continue
        result.append((child, _classify_orphan(child)))

    return result


def enumerate_refusal_ledger(report: Report, root: Path) -> None:
    """Enumerate operator-local refusal ledger entries for dry-run cleanup (PRD 082 R26)."""
    cfg = load_workflow_config(root)
    ledger_dir = pls.resolve_ledger_path(root, cfg)
    contract = pls.verify_ledger_path_contract(root, ledger_dir)
    if contract.get("verdict") != "ok":
        if ledger_dir.exists():
            report.protected.append(
                Item(
                    "refusal-ledger",
                    str(ledger_dir.relative_to(root)),
                    "protected",
                    "ledger-path-contract-fail",
                )
            )
        return
    entries = prl.list_refusals(root, cfg)
    if not entries:
        return
    report.notes.append(
        "refusal-ledger entries are purge candidates; reconciling a refused write remains a human decision"
    )
    for entry in entries:
        entry_id = str(entry.get("entryId") or entry.get("idempotencyKey") or "")
        unit_id = str(entry.get("unitId") or "")
        report.would_remove.append(
            Item(
                "refusal-ledger-entry",
                entry_id,
                "ledger-purge",
                f"unit={unit_id}; reconciling refused writes is operator-only",
            )
        )


def enumerate_cleanup(root: Path) -> Report:
    report = Report(dry_run=True)
    host_remote = host_remote_name(root)
    prefix = f"{host_remote}/"
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
        prefix = f"{host_remote}/"
        if remote == host_remote or "/" not in remote.removeprefix(prefix):
            continue
        short = remote.removeprefix(prefix)
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

    # Orphan worktrees: directories under .sw-worktrees absent from git's registered worktree list
    try:
        for orphan_path, classification in enumerate_orphan_worktrees(root):
            report.would_remove.append(
                Item("orphan-worktree", str(orphan_path), classification, f"classification={classification}")
            )
    except OSError as exc:
        report.errors.append(f"orphan-worktree enumeration aborted: volume_inaccessible — {exc}")

    from wave_state import resolve_state_path

    _protect_inflight_scoped_runs(report, root)
    if any(
        item.kind == "run-state"
        and any(
            token in item.detail
            for token in ("verdict=blocked", "verdict=halted", "verdict=watching")
        )
        for item in report.protected
    ):
        report.notes.append(
            "resumable deliver halt detected; preserving run-state hygiene files"
        )
    if inflight:
        state_rel = rel_to_repo(root, resolve_state_path(root, state_hint=deliver_view.state))
        if not any(
            i.kind == "run-state" and i.name == state_rel for i in report.protected
        ):
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

    enumerate_refusal_ledger(report, root)
    return report


_APPLY_KIND_ORDER = {"worktree": 0, "orphan-worktree": 1, "run-state": 2, "refusal-ledger-entry": 3, "remote": 4, "branch": 5}
# PRD 095: orphan-worktree (1) inserted between worktree (0) and run-state (2)


def _apply_sort_key(item: Item) -> tuple[int, str]:
    return (_APPLY_KIND_ORDER.get(item.kind, 99), item.name)


def apply_report(root: Path, report: Report) -> Report:
    report.dry_run = False
    host_remote = host_remote_name(root)
    prefix = f"{host_remote}/"
    for item in sorted(report.would_remove, key=_apply_sort_key):
        try:
            if item.kind == "branch":
                proc = git(root, "branch", "-D", item.name)
                if proc.returncode != 0:
                    report.errors.append(f"branch {item.name}: {proc.stderr.strip()}")
                    continue
                report.removed.append(item)
            elif item.kind == "remote":
                ref = item.name
                proc = git(root, "push", host_remote, "--delete", ref.removeprefix(prefix))
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
            elif item.kind == "orphan-worktree":
                path = Path(item.name)
                # race guard: re-check not in git's registered worktrees at apply time
                registered_now = {Path(wt["path"]).resolve() for wt in parse_worktrees(root)}
                if path.resolve() in registered_now:
                    report.protected.append(
                        Item("orphan-worktree", item.name, "protected", "registered-at-remove-time")
                    )
                    continue
                # provisioning sentinel guard
                sentinel = path.parent / (".sw-provisioning-" + path.name)
                if sentinel.exists():
                    report.protected.append(
                        Item("orphan-worktree", item.name, "protected", "provisioning-in-progress")
                    )
                    continue
                # path accessibility check
                try:
                    path.stat()
                except OSError as exc:
                    report.errors.append(f"orphan-worktree {item.name}: inaccessible — {exc}")
                    continue
                try:
                    _safe_tree_remove(path)
                    if item.reason == "husk":
                        git(root, "worktree", "prune", "--expire", "now")
                    report.removed.append(item)
                except OSError as exc:
                    report.protected.append(
                        Item(
                            "orphan-worktree",
                            item.name,
                            "partial_removal_error",
                            str(exc),
                        )
                    )
                    report.errors.append(f"orphan-worktree {item.name}: {exc}")
            elif item.kind == "run-state":
                protected, inflight_reason = _run_state_item_protected(root, item.name)
                if protected:
                    report.protected.append(
                        Item("run-state", item.name, "protected", inflight_reason)
                    )
                    report.errors.append(
                        f"run-state {item.name}: skipped delete — {inflight_reason}"
                    )
                    continue
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
            elif item.kind == "refusal-ledger-entry":
                cfg = load_workflow_config(root)
                ledger_dir = pls.resolve_ledger_path(root, cfg)
                result = pls.purge_entries(ledger_dir, [item.name], reason="cleanup-purge")
                if result.get("purged"):
                    report.removed.append(item)
                else:
                    report.errors.append(f"refusal-ledger-entry {item.name}: not found")
        except OSError as exc:
            report.errors.append(f"{item.kind} {item.name}: {exc}")
    report.would_remove = []
    return report


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    confirm = "--confirm" in sys.argv
    autonomous = "--autonomous" in sys.argv
    if autonomous:
        out = apply_autonomous_cleanup(root)
        print(json.dumps(out, indent=2))
        sys.exit(0 if out.get("verdict") == "pass" else 11)
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
