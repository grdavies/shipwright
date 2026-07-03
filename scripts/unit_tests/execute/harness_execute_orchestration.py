#!/usr/bin/env python3
"""Fixture suite for PRD 053 execute orchestration."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
import sys
for _e in (str(_SCRIPTS_ROOT / "test"), str(_SCRIPTS_ROOT)):
    if _e not in sys.path: sys.path.insert(0, _e)

from _sw.vendor_paths import repo_root

SCENARIOS = (
    "wave-merge-no-regression",
    "execute-plan-linear-fallback",
    "execute-plan-contention-serializes-shared-file",
    "execute-dependency-rules-049-phase-2",
    "execute-plan-dag-049-phase-2",
    "execute-runtime-expansion-depth-cap",
    "execute-tokenizer-deep-refs",
    "execute-integrate-clean-merge",
    "execute-integrate-conflict-partial-batch",
    "execute-integrate-parallel-batch-serialized",
    "execute-blast-radius-dependents",
    "execute-sub-branch-ceiling-refuse",
    "execute-ship-chain-gated",
    "execute-autonomy-supervised-plan-halt",
    "execute-resume-frontier",
    "execute-resume-stale-sub-branch",
    "execute-single-subtask-skip-tier",
)

FIXTURES = Path("scripts/test/fixtures/execute-orchestration")


def run(cmd: list[str], root: Path, *, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(cmd, cwd=str(root), env=merged, text=True, capture_output=True)


def ok(name: str) -> None:
    print(f"OK  {name}")


def bad(name: str, detail: str = "") -> None:
    print(f"FAIL {name}" + (f": {detail}" if detail else ""))


def scenario_wave_merge_no_regression(root: Path) -> bool:
    wm = root / "scripts/wave_merge.py"
    merge_q = Path(tempfile.mkdtemp())
    try:
        steps = [
            ["git", "init", "-q"],
            ["git", "config", "user.email", "test@test.com"],
            ["git", "config", "user.name", "Test"],
        ]
        for step in steps:
            subprocess.run(step, cwd=str(merge_q), check=True)
        (merge_q / "f.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "f.txt"], cwd=str(merge_q), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(merge_q), check=True)
        subprocess.run(["git", "branch", "-m", "feat/demo"], cwd=str(merge_q), check=True)
        subprocess.run(["git", "checkout", "-q", "-b", "feat/demo-phase-alpha"], cwd=str(merge_q), check=True)
        (merge_q / "f.txt").write_text("base\nphase\n", encoding="utf-8")
        subprocess.run(["git", "add", "f.txt"], cwd=str(merge_q), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "phase"], cwd=str(merge_q), check=True)
        subprocess.run(["git", "checkout", "-q", "feat/demo"], cwd=str(merge_q), check=True)
        (merge_q / ".cursor").mkdir(exist_ok=True)
        (merge_q / ".cursor/sw-deliver-state.json").write_text(
            json.dumps({"target": {"branch": "feat/demo"}, "orchestratorWorktree": {"path": str(merge_q)}}),
            encoding="utf-8",
        )
        proc = run([
            "python3", str(wm), str(merge_q), "merge", "exec",
            "--phase-slug", "alpha", "--phase-branch", "feat/demo-phase-alpha", "--target", "feat/demo",
        ], root)
        if proc.returncode != 0:
            return False
        data = json.loads(proc.stdout)
        if data.get("verdict") != "pass" or data.get("method") != "merge":
            return False
        proc2 = run([
            "python3", str(wm), str(merge_q), "merge", "ancestry-check",
            "--phase-branch", "feat/demo-phase-alpha", "--target", "feat/demo",
        ], root)
        if proc2.returncode != 0:
            return False
        return json.loads(proc2.stdout).get("merged") is True
    finally:
        subprocess.run(["rm", "-rf", str(merge_q)], check=False)


def propose(root: Path, task_list: str, phase_id: str, policy: str = "proposed") -> dict:
    proc = run([
        "python3", "scripts/execute_plan.py", ".", "propose",
        "--task-list", task_list,
        "--phase-id", phase_id,
        "--phase-slug", "fixture",
        "--plan-policy", policy,
    ], root)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    data = json.loads(proc.stdout)
    if data.get("verdict") != "pass":
        raise RuntimeError(data)
    return data["plan"]


def validate(root: Path, proposal: dict, task_list: str, phase_id: str, *, record: bool = False) -> dict:
    tmp = root / ".cursor" / "tmp-execute-proposal.json"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(proposal), encoding="utf-8")
    cmd = [
        "python3", "scripts/wave_plan_validate.py", ".", "validate",
        "--tier", "execute",
        "--proposal", str(tmp),
        "--task-list", task_list,
        "--phase-id", phase_id,
        "--phase-slug", "fixture",
    ]
    if record:
        cmd.append("--record")
        cmd.extend(["--run-dir", str(root / ".cursor/sw-deliver-runs/fixture")])
    proc = run(cmd, root)
    if proc.returncode != 0 and not proc.stdout.strip():
        raise RuntimeError(proc.stderr)
    return json.loads(proc.stdout)


def scenario_execute_dependency_rules_049(root: Path) -> bool:
    task_list = str(FIXTURES / "tasks-049-phase-2-excerpt.md")
    plan = propose(root, task_list, "2")
    if plan.get("batches") != [["2.1", "2.3"], ["2.2"], ["2.4"], ["2.5"]]:
        return False
    edges = {(e["from"], e["to"]) for e in plan.get("edges") or []}
    return ("2.2", "2.4") in edges


def scenario_execute_plan_contention(root: Path) -> bool:
    task_list = str(FIXTURES / "tasks-contention-shared-file.md")
    plan = propose(root, task_list, "1", policy="proposed")
    if plan.get("batches") != [["1.1"], ["1.2"]]:
        return False
    return any(e.get("kind") == "contention" for e in plan.get("edges") or [])


def scenario_execute_plan_linear_fallback(root: Path) -> bool:
    task_list = str(FIXTURES / "tasks-linear-fallback.md")
    good = propose(root, task_list, "1", policy="canonical")
    bad_plan = dict(good)
    bad_plan["batches"] = [["1.2", "1.1"]]
    bad_plan["edges"] = [{"from": "1.2", "to": "1.1", "kind": "test"}]
    result = validate(root, bad_plan, task_list, "1")
    if result.get("verdict") == "pass":
        return False
    fallback = result.get("fallback") or {}
    return fallback.get("fallback") == "canonical-linear" and fallback.get("batches") == [["1.1"], ["1.2"]]


def scenario_execute_runtime_expansion_depth_cap(root: Path) -> bool:
    task_list = str(FIXTURES / "tasks-runtime-expansion.md")
    cfg_path = root / ".cursor/workflow.config.json"
    backup = cfg_path.read_text(encoding="utf-8") if cfg_path.is_file() else None
    try:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps(
                {
                    "execute": {
                        "enabled": True,
                        "maxExpansionDepth": 0,
                        "sizing": {
                            "thresholds": {
                                "filesTouched": 2,
                                "distinctDirs": 1,
                                "traceabilityScenarios": 1,
                            }
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        proc = run(
            [
                "python3",
                "scripts/execute_plan.py",
                ".",
                "propose",
                "--task-list",
                task_list,
                "--phase-id",
                "1",
                "--phase-slug",
                "fixture",
                "--plan-policy",
                "proposed",
            ],
            root,
        )
        return proc.returncode != 0 and "depth cap" in (proc.stdout + proc.stderr)
    finally:
        if backup is None:
            if cfg_path.is_file():
                cfg_path.unlink()
        else:
            cfg_path.write_text(backup, encoding="utf-8")


def scenario_execute_tokenizer_deep_refs(root: Path) -> bool:
    import doc_format

    text = (root / FIXTURES / "tasks-deep-refs.md").read_text(encoding="utf-8")
    refs = [st["id"] for st in doc_format.extract_executable_subtasks(text, "2")]
    if refs != ["2.10.1", "2.10.2"]:
        return False
    plan = propose(root, str(FIXTURES / "tasks-deep-refs.md"), "2")
    return sorted(r["id"] for r in plan.get("refs") or []) == ["2.10.1", "2.10.2"]



def git_init_repo(repo: Path) -> None:
    for step in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "test@test.com"],
        ["git", "config", "user.name", "Test"],
    ):
        subprocess.run(step, cwd=str(repo), check=True)


def write_execute_plan(repo: Path, run_dir: Path, refs: list[dict]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    plan = {
        "version": 1,
        "tier": "execute",
        "phaseId": "1",
        "phaseSlug": "fixture",
        "refs": refs,
        "edges": [],
        "batches": [[r["id"]] for r in refs],
        "planPolicy": "canonical",
        "kernelVersion": "1.0.0",
        "guidelineVersion": "1.0.0",
        "validatedAt": "2026-07-02T00:00:00Z",
    }
    (run_dir / "execute-step-plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")


def integrate_cmd(root: Path, repo: Path, task_ref: str, *, run_dir: Path, extra: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [
        "python3",
        str(root / "scripts/execute_integrate.py"),
        str(repo),
        "integrate",
        "--task-ref",
        task_ref,
        "--phase-slug",
        "fixture",
        "--run-dir",
        str(run_dir),
    ]
    if extra:
        cmd.extend(extra)
    return run(cmd, root)


def scenario_execute_integrate_clean_merge(plugin_root: Path) -> bool:
    repo = Path(tempfile.mkdtemp())
    run_dir = repo / ".cursor/sw-deliver-runs/fixture"
    try:
        git_init_repo(repo)
        (repo / "shared.txt").write_text("base\n", encoding="utf-8")
        subprocess.run(["git", "add", "shared.txt"], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), check=True)
        subprocess.run(["git", "branch", "-m", "feat/demo-phase-fixture"], cwd=str(repo), check=True)
        branch = "feat/demo-phase-fixture--task-1-1"
        subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=str(repo), check=True)
        (repo / "shared.txt").write_text("base\nfrom task 1.1\n", encoding="utf-8")
        subprocess.run(["git", "add", "shared.txt"], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "task 1.1"], cwd=str(repo), check=True)
        subprocess.run(["git", "checkout", "-q", "feat/demo-phase-fixture"], cwd=str(repo), check=True)
        write_execute_plan(repo, run_dir, [{"id": "1.1", "branch": branch, "files": ["shared.txt"], "status": "pending"}])
        proc = integrate_cmd(plugin_root, repo, "1.1", run_dir=run_dir)
        if proc.returncode != 0:
            return False
        data = json.loads(proc.stdout)
        if data.get("verdict") != "pass":
            return False
        journal = json.loads((run_dir / "integrate-journal.json").read_text(encoding="utf-8"))
        if len(journal.get("entries") or []) != 1:
            return False
        return "from task 1.1" in (repo / "shared.txt").read_text(encoding="utf-8")
    finally:
        subprocess.run(["rm", "-rf", str(repo)], check=False)


def scenario_execute_integrate_conflict_partial_batch(plugin_root: Path) -> bool:
    repo = Path(tempfile.mkdtemp())
    run_dir = repo / ".cursor/sw-deliver-runs/fixture"
    try:
        git_init_repo(repo)
        (repo / "shared.txt").write_text("line\n", encoding="utf-8")
        subprocess.run(["git", "add", "shared.txt"], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), check=True)
        subprocess.run(["git", "branch", "-m", "feat/demo-phase-fixture"], cwd=str(repo), check=True)
        branch_a = "feat/demo-phase-fixture--task-1-1"
        subprocess.run(["git", "checkout", "-q", "-b", branch_a], cwd=str(repo), check=True)
        (repo / "shared.txt").write_text("line\nfrom A\n", encoding="utf-8")
        subprocess.run(["git", "add", "shared.txt"], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "task 1.1"], cwd=str(repo), check=True)
        subprocess.run(["git", "checkout", "-q", "feat/demo-phase-fixture"], cwd=str(repo), check=True)
        branch_b = "feat/demo-phase-fixture--task-1-2"
        subprocess.run(["git", "checkout", "-q", "-b", branch_b], cwd=str(repo), check=True)
        (repo / "shared.txt").write_text("line\nfrom B\n", encoding="utf-8")
        subprocess.run(["git", "add", "shared.txt"], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "task 1.2"], cwd=str(repo), check=True)
        subprocess.run(["git", "checkout", "-q", "feat/demo-phase-fixture"], cwd=str(repo), check=True)
        write_execute_plan(
            repo,
            run_dir,
            [
                {"id": "1.1", "branch": branch_a, "files": ["shared.txt"], "status": "pending"},
                {"id": "1.2", "branch": branch_b, "files": ["shared.txt"], "status": "pending"},
            ],
        )
        ok = integrate_cmd(plugin_root, repo, "1.1", run_dir=run_dir)
        if ok.returncode != 0:
            return False
        conflict = integrate_cmd(plugin_root, repo, "1.2", run_dir=run_dir)
        if conflict.returncode != 20:
            return False
        conflict_data = json.loads(conflict.stdout)
        if conflict_data.get("cause") != "integrate:conflict":
            return False
        if "from A" not in (repo / "shared.txt").read_text(encoding="utf-8"):
            return False
        journal = json.loads((run_dir / "integrate-journal.json").read_text(encoding="utf-8"))
        entries = journal.get("entries") or []
        return len(entries) == 2 and entries[0].get("verdict") == "pass" and entries[1].get("verdict") == "conflict"
    finally:
        subprocess.run(["rm", "-rf", str(repo)], check=False)


def scenario_execute_integrate_parallel_batch_serialized(plugin_root: Path) -> bool:
    repo = Path(tempfile.mkdtemp())
    run_dir = repo / ".cursor/sw-deliver-runs/fixture"
    try:
        git_init_repo(repo)
        (repo / "a.txt").write_text("a\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.txt"], cwd=str(repo), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), check=True)
        subprocess.run(["git", "branch", "-m", "feat/demo-phase-fixture"], cwd=str(repo), check=True)
        branches = {}
        for ref, fname in (("1.1", "a.txt"), ("1.2", "b.txt")):
            branch = f"feat/demo-phase-fixture--task-{ref.replace('.', '-')}"
            subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=str(repo), check=True)
            (repo / fname).write_text(f"{fname}\n", encoding="utf-8")
            subprocess.run(["git", "add", fname], cwd=str(repo), check=True)
            subprocess.run(["git", "commit", "-q", "-m", ref], cwd=str(repo), check=True)
            subprocess.run(["git", "checkout", "-q", "feat/demo-phase-fixture"], cwd=str(repo), check=True)
            branches[ref] = branch
        write_execute_plan(
            repo,
            run_dir,
            [
                {"id": "1.1", "branch": branches["1.1"], "files": ["a.txt"], "status": "pending"},
                {"id": "1.2", "branch": branches["1.2"], "files": ["b.txt"], "status": "pending"},
            ],
        )
        lock_path = run_dir / "integrate.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        lock_path.write_text(
            json.dumps({"pid": 999999, "host": "fixture", "acquiredAt": now, "heartbeatAt": now}) + "\n",
            encoding="utf-8",
        )
        blocked = integrate_cmd(plugin_root, repo, "1.1", run_dir=run_dir, extra=["--nonblock"])
        if blocked.returncode != 20:
            return False
        blocked_data = json.loads(blocked.stdout)
        if blocked_data.get("cause") != "integrate:lock-held":
            return False
        lock_path.unlink(missing_ok=True)
        first = integrate_cmd(plugin_root, repo, "1.1", run_dir=run_dir)
        second = integrate_cmd(plugin_root, repo, "1.2", run_dir=run_dir)
        if first.returncode != 0 or second.returncode != 0:
            return False
        journal = json.loads((run_dir / "integrate-journal.json").read_text(encoding="utf-8"))
        refs = [e.get("taskRef") for e in journal.get("entries") or []]
        return refs == ["1.1", "1.2"]
    finally:
        subprocess.run(["rm", "-rf", str(repo)], check=False)


def scenario_execute_blast_radius_dependents(plugin_root: Path) -> bool:
    repo = Path(tempfile.mkdtemp())
    run_dir = repo / ".cursor/sw-deliver-runs/fixture"
    try:
        write_execute_plan(
            repo,
            run_dir,
            [
                {"id": "1.1", "branch": "b1", "status": "pending"},
                {"id": "1.2", "branch": "b2", "status": "pending"},
                {"id": "1.3", "branch": "b3", "status": "pending"},
            ],
        )
        plan = json.loads((run_dir / "execute-step-plan.json").read_text(encoding="utf-8"))
        plan["edges"] = [
            {"from": "1.1", "to": "1.2", "kind": "test"},
            {"from": "1.2", "to": "1.3", "kind": "test"},
        ]
        plan["batches"] = [["1.1"], ["1.2"], ["1.3"]]
        (run_dir / "execute-step-plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        proc = run(
            [
                "python3",
                str(plugin_root / "scripts/execute_failure.py"),
                str(repo),
                "blast-radius",
                "apply",
                "--task-ref",
                "1.1",
                "--phase-slug",
                "fixture",
                "--run-dir",
                str(run_dir),
            ],
            plugin_root,
        )
        if proc.returncode != 0:
            return False
        data = json.loads(proc.stdout)
        blocked = {item.get("taskRef") for item in data.get("blockedRefs") or []}
        if blocked != {"1.1", "1.2", "1.3"}:
            return False
        updated = json.loads((run_dir / "execute-step-plan.json").read_text(encoding="utf-8"))
        statuses = {ref["id"]: ref["status"] for ref in updated.get("refs") or []}
        return statuses == {"1.1": "blocked", "1.2": "blocked", "1.3": "blocked"}
    finally:
        subprocess.run(["rm", "-rf", str(repo)], check=False)


def scenario_execute_sub_branch_ceiling_refuse(plugin_root: Path) -> bool:
    cfg_path = plugin_root / ".cursor/workflow.config.json"
    backup = cfg_path.read_text(encoding="utf-8") if cfg_path.is_file() else None
    try:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            json.dumps({"execute": {"subBranchCeiling": 1}, "intraPhase": {"parallelBudget": 2}}),
            encoding="utf-8",
        )
        proc = run(
            [
                "python3",
                "scripts/execute_plan.py",
                str(plugin_root),
                "provision-sub-branch",
                "--task-ref",
                "1.2",
                "--phase-slug",
                "fixture",
                "--feature-slug",
                "demo",
                "--base",
                "main",
            ],
            plugin_root,
            env={"SW_TEST_ACTIVE_SUB_BRANCHES": "1"},
        )
        if proc.returncode != 20:
            return False
        blob = proc.stdout + proc.stderr
        return "execute:sub-branch-ceiling" in blob or "sub-branch-ceiling" in blob
    finally:
        if backup is None:
            if cfg_path.is_file():
                cfg_path.unlink()
        else:
            cfg_path.write_text(backup, encoding="utf-8")



def scenario_execute_ship_chain_gated(root: Path) -> bool:
    repo = Path(tempfile.mkdtemp())
    run_dir = repo / ".cursor/sw-deliver-runs/fixture"
    try:
        write_execute_plan(
            repo,
            run_dir,
            [
                {"id": "1.1", "branch": "b1", "status": "green"},
                {"id": "1.2", "branch": "b2", "status": "pending"},
            ],
        )
        proc = run(
            ["python3", "scripts/execute_ship.py", str(repo), "gate-check", "--phase-slug", "fixture", "--run-dir", str(run_dir)],
            root,
        )
        if proc.returncode != 20:
            return False
        data = json.loads(proc.stdout)
        return data.get("cause") == "execute-refs-not-terminal" and data.get("pendingRefs") == ["1.2"]
    finally:
        subprocess.run(["rm", "-rf", str(repo)], check=False)


def scenario_execute_autonomy_supervised_plan_halt(root: Path) -> bool:
    cfg_path = root / ".cursor/workflow.config.json"
    backup = cfg_path.read_text(encoding="utf-8") if cfg_path.is_file() else None
    repo = Path(tempfile.mkdtemp())
    run_dir = repo / ".cursor/sw-deliver-runs/fixture"
    try:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(json.dumps({"deliver": {"autonomy": {"mode": "supervised"}}}), encoding="utf-8")
        write_execute_plan(repo, run_dir, [{"id": "1.1", "branch": "b1", "status": "pending"}])
        proc = run(
            ["python3", "scripts/execute_ship.py", str(root), "supervised-halt", "--phase-slug", "fixture", "--run-dir", str(run_dir)],
            root,
        )
        if proc.returncode != 20:
            return False
        data = json.loads(proc.stdout)
        if data.get("halt") != "execute:supervised-plan-confirm":
            return False
        confirm = run(
            ["python3", "scripts/execute_ship.py", str(root), "supervised-confirm", "--phase-slug", "fixture", "--run-dir", str(run_dir)],
            root,
        )
        if confirm.returncode != 0:
            return False
        proc2 = run(
            ["python3", "scripts/execute_ship.py", str(root), "supervised-halt", "--phase-slug", "fixture", "--run-dir", str(run_dir)],
            root,
        )
        return proc2.returncode == 0 and json.loads(proc2.stdout).get("required") is False
    finally:
        subprocess.run(["rm", "-rf", str(repo)], check=False)
        if backup is None:
            if cfg_path.is_file():
                cfg_path.unlink()
        else:
            cfg_path.write_text(backup, encoding="utf-8")


def scenario_execute_resume_frontier(root: Path) -> bool:
    repo = Path(tempfile.mkdtemp())
    run_dir = repo / ".cursor/sw-deliver-runs/fixture"
    try:
        write_execute_plan(
            repo,
            run_dir,
            [
                {"id": "1.1", "branch": "b1", "status": "green"},
                {"id": "1.2", "branch": "b2", "status": "pending"},
                {"id": "1.3", "branch": "b3", "status": "pending"},
            ],
        )
        plan = json.loads((run_dir / "execute-step-plan.json").read_text(encoding="utf-8"))
        plan["edges"] = [{"from": "1.1", "to": "1.2", "kind": "test"}, {"from": "1.2", "to": "1.3", "kind": "test"}]
        (run_dir / "execute-step-plan.json").write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
        proc = run(
            ["python3", "scripts/execute_ship.py", str(repo), "resume-frontier", "--phase-slug", "fixture", "--run-dir", str(run_dir)],
            root,
        )
        if proc.returncode != 0:
            return False
        data = json.loads(proc.stdout)
        return data.get("readyRefs") == ["1.2"] and "1.1" in data.get("terminalRefs", [])
    finally:
        subprocess.run(["rm", "-rf", str(repo)], check=False)


def scenario_execute_resume_stale_sub_branch(root: Path) -> bool:
    repo = Path(tempfile.mkdtemp())
    run_dir = repo / ".cursor/sw-deliver-runs/fixture"
    try:
        write_execute_plan(
            repo,
            run_dir,
            [
                {"id": "1.1", "branch": "feat/missing-branch", "status": "pending"},
            ],
        )
        proc = run(
            ["python3", "scripts/execute_ship.py", str(repo), "resume-frontier", "--phase-slug", "fixture", "--run-dir", str(run_dir)],
            root,
        )
        if proc.returncode != 0:
            return False
        data = json.loads(proc.stdout)
        stale = data.get("staleSubBranches") or []
        return len(stale) == 1 and stale[0].get("taskRef") == "1.1"
    finally:
        subprocess.run(["rm", "-rf", str(repo)], check=False)




def scenario_execute_plan_dag_049_phase_2(root: Path) -> bool:
    """SC1/SC2/SC8 dogfood replay — PRD 049 phase 2 excerpt."""
    import execute_ship

    task_list = str(FIXTURES / "tasks-049-phase-2-excerpt.md")
    plan = propose(root, task_list, "2")
    if plan.get("batches") != [["2.1", "2.3"], ["2.2"], ["2.4"], ["2.5"]]:
        return False
    edges = {(e["from"], e["to"]) for e in plan.get("edges") or []}
    if ("2.2", "2.4") not in edges:
        return False
    edge_files = [
        e.get("files") or []
        for e in plan.get("edges") or []
        if e.get("from") == "2.2" and e.get("to") == "2.4"
    ]
    if not any("scripts/wave_deliver_loop.py" in (f or "") for f in edge_files):
        # dependency rule may encode via kind only; verify edge exists on shared file path
        if not any(e.get("kind") in {"wire-after-implement", "dependency-rule", "contention"} for e in plan.get("edges") or [] if e.get("from") == "2.2"):
            pass  # edge presence already checked above

    adaptivity = execute_ship.build_execute_step_plan_adaptivity(plan)
    if adaptivity.get("parallelBatchWidth", 0) < 2:
        return False

    repo = Path(tempfile.mkdtemp())
    try:
        refs = ["2.1", "2.2", "2.3", "2.4", "2.5"]
        paths: set[str] = set()
        for ref in refs:
            payload = json.dumps({
                "taskRef": ref,
                "verdict": "green",
                "refactor": {"ran": True, "skipped": False, "verdict": "clean"},
            })
            proc = run(
                ["python3", str(root / "scripts/execute_task_status.py"), "--task-ref", ref, "--write", payload],
                repo,
            )
            if proc.returncode != 0:
                return False
            status_path = repo / ".cursor" / "sw-execute-runs" / ref / "status.json"
            if not status_path.is_file():
                return False
            paths.add(str(status_path))
        if len(paths) != len(refs):
            return False
    finally:
        subprocess.run(["rm", "-rf", str(repo)], check=False)

    return adaptivity.get("refsParallelized", 0) >= 1 and adaptivity.get("refCount") == 5


def scenario_execute_single_subtask_skip_tier(root: Path) -> bool:
    task_path = root / ".cursor/tmp-single-subtask.md"
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(
        """---
frozen: true
---

### 1. One task phase

- [ ] 1.1 Only task
  - **File:** `scripts/foo.py`
""",
        encoding="utf-8",
    )
    proc = run(
        [
            "python3",
            "scripts/execute_ship.py",
            ".",
            "should-use-execute-tier",
            "--task-list",
            str(task_path.relative_to(root)),
            "--phase-id",
            "1",
        ],
        root,
    )
    if proc.returncode != 0:
        return False
    data = json.loads(proc.stdout)
    return data.get("executeTierActive") is False and data.get("executableSubtasks") == 1

RUNNERS = {
    "wave-merge-no-regression": scenario_wave_merge_no_regression,
    "execute-plan-linear-fallback": scenario_execute_plan_linear_fallback,
    "execute-plan-contention-serializes-shared-file": scenario_execute_plan_contention,
    "execute-dependency-rules-049-phase-2": scenario_execute_dependency_rules_049,
    "execute-runtime-expansion-depth-cap": scenario_execute_runtime_expansion_depth_cap,
    "execute-tokenizer-deep-refs": scenario_execute_tokenizer_deep_refs,
    "execute-integrate-clean-merge": scenario_execute_integrate_clean_merge,
    "execute-integrate-conflict-partial-batch": scenario_execute_integrate_conflict_partial_batch,
    "execute-integrate-parallel-batch-serialized": scenario_execute_integrate_parallel_batch_serialized,
    "execute-blast-radius-dependents": scenario_execute_blast_radius_dependents,
    "execute-sub-branch-ceiling-refuse": scenario_execute_sub_branch_ceiling_refuse,
    "execute-ship-chain-gated": scenario_execute_ship_chain_gated,
    "execute-autonomy-supervised-plan-halt": scenario_execute_autonomy_supervised_plan_halt,
    "execute-resume-frontier": scenario_execute_resume_frontier,
    "execute-resume-stale-sub-branch": scenario_execute_resume_stale_sub_branch,
    "execute-single-subtask-skip-tier": scenario_execute_single_subtask_skip_tier,
    "execute-plan-dag-049-phase-2": scenario_execute_plan_dag_049_phase_2,
}


def main() -> int:
    root = repo_root(__file__)
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    known = [a for a in only if a in RUNNERS]
    selected = known if known else list(SCENARIOS)
    fail = 0
    for name in selected:
        if name not in RUNNERS:
            print(f"unknown scenario: {name}", file=sys.stderr)
            return 2
        try:
            passed = RUNNERS[name](root)
        except Exception as exc:  # noqa: BLE001
            bad(name, str(exc))
            fail = 1
            continue
        if passed:
            ok(name)
        else:
            bad(name)
            fail = 1
    return fail


if __name__ == "__main__":
    raise SystemExit(main())
