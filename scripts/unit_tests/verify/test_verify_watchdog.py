"""verify-watchdog-exhaustion fixture (PRD 055 R31)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_runner(repo_root: Path):
    path = repo_root / "scripts" / "test" / "_runner.py"
    spec = importlib.util.spec_from_file_location("test_runner_mod", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["test_runner_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_verify_watchdog_exhaustion_halts_with_resume(
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runner = _load_runner(repo_root)
    monkeypatch.setenv("SW_VERIFY_WATCHDOG_MINUTES", "0.001")

    manifest = [
        {"id": "slow-suite-a", "script": "scripts/test/run_pytest.py"},
        {"id": "slow-suite-b", "script": "scripts/test/run_pytest.py"},
    ]

    def fake_manifest(_root: Path):
        return manifest

    def slow_suite(*_args, **_kwargs):
        import time

        time.sleep(0.2)
        return 0

    monkeypatch.setattr(runner, "load_manifest", fake_manifest)
    monkeypatch.setattr(runner, "run_suite_module", slow_suite)

    halt_path = repo_root / ".cursor" / "sw-verify-watchdog-halt.json"
    if halt_path.is_file():
        halt_path.unlink()

    code = runner.run_manifest(repo_root)
    assert code == 1
    assert halt_path.is_file()
    report = json.loads(halt_path.read_text(encoding="utf-8"))
    assert report.get("halt") == "verify-watchdog-exhausted"
    assert report.get("lastSuiteId")
    assert report.get("resumeCommand")
