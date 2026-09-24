"""Post-merge verification selects configured consumer commands or argv-list pytest."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from wave_post_merge import pytest_argv, run_post_merge_verify, run_pytest_paths


def test_pytest_argv_keeps_space_paths_as_separate_elements() -> None:
    paths = [
        "scripts/unit_tests/dir with spaces/test_a.py",
        "scripts/unit_tests/other path/test_b.py",
    ]
    argv = pytest_argv(paths)
    assert isinstance(argv, list)
    assert argv[0]
    assert argv[-2] == paths[0]
    assert argv[-1] == paths[1]
    assert f"{paths[0]} {paths[1]}" not in argv


def test_run_pytest_paths_subprocess_receives_argv_list(tmp_path: Path) -> None:
    paths = [
        str(tmp_path / "suite with spaces" / "test_one.py"),
        str(tmp_path / "another path" / "test_two.py"),
    ]
    captured: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs.get("shell") is False
        captured.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    proc = run_pytest_paths(tmp_path, paths, run=fake_run)
    assert proc.returncode == 0
    assert len(captured) == 1
    argv = captured[0]
    assert isinstance(argv, list)
    assert paths[0] in argv
    assert paths[1] in argv
    # Space-joined form must never appear as a single argv element.
    assert f"{paths[0]} {paths[1]}" not in argv
    idx0 = argv.index(paths[0])
    idx1 = argv.index(paths[1])
    assert idx1 == idx0 + 1


def test_run_post_merge_verify_invokes_pytest_with_argv_list(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("wave_post_merge.is_plugin_self_repository", lambda _root: True)
    paths = [
        "scripts/unit_tests/path with space/test_x.py",
        "scripts/unit_tests/second path/test_y.py",
    ]
    captured: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs.get("shell") is False
        captured.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(
        "wave_post_merge._pytest_args_for_scope",
        lambda _root, _scope: paths,
    )
    monkeypatch.setattr(
        "wave_failure.verify_watchdog_max_minutes",
        lambda _root: None,
    )
    monkeypatch.setattr(
        "wave_failure.apply_harness_test_switches",
        lambda env, **_k: env,
    )
    monkeypatch.setattr(
        "wave_failure.enrich_verify_result",
        lambda result: result,
    )

    outcome = run_post_merge_verify(tmp_path, tmp_path, flaky_retries=0, scope="phase", run=fake_run)
    assert outcome["verdict"] == "pass"
    assert captured, "expected a pytest subprocess invocation"
    argv = captured[0]
    assert isinstance(argv, list)
    assert paths[0] in argv
    assert paths[1] in argv
    assert f"{paths[0]} {paths[1]}" not in argv


def test_consumer_post_merge_uses_configured_verify_without_pytest_registry(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("wave_post_merge.is_plugin_self_repository", lambda _root: False)
    config = tmp_path / ".shipwright" / "workflow.config.json"
    config.parent.mkdir()
    config.write_text(
        json.dumps({"verify": {"test": f"{sys.executable} -c 'print(\"consumer verified\")'"}}),
        encoding="utf-8",
    )

    outcome = run_post_merge_verify(tmp_path, tmp_path, flaky_retries=0)

    assert outcome["verdict"] == "pass"
    assert len(outcome["results"]) == 1
    assert "consumer verified" in outcome["results"][0]["stdoutTail"]
    assert "pytestArgs" not in outcome


def test_consumer_scope_does_not_read_shipwright_suite_registry(
    tmp_path: Path, monkeypatch
) -> None:
    from wave_failure import post_merge_verify_scope

    monkeypatch.setattr("repository_context.is_plugin_self_repository", lambda _root: False)
    monkeypatch.setattr(
        "test_scope.resolve_changed_paths",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected suite registry")),
    )

    assert post_merge_verify_scope(tmp_path) == "phase"


def test_consumer_post_merge_fails_when_verify_is_unconfigured(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("wave_post_merge.is_plugin_self_repository", lambda _root: False)

    outcome = run_post_merge_verify(tmp_path, tmp_path, flaky_retries=0)

    assert outcome["verdict"] == "fail"
    assert outcome["note"] == "no verify commands configured"
