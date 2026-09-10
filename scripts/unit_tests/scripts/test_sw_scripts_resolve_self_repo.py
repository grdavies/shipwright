"""Self-repo resolver integration smoke (PRD 078 phase 10 / PRD 338 R24)."""
from __future__ import annotations

from pathlib import Path

import pytest

from repository_context import (
    POSTURE_CONSUMER,
    POSTURE_PLUGIN_SELF,
    RepositoryContextError,
    detect_repository_posture,
    is_plugin_self_repository,
    resolve_repository_posture,
)
from sw_scripts_resolve import (
    is_shipwright_self_repo,
    resolve_script,
    resolve_scripts_dir,
    scripts_dir_is_trusted,
)


def _seed_heuristic_markers(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "version.txt").write_text("0.0.0-test\n", encoding="utf-8")
    (path / "core" / "sw-reference").mkdir(parents=True)
    scripts = path / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "check-gate.py").write_text("# marker\n", encoding="utf-8")
    (scripts / "resolve-model-tier.py").write_text("# marker\n", encoding="utf-8")


def _seed_sentinel_positive_self_repo(path: Path) -> None:
    _seed_heuristic_markers(path)
    (path / ".shipwright-dev").write_text("# sentinel\n", encoding="utf-8")


def test_sentinel_positive_self_repo(repo_root: Path) -> None:
    assert (repo_root / ".shipwright-dev").is_file()
    verdict = detect_repository_posture(repo_root)
    assert verdict.posture == POSTURE_PLUGIN_SELF
    assert verdict.sentinel_present is True
    assert verdict.heuristic_markers_present is True
    assert is_plugin_self_repository(repo_root)
    assert resolve_repository_posture(repo_root) == POSTURE_PLUGIN_SELF
    assert is_shipwright_self_repo(repo_root)


def test_ordinary_consumer_repo(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    verdict = detect_repository_posture(consumer)
    assert verdict.posture == POSTURE_CONSUMER
    assert verdict.sentinel_present is False
    assert verdict.heuristic_markers_present is False
    assert not is_plugin_self_repository(consumer)
    assert not is_shipwright_self_repo(consumer)


def test_consumer_trust_marker_spoof_refused(tmp_path: Path) -> None:
    spoof = tmp_path / "spoof"
    _seed_heuristic_markers(spoof)
    verdict = detect_repository_posture(spoof)
    assert verdict.posture == POSTURE_CONSUMER
    assert verdict.sentinel_present is False
    assert verdict.heuristic_markers_present is True
    assert verdict.reason == "heuristic-markers-without-sentinel"
    assert not is_plugin_self_repository(spoof)
    assert not is_shipwright_self_repo(spoof)


def test_ambiguous_sentinel_without_markers_fails_closed(tmp_path: Path) -> None:
    ambiguous = tmp_path / "ambiguous"
    ambiguous.mkdir()
    (ambiguous / ".shipwright-dev").write_text("# sentinel only\n", encoding="utf-8")
    with pytest.raises(RepositoryContextError, match="ambiguous layout"):
        resolve_repository_posture(ambiguous)
    assert not is_shipwright_self_repo(ambiguous)


def test_self_repo_scripts_dir_precedence(repo_root: Path) -> None:
    result = resolve_scripts_dir(repo_root)
    assert result.error is None
    assert result.source == "self-repo"
    assert result.path == (repo_root / "scripts").resolve()


def test_self_repo_resolve_deliver_entrypoints(repo_root: Path) -> None:
    for name in ("wave_deliver.py", "wave.py", "check-gate.py"):
        resolved = resolve_script(repo_root, name)
        assert resolved.is_file()
        assert resolved.parent.resolve() == (repo_root / "scripts").resolve()


def test_self_repo_detection_and_trust_markers(repo_root: Path) -> None:
    assert is_shipwright_self_repo(repo_root)
    scripts_dir = repo_root / "scripts"
    assert scripts_dir_is_trusted(scripts_dir)
    assert (scripts_dir / "check-gate.py").is_file()
    assert (scripts_dir / "resolve-model-tier.py").is_file()


def test_self_repo_wins_over_env_override(
    repo_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_root = tmp_path / "env-scripts"
    env_root.mkdir(parents=True)
    (env_root / "check-gate.py").write_text("# marker\n", encoding="utf-8")
    (env_root / "resolve-model-tier.py").write_text("# marker\n", encoding="utf-8")
    (env_root / "wave_deliver.py").write_text("# env copy\n", encoding="utf-8")
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(env_root))

    result = resolve_scripts_dir(repo_root)
    assert result.source == "self-repo"
    assert result.path == (repo_root / "scripts").resolve()

    resolved = resolve_script(repo_root, "wave_deliver.py")
    assert resolved.parent.resolve() == (repo_root / "scripts").resolve()


def test_spoofed_markers_do_not_win_over_env_or_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spoof = tmp_path / "spoof"
    _seed_heuristic_markers(spoof)

    env_root = tmp_path / "env-scripts"
    env_root.mkdir(parents=True)
    (env_root / "check-gate.py").write_text("# marker\n", encoding="utf-8")
    (env_root / "resolve-model-tier.py").write_text("# marker\n", encoding="utf-8")
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(env_root))

    result = resolve_scripts_dir(spoof)
    assert result.source == "env"
    assert result.path == env_root.resolve()
