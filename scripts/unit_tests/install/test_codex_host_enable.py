"""Codex personal marketplace + config.toml enablement (init path)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

import codex_host_enable  # noqa: E402
import install as install_mod  # noqa: E402
import runtime_requirements  # noqa: E402


def test_upsert_marketplace_creates_native_entry(tmp_path: Path) -> None:
    market = tmp_path / ".agents" / "plugins" / "marketplace.json"
    action = codex_host_enable.upsert_personal_marketplace(market)
    assert action == "created"
    data = json.loads(market.read_text(encoding="utf-8"))
    assert data["name"] == "personal"
    assert data["plugins"][0]["name"] == "shipwright"
    assert data["plugins"][0]["source"]["path"] == "./.codex/plugins/shipwright"
    assert data["plugins"][0]["category"] == "Productivity"
    assert data["plugins"][0]["policy"]["installation"] == "INSTALLED_BY_DEFAULT"
    assert codex_host_enable.upsert_personal_marketplace(market) == "unchanged"


def test_upsert_marketplace_preserves_other_plugins(tmp_path: Path) -> None:
    market = tmp_path / "marketplace.json"
    market.write_text(
        json.dumps(
            {
                "name": "personal",
                "interface": {"displayName": "Personal"},
                "plugins": [{"name": "other", "source": {"source": "local", "path": "./other"}}],
            }
        ),
        encoding="utf-8",
    )
    codex_host_enable.upsert_personal_marketplace(market)
    names = [p["name"] for p in json.loads(market.read_text(encoding="utf-8"))["plugins"]]
    assert names == ["other", "shipwright"]


def test_enable_plugin_in_config_appends_and_flips(tmp_path: Path) -> None:
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('model = "gpt-5"\n', encoding="utf-8")
    assert codex_host_enable.enable_plugin_in_config(config) == "updated"
    text = config.read_text(encoding="utf-8")
    assert '[plugins."shipwright@personal"]' in text
    assert "enabled = true" in text
    assert codex_host_enable.enable_plugin_in_config(config) == "unchanged"
    config.write_text(
        '[plugins."shipwright@personal"]\nenabled = false\n',
        encoding="utf-8",
    )
    assert codex_host_enable.enable_plugin_in_config(config) == "updated"
    assert "enabled = true" in config.read_text(encoding="utf-8")
    assert "enabled = false" not in config.read_text(encoding="utf-8")


def test_codex_install_registers_marketplace_and_enables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    dest = tmp_path / "plugin"
    dist = tmp_path / "dist" / "codex"
    (dist / ".codex-plugin").mkdir(parents=True)
    (dist / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "shipwright",
                "version": "0.0.0-test",
                "description": "test",
                "skills": "./skills/",
                "hooks": "./hooks/hooks.json",
                "interface": {"displayName": "Shipwright", "category": "Productivity"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (dist / "hooks").mkdir()
    (dist / "hooks" / "hooks.json").write_text("{}\n", encoding="utf-8")
    (dist / "version.txt").write_text("0.0.0-test\n", encoding="utf-8")
    (dist / "core" / "sw-reference").mkdir(parents=True)
    (dist / "core" / "sw-reference" / "memory-provider-catalog.json").write_text(
        '{"providers":[]}\n', encoding="utf-8"
    )

    monkeypatch.setattr(install_mod, "install_console", lambda **_kw: 0)
    rc = install_mod.install(
        dest, src=dist, integration="codex", install_hooks=False, home=home
    )
    assert rc == 0
    assert (dest / ".codex-plugin" / "plugin.json").is_file()
    market = json.loads((home / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
    assert market["plugins"][0]["name"] == "shipwright"
    config_text = (home / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert '[plugins."shipwright@personal"]' in config_text
    assert "enabled = true" in config_text


def test_codex_init_dry_run_enumerates_enablement_paths(tmp_path: Path) -> None:
    home = tmp_path / "home"
    dest = tmp_path / "plugin"
    src_root = tmp_path / "src"
    dist = src_root / "dist" / "codex"
    dist.mkdir(parents=True)
    (dist / "version.txt").write_text("0.0.0-test\n", encoding="utf-8")
    (dist / ".codex-plugin").mkdir()
    (dist / ".codex-plugin" / "plugin.json").write_text("{}\n", encoding="utf-8")
    consumer = tmp_path / "repo"
    consumer.mkdir()
    (consumer / ".git").mkdir()
    result = install_mod.init_packaged(
        integration="codex",
        repo=consumer,
        dest=dest,
        source_root=src_root,
        accept_ci_stub=False,
        dry_run=True,
        home=home,
    )
    assert result["verdict"] == "pass"
    paths = set(result["scope"]["allPaths"])
    assert str((home / ".agents" / "plugins" / "marketplace.json").resolve()) in paths
    assert str((home / ".codex" / "config.toml").resolve()) in paths
    assert str((dest / ".codex-plugin" / "plugin.json").resolve()) in paths


def test_runtime_bundle_copies_hidden_codex_plugin(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    dist = root / "dist" / "codex" / ".codex-plugin"
    dist.mkdir(parents=True)
    (dist / "plugin.json").write_text('{"name":"shipwright"}\n', encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "version.txt").write_text("0.0.0\n", encoding="utf-8")
    (root / "sw").mkdir()
    copied = runtime_requirements._copy_tree(root / "dist", root / "sw" / "dist")
    assert copied >= 1
    assert (root / "sw" / "dist" / "codex" / ".codex-plugin" / "plugin.json").is_file()
