#!/usr/bin/env python3
"""Dual-run legacy fixture suites vs pytest ports per migration wave (PRD 054 TR14)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

MIGRATION_WAVES_REL = Path("core/sw-reference/migration-waves.json")
RUN_PYTEST = Path("scripts/test/run_pytest.py")


def repo_root(start: Path | None = None) -> Path:
    start = start or SCRIPT_DIR
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists():
            return candidate
    return cur


def load_wave_inventory(root: Path, wave: str) -> list[dict[str, Any]]:
    path = root / MIGRATION_WAVES_REL
    data = json.loads(path.read_text(encoding="utf-8"))
    suites = (data.get("waves") or {}).get(wave, {}).get("suites") or []
    if not suites:
        raise ValueError(f"migration wave {wave!r} has no suites in {path}")
    return suites


def _sw_env(root: Path, base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    env["ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        p
        for p in (
            str(root / "scripts" / "test"),
            str(root / "scripts"),
            env.get("PYTHONPATH", ""),
        )
        if p
    )
    return env


def run_legacy(root: Path, legacy_rel: str, env: dict[str, str]) -> int:
    script = root / legacy_rel
    if not script.is_file():
        return 127
    if legacy_rel.endswith(".test"):
        completed = subprocess.run(
            ["bash", str(script)],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
        )
    else:
        completed = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
        )
    return completed.returncode


def pytest_target(root: Path, suite: dict[str, Any]) -> str:
    """Prefer per-suite test module over package directory (avoids shared-path bleed)."""
    legacy_base = str(suite.get("legacyBasename") or "")
    pytest_path = str(suite.get("pytestPath") or "")
    if legacy_base.startswith("run_") and legacy_base.endswith("_fixtures.py"):
        stem = legacy_base[len("run_") : -len("_fixtures.py")]
        module = root / pytest_path / f"test_{stem}.py"
        if module.is_file():
            return str(module.relative_to(root))
    return pytest_path


def run_pytest_path(root: Path, pytest_path: str, env: dict[str, str]) -> int:
    runner = root / RUN_PYTEST
    completed = subprocess.run(
        [sys.executable, str(runner), pytest_path, "-q"],
        cwd=str(root),
        env=env,
        capture_output=True,
        text=True,
    )
    return completed.returncode


def run_wave_parity(
    root: Path,
    wave: str,
    *,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Return human-readable failure messages; empty list means green."""
    root = root.resolve()
    env = _sw_env(root, env)
    failures: list[str] = []
    for suite in load_wave_inventory(root, wave):
        suite_id = str(suite.get("id") or "")
        legacy = str(suite.get("legacy") or "")
        if not legacy:
            failures.append(f"{suite_id}: missing legacy")
            continue
        pytest_path = pytest_target(root, suite)
        legacy_rc = run_legacy(root, legacy, env)
        pytest_rc = run_pytest_path(root, pytest_path, env)
        legacy_path = root / legacy
        if not legacy_path.is_file():
            if pytest_rc != 0:
                failures.append(f"{suite_id}: pytest {pytest_path} exit {pytest_rc} (legacy already removed)")
            continue
        if legacy_rc != pytest_rc:
            failures.append(
                f"{suite_id}: exit mismatch legacy={legacy_rc} pytest={pytest_rc} "
                f"({legacy} vs {pytest_path})"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if len(args) != 1 or args[0] not in {"W1", "W2", "W3"}:
        print("usage: migration_pytest_parity.py <W1|W2|W3>", file=sys.stderr)
        return 2
    root = repo_root()
    failures = run_wave_parity(root, args[0])
    if failures:
        for msg in failures:
            print(f"FAIL {msg}")
        print(f"SOME {args[0]} migration pytest parity checks FAILED")
        return 1
    print(f"ALL {args[0]} migration pytest parity checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
