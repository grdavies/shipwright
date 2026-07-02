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
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import repo_root

SCENARIOS = (
    "wave-merge-no-regression",
    "execute-plan-linear-fallback",
    "execute-plan-contention-serializes-shared-file",
    "execute-dependency-rules-049-phase-2",
    "execute-runtime-expansion-depth-cap",
    "execute-tokenizer-deep-refs",
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


RUNNERS = {
    "wave-merge-no-regression": scenario_wave_merge_no_regression,
    "execute-plan-linear-fallback": scenario_execute_plan_linear_fallback,
    "execute-plan-contention-serializes-shared-file": scenario_execute_plan_contention,
    "execute-dependency-rules-049-phase-2": scenario_execute_dependency_rules_049,
    "execute-runtime-expansion-depth-cap": scenario_execute_runtime_expansion_depth_cap,
    "execute-tokenizer-deep-refs": scenario_execute_tokenizer_deep_refs,
}


def main() -> int:
    root = repo_root(__file__)
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    selected = only if only else list(SCENARIOS)
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
