"""Resolver precedence + trust fixtures (PRD 073 phase 5 / PRD 078 phase 2)."""
from __future__ import annotations

from pathlib import Path

import pytest

from sw_scripts_resolve import (
    CONSUMER_NO_PLUGIN_ERROR,
    ScriptsResolveError,
    consumer_fallback_scripts,
    is_shipwright_self_repo,
    iter_plugin_script_candidates,
    plugin_install_scripts,
    resolve_script,
    resolve_scripts_dir,
    scripts_dir_is_trusted,
    validate_env_scripts_root,
)


def _seed_trusted_scripts(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "check-gate.py").write_text("# marker\n", encoding="utf-8")
    (path / "resolve-model-tier.py").write_text("# marker\n", encoding="utf-8")


def _seed_self_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "version.txt").write_text("0.0.0-test\n", encoding="utf-8")
    (path / "core" / "sw-reference").mkdir(parents=True)
    _seed_trusted_scripts(path / "scripts")


def test_self_repo_wins_over_env_and_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    self_root = tmp_path / "shipwright"
    _seed_self_repo(self_root)

    env_root = tmp_path / "env-scripts"
    _seed_trusted_scripts(env_root)

    plugin_root = tmp_path / "plugin-scripts"
    _seed_trusted_scripts(plugin_root)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_LOCAL_SCRIPTS", plugin_root)
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(env_root))

    result = resolve_scripts_dir(self_root)
    assert result.error is None
    assert result.source == "self-repo"
    assert result.path == (self_root / "scripts").resolve()


def test_env_validation_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    monkeypatch.delenv("SHIPWRIGHT_SCRIPTS", raising=False)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_LOCAL_SCRIPTS", tmp_path / "missing-plugin")
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_CACHE_ROOT", tmp_path / "missing-cache")

    path, err = validate_env_scripts_root("relative/scripts")
    assert path is None
    assert err is not None
    assert "absolute" in err

    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(tmp_path / "missing"))
    result = resolve_scripts_dir(consumer)
    assert result.path is None
    assert result.error is not None
    assert "does not exist" in result.error

    untrusted = tmp_path / "untrusted"
    untrusted.mkdir()
    (untrusted / "check-gate.py").write_text("# only one marker\n", encoding="utf-8")
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(untrusted))
    result = resolve_scripts_dir(consumer)
    assert result.path is None
    assert result.error is not None
    assert "trusted" in result.error


def test_local_plugin_root_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()

    plugin_scripts = tmp_path / "local" / "shipwright" / "scripts"
    _seed_trusted_scripts(plugin_scripts)
    (plugin_scripts / "wave_deliver.py").write_text("# plugin\n", encoding="utf-8")

    monkeypatch.delenv("SHIPWRIGHT_SCRIPTS", raising=False)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_LOCAL_SCRIPTS", plugin_scripts)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_CACHE_ROOT", tmp_path / "cache")

    result = resolve_scripts_dir(consumer)
    assert result.error is None
    assert result.source == "plugin-local"
    assert result.path == plugin_scripts.resolve()


def test_marketplace_cache_plugin_root_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()

    cache_scripts = tmp_path / "cache" / "cursor-public" / "shipwright" / "rev1" / "scripts"
    _seed_trusted_scripts(cache_scripts)
    (cache_scripts / "wave_deliver.py").write_text("# cache plugin\n", encoding="utf-8")

    monkeypatch.delenv("SHIPWRIGHT_SCRIPTS", raising=False)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_LOCAL_SCRIPTS", tmp_path / "missing-local")
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_CACHE_ROOT", tmp_path / "cache")

    result = resolve_scripts_dir(consumer)
    assert result.error is None
    assert result.source == "plugin-cache"
    assert result.path == cache_scripts.resolve()


def test_local_plugin_wins_over_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()

    local_scripts = tmp_path / "local" / "shipwright" / "scripts"
    cache_scripts = tmp_path / "cache" / "cursor-public" / "shipwright" / "rev1" / "scripts"
    _seed_trusted_scripts(local_scripts)
    _seed_trusted_scripts(cache_scripts)

    monkeypatch.delenv("SHIPWRIGHT_SCRIPTS", raising=False)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_LOCAL_SCRIPTS", local_scripts)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_CACHE_ROOT", tmp_path / "cache")

    result = resolve_scripts_dir(consumer)
    assert result.error is None
    assert result.source == "plugin-local"
    assert result.path == local_scripts.resolve()


def test_consumer_missing_plugin_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _seed_trusted_scripts(consumer / "scripts")

    monkeypatch.delenv("SHIPWRIGHT_SCRIPTS", raising=False)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_LOCAL_SCRIPTS", tmp_path / "missing-local")
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_CACHE_ROOT", tmp_path / "missing-cache")

    result = resolve_scripts_dir(consumer)
    assert result.path is None
    assert result.error == CONSUMER_NO_PLUGIN_ERROR
    assert result.source is None

    with pytest.raises(ScriptsResolveError, match="plugin not installed"):
        resolve_script(consumer, "wave_deliver.py")


def test_resolve_script_missing_raises(repo_root: Path) -> None:
    with pytest.raises(ScriptsResolveError, match="script missing"):
        resolve_script(repo_root, "definitely-missing-script.py")


def test_self_repo_detection(repo_root: Path) -> None:
    assert is_shipwright_self_repo(repo_root)
    assert scripts_dir_is_trusted(repo_root / "scripts")


def test_valid_env_scripts_root(tmp_path: Path) -> None:
    trusted = tmp_path / "trusted"
    _seed_trusted_scripts(trusted)
    path, err = validate_env_scripts_root(str(trusted))
    assert err is None
    assert path == trusted.resolve()


def test_consumer_fallback_helper_reports_trusted_dir(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    assert consumer_fallback_scripts(consumer) is None
    _seed_trusted_scripts(consumer / "scripts")
    assert consumer_fallback_scripts(consumer) == (consumer / "scripts").resolve()


def test_plugin_install_helper_uses_local_constant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_scripts = tmp_path / "plugin"
    _seed_trusted_scripts(plugin_scripts)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_LOCAL_SCRIPTS", plugin_scripts)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_CACHE_ROOT", tmp_path / "cache")
    assert plugin_install_scripts() == plugin_scripts.resolve()


def test_iter_plugin_script_candidates_includes_local_and_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    local_scripts = tmp_path / "local" / "shipwright" / "scripts"
    cache_scripts = tmp_path / "cache" / "publisher" / "shipwright" / "hash" / "scripts"
    local_scripts.mkdir(parents=True)
    cache_scripts.mkdir(parents=True)

    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_LOCAL_SCRIPTS", local_scripts)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_CACHE_ROOT", tmp_path / "cache")

    candidates = list(iter_plugin_script_candidates())
    assert candidates[0] == local_scripts
    assert cache_scripts in candidates
