"""Resolver precedence + trust fixtures (PRD 073 phase 5 / R2, R14, R15, R13)."""
from __future__ import annotations

from pathlib import Path

import pytest

from sw_scripts_resolve import (
    ScriptsResolveError,
    consumer_fallback_scripts,
    is_shipwright_self_repo,
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
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_SCRIPTS", plugin_root)
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(env_root))

    result = resolve_scripts_dir(self_root)
    assert result.error is None
    assert result.source == "self-repo"
    assert result.path == (self_root / "scripts").resolve()


def test_env_validation_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    monkeypatch.delenv("SHIPWRIGHT_SCRIPTS", raising=False)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_SCRIPTS", tmp_path / "missing-plugin")

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


def test_plugin_before_consumer_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    consumer_scripts = consumer / "scripts"
    _seed_trusted_scripts(consumer_scripts)
    (consumer_scripts / "wave_deliver.py").write_text("# forwarder\n", encoding="utf-8")

    plugin_scripts = tmp_path / "plugin"
    _seed_trusted_scripts(plugin_scripts)
    (plugin_scripts / "wave_deliver.py").write_text("# plugin\n", encoding="utf-8")

    monkeypatch.delenv("SHIPWRIGHT_SCRIPTS", raising=False)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_SCRIPTS", plugin_scripts)

    result = resolve_scripts_dir(consumer)
    assert result.error is None
    assert result.source == "plugin"
    assert result.path == plugin_scripts.resolve()


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


def test_consumer_fallback_only_when_trusted(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    assert consumer_fallback_scripts(consumer) is None
    _seed_trusted_scripts(consumer / "scripts")
    assert consumer_fallback_scripts(consumer) == (consumer / "scripts").resolve()


def test_plugin_install_helper_uses_constant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_scripts = tmp_path / "plugin"
    _seed_trusted_scripts(plugin_scripts)
    monkeypatch.setattr("sw_scripts_resolve.PLUGIN_SCRIPTS", plugin_scripts)
    assert plugin_install_scripts() == plugin_scripts.resolve()
