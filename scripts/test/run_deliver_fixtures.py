#!/usr/bin/env python3
"""Deliver terminal INDEX currency fixtures (PRD 055 R10)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _sw.cli import run_module_main
from _sw.vendor_paths import repo_root


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_repo_with_index() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="sw-deliver-fix-"))
    (tmp / "docs" / "prds").mkdir(parents=True)
    (tmp / ".cursor").mkdir()
    (tmp / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"defaultBaseBranch": "main"}), encoding="utf-8"
    )
    prds = tmp / "docs" / "prds"
    (prds / "INDEX.md").write_text(
        "| # | Slug | PRD | Tasks | Status |\n"
        "|---|------|-----|-------|--------|\n"
        "| 055 | workflow-fidelity | [x](x) | [tasks](y) | in-progress |\n",
        encoding="utf-8",
    )
    (prds / "COMPLETION-LOG.md").write_text("# Completion log\n", encoding="utf-8")
    (prds / "GAP-BACKLOG.md").write_text("# Gap backlog\n", encoding="utf-8")
    (tmp / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(tmp, "init", "-q")
    _git(tmp, "config", "user.email", "t@t.com")
    _git(tmp, "config", "user.name", "T")
    _git(tmp, "add", ".")
    _git(tmp, "commit", "-q", "-m", "init")
    _git(tmp, "branch", "-M", "main")
    return tmp


def scenario_inflight_run_complete_refuses_default_branch(root: Path) -> None:
    fix = _init_repo_with_index()
    state = {
        "prd_number": "055",
        "target": {"branch": "feat/fixture"},
        "phases": {"1": {"status": "green-merged"}},
    }
    (fix / ".cursor" / "sw-deliver-state.json").write_text(json.dumps(state), encoding="utf-8")
    scripts = root / "scripts"
    proc = subprocess.run(
        [sys.executable, str(scripts / "inflight_signal.py"), str(fix), "run-complete", "--commit"],
        cwd=str(fix),
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        raise AssertionError("inflight run-complete should refuse on main")
    blob = proc.stdout + proc.stderr
    if "refused" not in blob and "default branch" not in blob:
        raise AssertionError(f"expected refusal, got: {blob}")


def scenario_finalize_completion_index_complete(root: Path) -> None:
    fix = _init_repo_with_index()
    _git(fix, "checkout", "-q", "-b", "feat/orch")
    orch = fix
    state = {
        "prd_number": "055",
        "target": {"branch": "feat/orch"},
        "orchestratorWorktree": {"path": str(orch)},
        "phases": {"1": {"status": "green-merged"}},
        "completion": {"status": "completed-pending-merge"},
        "verdict": "running",
    }
    (fix / ".cursor" / "sw-deliver-state.json").write_text(json.dumps(state), encoding="utf-8")
    (fix / ".cursor" / "sw-deliver-plan.json").write_text("{}", encoding="utf-8")
    # simulate merged target by faking check-merge via completion state + all phases terminal
    scripts = root / "scripts"
    proc = subprocess.run(
        [
            sys.executable,
            str(scripts / "wave_living_docs.py"),
            str(fix),
            "reconcile",
            "--commit",
            "--orchestrator-worktree",
            str(orch),
        ],
        cwd=str(fix),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AssertionError(f"living-docs reconcile failed: {proc.stdout} {proc.stderr}")
    index = (orch / "docs" / "prds" / "INDEX.md").read_text(encoding="utf-8")
    if "| 055 " not in index or "complete" not in index:
        raise AssertionError(f"INDEX not flipped to complete: {index}")
    # verify finalize-completion hook exists in deliver loop
    loop = (root / "scripts" / "wave_deliver_loop.py").read_text(encoding="utf-8")
    if "living-docs reconcile failed during finalize-completion" not in loop:
        raise AssertionError("finalize-completion living-docs hook missing from wave_deliver_loop.py")


def main() -> int:
    root = repo_root(__file__)
    failures: list[str] = []
    scenarios = [
        ("inflight-run-complete-refuses-default-branch", scenario_inflight_run_complete_refuses_default_branch),
        ("finalize-completion-index-complete", scenario_finalize_completion_index_complete),
    ]
    for name, fn in scenarios:
        try:
            fn(root)
            print(f"OK  {name}")
        except Exception as exc:
            print(f"FAIL {name}: {exc}")
            failures.append(name)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run_module_main(main))
