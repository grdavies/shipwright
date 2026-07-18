"""Manifest entry.args forwarding fixtures (PRD 073 phase 3)."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


def _load_runner_lib(repo_root: Path):
    path = repo_root / "scripts" / "test" / "_runner_lib.py"
    spec = importlib.util.spec_from_file_location("runner_lib_mod", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["runner_lib_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_runner(repo_root: Path):
    path = repo_root / "scripts" / "test" / "_runner.py"
    spec = importlib.util.spec_from_file_location("test_runner_mod", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["test_runner_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_invoke_suite_main_zero_arg_main(repo_root: Path) -> None:
    runner_lib = _load_runner_lib(repo_root)
    mod = types.ModuleType("zero_arg_suite")

    def main() -> int:
        mod.called_with = None
        return 0

    mod.main = main
    assert runner_lib.invoke_suite_main(mod) == 0
    assert mod.called_with is None


def test_invoke_suite_main_forwards_argv(repo_root: Path) -> None:
    runner_lib = _load_runner_lib(repo_root)
    mod = types.ModuleType("argv_suite")

    def main(argv: list[str]) -> int:
        mod.received = list(argv)
        return 0

    mod.main = main
    forwarded = ["scripts/unit_tests/capability", "-q"]
    assert runner_lib.invoke_suite_main(mod, forwarded) == 0
    assert mod.received == forwarded


def test_run_manifest_forwards_entry_args(
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _load_runner(repo_root)
    captured: list[list[str] | None] = []

    manifest = [
        {
            "id": "scoped-pytest",
            "script": "scripts/test/run_pytest.py",
            "args": ["scripts/unit_tests/capability", "-q"],
        }
    ]

    def fake_manifest(_root: Path):
        return manifest

    def fake_suite(_path, *, suite_args=None, **_kwargs):
        captured.append(list(suite_args or []))
        return 0

    monkeypatch.setattr(runner, "load_manifest", fake_manifest)
    monkeypatch.setattr(runner, "run_suite_module", fake_suite)

    assert runner.run_manifest(repo_root) == 0
    assert captured == [["scripts/unit_tests/capability", "-q"]]


def test_run_pytest_no_default_when_args_present(
    repo_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_pytest_path = repo_root / "scripts" / "test" / "run_pytest.py"
    spec = importlib.util.spec_from_file_location("run_pytest_mod", run_pytest_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_pytest_mod"] = mod
    spec.loader.exec_module(mod)

    observed: list[list[str]] = []

    def fake_pytest_main(args: list[str]) -> int:
        observed.append(list(args))
        return 0

    import pytest as pytest_mod

    monkeypatch.setattr(pytest_mod, "main", fake_pytest_main)

    scoped = ["scripts/unit_tests/capability", "-q"]
    assert mod.run_pytest(scoped, root=repo_root) == 0
    assert observed == [scoped]
    assert "scripts/unit_tests" not in observed[0]
