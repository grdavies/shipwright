"""Self-repo resolver integration smoke (PRD 078 phase 10 / TR4, R5)."""
from __future__ import annotations

from pathlib import Path

import pytest

from sw_scripts_resolve import (
    is_shipwright_self_repo,
    resolve_script,
    resolve_scripts_dir,
    scripts_dir_is_trusted,
)


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
