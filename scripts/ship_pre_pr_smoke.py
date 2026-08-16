#!/usr/bin/env python3
"""Fail-closed pre-PR scoped pytest smoke (PRD 063 R4)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
TEST_DIR = SCRIPT_DIR / "test"
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

from _sw.cli import run_module_main

_PHASE_ENV_KEYS = frozenset(
    {
        "SW_RUN_DIR",
        "SW_REPO_ROOT",
        "SW_INTEGRATION_BRANCH",
        "SW_TASK_LIST",
    }
)


def _phase_env_keys() -> list[str]:
    return [k for k in os.environ if k.startswith("SW_PHASE") or k in _PHASE_ENV_KEYS]


def _resolve_integration_branch(root: Path) -> str:
    """Prefer durable deliver-state target; harness env is fallback only (R4)."""
    try:
        from wave_phase_pr import integration_branch

        resolved = integration_branch(root)
        if isinstance(resolved, str) and resolved.strip():
            return resolved.strip()
    except Exception:
        pass
    return (os.environ.get("SW_INTEGRATION_BRANCH") or "").strip()


def _seed_changed_paths_from_integration(root: Path) -> None:
    """Prefer integration-branch diff when upstream tracking yields an empty set.

    Phase branches often track themselves (or a tip equal to HEAD), so default
    ``git_changed_paths`` returns [] and phase smoke widens to full unit_tests.
    Seed ``SW_CHANGED_PATHS`` from the deliver-state integration branch (or
    ``SW_INTEGRATION_BRANCH`` harness fallback) before stripping phase-mode env.
    """
    if os.environ.get("SW_CHANGED_PATHS", "").strip():
        return
    integration = _resolve_integration_branch(root)
    if not integration:
        return
    import test_scope as ts

    paths = ts.git_changed_paths(root, integration)
    if paths:
        os.environ["SW_CHANGED_PATHS"] = "\n".join(paths)


def run_pre_pr_smoke(root: Path, *, scope: str = "phase") -> tuple[int, str | None]:
    from _runner import run_pytest_scope

    _seed_changed_paths_from_integration(root)
    saved = {k: os.environ.get(k) for k in _phase_env_keys()}
    try:
        for key in saved:
            os.environ.pop(key, None)
        os.environ["SW_TEST_SCOPE"] = scope
        ec = run_pytest_scope(root, scope=scope)
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
    if ec == 0:
        return 0, None
    return ec, f"pre-pr-smoke:pytest-exit-{ec}"


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    root = Path(args[0]).resolve() if args else Path.cwd().resolve()
    ec, cause = run_pre_pr_smoke(root)
    if ec == 0:
        print(json.dumps({"verdict": "pass", "action": "pre-pr-smoke", "scope": "phase"}))
        return 0
    print(
        json.dumps(
            {
                "verdict": "fail",
                "action": "pre-pr-smoke",
                "halt": "pre-pr-smoke",
                "cause": cause,
                "exitCode": ec,
            }
        ),
        file=sys.stderr,
    )
    return 20


if __name__ == "__main__":
    run_module_main(main)
