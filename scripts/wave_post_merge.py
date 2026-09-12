#!/usr/bin/env python3
"""Post-merge verify helpers — argv-list pytest invocation (PRD 348 R1/R1a).

``postMergeVerify`` must never space-join pytest paths into a shell string.
Args are always passed as separate argv elements via ``subprocess`` list form.
Shell-string construction (including ``shlex.join``) is intentionally rejected (D1).
"""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
RUN_PYTEST = SCRIPT_DIR / "test" / "run_pytest.py"
RUNNER = SCRIPT_DIR / "test" / "_runner.py"

RunFn = Callable[..., subprocess.CompletedProcess[str]]


def pytest_argv(
    pytest_args: Sequence[str],
    *,
    executable: str | None = None,
) -> list[str]:
    """Build a pytest subprocess argv list — each arg is its own element (R1)."""
    exe = executable or sys.executable
    return [exe, str(RUN_PYTEST), *[str(a) for a in pytest_args]]


def run_pytest_paths(
    root: Path,
    pytest_args: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    run: RunFn | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke pytest with an argv list so space-containing paths stay intact (R1)."""
    runner = run or subprocess.run
    argv = pytest_argv(pytest_args)
    return runner(
        argv,
        cwd=str(cwd or root),
        env=dict(env) if env is not None else None,
        text=True,
        capture_output=True,
        shell=False,
    )


def _scrub_deliver_env(env: dict[str, str]) -> dict[str, str]:
    for polluted in (
        "SW_RUN_DIR",
        "SW_PHASE_SLUG",
        "SW_PHASE_ID",
        "SW_PHASE_MODE",
        "SW_TASK_LIST",
    ):
        env.pop(polluted, None)
    env.setdefault("GIT_HTTP_LOW_SPEED_LIMIT", "1000")
    env.setdefault("GIT_HTTP_LOW_SPEED_TIME", "20")
    env.setdefault("GIT_TERMINAL_PROMPT", "0")
    return env


def _pytest_args_for_scope(root: Path, scope: str) -> list[str]:
    import test_scope as ts

    if scope == "full":
        return ["scripts/unit_tests"]
    changed = ts.resolve_changed_paths(root, None)
    plan = ts.build_plan(changed, scope=scope, root=root)
    args = list(plan.get("pytestArgs") or [])
    return args or ["scripts/unit_tests"]


def run_post_merge_verify(
    root: Path,
    cwd: Path,
    flaky_retries: int = 1,
    *,
    scope: str = "phase",
    harness: Any | None = None,
    run: RunFn | None = None,
) -> dict[str, Any]:
    """Run post-merge verify using argv-list pytest (never bash -c path joins)."""
    from wave_failure import (
        apply_harness_test_switches,
        enrich_verify_result,
        verify_watchdog_max_minutes,
    )

    runner = run or subprocess.run
    attempts = flaky_retries + 1
    last_results: list[dict[str, Any]] = []
    budget_minutes = verify_watchdog_max_minutes(root)
    pytest_args = _pytest_args_for_scope(root, scope)

    for attempt in range(1, attempts + 1):
        last_results = []
        env = {**os.environ, "SW_DELIVER_VERIFY": "1"}
        _scrub_deliver_env(env)
        scripts_path = str(root / "scripts")
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            scripts_path if not existing else os.pathsep.join([scripts_path, existing])
        )
        apply_harness_test_switches(env, harness=harness, scope=scope)
        if budget_minutes is not None:
            env.setdefault("SW_VERIFY_WATCHDOG_MINUTES", str(budget_minutes))

        # R1: pass pytest args as argv elements — never " ".join(paths).
        argv = pytest_argv(pytest_args)
        proc = run_pytest_paths(root, pytest_args, cwd=cwd, env=env, run=runner)
        last_results.append(
            enrich_verify_result(
                {
                    "command": " ".join(argv),
                    "argv": list(argv),
                    "exitCode": proc.returncode,
                    "stdoutTail": (proc.stdout or "")[-500:],
                    "stderrTail": (proc.stderr or "")[-500:],
                }
            )
        )
        ok = proc.returncode == 0

        # Full scope retains manifest coverage via argv-list runner invoke (not bash -c).
        if ok and scope == "full":
            manifest_argv = [sys.executable, str(RUNNER), "run-manifest"]
            manifest_proc = runner(
                manifest_argv,
                cwd=str(cwd),
                env=env,
                text=True,
                capture_output=True,
                shell=False,
            )
            last_results.append(
                enrich_verify_result(
                    {
                        "command": " ".join(manifest_argv),
                        "argv": list(manifest_argv),
                        "exitCode": manifest_proc.returncode,
                        "stdoutTail": (manifest_proc.stdout or "")[-500:],
                        "stderrTail": (manifest_proc.stderr or "")[-500:],
                    }
                )
            )
            ok = manifest_proc.returncode == 0

        if ok:
            return {
                "verdict": "pass",
                "attempts": attempt,
                "flaky": attempt > 1,
                "results": last_results,
                "scope": scope,
                "pytestArgs": list(pytest_args),
            }

    return {
        "verdict": "fail",
        "attempts": attempts,
        "flakyExhausted": True,
        "results": last_results,
        "scope": scope,
        "pytestArgs": list(pytest_args),
    }
